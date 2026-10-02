# -*- coding: utf-8 -*-
"""core/voice/tts_generation.py 单元测试（六）：引擎参数与资源管理协作。

覆盖 GPT-SoVITS 权重切换的四条判断分支、语言映射、voice 参数注入，以及
`get_resource_manager` 的加载/释放标记与全部异常吞噬分支。

纯 mock：假 manager / 假资源管理器，不加载模型、不合成语音。
"""

from __future__ import annotations

import io
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


class _Engine:
    """假引擎：可记录 / 可失败地处理 set_gpt_weights。"""

    def __init__(self, fail=False):
        self.fail = fail
        self.weights = []

    async def set_gpt_weights(self, path):
        if self.fail:
            raise RuntimeError("权重切换失败")
        self.weights.append(path)


class _RM:
    """假资源管理器：记录 mark_model_loaded 调用，可在指定 flag 上抛错。"""

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def mark_model_loaded(self, name, flag):
        self.calls.append((name, flag))
        if self.fail_on is not None and flag is self.fail_on:
            raise RuntimeError("rm down")


class _Mgr:
    """假 TTS manager：记录 synthesize_bytes 的调用参数。"""

    def __init__(self, engine=None):
        self.engine = engine if engine is not None else types.SimpleNamespace()
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
    monkeypatch.delenv("XIAOYOU_TTS_DEFAULT_REF_WAV", raising=False)
    monkeypatch.delenv("XIAOYOU_TTS_AUTO_PROMPT_TEXT", raising=False)
    _use_manager(env, env.mgr)
    return env


def _use_manager(env, mgr, rm=None, rm_exc=None):
    """替换 get_tts_manager / get_resource_manager（均在函数体内 import）。"""
    env.mgr = mgr

    async def _get():
        return mgr

    env.mp.setattr(cv, "get_tts_manager", _get)
    if rm_exc is not None:
        def _boom():
            raise rm_exc

        env.mp.setattr(crm, "get_resource_manager", _boom)
    else:
        env.mp.setattr(crm, "get_resource_manager", lambda: rm)
    return mgr


def _mk_ref(env, name="ref.mp3", data=b"ID3"):
    d = env.root / "ref_audio" / "female"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(data)
    return p


async def _run(env, extra=None, text="你好"):
    params = {"speaker_wav": str(_mk_ref(env))}
    params.update(extra or {})
    return await tg.generate_tts_with_async(text, params)


def _kw(env):
    return env.mgr.bytes_calls[0][1]


def _has(env, needle: str) -> bool:
    return any(needle in msg for _, msg in env.log.records)


# --------------------------------------------------------------------------
# 1. GPT-SoVITS 权重切换
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "weights,expected",
    [
        ("models/tts/voice.ckpt", ["models/tts/voice.ckpt"]),  # 真路径 → 切换
        ("models\\tts\\voice.ckpt", ["models\\tts\\voice.ckpt"]),  # 反斜杠路径
        ("ref.wav", []),  # 音频文件 → 忽略
        ("myvoice", []),  # 非路径 ID → 跳过
        ("default", []),  # default → 跳过
    ],
)
async def test_gpt_weights_switching_branches(env, weights, expected):
    engine = _Engine()
    _use_manager(env, _Mgr(engine=engine))
    await _run(env, {"gpt_sovits_weights": weights})
    assert engine.weights == expected


async def test_gpt_weights_switch_failure_is_logged(env):
    engine = _Engine(fail=True)
    _use_manager(env, _Mgr(engine=engine))
    got = await _run(env, {"gpt_sovits_weights": "models/tts/voice.ckpt"})
    assert got["source"] == "core_voice"
    assert _has(env, "Failed to switch GPT-SoVITS weights")


async def test_engine_without_set_gpt_weights_skips(env):
    engine = types.SimpleNamespace()  # 没有 set_gpt_weights
    _use_manager(env, _Mgr(engine=engine))
    got = await _run(env, {"gpt_sovits_weights": "models/tts/voice.ckpt"})
    assert not hasattr(engine, "weights")
    assert got["audio_base64"].startswith("data:audio/wav;base64,")


# --------------------------------------------------------------------------
# 2. 语言映射 / voice 注入
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text_lang,prompt_lang,expected",
    [
        ("en-US", "ja", ("en", "ja")),
        ("JA", "zh", ("ja", "zh")),
        (None, "中文", ("zh", "zh")),
    ],
)
async def test_lang_mapping(env, text_lang, prompt_lang, expected):
    await _run(env, {"text_lang": text_lang, "prompt_lang": prompt_lang})
    kw = _kw(env)
    assert (kw["text_lang"], kw["prompt_lang"]) == expected


@pytest.mark.parametrize("voice,expect", [("Aveline", "Aveline"), ("", None)])
async def test_voice_param_injected_only_when_truthy(env, voice, expect):
    await _run(env, {"voice": voice})
    kw = _kw(env)
    assert kw.get("voice") == expect


# --------------------------------------------------------------------------
# 3. 资源管理器协作
# --------------------------------------------------------------------------
async def test_resource_manager_marks_loaded_then_released(env):
    rm = _RM()
    _use_manager(env, _Mgr(), rm=rm)
    await _run(env)
    assert rm.calls == [("tts_engine", True), ("tts_engine", False)]


async def test_resource_manager_none_is_ignored(env):
    _use_manager(env, _Mgr(), rm=None)
    got = await _run(env)
    assert got["source"] == "core_voice"


async def test_resource_manager_lookup_failure_is_swallowed(env):
    _use_manager(env, _Mgr(), rm_exc=RuntimeError("no rm"))
    got = await _run(env)
    assert got["source"] == "core_voice"


async def test_resource_manager_release_failure_is_swallowed(env):
    rm = _RM(fail_on=False)
    _use_manager(env, _Mgr(), rm=rm)
    got = await _run(env)
    assert rm.calls == [("tts_engine", True), ("tts_engine", False)]
    assert got["source"] == "core_voice"
