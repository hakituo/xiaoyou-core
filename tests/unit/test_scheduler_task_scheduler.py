"""core/services/scheduler/task/task_scheduler.py 的单测。

覆盖范围：
- 模块级工具：``_get_cpp_engine``、``get_current_task_id``
- 静态配置推导：``_resolve_gpu_layers`` / ``_resolve_batch_size`` / ``_resolve_draft_config``
- 实例方法：``_build_llm_gpu_config``、``_ensure_cpp_llm_ready``
- 生命周期：``start`` / ``stop`` / ``_spawn_worker`` / ``_worker_coroutine``
- 任务接口：``_execute_task``、``schedule_task``、``schedule_gpu_task``、
  ``schedule_cpu_task``、``cancel_task``、``schedule_periodic_task``、
  ``clean_completed_tasks`` 以及全部查询方法
- LLM 提交：``submit_llm_task`` 的云端 / 本地 / C++ 三条分支
- 全局单例：``get_global_scheduler``、``initialize_scheduler``、``shutdown_scheduler``

「禁止 flaky」的做法：
- 不依赖真实时间：``_worker_coroutine`` 里的 ``wait_for`` 用 ``_WorkerAsyncio``
  按脚本决定抛超时 / 抛异常 / 抛取消 / 返回任务，覆盖 break 与 continue 两条路径；
- ``schedule_periodic_task`` 的 ``asyncio.sleep`` / ``create_task`` 同样换成脚本化
  fake，用「第 2 次 sleep 时把 ``_running`` 置假」来终止循环，不 sleep 真实秒数；
- 所有外部依赖（cpp 引擎、配置、LLM 模块、GPU 资源锁）都用轻量 fake 或 monkeypatch，
  绝不触碰真实模型 / 后端。
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
import types
from contextlib import asynccontextmanager

import pytest

from core.contracts import TaskStatus
from core.services.scheduler.task import task_scheduler as ts
from core.services.scheduler.task.task_scheduler import (
    GlobalTaskScheduler,
    TaskInfo,
    TaskPriority,
    TaskType,
    get_current_task_id,
)


# ============================================================
# 通用 fixture / fake
# ============================================================


@pytest.fixture()
def scheduler():
    """每个用例一个全新的调度器，避免线程池与内部状态跨用例串味。"""
    inst = GlobalTaskScheduler()
    yield inst
    with contextlib.suppress(Exception):
        inst._cpu_executor.shutdown(wait=False)


def _make_settings(**model_overrides):
    """构造一个覆盖 task_scheduler 所需字段的假 settings。"""
    model = types.SimpleNamespace(
        text_path="D:/models/x.gguf",
        n_gpu_layers=-1,
        n_ctx=4096,
        n_batch=None,
        flash_attn=False,
        offload_kqv=False,
        temperature=0.7,
        top_p=0.95,
        top_k=40,
        repetition_penalty=1.1,
        llm=types.SimpleNamespace(provider="local"),
    )
    for key, value in model_overrides.items():
        setattr(model, key, value)
    text_model = types.SimpleNamespace(draft_model_path=None, draft_gpu_device_id=-1)
    return types.SimpleNamespace(
        scheduler=types.SimpleNamespace(use_cpp=True, use_cpp_for_llm=True),
        model=model,
        model_adapter=types.SimpleNamespace(text_model=text_model),
    )


def _info(task_id, *, status=TaskStatus.PENDING, cancel_requested=False):
    """快速构造 TaskInfo。"""
    return TaskInfo(
        task_id=task_id,
        name=task_id,
        priority=TaskPriority.LOW,
        created_at=0.0,
        status=status,
        cancel_requested=cancel_requested,
    )


class _FakeCpp:
    """假的 C++ 调度引擎，只实现 task_scheduler 会用到的那部分接口。"""

    def __init__(self, *, enabled=False, scheduler=None, gpu_config=None, bio=None):
        self.enabled = enabled
        self.scheduler = scheduler
        self._gpu_config = gpu_config
        self.bio = bio
        self.started = None
        self.stopped = False
        self.applied = None
        self.last_kwargs = None

    def start(self, **kwargs):
        self.started = kwargs

    async def apply_llm_config(self, gpu_config, worker_count=4, preload_llm=False):
        self.applied = (gpu_config, worker_count, preload_llm)
        return True

    async def stop(self):
        self.stopped = True

    def get_biological_system(self):
        return self.bio

    async def submit_llm_task(self, prompt, **kwargs):
        self.last_kwargs = kwargs
        yield "tok1"
        yield "tok2"


class _FakeResourceLock:
    """记录 acquire 参数的假 GPU 资源锁。"""

    def __init__(self):
        self.calls = []

    @asynccontextmanager
    async def acquire(self, requestor, *, reject_if_full=False):
        self.calls.append((requestor, reject_if_full))
        yield


class _FakeQueue:
    """只统计 task_done 的假队列；get() 永远不会被真正 await。"""

    def __init__(self):
        self.done_calls = 0

    async def get(self):  # pragma: no cover - 由 _WorkerAsyncio.wait_for 关闭
        raise AssertionError("worker 测试中不应真正 await 队列")

    def task_done(self):
        self.done_calls += 1


class _WorkerAsyncio:
    """替换被测模块内的 asyncio 引用，用脚本驱动每次 ``wait_for``。

    只动 ``task_scheduler`` 的模块级引用，不改全局 asyncio 模块。
    """

    TimeoutError = asyncio.TimeoutError
    CancelledError = asyncio.CancelledError

    def __init__(self, steps):
        self.steps = list(steps)
        self.consumed = 0

    async def wait_for(self, coro, timeout):
        coro.close()
        if not self.steps:
            raise asyncio.CancelledError()
        step = self.steps.pop(0)
        self.consumed += 1
        return step()

    def __getattr__(self, name):
        return getattr(asyncio, name)


def _step_ok(item):
    return lambda: item


def _step_timeout():
    def _raise():
        raise asyncio.TimeoutError()

    return _raise


def _step_error():
    def _raise():
        raise ValueError("queue boom")

    return _raise


def _step_cancel():
    def _raise():
        raise asyncio.CancelledError()

    return _raise


# ============================================================
# 模块级工具
# ============================================================


class TestModuleHelpers:
    def test_get_cpp_engine_uses_auto_start_false(self, monkeypatch):
        import core.services.scheduler.cpp_scheduler_engine as engine_mod

        seen = {}

        def fake_get(auto_start=True):
            seen["auto_start"] = auto_start
            return "ENGINE"

        monkeypatch.setattr(engine_mod, "get_scheduler_engine", fake_get)
        assert ts._get_cpp_engine() == "ENGINE"
        assert seen["auto_start"] is False

    def test_get_current_task_id_default_none(self):
        assert get_current_task_id() is None

    def test_get_current_task_id_reads_contextvar(self):
        token = ts._current_task_id_ctx.set("abc")
        try:
            assert get_current_task_id() == "abc"
        finally:
            ts._current_task_id_ctx.reset(token)


# ============================================================
# 静态配置推导
# ============================================================


class TestResolveGpuLayers:
    def test_non_int_value_falls_back_to_minus_one(self):
        settings = types.SimpleNamespace(model=types.SimpleNamespace(n_gpu_layers="abc"))
        assert GlobalTaskScheduler._resolve_gpu_layers(settings, "cpp") == -1

    def test_python_backend_without_cuda_forces_zero(self, monkeypatch):
        fake_torch = types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda: False)
        )
        monkeypatch.setitem(sys.modules, "torch", fake_torch)
        settings = types.SimpleNamespace(model=types.SimpleNamespace(n_gpu_layers=-1))
        assert GlobalTaskScheduler._resolve_gpu_layers(settings, "python") == 0

    def test_python_backend_torch_import_error_forces_zero(self, monkeypatch):
        # sys.modules 中置 None 会让 ``import torch`` 抛 ImportError
        monkeypatch.setitem(sys.modules, "torch", None)
        settings = types.SimpleNamespace(model=types.SimpleNamespace(n_gpu_layers=-1))
        assert GlobalTaskScheduler._resolve_gpu_layers(settings, "python") == 0

    def test_zero_layers_with_cuda_available_restores_auto(self, monkeypatch):
        fake_torch = types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda: True)
        )
        monkeypatch.setitem(sys.modules, "torch", fake_torch)
        settings = types.SimpleNamespace(model=types.SimpleNamespace(n_gpu_layers=0))
        assert GlobalTaskScheduler._resolve_gpu_layers(settings, "python") == -1

    def test_zero_layers_probe_failure_keeps_zero(self, monkeypatch):
        class _Boom:
            @property
            def cuda(self):
                raise RuntimeError("no cuda")

        monkeypatch.setitem(sys.modules, "torch", _Boom())
        settings = types.SimpleNamespace(model=types.SimpleNamespace(n_gpu_layers=0))
        assert GlobalTaskScheduler._resolve_gpu_layers(settings, "python") == 0

    def test_non_python_backend_returns_layers_as_is(self):
        settings = types.SimpleNamespace(model=types.SimpleNamespace(n_gpu_layers=12))
        assert GlobalTaskScheduler._resolve_gpu_layers(settings, "cpp") == 12


class TestResolveBatchSize:
    def test_explicit_cfg_batch_wins(self):
        settings = _make_settings(n_ctx=4096, n_batch=256)
        assert GlobalTaskScheduler._resolve_batch_size(settings, 10, "cpp") == 256

    def test_auto_layers_nonzero_default_branch(self):
        settings = _make_settings(n_ctx=4096, n_batch=None)
        assert GlobalTaskScheduler._resolve_batch_size(settings, 10, "cpp") == 409

    def test_auto_layers_zero_branch(self):
        settings = _make_settings(n_ctx=4096, n_batch=None)
        assert GlobalTaskScheduler._resolve_batch_size(settings, 0, "cpp") == 409

    def test_python_backend_caps_at_256_when_zero_layers(self):
        settings = _make_settings(n_ctx=4096, n_batch=None)
        assert GlobalTaskScheduler._resolve_batch_size(settings, 0, "python") == 256

    def test_python_backend_caps_at_512_when_layers_present(self):
        settings = _make_settings(n_ctx=8192, n_batch=None)
        assert GlobalTaskScheduler._resolve_batch_size(settings, 10, "python") == 512

    def test_invalid_cfg_batch_treated_as_zero(self):
        settings = _make_settings(n_ctx=4096, n_batch="oops")
        assert GlobalTaskScheduler._resolve_batch_size(settings, 10, "cpp") == 409

    def test_batch_floor_is_32(self):
        settings = _make_settings(n_ctx=100, n_batch=None)
        assert GlobalTaskScheduler._resolve_batch_size(settings, 10, "cpp") == 32

    def test_exception_path_returns_128(self):
        class _BadCtx:
            def __int__(self):
                raise TypeError("bad ctx")

        settings = _make_settings(n_ctx=_BadCtx(), n_batch=None)
        assert GlobalTaskScheduler._resolve_batch_size(settings, 10, "cpp") == 128


class TestResolveDraftConfig:
    def test_valid_draft_config(self):
        settings = _make_settings()
        settings.model_adapter.text_model.draft_model_path = "D:/d.gguf"
        settings.model_adapter.text_model.draft_gpu_device_id = 0
        assert GlobalTaskScheduler._resolve_draft_config(settings) == ("D:/d.gguf", 0)

    def test_non_int_device_id_resets(self):
        settings = _make_settings()
        settings.model_adapter.text_model.draft_model_path = "D:/d.gguf"
        settings.model_adapter.text_model.draft_gpu_device_id = "x"
        assert GlobalTaskScheduler._resolve_draft_config(settings) == (None, -1)

    def test_negative_device_id_resets(self):
        settings = _make_settings()
        settings.model_adapter.text_model.draft_model_path = "D:/d.gguf"
        settings.model_adapter.text_model.draft_gpu_device_id = -1
        assert GlobalTaskScheduler._resolve_draft_config(settings) == (None, -1)

    def test_empty_path_resets(self):
        settings = _make_settings()
        settings.model_adapter.text_model.draft_model_path = ""
        settings.model_adapter.text_model.draft_gpu_device_id = 0
        assert GlobalTaskScheduler._resolve_draft_config(settings) == (None, -1)


# ============================================================
# _build_llm_gpu_config
# ============================================================


class TestBuildLlmGpuConfig:
    def test_none_when_scheduler_config_missing(self, scheduler):
        settings = _make_settings()
        settings.scheduler = None
        assert scheduler._build_llm_gpu_config(settings, "D:/m.gguf") is None

    def test_none_when_not_use_cpp_for_llm(self, scheduler):
        settings = _make_settings()
        settings.scheduler.use_cpp_for_llm = False
        assert scheduler._build_llm_gpu_config(settings, "D:/m.gguf") is None

    def test_none_when_path_not_gguf(self, scheduler):
        settings = _make_settings()
        settings.model.text_path = "D:/m.bin"
        assert scheduler._build_llm_gpu_config(settings, None) is None

    def test_builds_full_config(self, scheduler):
        settings = _make_settings(n_batch=128, flash_attn=True, offload_kqv=True)
        settings.model_adapter.text_model.draft_model_path = "D:/d.gguf"
        settings.model_adapter.text_model.draft_gpu_device_id = 1

        config = scheduler._build_llm_gpu_config(settings, None)

        assert config["backend"] == "cpp"
        assert config["model_path"] == "D:/models/x.gguf"
        assert config["n_gpu_layers"] == -1
        assert config["max_batch_size"] == 128
        assert config["n_ubatch"] == 128
        assert config["flash_attn"] is True
        assert config["offload_kqv"] is True
        assert config["draft_model_path"] == "D:/d.gguf"
        assert config["draft_gpu_device_id"] == 1
        assert config["temperature"] == 0.7
        assert config["top_p"] == 0.95
        assert config["top_k"] == 40
        assert config["repetition_penalty"] == 1.1

    def test_zero_layers_disables_flash_attn_and_kqv(self, scheduler):
        settings = _make_settings(n_gpu_layers=0, flash_attn=True, offload_kqv=True)
        config = scheduler._build_llm_gpu_config(settings, None)
        assert config["n_gpu_layers"] == 0
        assert config["flash_attn"] is False
        assert config["offload_kqv"] is False

    def test_exception_returns_none(self, scheduler):
        class _BoomScheduler:
            @property
            def use_cpp_for_llm(self):
                raise RuntimeError("boom")

        settings = _make_settings()
        settings.scheduler = _BoomScheduler()
        assert scheduler._build_llm_gpu_config(settings, None) is None


# ============================================================
# _ensure_cpp_llm_ready
# ============================================================


class TestEnsureCppLlmReady:
    def test_disabled_engine_returns_immediately(self, scheduler, monkeypatch):
        cpp = _FakeCpp(enabled=False)
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: cpp)
        asyncio.run(scheduler._ensure_cpp_llm_ready(None))
        assert cpp.applied is None
        assert cpp.started is None

    def test_starts_scheduler_when_cpp_scheduler_missing(self, scheduler, monkeypatch):
        cpp = _FakeCpp(enabled=True, scheduler=None)
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: cpp)
        started = {}

        async def fake_start(worker_count=3, llm_model_path=None):
            started["worker_count"] = worker_count

        monkeypatch.setattr(scheduler, "start", fake_start)
        asyncio.run(scheduler._ensure_cpp_llm_ready("D:/m.gguf"))
        assert started["worker_count"] == scheduler._worker_count
        assert cpp.applied is None

    def test_existing_gpu_config_short_circuits(self, scheduler, monkeypatch):
        cpp = _FakeCpp(enabled=True, scheduler=object(), gpu_config={"model_path": "x"})
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: cpp)
        asyncio.run(scheduler._ensure_cpp_llm_ready(None))
        assert cpp.applied is None

    def test_use_cpp_disabled_short_circuits(self, scheduler, monkeypatch):
        cpp = _FakeCpp(enabled=True, scheduler=object())
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: cpp)
        monkeypatch.setattr(ts, "get_config", lambda *a, **k: False)
        asyncio.run(scheduler._ensure_cpp_llm_ready(None))
        assert cpp.applied is None

    def test_no_gpu_config_short_circuits(self, scheduler, monkeypatch):
        cpp = _FakeCpp(enabled=True, scheduler=object())
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: cpp)
        monkeypatch.setattr(ts, "get_config", lambda *a, **k: True)
        monkeypatch.setattr(ts, "get_settings", lambda: _make_settings())
        monkeypatch.setattr(scheduler, "_build_llm_gpu_config", lambda s, p: None)
        asyncio.run(scheduler._ensure_cpp_llm_ready(None))
        assert cpp.applied is None

    def test_applies_llm_config(self, scheduler, monkeypatch):
        cpp = _FakeCpp(enabled=True, scheduler=object())
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: cpp)
        monkeypatch.setattr(ts, "get_config", lambda *a, **k: True)
        monkeypatch.setattr(ts, "get_settings", lambda: _make_settings())
        monkeypatch.setattr(
            scheduler, "_build_llm_gpu_config", lambda s, p: {"model_path": "x"}
        )
        asyncio.run(scheduler._ensure_cpp_llm_ready(None))
        assert cpp.applied == ({"model_path": "x"}, scheduler._worker_count, False)


# ============================================================
# start / stop / _spawn_worker
# ============================================================


class TestLifecycle:
    def test_start_creates_workers_and_is_idempotent(self, scheduler, monkeypatch):
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: _FakeCpp(enabled=False))

        async def scenario():
            await scheduler.start(worker_count=2)
            assert scheduler._running is True
            assert len(scheduler._workers) == 2
            assert scheduler._worker_count == 2
            # 重复 start 只告警，不重复起 worker
            await scheduler.start(worker_count=5)
            assert len(scheduler._workers) == 2
            await scheduler.stop()

        asyncio.run(scenario())
        assert scheduler._running is False
        assert scheduler._workers == []

    def test_stop_without_start_is_noop(self, scheduler, monkeypatch):
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: _FakeCpp(enabled=False))
        asyncio.run(scheduler.stop())
        assert scheduler._running is False

    def test_start_with_cpp_enabled_and_stops_engine(self, scheduler, monkeypatch):
        cpp = _FakeCpp(enabled=True)
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: cpp)
        monkeypatch.setattr(
            "config.integrated_config.get_settings", lambda: _make_settings()
        )
        monkeypatch.setattr(
            "core.utils.config_accessor.get_config", lambda *a, **k: True
        )
        monkeypatch.setattr(
            scheduler, "_build_llm_gpu_config", lambda s, p: {"model_path": "x"}
        )

        async def scenario():
            await scheduler.start(worker_count=1, llm_model_path="D:/m.gguf")
            await scheduler.stop()

        asyncio.run(scenario())
        assert cpp.started["worker_count"] == 1
        assert cpp.started["gpu_config"] == {"model_path": "x"}
        assert cpp.stopped is True

    def test_start_swallows_cpp_errors(self, scheduler, monkeypatch):
        cpp = _FakeCpp(enabled=True)
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: cpp)
        monkeypatch.setattr(
            "config.integrated_config.get_settings", lambda: _make_settings()
        )
        monkeypatch.setattr(
            "core.utils.config_accessor.get_config", lambda *a, **k: True
        )

        def boom(settings, path):
            raise RuntimeError("boom")

        monkeypatch.setattr(scheduler, "_build_llm_gpu_config", boom)

        async def scenario():
            await scheduler.start(worker_count=1)
            await scheduler.stop()

        asyncio.run(scenario())
        assert cpp.started is None

    def test_stop_tolerates_gather_cancellation(self, scheduler, monkeypatch):
        """stop() 等待 worker 收尾时被取消，应吞掉 CancelledError 继续收尾。"""
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: _FakeCpp(enabled=False))

        class _GatherRaisesAsyncio:
            """只让 gather 抛取消，其余委托真实 asyncio。"""

            CancelledError = asyncio.CancelledError

            async def gather(self, *args, **kwargs):
                raise asyncio.CancelledError()

            def __getattr__(self, name):
                return getattr(asyncio, name)

        monkeypatch.setattr(ts, "asyncio", _GatherRaisesAsyncio())

        async def scenario():
            scheduler._running = True
            await scheduler.stop()

        asyncio.run(scenario())
        assert scheduler._running is False
        assert scheduler._workers == []

    def test_spawn_worker_is_noop_when_not_running(self, scheduler):
        scheduler._spawn_worker("extra")
        assert scheduler._workers == []

    def test_spawn_worker_adds_worker_when_running(self, scheduler, monkeypatch):
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: _FakeCpp(enabled=False))

        async def scenario():
            scheduler._running = True
            scheduler._spawn_worker("extra")
            assert len(scheduler._workers) == 1
            await scheduler.stop()

        asyncio.run(scenario())


# ============================================================
# _worker_coroutine
# ============================================================


class TestWorkerCoroutine:
    def test_loop_exits_when_not_running(self, scheduler, monkeypatch):
        fake = _WorkerAsyncio([_step_ok((0, _info("never")))])
        monkeypatch.setattr(ts, "asyncio", fake)
        scheduler._task_queue = _FakeQueue()
        scheduler._running = False

        asyncio.run(scheduler._worker_coroutine("w"))

        assert fake.consumed == 0
        assert scheduler._task_queue.done_calls == 0

    def test_timeout_and_error_branches_continue(self, scheduler, monkeypatch):
        fake = _WorkerAsyncio([_step_timeout(), _step_error(), _step_cancel()])
        monkeypatch.setattr(ts, "asyncio", fake)
        scheduler._task_queue = _FakeQueue()
        scheduler._running = True

        asyncio.run(scheduler._worker_coroutine("w"))

        assert fake.consumed == 3
        # 这两条分支都在 task_done 之前 continue，不应计数
        assert scheduler._task_queue.done_calls == 0

    def test_success_path_updates_state_and_future(self, scheduler, monkeypatch):
        info = _info("t1")
        holder = {}

        async def scenario():
            scheduler._running = True
            scheduler._task_queue = _FakeQueue()
            future = asyncio.get_running_loop().create_future()
            holder["future"] = future
            scheduler._tasks["t1"] = {
                "info": info,
                "func": lambda: 42,
                "args": (),
                "kwargs": {},
            }
            scheduler._task_futures["t1"] = future
            await scheduler._worker_coroutine("w")

        fake = _WorkerAsyncio([_step_ok((0, info)), _step_cancel()])
        monkeypatch.setattr(ts, "asyncio", fake)
        asyncio.run(scenario())

        assert info.status == TaskStatus.COMPLETED
        assert info.result == 42
        assert info.start_time is not None and info.end_time is not None
        assert holder["future"].result() == 42
        # 执行参数被释放，避免内存泄漏
        assert scheduler._tasks["t1"]["func"] is None
        assert scheduler._task_queue.done_calls == 1

    def test_cancel_requested_path_skips_execution(self, scheduler, monkeypatch):
        info = _info("t2", cancel_requested=True)
        holder = {}

        async def scenario():
            scheduler._running = True
            scheduler._task_queue = _FakeQueue()
            future = asyncio.get_running_loop().create_future()
            holder["future"] = future
            scheduler._tasks["t2"] = {
                "info": info,
                "func": lambda: 1,
                "args": (),
                "kwargs": {},
            }
            scheduler._task_futures["t2"] = future
            await scheduler._worker_coroutine("w")
            with contextlib.suppress(BaseException):
                future.exception()

        fake = _WorkerAsyncio([_step_ok((0, info)), _step_cancel()])
        monkeypatch.setattr(ts, "asyncio", fake)
        asyncio.run(scenario())

        assert info.status == TaskStatus.CANCELLED
        assert holder["future"].done() is True
        assert scheduler._task_queue.done_calls == 1

    def test_missing_task_data_is_skipped(self, scheduler, monkeypatch):
        info = _info("ghost")

        async def scenario():
            scheduler._running = True
            scheduler._task_queue = _FakeQueue()
            await scheduler._worker_coroutine("w")

        fake = _WorkerAsyncio([_step_ok((0, info)), _step_cancel()])
        monkeypatch.setattr(ts, "asyncio", fake)
        asyncio.run(scenario())

        assert info.status == TaskStatus.PENDING
        assert scheduler._task_queue.done_calls == 1

    def test_none_func_is_skipped_after_marking_running(self, scheduler, monkeypatch):
        info = _info("t3")

        async def scenario():
            scheduler._running = True
            scheduler._task_queue = _FakeQueue()
            scheduler._tasks["t3"] = {
                "info": info,
                "func": None,
                "args": (),
                "kwargs": {},
            }
            await scheduler._worker_coroutine("w")

        fake = _WorkerAsyncio([_step_ok((0, info)), _step_cancel()])
        monkeypatch.setattr(ts, "asyncio", fake)
        asyncio.run(scenario())

        assert info.status == TaskStatus.RUNNING
        assert scheduler._task_queue.done_calls == 1

    def test_execution_failure_marks_task_failed(self, scheduler, monkeypatch):
        info = _info("t4")
        holder = {}

        def boom():
            raise ValueError("kaboom")

        async def scenario():
            scheduler._running = True
            scheduler._task_queue = _FakeQueue()
            future = asyncio.get_running_loop().create_future()
            holder["future"] = future
            scheduler._tasks["t4"] = {
                "info": info,
                "func": boom,
                "args": (),
                "kwargs": {},
            }
            scheduler._task_futures["t4"] = future
            await scheduler._worker_coroutine("w")

        fake = _WorkerAsyncio([_step_ok((0, info)), _step_cancel()])
        monkeypatch.setattr(ts, "asyncio", fake)
        asyncio.run(scenario())

        assert info.status == TaskStatus.FAILED
        assert "kaboom" in info.error
        assert holder["future"].done() is True
        assert isinstance(holder["future"].exception(), ValueError)
        assert scheduler._task_queue.done_calls == 1

    def test_unexpected_outer_exception_is_contained(self, scheduler, monkeypatch):
        class _BoomInfo:
            @property
            def cancel_requested(self):
                raise RuntimeError("outer boom")

        async def scenario():
            scheduler._running = True
            scheduler._task_queue = _FakeQueue()
            await scheduler._worker_coroutine("w")

        fake = _WorkerAsyncio([_step_ok((0, _BoomInfo())), _step_cancel()])
        monkeypatch.setattr(ts, "asyncio", fake)
        asyncio.run(scenario())

        assert scheduler._task_queue.done_calls == 1


# ============================================================
# _execute_task
# ============================================================


class TestExecuteTask:
    def test_gpu_bound_acquires_resource_lock(self, scheduler, monkeypatch):
        lock = _FakeResourceLock()
        monkeypatch.setattr(ts, "get_resource_lock", lambda: lock)
        result = asyncio.run(
            scheduler._execute_task(lambda a, b: a + b, TaskType.GPU_BOUND, 1, b=2)
        )
        assert result == 3
        assert lock.calls == [("TaskScheduler_GPU", True)]

    def test_cpu_bound_uses_thread_pool(self, scheduler):
        result = asyncio.run(
            scheduler._execute_task(lambda x: x * 3, TaskType.CPU_BOUND, 4)
        )
        assert result == 12

    def test_default_async_function_is_awaited(self, scheduler):
        async def coro(x):
            return x + 1

        assert asyncio.run(scheduler._execute_task(coro, TaskType.DEFAULT, 1)) == 2

    def test_default_sync_function_runs_in_thread(self, scheduler):
        assert (
            asyncio.run(scheduler._execute_task(lambda: "sync", TaskType.DEFAULT))
            == "sync"
        )

    def test_default_sync_function_returning_coroutine_is_awaited(self, scheduler):
        async def inner():
            return "awaited"

        def outer():
            return inner()

        assert (
            asyncio.run(scheduler._execute_task(outer, TaskType.DEFAULT)) == "awaited"
        )


# ============================================================
# get_task / schedule_task
# ============================================================


class TestGetTask:
    def test_existing_and_missing(self, scheduler):
        info = _info("a")
        scheduler._tasks["a"] = {"info": info}
        assert scheduler.get_task("a") is info
        assert scheduler.get_task("missing") is None


class TestScheduleTask:
    def test_raises_when_not_running(self, scheduler):
        with pytest.raises(RuntimeError, match="调度器未启动"):
            asyncio.run(scheduler.schedule_task(lambda: None))
        assert scheduler._tasks == {}

    def test_schedules_with_defaults(self, scheduler):
        async def scenario():
            scheduler._running = True
            return await scheduler.schedule_task(lambda: 1, name="job")

        task_id = asyncio.run(scenario())
        stored = scheduler._tasks[task_id]
        assert stored["info"].name == "job"
        assert stored["info"].priority is TaskPriority.MEDIUM
        assert stored["info"].task_type is TaskType.DEFAULT
        assert stored["info"].status == TaskStatus.PENDING
        assert stored["kwargs"] == {}
        assert task_id in scheduler._task_futures
        assert scheduler._next_task_id == 1

    def test_int_priority_is_converted(self, scheduler):
        async def scenario():
            scheduler._running = True
            return await scheduler.schedule_task(
                lambda: 1, priority=3, args=(1,), kwargs={"a": 2}
            )

        task_id = asyncio.run(scenario())
        stored = scheduler._tasks[task_id]
        assert stored["info"].priority is TaskPriority.CRITICAL
        assert stored["args"] == (1,)
        assert stored["kwargs"] == {"a": 2}

    def test_invalid_int_priority_raises(self, scheduler):
        async def scenario():
            scheduler._running = True
            await scheduler.schedule_task(lambda: 1, priority=99)

        with pytest.raises(ValueError):
            asyncio.run(scenario())

    def test_queue_ordering_prefers_high_priority(self, scheduler):
        async def scenario():
            scheduler._running = True
            low = await scheduler.schedule_task(lambda: 1, priority=TaskPriority.LOW)
            high = await scheduler.schedule_task(lambda: 1, priority=TaskPriority.HIGH)
            first = scheduler._task_queue.get_nowait()
            second = scheduler._task_queue.get_nowait()
            return low, high, first, second

        low, high, first, second = asyncio.run(scenario())
        assert first[1].task_id == high
        assert second[1].task_id == low


class TestQuickSchedulers:
    def test_schedule_gpu_task(self, scheduler):
        async def scenario():
            scheduler._running = True
            return await scheduler.schedule_gpu_task(lambda: 1, 5, extra=1)

        task_id = asyncio.run(scenario())
        stored = scheduler._tasks[task_id]
        assert stored["info"].task_type is TaskType.GPU_BOUND
        assert stored["info"].name == "gpu_task"
        assert stored["info"].priority is TaskPriority.HIGH
        assert stored["args"] == (5,)
        assert stored["kwargs"] == {"extra": 1}

    def test_schedule_cpu_task_with_overrides(self, scheduler):
        async def scenario():
            scheduler._running = True
            return await scheduler.schedule_cpu_task(
                lambda: 1, name="mine", priority=TaskPriority.LOW
            )

        task_id = asyncio.run(scenario())
        stored = scheduler._tasks[task_id]
        assert stored["info"].task_type is TaskType.CPU_BOUND
        assert stored["info"].name == "mine"
        assert stored["info"].priority is TaskPriority.LOW


# ============================================================
# cancel_task
# ============================================================


class TestCancelTask:
    def test_missing_task_returns_false(self, scheduler):
        assert asyncio.run(scheduler.cancel_task("nope")) is False

    def test_completed_task_cannot_be_cancelled(self, scheduler):
        scheduler._tasks["c"] = {"info": _info("c", status=TaskStatus.COMPLETED)}
        assert asyncio.run(scheduler.cancel_task("c")) is False

    def test_failed_task_cannot_be_cancelled(self, scheduler):
        scheduler._tasks["f"] = {"info": _info("f", status=TaskStatus.FAILED)}
        assert asyncio.run(scheduler.cancel_task("f")) is False

    def test_running_task_is_marked_for_cancel(self, scheduler):
        info = _info("r", status=TaskStatus.RUNNING)
        scheduler._tasks["r"] = {"info": info}
        assert asyncio.run(scheduler.cancel_task("r")) is True
        assert info.cancel_requested is True
        assert info.status == TaskStatus.RUNNING

    def test_pending_task_is_cancelled_and_future_notified(self, scheduler):
        info = _info("p")
        holder = {}

        async def scenario():
            scheduler._tasks["p"] = {"info": info}
            future = asyncio.get_running_loop().create_future()
            holder["future"] = future
            scheduler._task_futures["p"] = future
            result = await scheduler.cancel_task("p")
            with contextlib.suppress(BaseException):
                future.exception()
            return result

        result = asyncio.run(scenario())
        assert result is True
        assert info.status == TaskStatus.CANCELLED
        assert info.cancel_requested is True
        assert holder["future"].done() is True


# ============================================================
# 查询方法
# ============================================================


class TestQueries:
    def test_get_task_status_and_info_alias(self, scheduler):
        info = _info("q")
        scheduler._tasks["q"] = {"info": info}

        async def scenario():
            return (
                await scheduler.get_task_status("q"),
                await scheduler.get_task_status("missing"),
                await scheduler.get_task_info("q"),
            )

        found, missing, alias = asyncio.run(scenario())
        assert found is info
        assert alias is info
        assert missing is None

    def test_get_task_future(self, scheduler):
        holder = {}

        async def scenario():
            future = asyncio.get_running_loop().create_future()
            holder["future"] = future
            scheduler._task_futures["q"] = future
            return (
                await scheduler.get_task_future("q"),
                await scheduler.get_task_future("x"),
            )

        found, missing = asyncio.run(scenario())
        assert found is holder["future"]
        assert missing is None

    def test_get_all_and_active_tasks(self, scheduler):
        scheduler._tasks = {
            "a": {"info": _info("a", status=TaskStatus.PENDING)},
            "b": {"info": _info("b", status=TaskStatus.RUNNING)},
            "c": {"info": _info("c", status=TaskStatus.COMPLETED)},
        }

        async def scenario():
            return await scheduler.get_all_tasks(), await scheduler.get_active_tasks()

        all_tasks, active = asyncio.run(scenario())
        assert set(all_tasks) == {"a", "b", "c"}
        assert set(active) == {"a", "b"}


# ============================================================
# schedule_periodic_task
# ============================================================


class TestSchedulePeriodicTask:
    def test_periodic_wrapper_submits_then_reports_failure(
        self, scheduler, monkeypatch
    ):
        captured = {}
        sleep_calls = {"n": 0}

        class _DummyTask:
            def add_done_callback(self, cb):
                self.cb = cb

        async def fake_sleep(delay):
            # 用真实 asyncio 让出控制权，但不消耗真实时间
            await asyncio.sleep(0)
            sleep_calls["n"] += 1
            # 第 2 次 sleep 时停掉调度器：让第 2 次 schedule_task 走失败分支
            if sleep_calls["n"] >= 2:
                scheduler._running = False

        class _PeriodicAsyncio:
            def create_task(self, coro):
                captured["coro"] = coro
                return _DummyTask()

            def sleep(self, delay):
                return fake_sleep(delay)

            def __getattr__(self, name):
                return getattr(asyncio, name)

        monkeypatch.setattr(ts, "asyncio", _PeriodicAsyncio())

        async def scenario():
            scheduler._running = True
            periodic_id = await scheduler.schedule_periodic_task(
                lambda: 1, interval=1.0, name="periodic"
            )
            await captured["coro"]
            return periodic_id

        periodic_id = asyncio.run(scenario())

        assert periodic_id.startswith("periodic_")
        assert sleep_calls["n"] == 2
        names = [entry["info"].name for entry in scheduler._tasks.values()]
        assert "periodic_run" in names


# ============================================================
# clean_completed_tasks
# ============================================================


class TestCleanCompletedTasks:
    def test_removes_only_expired_terminal_tasks(self, scheduler):
        now = time.time()
        expired = _info("expired", status=TaskStatus.COMPLETED)
        expired.end_time = now - 7200
        fresh = _info("fresh", status=TaskStatus.FAILED)
        fresh.end_time = now - 10
        running = _info("running", status=TaskStatus.RUNNING)
        no_end = _info("no_end", status=TaskStatus.CANCELLED)
        scheduler._tasks = {
            "expired": {"info": expired},
            "fresh": {"info": fresh},
            "running": {"info": running},
            "no_end": {"info": no_end},
        }

        cleaned = asyncio.run(scheduler.clean_completed_tasks(max_age=3600))

        assert cleaned == 1
        assert set(scheduler._tasks) == {"fresh", "running", "no_end"}

    def test_nothing_to_clean(self, scheduler):
        assert asyncio.run(scheduler.clean_completed_tasks()) == 0


# ============================================================
# submit_llm_task
# ============================================================


class TestSubmitLlmTask:
    @staticmethod
    def _collect(scheduler, *args, **kwargs):
        async def run():
            return [chunk async for chunk in scheduler.submit_llm_task(*args, **kwargs)]

        return asyncio.run(run())

    def test_cloud_provider_streams_and_passes_error_signal(self, scheduler, monkeypatch):
        settings = _make_settings()
        settings.model.llm = types.SimpleNamespace(provider="openai")
        monkeypatch.setattr(ts, "get_settings", lambda: settings)

        class _FakeLlm:
            async def stream_chat(self, messages, **kwargs):
                yield {"error": "rate limit"}
                yield {"content": "hello"}
                yield {"text": "world"}
                yield {"content": ""}
                yield "raw"

        import core.llm as llm_pkg

        monkeypatch.setattr(llm_pkg, "get_llm_module", lambda: _FakeLlm())

        chunks = self._collect(scheduler, "hi")

        assert chunks == [{"error": "rate limit"}, "hello", "world", "raw"]

    def test_cloud_provider_failure_yields_fallback_message(self, scheduler, monkeypatch):
        settings = _make_settings()
        settings.model.llm = types.SimpleNamespace(provider="anthropic")
        monkeypatch.setattr(ts, "get_settings", lambda: settings)

        import core.llm as llm_pkg

        def boom():
            raise RuntimeError("no llm")

        monkeypatch.setattr(llm_pkg, "get_llm_module", boom)

        chunks = self._collect(scheduler, "hi")

        assert len(chunks) == 1
        assert "云端服务暂时不可用" in chunks[0]

    def test_local_provider_without_cpp_reports_unavailable(self, scheduler, monkeypatch):
        settings = _make_settings()
        monkeypatch.setattr(ts, "get_settings", lambda: settings)
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: _FakeCpp(enabled=False))

        chunks = self._collect(scheduler, "hi", model_hint="D:/m.gguf")

        assert chunks == ["服务未就绪 (Scheduler Unavailable)"]

    def test_local_provider_cpp_streams_tokens(self, scheduler, monkeypatch):
        settings = _make_settings()
        monkeypatch.setattr(ts, "get_settings", lambda: settings)
        cpp = _FakeCpp(enabled=True, scheduler=object(), gpu_config={"model_path": "x"})
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: cpp)

        ensured = []

        async def fake_ensure(path):
            ensured.append(path)

        monkeypatch.setattr(scheduler, "_ensure_cpp_llm_ready", fake_ensure)

        chunks = self._collect(scheduler, "hi", model_hint="D:/m.gguf")

        assert chunks == ["tok1", "tok2"]
        assert ensured == ["D:/m.gguf"]
        assert cpp.last_kwargs.get("model_path") == "D:/m.gguf"

    def test_model_hint_dropped_when_model_path_present(self, scheduler, monkeypatch):
        settings = _make_settings()
        monkeypatch.setattr(ts, "get_settings", lambda: settings)
        cpp = _FakeCpp(enabled=True, scheduler=object(), gpu_config={"model_path": "x"})
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: cpp)

        ensured = []

        async def fake_ensure(path):
            ensured.append(path)

        monkeypatch.setattr(scheduler, "_ensure_cpp_llm_ready", fake_ensure)

        chunks = self._collect(
            scheduler, "hi", model_hint="IGNORED", model_path="D:/m.bin"
        )

        assert chunks == ["tok1", "tok2"]
        # .bin 不是 gguf，desired_model_path 被归一化为 None
        assert ensured == [None]
        assert "model_hint" not in cpp.last_kwargs

    def test_cpp_submit_failure_yields_busy_message(self, scheduler, monkeypatch):
        settings = _make_settings()
        monkeypatch.setattr(ts, "get_settings", lambda: settings)

        class _FailCpp(_FakeCpp):
            async def submit_llm_task(self, prompt, **kwargs):
                raise RuntimeError("engine down")
                yield  # pragma: no cover - 保持异步生成器语义

        cpp = _FailCpp(enabled=True, scheduler=object(), gpu_config={"model_path": "x"})
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: cpp)

        async def fake_ensure(path):
            return None

        monkeypatch.setattr(scheduler, "_ensure_cpp_llm_ready", fake_ensure)

        chunks = self._collect(scheduler, "hi")

        assert len(chunks) == 1
        assert "系统繁忙" in chunks[0]

    def test_ensure_failure_is_swallowed(self, scheduler, monkeypatch):
        settings = _make_settings()
        monkeypatch.setattr(ts, "get_settings", lambda: settings)
        # enabled=True 但 _gpu_config 为空：ensure 抛错后落到最终兜底
        cpp = _FakeCpp(enabled=True, scheduler=object())
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: cpp)

        async def boom(path):
            raise RuntimeError("ensure failed")

        monkeypatch.setattr(scheduler, "_ensure_cpp_llm_ready", boom)

        chunks = self._collect(scheduler, "hi")

        assert chunks == ["服务未就绪 (Scheduler Unavailable)"]


# ============================================================
# get_biological_system
# ============================================================


class TestGetBiologicalSystem:
    def test_enabled_engine_returns_bio_system(self, scheduler, monkeypatch):
        bio = object()
        cpp = _FakeCpp(enabled=True, bio=bio)
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: cpp)
        assert asyncio.run(scheduler.get_biological_system()) is bio

    def test_disabled_engine_returns_none(self, scheduler, monkeypatch):
        monkeypatch.setattr(ts, "_get_cpp_engine", lambda: _FakeCpp(enabled=False))
        assert asyncio.run(scheduler.get_biological_system()) is None


# ============================================================
# 全局单例与生命周期函数
# ============================================================


class TestGlobalHelpers:
    def test_get_global_scheduler_is_singleton(self, monkeypatch):
        monkeypatch.setattr(ts, "_global_scheduler", None)
        first = ts.get_global_scheduler()
        try:
            assert isinstance(first, GlobalTaskScheduler)
            assert ts.get_global_scheduler() is first
        finally:
            first._cpu_executor.shutdown(wait=False)

    def test_initialize_scheduler_wires_periodic_cleanup(self, monkeypatch):
        calls = {}

        class _FakeScheduler:
            async def start(self):
                calls["start"] = True

            async def clean_completed_tasks(self, max_age=3600):
                return 0

            async def schedule_periodic_task(self, func, interval, name, args):
                calls["periodic"] = (func, interval, name, args)
                return "pid"

        monkeypatch.setattr(ts, "get_global_scheduler", lambda: _FakeScheduler())
        asyncio.run(ts.initialize_scheduler())

        assert calls["start"] is True
        assert calls["periodic"][1] == 300
        assert calls["periodic"][2] == "cleanup_completed_tasks"
        assert calls["periodic"][3] == (3600,)

    def test_shutdown_scheduler_stops_and_clears(self, monkeypatch):
        stopped = {"value": False}

        class _FakeScheduler:
            async def stop(self):
                stopped["value"] = True

        monkeypatch.setattr(ts, "_global_scheduler", _FakeScheduler())
        asyncio.run(ts.shutdown_scheduler())

        assert stopped["value"] is True
        assert ts._global_scheduler is None

    def test_shutdown_scheduler_without_instance(self, monkeypatch):
        monkeypatch.setattr(ts, "_global_scheduler", None)
        asyncio.run(ts.shutdown_scheduler())
        assert ts._global_scheduler is None
