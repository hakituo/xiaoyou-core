#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cpp_scheduler_engine 主模块核心单测
====================================

目标：把 ``core/services/scheduler/cpp_scheduler_engine.py`` 推到接近 100% 行覆盖。

设计要点：
1. **不依赖真实 C++ 扩展**：``scheduler_py`` 在 CI(ubuntu) 上不存在，因此所有测试
   都通过 ``monkeypatch`` 把 ``is_cpp_scheduler_available`` 固定成确定值，或直接注入
   替身对象；不会因为缺少扩展而失败或报错。
2. **不依赖真实时间 / 不起线程 / 不 sleep**：停止事件、worker、时钟全部用 stub。
3. **不污染全局**：单例 ``CPPSchedulerEngine._instance`` 与模块级
   ``_cpp_scheduler_engine_instance`` / ``_engine_started`` 均通过 fixture 保存并恢复；
   ``sys.modules`` 注入的假 ``torch`` 也由 monkeypatch 自动还原。

运行方式::

    venv_core/Scripts/python.exe -m pytest tests/unit/test_cpp_scheduler_engine_core.py -q -n 0
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import core.services.scheduler.cpp_scheduler_engine as cse
from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine
from core.services.scheduler.utils.circuit_breaker import create_breaker_state
from core.utils.concurrency.async_locks import LazyAsyncLock


# ==================== 测试替身 ====================


class _RaisingLock:
    """进入上下文即抛异常，用于覆盖 ``except`` 兜底分支。"""

    def __enter__(self):
        raise RuntimeError("lock boom")

    def __exit__(self, *exc_info):
        return False


class _FakeWorker:
    """GPULLMWorker 替身。"""

    def __init__(self, name, init_result=True, shutdown_raises=False):
        self.name = name
        self.init_result = init_result
        self.shutdown_raises = shutdown_raises
        self.config = None
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1
        if self.shutdown_raises:
            raise RuntimeError("shutdown boom")

    def setModelConfig(self, config):
        self.config = config

    def initialize(self):
        return self.init_result


class _FakeModel:
    """资源管理器里的模型条目替身。"""

    def __init__(self, memory_usage_mb=100):
        self.device = None
        self.vram_usage_mb = None
        self.memory_usage_mb = memory_usage_mb
        self.is_offloaded = None


class _FakeResourceManager:
    def __init__(self, model=None, register_raises=False, mark_raises=False):
        self.models = {"llm_engine": model} if model is not None else {}
        self.register_raises = register_raises
        self.mark_raises = mark_raises
        self.register_calls = []
        self.mark_calls = []

    def register_model(self, **kwargs):
        if self.register_raises:
            raise RuntimeError("register boom")
        self.register_calls.append(kwargs)

    def mark_model_loaded(self, model_id, loaded):
        if self.mark_raises:
            raise RuntimeError("mark boom")
        self.mark_calls.append((model_id, loaded))


class _FakeCuda:
    def __init__(self, available=False, total_memory=None, raise_on_probe=False):
        self._available = available
        self._total = total_memory
        self._raise = raise_on_probe

    def is_available(self):
        if self._raise:
            raise RuntimeError("cuda probe failed")
        return self._available

    def get_device_properties(self, index):
        return SimpleNamespace(total_memory=self._total)


class _FakeTorch:
    def __init__(self, cuda):
        self.cuda = cuda


# ==================== 通用工具 ====================


def _new_engine(**overrides):
    """绕过 ``__init__`` 构造一个属性齐备的引擎（单测惯例）。"""
    eng = CPPSchedulerEngine.__new__(CPPSchedulerEngine)
    eng.scheduler = None
    eng.bio_system = None
    eng._enabled_checked = True
    eng._enabled_value = True
    eng._initialized = True
    eng._started = False
    eng._gpu_config = None
    eng._llm_backend = None
    eng._gpu_worker_ready = False
    eng._gpu_llm_worker = None
    eng._llm_setup_lock = LazyAsyncLock()
    eng._active_state_lock = threading.Lock()
    eng._active_python_stop_event = None
    eng._active_cpp_task_id = None
    eng._breaker_threshold = 3
    eng._breaker_min_cooldown_s = 5.0
    eng._breaker_max_cooldown_s = 60.0
    eng._breaker = create_breaker_state(5.0)
    eng._saved_llm_state = None
    eng._saved_llm_state_ts = 0.0
    eng._last_llm_stats = None
    eng.model_manager = SimpleNamespace(llm=None)
    eng.gpu_manager = SimpleNamespace(
        _prev_cpp_gpu_device_id=None,
        _prev_cpp_draft_gpu_device_id=None,
    )
    eng.lifecycle = SimpleNamespace()
    eng.inference_executor = SimpleNamespace()
    eng.health_monitor = SimpleNamespace()
    eng.bio_system_manager = SimpleNamespace()
    for key, value in overrides.items():
        setattr(eng, key, value)
    return eng


def _make_settings(
    *,
    scheduler=None,
    text_path="model.gguf",
    n_ctx=4096,
    n_batch=512,
    n_gpu_layers=-1,
    temperature=0.8,
    top_p=0.9,
    top_k=40,
    repetition_penalty=1.1,
    llm_backend="cpp",
):
    """构造 ``_build_gpu_config`` 需要的 settings 替身。"""
    model = SimpleNamespace(
        text_path=text_path,
        n_ctx=n_ctx,
        n_batch=n_batch,
        n_gpu_layers=n_gpu_layers,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        repetition_penalty=repetition_penalty,
    )
    if scheduler is None:
        scheduler = SimpleNamespace(use_cpp_for_llm=True, llm_backend=llm_backend)
    return SimpleNamespace(scheduler=scheduler, model=model)


def _set_torch(monkeypatch, cuda):
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch(cuda))


@pytest.fixture(autouse=True)
def _isolate_singleton(monkeypatch):
    """隔离单例：每个用例前后恢复 ``CPPSchedulerEngine._instance``。"""
    monkeypatch.setattr(CPPSchedulerEngine, "_instance", None)


@pytest.fixture()
def module_globals(monkeypatch):
    """隔离模块级全局实例/启动标记。"""
    monkeypatch.setattr(cse, "_cpp_scheduler_engine_instance", None)
    monkeypatch.setattr(cse, "_engine_started", False)
    return cse


# ==================== enabled / 代理属性 ====================


class TestEnabledAndProxyProperties:
    """``enabled`` 与 ``llm`` 代理属性。"""

    def test_enabled_returns_cached_value(self):
        """已检查过时直接返回缓存值。"""
        eng = _new_engine(_enabled_value=True)
        assert eng.enabled is True

        eng._enabled_value = False
        assert eng.enabled is False

    def test_enabled_probes_cpp_availability_once(self, monkeypatch):
        """首次访问触发探测，之后走缓存不再调用。"""
        probe = Mock(return_value=True)
        monkeypatch.setattr(cse, "is_cpp_scheduler_available", probe)
        eng = _new_engine(_enabled_checked=False, _enabled_value=False)

        assert eng.enabled is True
        assert eng.enabled is True
        assert probe.call_count == 1

    def test_llm_property_get_and_set(self):
        """``llm`` 读写都代理到 model_manager。"""
        eng = _new_engine()
        eng.model_manager = SimpleNamespace(llm="OLD")

        assert eng.llm == "OLD"

        eng.llm = "NEW"
        assert eng.model_manager.llm == "NEW"


# ==================== 断路器 ====================


class TestBreakerDelegation:
    """断路器方法委托。"""

    def test_breaker_lifecycle(self):
        """失败累计到阈值后熔断，成功后复位。"""
        eng = _new_engine()

        assert eng._breaker_is_open("llm") is False
        eng._breaker_on_failure("llm")
        eng._breaker_on_failure("llm")
        assert eng._breaker_is_open("llm") is False

        eng._breaker_on_failure("llm")
        assert eng._breaker_is_open("llm") is True

        eng._breaker_on_success("llm")
        assert eng._breaker_is_open("llm") is False

    def test_get_breaker_status_snapshot(self):
        """状态快照包含 llm / image 两个 key。"""
        eng = _new_engine()

        status = eng.get_breaker_status()

        assert set(status) == {"llm", "image"}
        assert status["llm"]["failures"] == 0


# ==================== 活动状态 ====================


class TestActiveStateManagement:
    """活动状态读写与异常兜底。"""

    def test_set_and_clear_python_stop_event(self):
        """只有同一个 stop_event 才会被清除。"""
        eng = _new_engine()
        ev1 = threading.Event()
        ev2 = threading.Event()

        eng._set_active_python_stop_event(ev1)
        assert eng._active_python_stop_event is ev1

        eng._clear_active_python_stop_event(ev2)
        assert eng._active_python_stop_event is ev1

        eng._clear_active_python_stop_event(ev1)
        assert eng._active_python_stop_event is None

    def test_set_active_cpp_task_id(self):
        """任务 ID 可写可清。"""
        eng = _new_engine()

        eng._set_active_cpp_task_id("task-1")
        assert eng._active_cpp_task_id == "task-1"

        eng._set_active_cpp_task_id(None)
        assert eng._active_cpp_task_id is None

    def test_state_helpers_swallow_lock_errors(self):
        """锁异常时三个 setter/clear 都不抛出。"""
        eng = _new_engine()
        eng._active_state_lock = _RaisingLock()

        eng._set_active_python_stop_event(threading.Event())
        eng._clear_active_python_stop_event(threading.Event())
        eng._set_active_cpp_task_id("task-x")

        assert eng._active_python_stop_event is None
        assert eng._active_cpp_task_id is None


class TestIsBusy:
    """``is_busy`` 各分支。"""

    def test_is_busy_false_when_disabled(self):
        """引擎未启用时恒为 False。"""
        eng = _new_engine(_enabled_value=False, _active_cpp_task_id="t")
        assert eng.is_busy() is False

    def test_is_busy_false_when_idle(self):
        """无活动状态时为 False。"""
        assert _new_engine().is_busy() is False

    def test_is_busy_true_when_python_inferencing(self):
        """有 Python 停止事件时为 True。"""
        eng = _new_engine(_active_python_stop_event=threading.Event())
        assert eng.is_busy() is True

    def test_is_busy_true_when_cpp_task_active(self):
        """有 C++ 任务时为 True。"""
        eng = _new_engine(_active_cpp_task_id="task-9")
        assert eng.is_busy() is True

    def test_is_busy_swallows_lock_error(self):
        """锁异常时安全返回 False。"""
        eng = _new_engine(_active_state_lock=_RaisingLock())
        assert eng.is_busy() is False


class TestRequestStopCurrentInference:
    """``request_stop_current_inference`` 各分支。"""

    def test_sets_event_and_cancels_cpp_task(self):
        """同时置位停止事件并取消 C++ 任务。"""
        ev = threading.Event()
        scheduler = SimpleNamespace(cancelTask=Mock())
        eng = _new_engine(
            _active_python_stop_event=ev,
            _active_cpp_task_id="task-7",
            scheduler=scheduler,
        )

        asyncio.run(eng.request_stop_current_inference())

        assert ev.is_set() is True
        scheduler.cancelTask.assert_called_once_with("task-7")

    def test_noop_when_idle(self):
        """无活动状态时不做任何事。"""
        eng = _new_engine()

        asyncio.run(eng.request_stop_current_inference())

        assert eng._active_python_stop_event is None

    def test_swallows_event_set_error(self):
        """stop_event.set() 抛异常被吞掉。"""

        class _BadEvent:
            def set(self):
                raise RuntimeError("set boom")

        eng = _new_engine(_active_python_stop_event=_BadEvent())

        asyncio.run(eng.request_stop_current_inference())

        assert eng._active_python_stop_event is not None

    def test_swallows_cancel_task_error(self):
        """cancelTask 抛异常被吞掉。"""
        scheduler = SimpleNamespace(cancelTask=Mock(side_effect=RuntimeError("boom")))
        eng = _new_engine(_active_cpp_task_id="task-8", scheduler=scheduler)

        asyncio.run(eng.request_stop_current_inference())

        scheduler.cancelTask.assert_called_once_with("task-8")

    def test_skips_cancel_without_scheduler(self):
        """有任务 ID 但 scheduler 为 None 时跳过取消。"""
        eng = _new_engine(_active_cpp_task_id="task-9", scheduler=None)

        asyncio.run(eng.request_stop_current_inference())

        assert eng.scheduler is None

    def test_swallows_lock_error(self):
        """取锁异常时走兜底分支并安全返回。"""
        eng = _new_engine(_active_state_lock=_RaisingLock())

        asyncio.run(eng.request_stop_current_inference())

        assert eng._active_cpp_task_id is None


# ==================== 健康检查 / 重启 代理 ====================


class TestHealthDelegation:
    """``_restart_scheduler`` / ``_health_check_gpu_worker`` 委托。"""

    def test_restart_scheduler_delegates(self):
        """重启委托给 health_monitor。"""
        eng = _new_engine()
        eng.health_monitor = SimpleNamespace(restart_scheduler=AsyncMock(return_value=True))

        assert asyncio.run(eng._restart_scheduler()) is True
        eng.health_monitor.restart_scheduler.assert_awaited_once()

    def test_health_check_gpu_worker_delegates(self):
        """健康检查委托给 health_monitor。"""
        eng = _new_engine()
        eng.health_monitor = SimpleNamespace(
            health_check_gpu_worker=AsyncMock(return_value=False)
        )

        assert asyncio.run(eng._health_check_gpu_worker()) is False


# ==================== 模型切换 ====================


class TestMaybeSwitchCppModel:
    """``_maybe_switch_cpp_model`` 前置条件与切换流程。"""

    @pytest.fixture(autouse=True)
    def _identity_normalize(self, monkeypatch):
        """路径规范化替换成恒等函数，保证断言与文件系统无关。"""
        llm_utils = importlib.import_module("core.modules.llm.utils")

        monkeypatch.setattr(llm_utils, "normalize_local_path", lambda p: str(p))

    def test_false_when_disabled(self):
        """引擎未启用直接返回 False。"""
        eng = _new_engine(_enabled_value=False)

        assert asyncio.run(eng._maybe_switch_cpp_model("/m/a.gguf")) is False

    def test_false_when_backend_not_cpp(self):
        """非 cpp 后端直接返回 False。"""
        eng = _new_engine(_llm_backend="python", _gpu_config={})

        assert asyncio.run(eng._maybe_switch_cpp_model("/m/a.gguf")) is False

    def test_false_when_gpu_config_not_dict(self):
        """GPU 配置缺失直接返回 False。"""
        eng = _new_engine(_llm_backend="cpp", _gpu_config=None)

        assert asyncio.run(eng._maybe_switch_cpp_model("/m/a.gguf")) is False

    def test_false_when_requested_path_not_str(self):
        """请求路径非字符串直接返回 False。"""
        eng = _new_engine(_llm_backend="cpp", _gpu_config={})

        assert asyncio.run(eng._maybe_switch_cpp_model(None)) is False

    def test_false_when_requested_path_not_gguf(self):
        """空路径或非 .gguf 直接返回 False。"""
        eng = _new_engine(_llm_backend="cpp", _gpu_config={})

        assert asyncio.run(eng._maybe_switch_cpp_model("")) is False
        assert asyncio.run(eng._maybe_switch_cpp_model("/m/a.bin")) is False

    def test_false_when_already_loaded(self):
        """归一化后路径相同则视为已加载。"""
        eng = _new_engine(
            _llm_backend="cpp", _gpu_config={"model_path": "/m/a.gguf"}
        )

        assert asyncio.run(eng._maybe_switch_cpp_model("/m/a.gguf")) is False

    def test_switches_model_and_resets_worker(self):
        """路径变化时更新配置并重建 GPU worker。"""
        scheduler = SimpleNamespace()
        eng = _new_engine(
            _llm_backend="cpp",
            _gpu_config={"model_path": "/m/old.gguf"},
            _gpu_worker_ready=True,
            scheduler=scheduler,
        )
        setup = Mock()
        eng._setup_gpu_worker = setup

        assert asyncio.run(eng._maybe_switch_cpp_model("/m/new.gguf")) is True

        assert eng._gpu_config["model_path"] == "/m/new.gguf"
        assert eng._gpu_worker_ready is False
        setup.assert_called_once_with(eng._gpu_config)

    def test_switches_without_scheduler_skips_worker_setup(self):
        """scheduler 为 None 时只改配置，不重建 worker。"""
        eng = _new_engine(
            _llm_backend="cpp",
            _gpu_config={"model_path": "/m/old.gguf"},
            scheduler=None,
        )
        setup = Mock()
        eng._setup_gpu_worker = setup

        assert asyncio.run(eng._maybe_switch_cpp_model("/m/new.gguf")) is True
        setup.assert_not_called()

    def test_false_when_model_changed_during_stop(self):
        """停止推理期间模型已被切走 → 二次检查返回 False。"""
        eng = _new_engine(
            _llm_backend="cpp",
            _gpu_config={"model_path": "/m/old.gguf"},
            scheduler=SimpleNamespace(),
        )

        async def _fake_stop():
            # 模拟并发切换把 model_path 改成目标值
            eng._gpu_config["model_path"] = "/m/new.gguf"

        eng.request_stop_current_inference = _fake_stop

        assert asyncio.run(eng._maybe_switch_cpp_model("/m/new.gguf")) is False


# ==================== 生命周期 / 模型管理代理 ====================


class TestLifecycleProxy:
    """生命周期代理方法。"""

    def test_start_proxies(self):
        """``start`` 原样转发参数。"""
        eng = _new_engine()
        eng.lifecycle = SimpleNamespace(start=Mock(return_value="ok"))

        assert eng.start(2, {"a": 1}, True) == "ok"
        eng.lifecycle.start.assert_called_once_with(2, {"a": 1}, True)

    def test_apply_llm_config_proxies(self):
        """``apply_llm_config`` 转发并 await。"""
        eng = _new_engine()
        eng.lifecycle = SimpleNamespace(apply_llm_config=AsyncMock(return_value=True))

        assert asyncio.run(eng.apply_llm_config({"a": 1}, 3, True)) is True
        eng.lifecycle.apply_llm_config.assert_awaited_once_with({"a": 1}, 3, True)

    def test_stop_proxies(self):
        """``stop`` 转发并 await。"""
        eng = _new_engine()
        eng.lifecycle = SimpleNamespace(stop=AsyncMock(return_value=None))

        asyncio.run(eng.stop())

        eng.lifecycle.stop.assert_awaited_once()

    def test_get_status_proxies(self):
        """``get_status`` 原样返回。"""
        eng = _new_engine()
        eng.lifecycle = SimpleNamespace(get_status=Mock(return_value={"enabled": True}))

        assert eng.get_status() == {"enabled": True}


class TestReloadAndPreloadLLM:
    """``_reload_llm`` / ``preload_llm`` / ``unload_llm``。"""

    def test_reload_noop_without_gpu_config(self):
        """无 GPU 配置时直接返回。"""
        eng = _new_engine(_gpu_config=None)
        eng._setup_python_llm = Mock()

        asyncio.run(eng._reload_llm())

        eng._setup_python_llm.assert_not_called()

    def test_reload_cpp_backend_builds_worker(self, monkeypatch):
        """cpp 后端且 worker 未就绪时重建 worker。"""
        offload = AsyncMock()
        monkeypatch.setattr(cse, "offload_tts_services", offload)
        eng = _new_engine(
            _gpu_config={"model_path": "/m/a.gguf"},
            _llm_backend="cpp",
            _gpu_worker_ready=False,
        )
        setup = Mock()
        eng._setup_gpu_worker = setup

        asyncio.run(eng._reload_llm())

        offload.assert_awaited_once_with("CPPScheduler")
        setup.assert_called_once_with(eng._gpu_config)

    def test_reload_cpp_backend_skips_ready_worker(self, monkeypatch):
        """cpp 后端 worker 已就绪时不重建。"""
        monkeypatch.setattr(cse, "offload_tts_services", AsyncMock())
        eng = _new_engine(
            _gpu_config={"model_path": "/m/a.gguf"},
            _llm_backend="cpp",
            _gpu_worker_ready=True,
        )
        setup = Mock()
        eng._setup_gpu_worker = setup

        asyncio.run(eng._reload_llm())

        setup.assert_not_called()

    def test_reload_python_backend_loads_missing_llm(self, monkeypatch):
        """python 后端且 llm 为空时加载。"""
        monkeypatch.setattr(cse, "offload_tts_services", AsyncMock())
        eng = _new_engine(
            _gpu_config={"model_path": "/m/a.gguf"},
            _llm_backend="python",
        )
        eng.model_manager = SimpleNamespace(llm=None)
        setup = Mock()
        eng._setup_python_llm = setup

        asyncio.run(eng._reload_llm())

        setup.assert_called_once_with(eng._gpu_config)

    def test_reload_python_backend_keeps_existing_llm(self, monkeypatch):
        """python 后端已有 llm 实例时不重复加载。"""
        monkeypatch.setattr(cse, "offload_tts_services", AsyncMock())
        eng = _new_engine(
            _gpu_config={"model_path": "/m/a.gguf"},
            _llm_backend="python",
        )
        eng.model_manager = SimpleNamespace(llm=object())
        setup = Mock()
        eng._setup_python_llm = setup

        asyncio.run(eng._reload_llm())

        setup.assert_not_called()

    def test_preload_llm_returns_when_disabled(self):
        """未启用时不预加载。"""
        eng = _new_engine(_enabled_value=False, _gpu_config={"model_path": "a"})
        reload_mock = AsyncMock()
        eng._reload_llm = reload_mock

        asyncio.run(eng.preload_llm())

        reload_mock.assert_not_awaited()

    def test_preload_llm_returns_without_gpu_config(self):
        """无 GPU 配置时不预加载。"""
        eng = _new_engine(_gpu_config=None)
        reload_mock = AsyncMock()
        eng._reload_llm = reload_mock

        asyncio.run(eng.preload_llm())

        reload_mock.assert_not_awaited()

    def test_preload_llm_calls_reload(self):
        """有配置时委托 ``_reload_llm``。"""
        eng = _new_engine(_gpu_config={"model_path": "a"})
        reload_mock = AsyncMock()
        eng._reload_llm = reload_mock

        asyncio.run(eng.preload_llm())

        reload_mock.assert_awaited_once()

    def test_unload_llm_delegates(self):
        """卸载委托 model_manager。"""
        eng = _new_engine()
        eng.model_manager = SimpleNamespace(unload_llm=AsyncMock())

        asyncio.run(eng.unload_llm())

        eng.model_manager.unload_llm.assert_awaited_once()

    def test_setup_python_llm_delegates(self):
        """``_setup_python_llm`` 转发 return_instance。"""
        eng = _new_engine()
        mm = SimpleNamespace(setup_python_llm=Mock(return_value="INST"))
        eng.model_manager = mm

        assert eng._setup_python_llm({"a": 1}, True) == "INST"
        mm.setup_python_llm.assert_called_once_with({"a": 1}, True)


# ==================== GPU Worker 装配 ====================


class TestSetupGpuWorker:
    """``_setup_gpu_worker`` 各分支。"""

    def test_raises_without_scheduler(self):
        """没有调度器时走异常兜底并把 ready 置 False。"""
        eng = _new_engine(scheduler=None, _gpu_worker_ready=True)

        eng._setup_gpu_worker({"model_path": "/m/a.gguf"})

        assert eng._gpu_worker_ready is False

    def test_creates_and_registers_new_worker(self, monkeypatch):
        """首次创建 worker 并注册到调度器。"""
        created = {}

        def _factory(name):
            created["worker"] = _FakeWorker(name)
            return created["worker"]

        monkeypatch.setattr(
            "core.services.scheduler.scheduler_wrapper._get_scheduler_class",
            lambda cls_name: _factory if cls_name == "GPULLMWorker" else None,
        )
        rm = _FakeResourceManager(model=_FakeModel())
        monkeypatch.setattr("core.resource_manager.get_resource_manager", lambda: rm)

        scheduler = SimpleNamespace(addWorker=Mock())
        eng = _new_engine(scheduler=scheduler)
        eng.model_manager = SimpleNamespace(
            llm=None, _build_cpp_llm_config=lambda cfg: {"built": cfg}
        )

        eng._setup_gpu_worker({"model_path": "/m/a.gguf"})

        worker = created["worker"]
        assert worker.name == "gpu-worker-0"
        assert worker.config == {"built": {"model_path": "/m/a.gguf"}}
        scheduler.addWorker.assert_called_once_with(worker)
        assert eng._gpu_worker_ready is True
        assert rm.mark_calls == [("llm_engine", True)]

    def test_reuses_existing_worker_without_register(self, monkeypatch):
        """已有 worker 时复用，不再 addWorker；shutdown 异常被吞掉。"""
        existing = _FakeWorker("gpu-worker-0", shutdown_raises=True)
        monkeypatch.setattr(
            "core.services.scheduler.scheduler_wrapper._get_scheduler_class",
            lambda cls_name: _FakeWorker,
        )
        monkeypatch.setattr(
            "core.resource_manager.get_resource_manager",
            lambda: _FakeResourceManager(model=_FakeModel()),
        )

        scheduler = SimpleNamespace(addWorker=Mock())
        eng = _new_engine(scheduler=scheduler, _gpu_llm_worker=existing)
        eng.model_manager = SimpleNamespace(
            llm=None, _build_cpp_llm_config=lambda cfg: cfg
        )

        eng._setup_gpu_worker({"model_path": "/m/a.gguf"})

        assert existing.shutdown_calls == 1
        scheduler.addWorker.assert_not_called()
        assert eng._gpu_worker_ready is True

    def test_initialize_failure_marks_not_ready(self, monkeypatch):
        """worker.initialize() 返回假时 ready 置 False。"""
        monkeypatch.setattr(
            "core.services.scheduler.scheduler_wrapper._get_scheduler_class",
            lambda cls_name: _FakeWorker,
        )
        monkeypatch.setattr(
            "core.resource_manager.get_resource_manager",
            lambda: _FakeResourceManager(model=_FakeModel()),
        )

        scheduler = SimpleNamespace(addWorker=Mock())
        eng = _new_engine(
            scheduler=scheduler,
            _gpu_llm_worker=_FakeWorker("w", init_result=False),
        )
        eng.model_manager = SimpleNamespace(
            llm=None, _build_cpp_llm_config=lambda cfg: cfg
        )

        eng._setup_gpu_worker({"model_path": "/m/a.gguf"})

        assert eng._gpu_worker_ready is False
        scheduler.addWorker.assert_not_called()

    def test_resource_manager_failure_is_swallowed(self, monkeypatch):
        """资源管理器上报失败不影响 worker 就绪。"""
        monkeypatch.setattr(
            "core.services.scheduler.scheduler_wrapper._get_scheduler_class",
            lambda cls_name: _FakeWorker,
        )
        rm = _FakeResourceManager(model=_FakeModel(), mark_raises=True)
        monkeypatch.setattr("core.resource_manager.get_resource_manager", lambda: rm)

        eng = _new_engine(
            scheduler=SimpleNamespace(addWorker=Mock()),
            _gpu_llm_worker=_FakeWorker("w"),
        )
        eng.model_manager = SimpleNamespace(
            llm=None, _build_cpp_llm_config=lambda cfg: cfg
        )

        eng._setup_gpu_worker({"model_path": "/m/a.gguf"})

        assert eng._gpu_worker_ready is True


# ==================== 显存卸载 / 回迁 ====================


class TestOffloadRestoreProxy:
    """``offload_llm_to_cpu`` 代理与 python 回迁。"""

    def test_offload_cpp_backend_releases_vram(self):
        """cpp 后端走 release_llm_vram_for_image_gen。"""
        eng = _new_engine(_llm_backend="cpp")
        release = AsyncMock()
        eng.release_llm_vram_for_image_gen = release
        eng.gpu_manager = SimpleNamespace(offload_llm_to_cpu=AsyncMock())

        asyncio.run(eng.offload_llm_to_cpu(urgent=True))

        release.assert_awaited_once()
        eng.gpu_manager.offload_llm_to_cpu.assert_not_awaited()

    def test_offload_python_backend_delegates(self):
        """非 cpp 后端委托 gpu_manager。"""
        eng = _new_engine(_llm_backend="python")
        eng.gpu_manager = SimpleNamespace(offload_llm_to_cpu=AsyncMock())

        asyncio.run(eng.offload_llm_to_cpu(urgent=True))

        eng.gpu_manager.offload_llm_to_cpu.assert_awaited_once_with(True)

    def test_restore_python_backend_delegates(self):
        """非 cpp 后端回迁委托 gpu_manager。"""
        eng = _new_engine(_llm_backend="python")
        eng.gpu_manager = SimpleNamespace(
            restore_llm_to_gpu=AsyncMock(return_value=True)
        )

        assert asyncio.run(eng.restore_llm_to_gpu()) is True

    def test_kv_cache_proxies(self):
        """KV Cache 卸载/回迁委托 gpu_manager。"""
        eng = _new_engine()
        eng.gpu_manager = SimpleNamespace(
            offload_kv_cache_to_cpu=AsyncMock(return_value=True),
            restore_kv_cache_to_gpu=AsyncMock(return_value=False),
        )

        assert asyncio.run(eng.offload_kv_cache_to_cpu()) is True
        assert asyncio.run(eng.restore_kv_cache_to_gpu()) is False


class TestRestoreLlmToGpuCpp:
    """``restore_llm_to_gpu`` 的 cpp 分支。"""

    def test_uses_prev_device_ids(self):
        """优先使用上次记录的设备号。"""
        eng = _new_engine(
            _llm_backend="cpp",
            _gpu_config={"gpu_device_id": 9, "draft_gpu_device_id": 8},
        )
        eng.gpu_manager = SimpleNamespace(
            _prev_cpp_gpu_device_id=2, _prev_cpp_draft_gpu_device_id=1
        )
        switch = AsyncMock(return_value=True)
        eng._switch_cpp_llm_worker_device = switch

        assert asyncio.run(eng.restore_llm_to_gpu()) is True
        switch.assert_awaited_once_with(2, 1)

    def test_falls_back_to_gpu_config(self):
        """无历史记录时从 gpu_config 取设备号。"""
        eng = _new_engine(
            _llm_backend="cpp",
            _gpu_config={"gpu_device_id": 1, "draft_gpu_device_id": 3},
        )
        switch = AsyncMock(return_value=True)
        eng._switch_cpp_llm_worker_device = switch

        assert asyncio.run(eng.restore_llm_to_gpu()) is True
        switch.assert_awaited_once_with(1, 3)

    def test_bad_config_values_fall_back_to_defaults(self):
        """非法配置值回退到 0 / -1。"""
        eng = _new_engine(
            _llm_backend="cpp",
            _gpu_config={"gpu_device_id": "abc", "draft_gpu_device_id": "xyz"},
        )
        switch = AsyncMock(return_value=True)
        eng._switch_cpp_llm_worker_device = switch

        assert asyncio.run(eng.restore_llm_to_gpu()) is True
        switch.assert_awaited_once_with(0, -1)

    def test_negative_gpu_id_falls_back_to_zero(self):
        """负的 gpu_device_id 回退到 0。"""
        eng = _new_engine(_llm_backend="cpp", _gpu_config={"gpu_device_id": -5})
        switch = AsyncMock(return_value=True)
        eng._switch_cpp_llm_worker_device = switch

        assert asyncio.run(eng.restore_llm_to_gpu()) is True
        switch.assert_awaited_once_with(0, -1)

    def test_reports_failure(self):
        """切换失败时返回 False。"""
        eng = _new_engine(_llm_backend="cpp", _gpu_config={"gpu_device_id": 0})
        eng._switch_cpp_llm_worker_device = AsyncMock(return_value=False)

        assert asyncio.run(eng.restore_llm_to_gpu()) is False


class TestReleaseLlmVramForImageGen:
    """``release_llm_vram_for_image_gen`` 各分支。"""

    def test_python_backend_offloads_urgently(self):
        """python 后端触发紧急卸载。"""
        eng = _new_engine(_llm_backend="python")
        offload = AsyncMock()
        eng.offload_llm_to_cpu = offload

        asyncio.run(eng.release_llm_vram_for_image_gen())

        offload.assert_awaited_once_with(urgent=True)

    def test_cpp_without_gpu_config_returns(self):
        """cpp 后端但无配置时直接返回。"""
        eng = _new_engine(_llm_backend="cpp", _gpu_config=None)
        switch = AsyncMock()
        eng._switch_cpp_llm_worker_device = switch

        asyncio.run(eng.release_llm_vram_for_image_gen())

        switch.assert_not_awaited()

    def test_cpp_switches_worker_to_cpu(self):
        """记录原设备号并切到 CPU。"""
        eng = _new_engine(
            _llm_backend="cpp",
            _gpu_config={"gpu_device_id": 0, "draft_gpu_device_id": -1},
        )
        switch = AsyncMock(return_value=True)
        eng._switch_cpp_llm_worker_device = switch

        asyncio.run(eng.release_llm_vram_for_image_gen())

        assert eng.gpu_manager._prev_cpp_gpu_device_id == 0
        assert eng.gpu_manager._prev_cpp_draft_gpu_device_id == -1
        switch.assert_awaited_once_with(-1, -1)

    def test_cpp_warns_when_switch_fails(self):
        """切换失败时只告警不抛异常。"""
        eng = _new_engine(_llm_backend="cpp", _gpu_config={"gpu_device_id": 0})
        eng._switch_cpp_llm_worker_device = AsyncMock(return_value=False)

        asyncio.run(eng.release_llm_vram_for_image_gen())

        assert eng.gpu_manager._prev_cpp_gpu_device_id == 0

    def test_cpp_cpu_only_updates_resource_manager(self, monkeypatch):
        """gpu_device_id 为负时仅更新资源管理器状态后返回。"""
        model = _FakeModel()
        rm = _FakeResourceManager(model=model)
        eng = _new_engine(_llm_backend="cpp", _gpu_config={"gpu_device_id": -1})
        eng._switch_cpp_llm_worker_device = AsyncMock()
        monkeypatch.setattr("core.resource_manager.get_resource_manager", lambda: rm)

        asyncio.run(eng.release_llm_vram_for_image_gen())

        assert model.device == "CPU"
        assert model.vram_usage_mb == 0
        assert rm.mark_calls == [("llm_engine", True)]
        eng._switch_cpp_llm_worker_device.assert_not_awaited()

    def test_cpp_cpu_only_without_model_entry(self, monkeypatch):
        """资源管理器里没有 llm_engine 条目时安全返回。"""
        rm = _FakeResourceManager(model=None)
        eng = _new_engine(_llm_backend="cpp", _gpu_config={"gpu_device_id": -1})
        eng._switch_cpp_llm_worker_device = AsyncMock()
        monkeypatch.setattr("core.resource_manager.get_resource_manager", lambda: rm)

        asyncio.run(eng.release_llm_vram_for_image_gen())

        assert rm.mark_calls == [("llm_engine", True)]
        eng._switch_cpp_llm_worker_device.assert_not_awaited()

    def test_cpp_cpu_only_swallows_resource_manager_error(self, monkeypatch):
        """资源管理器抛异常时静默返回。"""

        def _boom():
            raise RuntimeError("rm boom")

        eng = _new_engine(_llm_backend="cpp", _gpu_config={"gpu_device_id": -1})
        eng._switch_cpp_llm_worker_device = AsyncMock()
        monkeypatch.setattr("core.resource_manager.get_resource_manager", _boom)

        asyncio.run(eng.release_llm_vram_for_image_gen())

        eng._switch_cpp_llm_worker_device.assert_not_awaited()

    def test_cpp_invalid_device_ids_are_ignored(self):
        """设备号无法转 int 时按 None 处理，仍执行切换。"""
        eng = _new_engine(
            _llm_backend="cpp",
            _gpu_config={"gpu_device_id": "bad", "draft_gpu_device_id": "worse"},
        )
        switch = AsyncMock(return_value=True)
        eng._switch_cpp_llm_worker_device = switch

        asyncio.run(eng.release_llm_vram_for_image_gen())

        assert eng.gpu_manager._prev_cpp_gpu_device_id is None
        assert eng.gpu_manager._prev_cpp_draft_gpu_device_id is None
        switch.assert_awaited_once_with(-1, -1)


class TestSwitchCppLlmWorkerDevice:
    """``_switch_cpp_llm_worker_device`` 各分支。"""

    def test_false_when_backend_not_cpp(self):
        """非 cpp 后端返回 False。"""
        eng = _new_engine(_llm_backend="python", scheduler=SimpleNamespace())

        assert asyncio.run(eng._switch_cpp_llm_worker_device(0)) is False

    def test_false_without_scheduler(self):
        """无调度器返回 False。"""
        eng = _new_engine(_llm_backend="cpp", scheduler=None)

        assert asyncio.run(eng._switch_cpp_llm_worker_device(0)) is False

    def test_false_when_gpu_config_not_dict(self):
        """配置不是 dict 返回 False。"""
        eng = _new_engine(
            _llm_backend="cpp", scheduler=SimpleNamespace(), _gpu_config=None
        )

        assert asyncio.run(eng._switch_cpp_llm_worker_device(0)) is False

    def test_false_without_worker(self):
        """没有 worker 返回 False。"""
        eng = _new_engine(
            _llm_backend="cpp",
            scheduler=SimpleNamespace(),
            _gpu_config={"gpu_device_id": 0},
            _gpu_llm_worker=None,
        )

        assert asyncio.run(eng._switch_cpp_llm_worker_device(0)) is False

    def test_switch_to_gpu_updates_model_state(self, monkeypatch):
        """切到 GPU 时更新模型设备状态。"""
        model = _FakeModel()
        rm = _FakeResourceManager(model=model)
        monkeypatch.setattr("core.resource_manager.get_resource_manager", lambda: rm)

        worker = _FakeWorker("w")
        eng = _new_engine(
            _llm_backend="cpp",
            scheduler=SimpleNamespace(),
            _gpu_config={"gpu_device_id": 0, "draft_gpu_device_id": -1},
            _gpu_llm_worker=worker,
        )
        eng.model_manager = SimpleNamespace(_build_cpp_llm_config=lambda cfg: {"cfg": cfg})
        eng.request_stop_current_inference = AsyncMock()

        assert asyncio.run(eng._switch_cpp_llm_worker_device(0, -1)) is True

        assert eng._gpu_config["gpu_device_id"] == 0
        assert eng._gpu_worker_ready is True
        assert model.device == "GPU"
        assert model.is_offloaded is False
        assert rm.mark_calls == [("llm_engine", True)]

    def test_switch_to_cpu_updates_model_state(self, monkeypatch):
        """切到 CPU 时标记 offloaded 并抬高内存占用。"""
        model = _FakeModel(memory_usage_mb=100)
        rm = _FakeResourceManager(model=model)
        monkeypatch.setattr("core.resource_manager.get_resource_manager", lambda: rm)

        eng = _new_engine(
            _llm_backend="cpp",
            scheduler=SimpleNamespace(),
            _gpu_config={"gpu_device_id": 0},
            _gpu_llm_worker=_FakeWorker("w", init_result=False),
        )
        eng.model_manager = SimpleNamespace(_build_cpp_llm_config=lambda cfg: cfg)
        eng.request_stop_current_inference = AsyncMock()

        assert asyncio.run(eng._switch_cpp_llm_worker_device(-1, -1)) is False

        assert model.device == "CPU"
        assert model.vram_usage_mb == 0
        assert model.memory_usage_mb == 450
        assert model.is_offloaded is True
        assert rm.mark_calls == [("llm_engine", False)]

    def test_swallows_resource_manager_error(self, monkeypatch):
        """资源管理器异常不影响返回值。"""
        monkeypatch.setattr(
            "core.resource_manager.get_resource_manager",
            lambda: _FakeResourceManager(model=_FakeModel(), mark_raises=True),
        )
        eng = _new_engine(
            _llm_backend="cpp",
            scheduler=SimpleNamespace(),
            _gpu_config={"gpu_device_id": 0},
            _gpu_llm_worker=_FakeWorker("w"),
        )
        eng.model_manager = SimpleNamespace(_build_cpp_llm_config=lambda cfg: cfg)
        eng.request_stop_current_inference = AsyncMock()

        assert asyncio.run(eng._switch_cpp_llm_worker_device(0)) is True

    def test_swallows_stop_and_shutdown_errors(self, monkeypatch):
        """停止推理与 worker.shutdown 抛异常都被吞掉。"""
        monkeypatch.setattr(
            "core.resource_manager.get_resource_manager",
            lambda: _FakeResourceManager(model=None),
        )
        eng = _new_engine(
            _llm_backend="cpp",
            scheduler=SimpleNamespace(),
            _gpu_config={"gpu_device_id": 0},
            _gpu_llm_worker=_FakeWorker("w", shutdown_raises=True),
        )
        eng.model_manager = SimpleNamespace(_build_cpp_llm_config=lambda cfg: cfg)

        async def _boom():
            raise RuntimeError("stop boom")

        eng.request_stop_current_inference = _boom

        assert asyncio.run(eng._switch_cpp_llm_worker_device(0)) is True


# ==================== 会话 KV Cache 清理 ====================


class TestClearConversationCache:
    """``clear_conversation_cache`` 各分支。"""

    def test_false_for_empty_id(self):
        """空会话 ID 返回 False。"""
        eng = _new_engine(_llm_backend="cpp")

        assert asyncio.run(eng.clear_conversation_cache("  ")) is False

    def test_false_for_non_cpp_backend(self):
        """非 cpp 后端返回 False。"""
        eng = _new_engine(_llm_backend="python")

        assert asyncio.run(eng.clear_conversation_cache("c1")) is False

    def test_false_without_worker_interface(self):
        """worker 未提供清理接口时返回 False。"""
        eng = _new_engine(_llm_backend="cpp", _gpu_llm_worker=None)

        assert asyncio.run(eng.clear_conversation_cache("c1")) is False

    def test_success_returns_true(self):
        """清理成功返回 True 并传入归一化 ID。"""
        clear = Mock(return_value=True)
        eng = _new_engine(
            _llm_backend="cpp",
            _gpu_llm_worker=SimpleNamespace(clearConversationCache=clear),
        )

        assert asyncio.run(eng.clear_conversation_cache("  c1  ")) is True
        clear.assert_called_once_with("c1")

    def test_returns_false_when_not_cleared(self):
        """底层返回假时返回 False。"""
        eng = _new_engine(
            _llm_backend="cpp",
            _gpu_llm_worker=SimpleNamespace(clearConversationCache=Mock(return_value=False)),
        )

        assert asyncio.run(eng.clear_conversation_cache("c1")) is False

    def test_swallows_exception(self):
        """底层抛异常时返回 False。"""
        eng = _new_engine(
            _llm_backend="cpp",
            _gpu_llm_worker=SimpleNamespace(
                clearConversationCache=Mock(side_effect=RuntimeError("boom"))
            ),
        )

        assert asyncio.run(eng.clear_conversation_cache("c1")) is False


# ==================== 其它代理 ====================


class TestMiscDelegation:
    """推理提交与生物系统/统计代理。"""

    def test_submit_llm_task_streams_from_executor(self):
        """``submit_llm_task`` 逐个转发 executor 的 token。"""

        async def _fake_gen(prompt, **kwargs):
            yield f"{prompt}-0"
            yield f"{prompt}-1"

        eng = _new_engine()
        eng.inference_executor = SimpleNamespace(submit_llm_task=_fake_gen)

        async def _collect():
            return [tok async for tok in eng.submit_llm_task("hi")]

        assert asyncio.run(_collect()) == ["hi-0", "hi-1"]

    def test_get_biological_system_delegates(self):
        """生物系统查询委托 bio_system_manager。"""
        eng = _new_engine()
        eng.bio_system_manager = SimpleNamespace(
            get_biological_system=Mock(return_value="BIO")
        )

        assert eng.get_biological_system() == "BIO"

    def test_get_last_llm_stats(self):
        """统计信息读实例属性。"""
        eng = _new_engine(_last_llm_stats={"backend": "cpp"})
        assert eng.get_last_llm_stats() == {"backend": "cpp"}

        eng._last_llm_stats = None
        assert eng.get_last_llm_stats() is None


# ==================== __init__ ====================


class TestInit:
    """``__init__`` 各分支（真实构造，结束后关闭线程池）。"""

    def _construct(self):
        eng = CPPSchedulerEngine()
        return eng

    def test_disabled_engine_skips_registration(self, monkeypatch):
        """未启用时不注册 LLM 资源。"""
        monkeypatch.setattr(cse, "is_cpp_scheduler_available", lambda: False)
        eng = self._construct()
        try:
            assert eng._initialized is True
            assert eng.scheduler is None
            assert eng._gpu_worker_ready is False
            assert set(eng._breaker) == {"llm", "image"}
            assert eng._breaker_threshold == 3
        finally:
            eng.model_manager.shutdown()

    def test_enabled_engine_registers_llm(self, monkeypatch):
        """启用且配置指向 gguf 时注册 llm_engine。"""
        monkeypatch.setattr(cse, "is_cpp_scheduler_available", lambda: True)
        settings = SimpleNamespace(
            scheduler=SimpleNamespace(use_cpp=True, use_cpp_for_llm=True)
        )
        monkeypatch.setattr(
            "config.integrated_config.get_settings", lambda: settings
        )
        monkeypatch.setattr(cse, "get_config", lambda *a, **k: "/m/text.gguf")

        rm = _FakeResourceManager()
        monkeypatch.setattr("core.resource_manager.get_resource_manager", lambda: rm)

        eng = self._construct()
        try:
            assert len(rm.register_calls) == 1
            call = rm.register_calls[0]
            assert call["model_id"] == "llm_engine"
            assert call["model_type"] == "llm"
            assert call["instance"] is eng
        finally:
            eng.model_manager.shutdown()

    def test_enabled_engine_skips_registration_when_settings_raise(self, monkeypatch):
        """读取设置异常时降级为不注册。"""
        monkeypatch.setattr(cse, "is_cpp_scheduler_available", lambda: True)

        def _boom():
            raise RuntimeError("settings boom")

        monkeypatch.setattr("config.integrated_config.get_settings", _boom)
        rm = _FakeResourceManager()
        monkeypatch.setattr("core.resource_manager.get_resource_manager", lambda: rm)

        eng = self._construct()
        try:
            assert rm.register_calls == []
        finally:
            eng.model_manager.shutdown()

    def test_enabled_engine_skips_registration_for_non_gguf(self, monkeypatch):
        """文本模型不是 gguf 时不注册。"""
        monkeypatch.setattr(cse, "is_cpp_scheduler_available", lambda: True)
        settings = SimpleNamespace(
            scheduler=SimpleNamespace(use_cpp=True, use_cpp_for_llm=True)
        )
        monkeypatch.setattr("config.integrated_config.get_settings", lambda: settings)
        monkeypatch.setattr(cse, "get_config", lambda *a, **k: "/m/text.bin")
        rm = _FakeResourceManager()
        monkeypatch.setattr("core.resource_manager.get_resource_manager", lambda: rm)

        eng = self._construct()
        try:
            assert rm.register_calls == []
        finally:
            eng.model_manager.shutdown()

    def test_registration_failure_is_logged(self, monkeypatch):
        """注册抛异常时不影响构造。"""
        monkeypatch.setattr(cse, "is_cpp_scheduler_available", lambda: True)
        settings = SimpleNamespace(
            scheduler=SimpleNamespace(use_cpp=True, use_cpp_for_llm=True)
        )
        monkeypatch.setattr("config.integrated_config.get_settings", lambda: settings)
        monkeypatch.setattr(cse, "get_config", lambda *a, **k: "/m/text.gguf")
        rm = _FakeResourceManager(register_raises=True)
        monkeypatch.setattr("core.resource_manager.get_resource_manager", lambda: rm)

        eng = self._construct()
        try:
            assert eng._initialized is True
        finally:
            eng.model_manager.shutdown()

    def test_init_is_idempotent(self, monkeypatch):
        """重复 ``__init__`` 直接返回，不重置状态。"""
        monkeypatch.setattr(cse, "is_cpp_scheduler_available", lambda: False)
        eng = self._construct()
        try:
            eng._marker = "keep"
            eng.__init__()
            assert eng._marker == "keep"
        finally:
            eng.model_manager.shutdown()


# ==================== 模块级函数 ====================


class TestGetSchedulerEngine:
    """``get_scheduler_engine`` 与自动启动。"""

    def test_creates_instance_once(self, monkeypatch, module_globals):
        """首次调用创建实例，之后复用。"""
        created = []

        class _StubEngine:
            enabled = False

            def __init__(self):
                created.append(self)

        monkeypatch.setattr(cse, "CPPSchedulerEngine", _StubEngine)

        first = cse.get_scheduler_engine()
        second = cse.get_scheduler_engine()

        assert first is second
        assert len(created) == 1

    def test_auto_start_only_once(self, monkeypatch, module_globals):
        """仅在首次且未启动时触发自动启动。"""
        engine = SimpleNamespace(enabled=True)
        monkeypatch.setattr(cse, "_cpp_scheduler_engine_instance", engine)
        auto_start = Mock()
        monkeypatch.setattr(cse, "_auto_start_engine", auto_start)

        assert cse.get_scheduler_engine(auto_start=True) is engine
        auto_start.assert_called_once_with(engine)

        monkeypatch.setattr(cse, "_engine_started", True)
        cse.get_scheduler_engine(auto_start=True)
        auto_start.assert_called_once()

    def test_auto_start_skipped_when_disabled(self, monkeypatch, module_globals):
        """引擎未启用时不自动启动。"""
        engine = SimpleNamespace(enabled=False)
        monkeypatch.setattr(cse, "_cpp_scheduler_engine_instance", engine)
        auto_start = Mock()
        monkeypatch.setattr(cse, "_auto_start_engine", auto_start)

        assert cse.get_scheduler_engine(auto_start=True) is engine
        auto_start.assert_not_called()

    def test_auto_start_disabled_by_flag(self, monkeypatch, module_globals):
        """auto_start=False 时不启动。"""
        engine = SimpleNamespace(enabled=True)
        monkeypatch.setattr(cse, "_cpp_scheduler_engine_instance", engine)
        auto_start = Mock()
        monkeypatch.setattr(cse, "_auto_start_engine", auto_start)

        cse.get_scheduler_engine(auto_start=False)
        auto_start.assert_not_called()


class TestEnsureSchedulerStarted:
    """``ensure_scheduler_started``。"""

    def test_starts_when_enabled(self, monkeypatch, module_globals):
        """引擎可用时触发自动启动。"""
        engine = SimpleNamespace(enabled=True)
        monkeypatch.setattr(cse, "get_scheduler_engine", lambda auto_start=True: engine)
        auto_start = Mock()
        monkeypatch.setattr(cse, "_auto_start_engine", auto_start)

        assert cse.ensure_scheduler_started() is engine
        auto_start.assert_called_once_with(engine)

    def test_skips_when_disabled(self, monkeypatch, module_globals):
        """引擎不可用时不触发。"""
        engine = SimpleNamespace(enabled=False)
        monkeypatch.setattr(cse, "get_scheduler_engine", lambda auto_start=True: engine)
        auto_start = Mock()
        monkeypatch.setattr(cse, "_auto_start_engine", auto_start)

        assert cse.ensure_scheduler_started() is engine
        auto_start.assert_not_called()


class TestBuildGpuConfig:
    """``_build_gpu_config`` 各分支。"""

    def test_returns_none_without_scheduler(self):
        """没有 scheduler 配置返回 None。"""
        settings = SimpleNamespace(scheduler=None, model=SimpleNamespace(text_path="m.gguf"))
        assert cse._build_gpu_config(settings) is None

    def test_returns_none_when_not_use_cpp_for_llm(self):
        """未启用 use_cpp_for_llm 返回 None。"""
        settings = _make_settings(
            scheduler=SimpleNamespace(use_cpp_for_llm=False, llm_backend="cpp")
        )
        assert cse._build_gpu_config(settings) is None

    def test_returns_none_without_text_path(self):
        """缺少文本模型路径返回 None。"""
        settings = _make_settings(text_path=None)
        assert cse._build_gpu_config(settings) is None

    def test_returns_none_for_non_gguf(self):
        """非 gguf 模型返回 None。"""
        settings = _make_settings(text_path="/m/model.bin")
        assert cse._build_gpu_config(settings) is None

    def test_basic_config(self, monkeypatch):
        """常规配置返回预期字段，缺省值走 or 兜底。"""
        _set_torch(monkeypatch, _FakeCuda(available=False))
        settings = _make_settings(
            n_ctx=4096,
            n_batch=512,
            n_gpu_layers=-1,
            temperature=None,
            top_p=None,
            top_k=None,
            repetition_penalty=None,
        )

        config = cse._build_gpu_config(settings)

        assert config is not None
        assert config["backend"] == "cpp"
        assert config["model_path"] == "model.gguf"
        assert config["max_context_size"] == 4096
        assert config["max_batch_size"] == 512
        assert config["n_gpu_layers"] == -1
        assert config["temperature"] == 0.7
        assert config["top_p"] == 0.95
        assert config["top_k"] == 40
        assert config["repetition_penalty"] == 1.1

    def test_defaults_batch_when_invalid(self, monkeypatch):
        """非法 batch / layers 回退到默认值。"""
        _set_torch(monkeypatch, _FakeCuda(available=False))
        settings = _make_settings(n_ctx=1024, n_batch=None, n_gpu_layers="abc")

        config = cse._build_gpu_config(settings)

        assert config is not None
        assert config["max_batch_size"] == 512  # min(512, 1024)
        assert config["n_gpu_layers"] == -1

    def test_clamps_batch_to_context(self, monkeypatch):
        """batch 大于 ctx 时被压到 ctx。"""
        _set_torch(monkeypatch, _FakeCuda(available=False))
        settings = _make_settings(n_ctx=1024, n_batch=4096, n_gpu_layers=10)

        config = cse._build_gpu_config(settings)

        assert config is not None
        assert config["max_batch_size"] == 1024

    def test_small_gpu_clamps_parameters(self, monkeypatch):
        """小显存（<=8G）压缩上下文/batch 并限制层数。"""
        _set_torch(
            monkeypatch,
            _FakeCuda(available=True, total_memory=4096 * 1024 * 1024),
        )
        settings = _make_settings(n_ctx=4096, n_batch=512, n_gpu_layers=-1)

        config = cse._build_gpu_config(settings)

        assert config is not None
        assert config["max_context_size"] == 2048
        assert config["max_batch_size"] == 256
        assert config["n_gpu_layers"] == 50

    def test_small_gpu_keeps_reasonable_layer_count(self, monkeypatch):
        """小显存但层数已在合理范围内时不强制改成 50。"""
        _set_torch(
            monkeypatch,
            _FakeCuda(available=True, total_memory=4096 * 1024 * 1024),
        )
        settings = _make_settings(n_ctx=4096, n_batch=512, n_gpu_layers=40)

        config = cse._build_gpu_config(settings)

        assert config is not None
        assert config["n_gpu_layers"] == 40

    def test_large_gpu_does_not_clamp(self, monkeypatch):
        """大显存不做压缩。"""
        _set_torch(
            monkeypatch,
            _FakeCuda(available=True, total_memory=24576 * 1024 * 1024),
        )
        settings = _make_settings(n_ctx=4096, n_batch=512, n_gpu_layers=-1)

        config = cse._build_gpu_config(settings)

        assert config is not None
        assert config["max_context_size"] == 4096
        assert config["n_gpu_layers"] == -1

    def test_gpu_probe_error_is_ignored(self, monkeypatch):
        """探测显存异常时按无 GPU 处理。"""
        _set_torch(monkeypatch, _FakeCuda(available=True, raise_on_probe=True))
        settings = _make_settings(n_ctx=4096, n_batch=512, n_gpu_layers=-1)

        config = cse._build_gpu_config(settings)

        assert config is not None
        assert config["max_context_size"] == 4096

    def test_returns_none_on_unexpected_error(self):
        """字段缺失导致异常时整体返回 None。"""
        model = SimpleNamespace(text_path="model.gguf")  # 缺少 n_ctx
        settings = SimpleNamespace(
            scheduler=SimpleNamespace(use_cpp_for_llm=True, llm_backend="cpp"),
            model=model,
        )

        assert cse._build_gpu_config(settings) is None


class TestAutoStartEngine:
    """``_auto_start_engine`` 各分支。"""

    def test_noop_when_engine_already_started(self, monkeypatch, module_globals):
        """全局已启动标记为真时直接返回。"""
        monkeypatch.setattr(cse, "_engine_started", True)
        engine = SimpleNamespace(start=Mock())

        cse._auto_start_engine(engine)

        engine.start.assert_not_called()

    def test_noop_when_already_attempted(self, module_globals):
        """同一引擎只尝试一次。"""
        engine = SimpleNamespace(start=Mock(), _auto_start_attempted=True)

        cse._auto_start_engine(engine)

        engine.start.assert_not_called()

    def test_returns_when_use_cpp_disabled(self, monkeypatch, module_globals):
        """配置未启用 C++ 时不启动。"""
        settings = SimpleNamespace(scheduler=SimpleNamespace(use_cpp=False))
        monkeypatch.setattr("config.integrated_config.get_settings", lambda: settings)
        engine = SimpleNamespace(start=Mock())

        cse._auto_start_engine(engine)

        engine.start.assert_not_called()
        assert cse._engine_started is False

    def test_starts_engine(self, monkeypatch, module_globals):
        """启用 C++ 时按配置启动引擎并置位全局标记。"""
        settings = SimpleNamespace(
            scheduler=SimpleNamespace(use_cpp=True), model=SimpleNamespace()
        )
        monkeypatch.setattr("config.integrated_config.get_settings", lambda: settings)
        monkeypatch.setattr(
            "core.utils.config_accessor.get_config", lambda *a, **k: 6
        )
        engine = SimpleNamespace(start=Mock())

        cse._auto_start_engine(engine)

        engine.start.assert_called_once_with(worker_count=6, gpu_config=None)
        assert cse._engine_started is True

    def test_swallows_start_error(self, monkeypatch, module_globals):
        """启动异常被吞掉且不置位标记。"""
        settings = SimpleNamespace(
            scheduler=SimpleNamespace(use_cpp=True), model=SimpleNamespace()
        )
        monkeypatch.setattr("config.integrated_config.get_settings", lambda: settings)
        monkeypatch.setattr("core.utils.config_accessor.get_config", lambda *a, **k: 4)
        engine = SimpleNamespace(start=Mock(side_effect=RuntimeError("start boom")))

        cse._auto_start_engine(engine)

        assert cse._engine_started is False


class TestModuleGetattr:
    """模块级 ``__getattr__`` 兼容层。"""

    def test_returns_engine_for_legacy_name(self, monkeypatch, module_globals):
        """旧名 ``cpp_scheduler_engine`` 返回全局引擎。"""
        sentinel = object()
        monkeypatch.setattr(cse, "get_scheduler_engine", lambda: sentinel)

        assert cse.__getattr__("cpp_scheduler_engine") is sentinel

    def test_raises_for_unknown_name(self):
        """未知属性抛 AttributeError。"""
        with pytest.raises(AttributeError):
            cse.__getattr__("definitely_not_here")


class TestGetSchedulerStatus:
    """``get_scheduler_status`` 各分支。"""

    def test_returns_status_when_enabled(self, monkeypatch, module_globals):
        """引擎可用时返回状态字典。"""
        engine = SimpleNamespace(
            enabled=True, get_status=Mock(return_value={"enabled": True})
        )
        monkeypatch.setattr(cse, "get_scheduler_engine", lambda: engine)

        assert cse.get_scheduler_status() == {"enabled": True}

    def test_returns_none_when_disabled(self, monkeypatch, module_globals):
        """引擎不可用时返回 None。"""
        engine = SimpleNamespace(enabled=False, get_status=Mock())
        monkeypatch.setattr(cse, "get_scheduler_engine", lambda: engine)

        assert cse.get_scheduler_status() is None

    def test_returns_none_on_error(self, monkeypatch, module_globals):
        """取状态异常时返回 None。"""

        def _boom():
            raise RuntimeError("status boom")

        monkeypatch.setattr(cse, "get_scheduler_engine", _boom)

        assert cse.get_scheduler_status() is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q", "-n", "0"]))
