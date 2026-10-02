"""multimodal/tts_manager.py 单元测试（五）：同步合成入口 `text_to_speech`。

⚠️ 依赖前提同 `test_tts_manager_core.py`：`soundfile` 属 voice 可选 extra，
CI 未安装 → 用 `importorskip` 整体跳过而不是失败。

⚠️ 不启动真实引擎/后台循环：`_ensure_background_loop` 与
`asyncio.run_coroutine_threadsafe` 都用替身（后者走模块内 asyncio 代理，不动全局 asyncio）。
"""

from __future__ import annotations

import asyncio
import concurrent.futures

import pytest

from multimodal import tts_manager as tm  # noqa: E402
from multimodal.tts_manager import TTSCacheConfig, TTSCacheManager  # noqa: E402


def _make(monkeypatch, tmp_path, config=None):
    temp_dir = tmp_path / "tts"
    monkeypatch.setattr(TTSCacheManager, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(tm, "_tts_manager_instance", None)
    cfg = config or TTSCacheConfig(min_free_disk_mb=0)
    return TTSCacheManager(cfg)


class _FakeThreadFuture:
    """`concurrent.futures.Future` 替身。"""

    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error

    def result(self, timeout=None):  # noqa: ANN001
        if self.error is not None:
            raise self.error
        return self.value


class _AsyncioProxy:
    """只拦截 `run_coroutine_threadsafe`，其余透传真实 asyncio。"""

    def __init__(self, real, factory):
        self._real = real
        self._factory = factory

    def __getattr__(self, name):
        return getattr(self._real, name)

    def run_coroutine_threadsafe(self, coro, loop):  # noqa: ANN001
        # 交给 factory 决定：真跑一遍（拿真实返回值）还是直接构造异常 future
        return self._factory(coro)


class _Engine:
    def __init__(self, *, bytes_payload=None, array_payload=None, last_error=None,
                 thread_error=None):
        self.settings = object()
        self.bytes_payload = bytes_payload
        self.array_payload = array_payload
        self.last_error = last_error
        self.thread_error = thread_error
        self.bytes_calls = []
        self.array_calls = []

    async def synthesize_bytes(self, text, speed=None, voice=None):  # noqa: ANN001
        self.bytes_calls.append((text, speed, voice))
        return self.bytes_payload

    async def synthesize(self, text, speed=None, voice=None):  # noqa: ANN001
        self.array_calls.append((text, speed, voice))
        return self.array_payload


def _ready(monkeypatch, tmp_path, engine, config=None):
    mgr = _make(monkeypatch, tmp_path, config)
    mgr.new_engine = engine
    mgr._initialized = True
    monkeypatch.setattr(TTSCacheManager, "_ensure_background_loop", lambda self: None)
    return mgr


def _patch_threadsafe(monkeypatch, engine, *, force_error=None):
    """让 run_coroutine_threadsafe 真的执行协程并返回受控 future。

    - 默认：`asyncio.run(coro)` 真的跑一遍引擎方法，拿真实返回值
      （这样也能断言引擎被怎么调的）；协程抛异常时把异常放进 future。
    - `force_error=<exc>`：不执行协程，直接让 `future.result()` 抛该异常。
    """
    if force_error is not None:

        def _factory(coro):  # noqa: ANN001
            coro.close()
            return _FakeThreadFuture(error=force_error)

    else:

        def _factory(coro):  # noqa: ANN001
            try:
                return _FakeThreadFuture(value=asyncio.run(coro))
            except Exception as exc:  # noqa: BLE001
                return _FakeThreadFuture(error=exc)

    monkeypatch.setattr(tm, "asyncio", _AsyncioProxy(asyncio, _factory))


# --------------------------------------------------------------------------
# 1. 前置校验
# --------------------------------------------------------------------------


def test_sync_empty_text_raises(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="非空文本"):
        mgr.text_to_speech("")


def test_sync_raises_when_shutting_down(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    mgr._shutting_down = True

    with pytest.raises(tm.TTSSynthesisError, match="正在关闭"):
        mgr.text_to_speech("你好")


def test_sync_raises_when_initialize_fails(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    monkeypatch.setattr(TTSCacheManager, "_initialize", lambda self: False)

    with pytest.raises(tm.TTSInitializationError, match="初始化失败"):
        mgr.text_to_speech("你好")


# --------------------------------------------------------------------------
# 2. 缓存与去重
# --------------------------------------------------------------------------


def test_sync_returns_cached_path(monkeypatch, tmp_path):
    mgr = _ready(monkeypatch, tmp_path, _Engine(bytes_payload=b"X"))
    cached = tmp_path / "tts" / "cached.wav"
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"x")
    mgr._cache_put(mgr._generate_cache_key("你好"), str(cached))

    assert mgr.text_to_speech("你好") == str(cached)
    assert mgr._synthesis_count == 0


def test_sync_non_owner_returns_existing_future_result(monkeypatch, tmp_path):
    """已有 inflight 时直接取它的结果。"""
    mgr = _ready(monkeypatch, tmp_path, _Engine())
    key = mgr._generate_cache_key("你好")
    existing = concurrent.futures.Future()
    existing.set_result("/tmp/shared.wav")
    mgr._inflight_sync[key] = existing

    assert mgr.text_to_speech("你好") == "/tmp/shared.wav"


def test_sync_non_owner_timeout_raises(monkeypatch, tmp_path):
    """等待 inflight 超时 → TTSTimeoutError，并清掉条目。"""
    mgr = _ready(monkeypatch, tmp_path, _Engine(), TTSCacheConfig(min_free_disk_mb=0,
                                                                 synthesis_timeout_sec=0))
    key = mgr._generate_cache_key("你好")
    mgr._inflight_sync[key] = concurrent.futures.Future()  # 永不完成

    with pytest.raises(tm.TTSTimeoutError, match="合成超时"):
        mgr.text_to_speech("你好")

    assert key not in mgr._inflight_sync


# --------------------------------------------------------------------------
# 3. 合成：字节分支
# --------------------------------------------------------------------------


def test_sync_bytes_path_writes_and_caches(monkeypatch, tmp_path):
    engine = _Engine(bytes_payload=b"BYTES")
    mgr = _ready(monkeypatch, tmp_path, engine)
    _patch_threadsafe(monkeypatch, engine)

    result = mgr.text_to_speech("你好", speed=1.5, voice="v9")

    assert result.endswith(".wav")
    assert open(result, "rb").read() == b"BYTES"
    assert mgr._synthesis_count == 1
    assert mgr._inflight_sync == {}
    assert engine.bytes_calls == [("你好", 1.5, "v9")]


def test_sync_defaults_speed_to_one(monkeypatch, tmp_path):
    engine = _Engine(bytes_payload=b"B")
    mgr = _ready(monkeypatch, tmp_path, engine)
    _patch_threadsafe(monkeypatch, engine)

    mgr.text_to_speech("你好")

    assert engine.bytes_calls[0][1] == 1.0


# --------------------------------------------------------------------------
# 4. 合成：数组分支
# --------------------------------------------------------------------------


def test_sync_array_path_writes_via_soundfile(monkeypatch, tmp_path):
    engine = _Engine(bytes_payload=None, array_payload=b"\x00\x01")
    mgr = _ready(monkeypatch, tmp_path, engine)
    _patch_threadsafe(monkeypatch, engine)
    sf = pytest.importorskip("soundfile", exc_type=ImportError, reason="只有 sf.write 分支需要 voice extra")
    seen = []
    monkeypatch.setattr(sf, "write", lambda path, data, rate: seen.append((data, rate)))

    result = mgr.text_to_speech("你好")

    assert seen == [(b"\x00\x01", 32000)]
    assert result.endswith(".wav")
    assert engine.array_calls and engine.array_calls[0][0] == "你好"


def test_sync_empty_audio_uses_engine_last_error(monkeypatch, tmp_path):
    """音频为空时优先用引擎的 last_error 作为错误文案。"""
    engine = _Engine(bytes_payload=None, array_payload=b"", last_error="模型未加载")
    mgr = _ready(monkeypatch, tmp_path, engine)
    _patch_threadsafe(monkeypatch, engine)

    with pytest.raises(tm.TTSSynthesisError, match="模型未加载"):
        mgr.text_to_speech("你好")


def test_sync_empty_audio_defaults_message(monkeypatch, tmp_path):
    engine = _Engine(bytes_payload=None, array_payload=b"")
    mgr = _ready(monkeypatch, tmp_path, engine)
    _patch_threadsafe(monkeypatch, engine)

    with pytest.raises(tm.TTSSynthesisError, match="生成的音频数据为空"):
        mgr.text_to_speech("你好")


# --------------------------------------------------------------------------
# 5. 失败路径
# --------------------------------------------------------------------------


def test_sync_thread_timeout_raises_and_clears(monkeypatch, tmp_path):
    engine = _Engine()
    mgr = _ready(monkeypatch, tmp_path, engine)
    _patch_threadsafe(monkeypatch, engine, force_error=concurrent.futures.TimeoutError())

    with pytest.raises(tm.TTSTimeoutError, match="合成超时"):
        mgr.text_to_speech("你好")

    assert mgr._inflight_sync == {}


def test_sync_tts_error_is_reraised_as_is(monkeypatch, tmp_path):
    engine = _Engine()
    mgr = _ready(monkeypatch, tmp_path, engine)
    _patch_threadsafe(monkeypatch, engine, force_error=tm.TTSSynthesisError("引擎拒绝"))

    with pytest.raises(tm.TTSSynthesisError, match="引擎拒绝"):
        mgr.text_to_speech("你好")


def test_sync_unknown_error_is_wrapped(monkeypatch, tmp_path):
    engine = _Engine()
    mgr = _ready(monkeypatch, tmp_path, engine)
    _patch_threadsafe(monkeypatch, engine, force_error=RuntimeError("底层炸了"))

    with pytest.raises(tm.TTSSynthesisError, match="语音合成失败"):
        mgr.text_to_speech("你好")


def test_sync_failure_clears_inflight(monkeypatch, tmp_path):
    engine = _Engine()
    mgr = _ready(monkeypatch, tmp_path, engine)
    _patch_threadsafe(monkeypatch, engine, force_error=RuntimeError("炸"))

    with pytest.raises(tm.TTSSynthesisError):
        mgr.text_to_speech("你好")

    assert mgr._inflight_sync == {}
