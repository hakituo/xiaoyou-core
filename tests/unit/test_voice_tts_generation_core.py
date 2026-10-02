# -*- coding: utf-8 -*-
"""core/voice/tts_generation.py 单元测试（五）：主流程音频分支与异常。

覆盖 `generate_tts_with_async` 后半段：WAV 直返、MP3 直返、PCM 二次合成转 WAV、
超时/异常、保存文件失败降级。

纯 mock：假 manager 返回内存字节/数组，假 `soundfile` 注入 `sys.modules`
（`soundfile` 属 voice 可选 extra，CI 不装），文件 IO 只落 tmp_path。
"""

from __future__ import annotations

import asyncio
import base64
import io
import sys
import types
import wave

import numpy as np
import pytest

import core.resource_manager as crm
import core.voice as cv
import core.voice.tts_generation as tg


# --------------------------------------------------------------------------
# 桩与夹具
# --------------------------------------------------------------------------
def _wav_bytes(sr: int = 16000, n: int = 800) -> bytes:
    """构造一段合法的最小 WAV（单声道 16bit）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


def _settings(cache_dir="cache"):
    tts = types.SimpleNamespace(auto_prompt_text=False, auto_prompt_text_from_ref=False)
    return types.SimpleNamespace(
        model=types.SimpleNamespace(cache_dir=cache_dir),
        voice=types.SimpleNamespace(tts=tts),
    )


class _Logger:
    """记录日志调用的假 logger（项目日志不传播到 caplog）。"""

    def __init__(self):
        self.records = []

    def _recorder(self, level):
        def _log(msg, *args, **kwargs):
            self.records.append((level, str(msg)))

        return _log

    def __getattr__(self, name):
        return self._recorder(name)


class _Mgr:
    """假 TTS manager：可控 synthesize_bytes / synthesize 的返回与异常。"""

    def __init__(self, bytes_result=None, bytes_exc=None, array_result=None,
                 array_exc=None, last_error=None, engine=None, sample_rate=32000):
        self.engine = engine if engine is not None else types.SimpleNamespace()
        self._bytes = _wav_bytes() if bytes_result is None else bytes_result
        self._bytes_exc = bytes_exc
        self._array = array_result
        self._array_exc = array_exc
        self.last_error = last_error
        self.sample_rate = sample_rate
        self.bytes_calls = []
        self.synth_calls = []

    async def get_engine(self):
        return self.engine

    async def synthesize_bytes(self, text, **kwargs):
        self.bytes_calls.append((text, kwargs))
        if self._bytes_exc is not None:
            raise self._bytes_exc
        return self._bytes

    async def synthesize(self, **kwargs):
        self.synth_calls.append(kwargs)
        if self._array_exc is not None:
            raise self._array_exc
        return self._array


class _FakeSf:
    """假 soundfile：write 只往目标写常量字节（本文件目标恒为 BytesIO）。"""

    def __init__(self):
        self.calls = {"write": 0}

    def write(self, target, mono, sr, **kwargs):
        self.calls["write"] += 1
        target.write(b"WAVDATA")


@pytest.fixture
def env(monkeypatch, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    env = types.SimpleNamespace(
        root=root, tmp=tmp_path, mgr=_Mgr(), mp=monkeypatch, log=_Logger()
    )
    monkeypatch.setattr(tg, "_project_root", lambda: str(root))
    monkeypatch.setattr(tg, "_project_root_path", lambda: root)
    monkeypatch.setattr(tg, "_tts_prompt_text_cache", {})
    monkeypatch.setattr(tg, "now_str", lambda _fmt: "20260101_000000")
    monkeypatch.setattr(tg, "get_settings", lambda: _settings())
    monkeypatch.setattr(tg, "logger", env.log)
    monkeypatch.setattr(crm, "get_resource_manager", lambda: None)
    monkeypatch.delenv("XIAOYOU_TTS_DEFAULT_REF_WAV", raising=False)
    monkeypatch.delenv("XIAOYOU_TTS_AUTO_PROMPT_TEXT", raising=False)
    _use_manager(env, env.mgr)
    return env


def _use_manager(env, mgr):
    env.mgr = mgr

    async def _get():
        return mgr

    env.mp.setattr(cv, "get_tts_manager", _get)
    return mgr


def _use_sf(env) -> _FakeSf:
    sf = _FakeSf()
    env.mp.setitem(sys.modules, "soundfile", sf)
    return sf


def _mk_ref(env, name="ref.mp3", data=b"ID3"):
    d = env.root / "ref_audio" / "female"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(data)
    return p


def _params(env):
    return {"speaker_wav": str(_mk_ref(env))}


def _has(env, needle: str) -> bool:
    return any(needle in msg for _, msg in env.log.records)


# --------------------------------------------------------------------------
# 1. WAV / MP3 直返
# --------------------------------------------------------------------------
async def test_wav_bytes_use_header_sample_rate_and_save_file(env):
    _use_manager(env, _Mgr(bytes_result=_wav_bytes(sr=24000)))
    got = await tg.generate_tts_with_async("你好", _params(env))
    assert got["audio_base64"].startswith("data:audio/wav;base64,")
    assert got["sample_rate"] == 24000
    assert got["text"] == "你好"
    assert got["source"] == "core_voice"
    fname = got["file_path"].split("/")[-1]
    assert got["file_path"] == f"output/voice/{fname}"
    assert (env.root / "output" / "voice" / fname).read_bytes() == _wav_bytes(sr=24000)


async def test_wav_with_broken_header_falls_back_to_default_rate(env):
    broken = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 4
    _use_manager(env, _Mgr(bytes_result=broken))
    got = await tg.generate_tts_with_async("你好", _params(env))
    assert got["sample_rate"] == 32000
    assert got["audio_base64"].startswith("data:audio/wav;base64,")


async def test_mp3_bytes_returned_with_mpeg_mime(env):
    _use_manager(env, _Mgr(bytes_result=b"ID3\x03\x00\x00\x00"))
    got = await tg.generate_tts_with_async("你好", _params(env))
    assert got["audio_base64"].startswith("data:audio/mpeg;base64,")
    assert got["sample_rate"] == 32000
    assert _has(env, "返回 MP3 格式音频")


# --------------------------------------------------------------------------
# 2. PCM 二次合成转 WAV
# --------------------------------------------------------------------------
async def test_pcm_fallback_converts_array_to_wav(env):
    sf = _use_sf(env)
    _use_manager(env, _Mgr(bytes_result=b"", array_result=np.zeros(1000, dtype="float32")))
    got = await tg.generate_tts_with_async("你好", _params(env))
    assert sf.calls["write"] == 1
    assert base64.b64decode(got["audio_base64"].split(",")[1]) == b"WAVDATA"
    assert got["sample_rate"] == 32000
    assert _has(env, "静音") and _has(env, "过短")


@pytest.mark.parametrize(
    "engine_sr,mgr_sr,expected", [(44100, 32000, 44100), (None, 16000, 16000)]
)
async def test_pcm_fallback_sample_rate_source(env, engine_sr, mgr_sr, expected):
    """引擎自带 sample_rate 时优先用它，否则退回 manager 的。"""
    _use_sf(env)
    if engine_sr is None:
        engine = types.SimpleNamespace()
    else:
        engine = types.SimpleNamespace(sample_rate=engine_sr)
    mgr = _Mgr(
        bytes_result=b"",
        array_result=np.full(8000, 0.5, dtype="float32"),
        engine=engine,
        sample_rate=mgr_sr,
    )
    _use_manager(env, mgr)
    got = await tg.generate_tts_with_async("你好", _params(env))
    assert got["sample_rate"] == expected


async def test_pcm_fallback_empty_result_reports_last_error(env):
    _use_manager(env, _Mgr(bytes_result=b"", array_result=None, last_error="引擎炸了"))
    with pytest.raises(RuntimeError, match="引擎炸了"):
        await tg.generate_tts_with_async("你好", _params(env))


async def test_pcm_fallback_empty_result_default_message(env):
    _use_manager(env, _Mgr(bytes_result=b"", array_result=None))
    with pytest.raises(RuntimeError, match="TTS生成结果为空"):
        await tg.generate_tts_with_async("你好", _params(env))


# --------------------------------------------------------------------------
# 3. 超时 / 异常 / 保存失败
# --------------------------------------------------------------------------
async def test_synthesize_bytes_timeout_raises(env):
    _use_manager(env, _Mgr(bytes_exc=asyncio.TimeoutError()))
    with pytest.raises(RuntimeError, match="TTS生成超时"):
        await tg.generate_tts_with_async("你好", _params(env))


async def test_second_synthesize_timeout_raises(env):
    _use_manager(env, _Mgr(bytes_result=b"", array_exc=asyncio.TimeoutError()))
    with pytest.raises(RuntimeError, match="TTS生成超时"):
        await tg.generate_tts_with_async("你好", _params(env))


async def test_synthesize_bytes_generic_error_falls_back_to_array(env):
    _use_sf(env)
    _use_manager(env, _Mgr(bytes_exc=ValueError("bad"), array_result=np.full(8000, 0.5, dtype="float32")))
    got = await tg.generate_tts_with_async("你好", _params(env))
    assert got["sample_rate"] == 32000
    assert env.mgr.synth_calls  # 确实退到了第二次 synthesize


async def test_save_file_failure_keeps_empty_file_path(env, monkeypatch):
    async def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(tg.asyncio, "to_thread", _boom)
    _use_manager(env, _Mgr(bytes_result=_wav_bytes()))
    got = await tg.generate_tts_with_async("你好", _params(env))
    assert got["file_path"] == ""
    assert _has(env, "保存TTS文件失败")
