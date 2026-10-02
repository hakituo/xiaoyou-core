"""multimodal/tts_manager.py 单元测试（四）：异步合成入口 `async_text_to_speech`。

⚠️ 依赖前提同 `test_tts_manager_core.py`：`soundfile` 属 voice 可选 extra，
CI 未安装 → 用 `importorskip` 整体跳过而不是失败。

⚠️ 不启动真实引擎、不联网；`TEMP_DIR` 重定向到 tmp_path；引擎用替身。
"""

from __future__ import annotations

import asyncio

import pytest

from multimodal import tts_manager as tm  # noqa: E402
from multimodal.tts_manager import TTSCacheConfig, TTSCacheManager  # noqa: E402


def _make(monkeypatch, tmp_path, config=None):
    temp_dir = tmp_path / "tts"
    monkeypatch.setattr(TTSCacheManager, "TEMP_DIR", str(temp_dir))
    monkeypatch.setattr(tm, "_tts_manager_instance", None)
    cfg = config or TTSCacheConfig(min_free_disk_mb=0)
    return TTSCacheManager(cfg)


class _EngineBytes:
    """带 `synthesize_bytes` 的引擎替身（走字节写入分支）。"""

    def __init__(self, payload=b"AUDIO", error=None):
        self.settings = object()
        self.payload = payload
        self.error = error
        self.calls = []

    async def synthesize_bytes(self, text, speed=None, voice=None):  # noqa: ANN001
        self.calls.append((text, speed, voice))
        if self.error:
            raise self.error
        return self.payload

    async def initialize(self):
        return None


class _EngineArray:
    """不带 `synthesize_bytes` 的引擎替身（走 sf.write 分支）。"""

    def __init__(self, payload=b"\x00\x01", last_error=None):
        self.settings = object()
        self.payload = payload
        self.last_error = last_error
        self.calls = []

    async def synthesize(self, text, speed=None, voice=None):  # noqa: ANN001
        self.calls.append((text, speed, voice))
        return self.payload


def _ready(mgr, engine):
    """把管理器置为「已初始化 + 指定引擎」。"""
    mgr.new_engine = engine
    mgr._initialized = True
    return mgr


# --------------------------------------------------------------------------
# 1. 前置校验
# --------------------------------------------------------------------------


def test_async_empty_text_raises_value_error(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="非空文本"):
        asyncio.run(mgr.async_text_to_speech(""))


def test_async_raises_when_shutting_down(monkeypatch, tmp_path):
    mgr = _make(monkeypatch, tmp_path)
    mgr._shutting_down = True

    with pytest.raises(tm.TTSSynthesisError, match="正在关闭"):
        asyncio.run(mgr.async_text_to_speech("你好"))


def test_async_lazy_initializes_engine(monkeypatch, tmp_path):
    """未初始化且没有引擎时，就地创建并 initialize。"""
    mgr = _make(monkeypatch, tmp_path)
    engine = _EngineBytes()
    monkeypatch.setattr("core.voice.tts_engine.TTSManager", lambda: engine)

    result = asyncio.run(mgr.async_text_to_speech("你好"))

    assert mgr._initialized is True
    assert result.endswith(".wav")


def test_async_propagates_disk_space_error(monkeypatch, tmp_path):
    cfg = TTSCacheConfig(min_free_disk_mb=1)
    mgr = _ready(_make(monkeypatch, tmp_path, cfg), _EngineBytes())
    monkeypatch.setattr(tm, "_get_disk_usage", lambda path: (0, 0))

    with pytest.raises(tm.TTSDiskSpaceError):
        asyncio.run(mgr.async_text_to_speech("你好"))


# --------------------------------------------------------------------------
# 2. 缓存与去重
# --------------------------------------------------------------------------


def test_async_returns_cached_path(monkeypatch, tmp_path):
    mgr = _ready(_make(monkeypatch, tmp_path), _EngineBytes())
    cached = tmp_path / "tts" / "cached.wav"
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"x")
    key = mgr._generate_cache_key("你好")
    mgr._cache_put(key, str(cached))

    assert asyncio.run(mgr.async_text_to_speech("你好")) == str(cached)
    assert mgr._synthesis_count == 0, "缓存命中不该触发合成"


def test_async_non_owner_waits_for_inflight(monkeypatch, tmp_path):
    """已有 inflight 时不做 owner，转去等待结果。"""
    mgr = _ready(_make(monkeypatch, tmp_path), _EngineBytes())
    path = tmp_path / "tts" / "shared.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    key = mgr._generate_cache_key("你好")

    async def _run():
        fut = asyncio.get_running_loop().create_future()
        mgr._inflight_async[key] = fut
        asyncio.get_running_loop().call_soon(fut.set_result, str(path))
        return await mgr.async_text_to_speech("你好")

    assert asyncio.run(_run()) == str(path)
    assert mgr._synthesis_count == 0


# --------------------------------------------------------------------------
# 3. 合成：字节分支
# --------------------------------------------------------------------------


def test_async_synthesize_bytes_writes_and_caches(monkeypatch, tmp_path):
    engine = _EngineBytes(payload=b"BYTES")
    mgr = _ready(_make(monkeypatch, tmp_path), engine)

    result = asyncio.run(mgr.async_text_to_speech("你好", speed=1.2, voice="v1"))

    assert result.endswith(".wav")
    assert open(result, "rb").read() == b"BYTES"
    assert mgr._synthesis_count == 1
    assert mgr._inflight_async == {}, "完成后应清掉 inflight"
    assert engine.calls == [("你好", 1.2, "v1")]


def test_async_defaults_speed_to_one(monkeypatch, tmp_path):
    engine = _EngineBytes()
    mgr = _ready(_make(monkeypatch, tmp_path), engine)

    asyncio.run(mgr.async_text_to_speech("你好"))

    assert engine.calls[0][1] == 1.0


def test_async_empty_bytes_falls_through_to_array_path(monkeypatch, tmp_path):
    """synthesize_bytes 返回空 → 回落到 synthesize()。"""
    engine = _EngineBytes(payload=b"")
    mgr = _ready(_make(monkeypatch, tmp_path), engine)
    sf = pytest.importorskip("soundfile", exc_type=ImportError, reason="只有 sf.write 分支需要 voice extra")
    seen = []
    monkeypatch.setattr(sf, "write", lambda path, data, rate: seen.append((path, rate)))

    engine.synthesize = _array_synth(b"\x01\x02")

    result = asyncio.run(mgr.async_text_to_speech("你好"))

    assert seen and seen[0][1] == 32000
    assert result.endswith(".wav")


def _array_synth(payload):
    async def _synth(text, speed=None, voice=None):  # noqa: ANN001
        return payload

    return _synth


# --------------------------------------------------------------------------
# 4. 合成：数组分支
# --------------------------------------------------------------------------


def test_async_array_path_writes_via_soundfile(monkeypatch, tmp_path):
    engine = _EngineArray(payload=b"\x00\x01")
    mgr = _ready(_make(monkeypatch, tmp_path), engine)
    sf = pytest.importorskip("soundfile", exc_type=ImportError, reason="只有 sf.write 分支需要 voice extra")
    seen = []
    monkeypatch.setattr(sf, "write", lambda path, data, rate: seen.append((path, data, rate)))

    result = asyncio.run(mgr.async_text_to_speech("你好"))

    assert seen and seen[0][1] == b"\x00\x01"
    assert seen[0][2] == 32000
    assert result.endswith(".wav")


def test_async_empty_array_raises_synthesis_error(monkeypatch, tmp_path):
    engine = _EngineArray(payload=b"")
    mgr = _ready(_make(monkeypatch, tmp_path), engine)

    with pytest.raises(tm.TTSSynthesisError, match="生成的音频数据为空"):
        asyncio.run(mgr.async_text_to_speech("你好"))


# --------------------------------------------------------------------------
# 5. 失败路径
# --------------------------------------------------------------------------


def test_async_tts_error_is_reraised_as_is(monkeypatch, tmp_path):
    """已经是 TTSError 的异常原样抛出，不再包一层。"""
    engine = _EngineBytes(error=tm.TTSSynthesisError("引擎拒绝"))
    mgr = _ready(_make(monkeypatch, tmp_path), engine)

    with pytest.raises(tm.TTSSynthesisError, match="引擎拒绝"):
        asyncio.run(mgr.async_text_to_speech("你好"))


def test_async_unknown_error_is_wrapped(monkeypatch, tmp_path):
    engine = _EngineBytes(error=RuntimeError("底层炸了"))
    mgr = _ready(_make(monkeypatch, tmp_path), engine)

    with pytest.raises(tm.TTSSynthesisError, match="语音合成失败"):
        asyncio.run(mgr.async_text_to_speech("你好"))


def test_async_failure_clears_inflight(monkeypatch, tmp_path):
    engine = _EngineBytes(error=RuntimeError("炸"))
    mgr = _ready(_make(monkeypatch, tmp_path), engine)

    with pytest.raises(tm.TTSSynthesisError):
        asyncio.run(mgr.async_text_to_speech("你好"))

    assert mgr._inflight_async == {}, "失败后也应清掉 inflight，避免后续请求永久等待"
