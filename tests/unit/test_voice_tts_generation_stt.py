# -*- coding: utf-8 -*-
"""core/voice/tts_generation.py 单元测试（三）：参考音频自动识别 prompt_text。

覆盖 `auto_prompt_text` 三个开关来源（settings 两个字段 + 环境变量）以及 STT
识别成功 / 空结果 / 抛异常 / 写缓存失败四条支路。

纯 mock：STT manager 与 engine 都是假对象，绝不加载模型或发网络请求。
"""

from __future__ import annotations

import hashlib
import io
import os
import types
import wave

import pytest

import core.resource_manager as crm
import core.voice as cv
import core.voice.tts_generation as tg


# --------------------------------------------------------------------------
# 桩与夹具
# --------------------------------------------------------------------------
def _wav_bytes(sr: int = 16000, n: int = 800) -> bytes:
    """构造一段合法的最小 WAV（单声道 16bit），让 is_wav 分支命中。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


def _settings(cache_dir="cache", auto=False, auto_from_ref=False):
    tts = types.SimpleNamespace(
        auto_prompt_text=auto, auto_prompt_text_from_ref=auto_from_ref
    )
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


class _SttEngine:
    """假 STT engine：记录 transcribe 收到的音频字节。"""

    def __init__(self, res=None, exc=None):
        self.res = res
        self.exc = exc
        self.calls = []

    async def transcribe(self, audio_bytes):
        self.calls.append(audio_bytes)
        if self.exc is not None:
            raise self.exc
        return self.res


class _SttMgr:
    def __init__(self, engine):
        self._engine = engine

    async def get_engine(self):
        return self._engine


class _Mgr:
    """假 TTS manager：只记录 synthesize_bytes 的调用参数。"""

    def __init__(self):
        self.engine = types.SimpleNamespace()
        self.sample_rate = 32000
        self.bytes_calls = []

    async def get_engine(self):
        return self.engine

    async def synthesize_bytes(self, text, **kwargs):
        self.bytes_calls.append((text, kwargs))
        return _wav_bytes()

    async def synthesize(self, **kwargs):
        raise AssertionError("本文件不应调用 synthesize")


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

    async def _get():
        return env.mgr

    monkeypatch.setattr(cv, "get_tts_manager", _get)
    monkeypatch.setattr(crm, "get_resource_manager", lambda: None)
    monkeypatch.delenv("XIAOYOU_TTS_DEFAULT_REF_WAV", raising=False)
    monkeypatch.delenv("XIAOYOU_TTS_AUTO_PROMPT_TEXT", raising=False)
    return env


def _use_stt(env, engine=None, exc=None):
    """替换 get_stt_manager（函数体内 import，patch 源模块）。"""
    if exc is not None:
        async def _boom():
            raise exc

        env.mp.setattr(cv, "get_stt_manager", _boom)
        return None
    mgr = _SttMgr(engine)
    async def _get():
        return mgr

    env.mp.setattr(cv, "get_stt_manager", _get)
    return mgr


def _mk_ref(env, name="ref.mp3", data=b"ID3"):
    d = env.root / "ref_audio" / "female"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(data)
    return p


def _digest(path) -> str:
    return hashlib.md5(os.path.abspath(str(path)).encode("utf-8")).hexdigest()


async def _run(env, params, text="你好"):
    return await tg.generate_tts_with_async(text, params)


def _kw(env):
    return env.mgr.bytes_calls[0][1]


def _has(env, needle: str) -> bool:
    return any(needle in msg for _, msg in env.log.records)


# --------------------------------------------------------------------------
# 1. 开关来源
# --------------------------------------------------------------------------
@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on", " On "])
async def test_auto_prompt_env_flag_truthy(env, monkeypatch, val):
    monkeypatch.setenv("XIAOYOU_TTS_AUTO_PROMPT_TEXT", val)
    p = _mk_ref(env)
    _use_stt(env, _SttEngine(res={"text": "环境开关"}))
    await _run(env, {"speaker_wav": str(p)})
    assert _kw(env)["prompt_text"] == "环境开关"


@pytest.mark.parametrize(
    "kwargs", [{"auto": True}, {"auto_from_ref": True}]
)
async def test_auto_prompt_settings_flags(env, kwargs):
    env.mp.setattr(tg, "get_settings", lambda: _settings(**kwargs))
    p = _mk_ref(env)
    _use_stt(env, _SttEngine(res={"text": "配置开关"}))
    await _run(env, {"speaker_wav": str(p)})
    assert _kw(env)["prompt_text"] == "配置开关"


# --------------------------------------------------------------------------
# 2. STT 识别结果
# --------------------------------------------------------------------------
async def test_auto_stt_success_writes_prompt_cache(env):
    cache = env.tmp / "cache"
    env.mp.setattr(tg, "get_settings", lambda: _settings(cache_dir=str(cache), auto=True))
    p = _mk_ref(env)
    engine = _SttEngine(res={"text": "识别文本"})
    _use_stt(env, engine)
    await _run(env, {"speaker_wav": str(p)})
    assert _kw(env)["prompt_text"] == "识别文本"
    assert engine.calls == [p.read_bytes()]  # 确实把参考音频喂给了 STT
    assert (cache / "tts_prompt_text" / f"{_digest(p)}.txt").read_text(
        encoding="utf-8"
    ) == "识别文本"


async def test_auto_stt_empty_result_keeps_none(env):
    env.mp.setattr(tg, "get_settings", lambda: _settings(auto=True))
    p = _mk_ref(env)
    _use_stt(env, _SttEngine(res={}))
    await _run(env, {"speaker_wav": str(p)})
    assert _kw(env)["prompt_text"] is None


async def test_auto_stt_failure_is_logged(env):
    env.mp.setattr(tg, "get_settings", lambda: _settings(auto=True))
    p = _mk_ref(env)
    _use_stt(env, exc=RuntimeError("stt down"))
    await _run(env, {"speaker_wav": str(p)})
    assert _kw(env)["prompt_text"] is None
    assert _has(env, "自动识别提示文本失败")


async def test_auto_stt_write_cache_failure_logged(env):
    """prompt 缓存文件位置被目录占住：读失败 → STT 成功 → 写失败但仅告警。"""
    cache = env.tmp / "cache"
    env.mp.setattr(tg, "get_settings", lambda: _settings(cache_dir=str(cache), auto=True))
    p = _mk_ref(env)
    (cache / "tts_prompt_text" / f"{_digest(p)}.txt").mkdir(parents=True)
    _use_stt(env, _SttEngine(res={"text": "STT文本"}))
    await _run(env, {"speaker_wav": str(p)})
    assert _kw(env)["prompt_text"] == "STT文本"
    assert _has(env, "写入 prompt_text 缓存失败")
