"""core/voice/engines/qwen3_tts_engine.py —— 合成入口与批处理单元测试。

覆盖 ``synthesize_bytes``（显存预检 / 批处理队列）与 ``_process_batch`` /
``_process_single``。``_do_synthesize`` 与 ``synthesize`` 见
``test_voice_qwen3_tts_engine_do_synthesize.py``。

**绝不加载真实模型**：模型对象由替身提供（``generate_voice_clone`` 返回可控的 numpy
小数组），``ThreadPoolExecutor`` 换成就地执行的替身；不下载权重、不使用 GPU、不发起
网络请求，文件 IO 全部落在 ``tmp_path``。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import io
import types

import numpy as np
import pytest

import core.resource_manager as rm_mod
import config.integrated_config as cfg_mod
import core.voice.engines.qwen3_tts_engine as mod
from core.voice.engines.qwen3_tts_engine import Qwen3TTSEngine

# `soundfile` 属 voice 可选 extra（pyproject.toml），CI 只跑 `uv sync --extra dev` 不装它。
# 缺依赖时整体跳过而不是失败（与 test_tts_manager_core.py 同口径）。
sf = pytest.importorskip("soundfile", exc_type=ImportError,
                         reason="soundfile 属 voice 可选 extra，CI 未安装")


class _RecordingLogger:
    """模块级 logger 替身（真实 logger 的 propagate=False，不便用 caplog）。"""

    def __init__(self):
        self.records = []

    def messages(self, level=None):
        return [m for lv, m in self.records if level is None or lv == level]

    def _bind(level):
        def _log(self, msg, *args, **kwargs):
            self.records.append((level, msg))
        return _log

    debug, info, warning, error = (_bind("debug"), _bind("info"),
                                   _bind("warning"), _bind("error"))


class _SettingsStub:
    def __init__(self, reference_audio=None, tts_vram_threshold_mb=0):
        self.voice = types.SimpleNamespace(
            reference_audio=reference_audio,
            tts_vram_threshold_mb=tts_vram_threshold_mb,
        )


class _InlineExecutor:
    """就地执行的 executor 替身：submit 立即同步跑完，避免真实线程与竞态。"""

    def __init__(self):
        self.shutdown_calls = []

    def submit(self, fn, *args, **kwargs):
        future = concurrent.futures.Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # 需原样透传给调用方
            future.set_exception(exc)
        return future

    def shutdown(self, wait=True):
        self.shutdown_calls.append(wait)


class _FakeModel:
    """TTS 模型替身：记录 generate_voice_clone 入参，返回可控音频。"""

    def __init__(self, *, faster=False, wavs=None, sr=24000, exc=None):
        self.calls = []
        self._wavs = wavs if wavs is not None else [np.zeros(240, dtype=np.float32)]
        self._sr, self._exc = sr, exc
        if faster:
            self.predictor_graph = object()

    def generate_voice_clone(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._wavs, self._sr


class _RMStub:
    """资源管理器替身：可切换是否暴露 ``get_gpu_free_mb`` / ``monitor``。"""

    def __init__(self, *, free_mb=None, monitor_usage=None, raise_exc=None,
                 has_free_attr=True, has_monitor=True):
        async def probe(value):
            if raise_exc is not None:
                raise raise_exc
            return value

        if has_free_attr:
            self.get_gpu_free_mb = lambda: probe(free_mb)
        if has_monitor:
            self.monitor = types.SimpleNamespace(
                get_gpu_memory_usage_async=lambda: probe(monitor_usage))


class _FakeTimer:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class _FakeResourceLock:
    """全局资源锁替身：记录 acquire 入参并进入/退出异步上下文。"""

    def __init__(self, record):
        self._record = record

    def acquire(self, requestor, *, reject_if_full=False):
        self._record.append((requestor, reject_if_full))
        return self

    async def __aenter__(self):
        self._record.append("enter")
        return self

    async def __aexit__(self, *exc_info):
        self._record.append("exit")
        return False


async def _drain(rounds=4):
    """让出事件循环若干轮，用于观察 fire-and-forget 任务的完成回调。"""
    for _ in range(rounds):
        await asyncio.sleep(0)


@pytest.fixture
def engine():
    eng = Qwen3TTSEngine()
    eng._executor = _InlineExecutor()
    yield eng


def _patch_do_synthesize(engine, monkeypatch, *, result=b"AUDIO", exc=None):
    calls = []

    async def _do(text, **kwargs):
        calls.append((text, kwargs))
        if exc is not None:
            raise exc
        return result

    monkeypatch.setattr(engine, "_do_synthesize", _do)
    return calls


def _patch_local_settings(monkeypatch, *, threshold=1000):
    """patch ``synthesize_bytes`` 内函数体局部 import 的源模块。"""
    monkeypatch.setattr(cfg_mod, "get_settings",
                        lambda: _SettingsStub(tts_vram_threshold_mb=threshold))


def _patch_local_rm(monkeypatch, rm):
    monkeypatch.setattr(rm_mod, "get_resource_manager", lambda: rm)


def _wav_bytes(samples=240, sample_rate=24000, value=0.5):
    buf = io.BytesIO()
    sf.write(buf, np.full(samples, value, dtype=np.float32), sample_rate,
             format="WAV")
    return buf.getvalue()


class TestSynthesizeBytesVramGuard:
    @pytest.fixture(autouse=True)
    def _env(self, engine, monkeypatch):
        _patch_local_settings(monkeypatch, threshold=1000)
        engine._model = object()       # 非 None
        engine.current_device = "cpu"  # 触发预检
        engine._batch_max_size = 1
        return engine

    async def _run(self, engine, monkeypatch):
        calls = _patch_do_synthesize(engine, monkeypatch, result=b"OK")
        return await engine.synthesize_bytes("hi"), calls

    @pytest.mark.parametrize("rm", [
        None,                                              # 无资源管理器
        _RMStub(free_mb=None),                             # 空闲显存探测失败
        _RMStub(free_mb=2000),                             # 空闲显存充足
        _RMStub(has_free_attr=False, monitor_usage=None),  # 走 monitor 但无数据
        _RMStub(has_free_attr=False, monitor_usage=(1000, 8000)),
    ])
    async def test_vram_ok_proceeds(self, engine, monkeypatch, rm):
        _patch_local_rm(monkeypatch, rm)
        out, calls = await self._run(engine, monkeypatch)
        assert out == b"OK"
        assert calls == [("hi", {})]

    @pytest.mark.parametrize("rm,message", [
        (_RMStub(free_mb=500), "显存不足"),
        (_RMStub(has_free_attr=False, monitor_usage=(9000, 9500)), "显存不足"),
        (_RMStub(raise_exc=RuntimeError("probe failed")), "probe failed"),
    ])
    async def test_vram_guard_raises(self, engine, monkeypatch, rm, message):
        _patch_local_rm(monkeypatch, rm)
        with pytest.raises(RuntimeError, match=message):
            await engine.synthesize_bytes("hi")

    async def test_generic_error_is_logged_and_ignored(self, engine, monkeypatch):
        rec = _RecordingLogger()
        monkeypatch.setattr(mod, "logger", rec)
        _patch_local_rm(monkeypatch, _RMStub(raise_exc=ValueError("odd probe")))
        out, _ = await self._run(engine, monkeypatch)
        assert out == b"OK"
        assert any("Failed to check VRAM" in m for m in rec.messages("warning"))


class TestSynthesizeBytesQueue:
    async def test_lazy_initialize_when_model_missing(self, engine, monkeypatch):
        engine._model, engine.current_device = None, "cpu"
        engine._batch_max_size = 1
        _patch_local_settings(monkeypatch)
        _patch_local_rm(monkeypatch, None)
        init_calls = []

        async def _fake_init():
            init_calls.append(1)
            engine._model = object()

        monkeypatch.setattr(engine, "initialize", _fake_init)
        _patch_do_synthesize(engine, monkeypatch, result=b"INIT")
        assert await engine.synthesize_bytes("hi") == b"INIT"
        assert init_calls == [1]

    async def test_timer_paths(self, engine, monkeypatch):
        engine._model, engine.current_device = object(), "cuda"
        # 队列已满：取消挂起定时器并立即触发批处理
        engine._batch_max_size = 1
        timer = _FakeTimer()
        engine._batch_timer = timer
        _patch_do_synthesize(engine, monkeypatch, result=b"FULL")
        assert await engine.synthesize_bytes("hi") == b"FULL"
        assert timer.cancelled is True
        assert engine._batch_timer is None
        # 首个请求：挂定时器，到期后触发批处理
        engine._batch_max_size = 4
        engine._batch_max_wait = 0  # 立即到期，避免真实等待
        spawned = []
        original = engine._spawn_batch_task

        def _record(coro):
            spawned.append(coro)
            return original(coro)

        monkeypatch.setattr(engine, "_spawn_batch_task", _record)
        _patch_do_synthesize(engine, monkeypatch, result=b"TIMER")
        assert await engine.synthesize_bytes("hi") == b"TIMER"
        await _drain()
        assert len(spawned) == 1

    async def test_batch_failure_is_logged_and_reraised(self, engine, monkeypatch):
        rec = _RecordingLogger()
        monkeypatch.setattr(mod, "logger", rec)
        engine._model, engine.current_device = object(), "cuda"
        engine._batch_max_size = 1
        _patch_do_synthesize(engine, monkeypatch, exc=ValueError("infer boom"))
        with pytest.raises(ValueError, match="infer boom"):
            await engine.synthesize_bytes("hi")
        assert any("批处理请求失败" in m for m in rec.messages("error"))


class TestProcessBatch:
    async def test_empty_queue_and_cap_by_max_size(self, engine, monkeypatch):
        calls = _patch_do_synthesize(engine, monkeypatch, result=b"Y")
        engine._batch_queue = []
        await engine._process_batch()
        assert calls == []
        loop = asyncio.get_running_loop()
        f1 = loop.create_future()
        engine._batch_max_size = 1
        engine._batch_queue = [
            {"id": "a", "text": "t1", "kwargs": {}, "future": f1},
            {"id": "b", "text": "t2", "kwargs": {}, "future": loop.create_future()},
        ]
        await engine._process_batch()
        assert await f1 == b"Y"
        assert len(engine._batch_queue) == 1  # 超出 max_size 的留在队列
        assert calls == [("t1", {})]

    async def test_single_item_processed_directly(self, engine, monkeypatch):
        calls = _patch_do_synthesize(engine, monkeypatch, result=b"ONE")
        future = asyncio.get_running_loop().create_future()
        engine._batch_queue = [
            {"id": "a", "text": "t", "kwargs": {}, "future": future}]
        engine._batch_timer = object()
        await engine._process_batch()
        assert await future == b"ONE"
        assert (engine._batch_queue, engine._batch_timer) == ([], None)
        assert calls == [("t", {})]

    async def test_multiple_items_logged_and_all_processed(self, engine, monkeypatch):
        rec = _RecordingLogger()
        monkeypatch.setattr(mod, "logger", rec)
        calls = _patch_do_synthesize(engine, monkeypatch, result=b"X")
        loop = asyncio.get_running_loop()
        f1, f2 = loop.create_future(), loop.create_future()
        engine._batch_max_size = 4
        engine._batch_queue = [
            {"id": "a", "text": "t1", "kwargs": {}, "future": f1},
            {"id": "b", "text": "t2", "kwargs": {}, "future": f2},
        ]
        await engine._process_batch()
        assert [await f1, await f2] == [b"X", b"X"]
        assert calls == [("t1", {}), ("t2", {})]
        assert any("批量处理: 2条请求" in m for m in rec.messages("info"))

    async def test_process_single_success_and_failure(self, engine, monkeypatch):
        loop = asyncio.get_running_loop()
        _patch_do_synthesize(engine, monkeypatch, result=b"R")
        ok_future = loop.create_future()
        await engine._process_single({"text": "t", "kwargs": {}, "future": ok_future})
        assert await ok_future == b"R"

        _patch_do_synthesize(engine, monkeypatch, exc=ValueError("boom"))
        bad_future = loop.create_future()
        await engine._process_single({"text": "t", "kwargs": {}, "future": bad_future})
        assert isinstance(bad_future.exception(), ValueError)

