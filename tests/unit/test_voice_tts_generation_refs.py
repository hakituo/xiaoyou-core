# -*- coding: utf-8 -*-
"""core/voice/tts_generation.py 单元测试（一）：模块级助手 + 参考音频解析。

覆盖 `_project_root` / `_project_root_path` / `_voice_dir` 三个助手，以及
`generate_tts_with_async` 前半段对 `speaker_wav` / `reference_audio` 的归一化分支。

全部走纯 mock：TTS manager 用假对象，配置用 SimpleNamespace，文件 IO 只落
pytest 的 tmp_path，不加载模型、不发网络请求、不合成语音。
"""

from __future__ import annotations

import io
import os
import types
import wave

import pytest

import core.resource_manager as crm
import core.utils.common as common
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
    """假 settings：只保留被测代码实际读取的字段。"""
    tts = types.SimpleNamespace(
        auto_prompt_text=auto, auto_prompt_text_from_ref=auto_from_ref
    )
    return types.SimpleNamespace(
        model=types.SimpleNamespace(cache_dir=cache_dir),
        voice=types.SimpleNamespace(tts=tts),
    )


class _Engine:
    """假引擎：记录 set_gpt_weights 调用。"""

    def __init__(self, sample_rate=32000):
        self.sample_rate = sample_rate
        self.weights = []

    async def set_gpt_weights(self, path):
        self.weights.append(path)


class _Mgr:
    """假 TTS manager：记录 synthesize_bytes / synthesize 的调用参数。"""

    def __init__(self, bytes_result=None, bytes_exc=None, array_result=None,
                 array_exc=None, last_error=None, engine=None):
        self.engine = engine if engine is not None else _Engine()
        self._bytes = _wav_bytes() if bytes_result is None else bytes_result
        self._bytes_exc = bytes_exc
        self._array = array_result
        self._array_exc = array_exc
        self.last_error = last_error
        self.sample_rate = 32000
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


@pytest.fixture
def env(monkeypatch, tmp_path):
    """把项目根 / 配置 / TTS manager 全部重定向到临时目录与假对象。"""
    root = tmp_path / "root"
    root.mkdir()
    env = types.SimpleNamespace(root=root, tmp=tmp_path, mgr=None, mp=monkeypatch)
    monkeypatch.setattr(tg, "_project_root", lambda: str(root))
    monkeypatch.setattr(tg, "_project_root_path", lambda: root)
    monkeypatch.setattr(tg, "_tts_prompt_text_cache", {})
    monkeypatch.setattr(tg, "now_str", lambda _fmt: "20260101_000000")
    monkeypatch.setattr(tg, "get_settings", lambda: _settings())
    monkeypatch.delenv("XIAOYOU_TTS_DEFAULT_REF_WAV", raising=False)
    monkeypatch.delenv("XIAOYOU_TTS_AUTO_PROMPT_TEXT", raising=False)
    _use_manager(env, _Mgr())
    return env


def _mk_ref(env, name="ref.mp3", data=b"ID3"):
    """在 <root>/ref_audio/female 下放一个参考音频文件。"""
    d = env.root / "ref_audio" / "female"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(data)
    return p


def _default_ref(env) -> str:
    return str(env.root / "ref_audio" / "female" / "ref_calm.wav")


async def _run(env, params, text="你好"):
    return await tg.generate_tts_with_async(text, params)


def _kw(env):
    """synthesize_bytes 首次调用的关键字参数。"""
    return env.mgr.bytes_calls[0][1]


# --------------------------------------------------------------------------
# 1. 模块级助手
# --------------------------------------------------------------------------
def test_project_root_returns_str(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "get_project_root", lambda: tmp_path)
    got = tg._project_root()
    assert got == str(tmp_path)
    assert isinstance(got, str)


def test_project_root_path_returns_path(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "get_project_root", lambda: tmp_path)
    assert tg._project_root_path() == tmp_path


def test_voice_dir_creates_and_returns_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(tg, "_project_root", lambda: str(tmp_path / "r"))
    first = tg._voice_dir()
    second = tg._voice_dir()  # 第二次走 exist_ok=True 分支
    assert first == os.path.join(str(tmp_path / "r"), "output", "voice")
    assert first == second
    assert os.path.isdir(first)


# --------------------------------------------------------------------------
# 2. speaker_wav / reference_audio 归一化
# --------------------------------------------------------------------------
@pytest.mark.parametrize("token", ["default", "female", "DEFAULT", "Female"])
async def test_default_token_falls_back_to_default_path(env, token):
    await _run(env, {"speaker_wav": token})
    assert _kw(env)["reference_audio"] == _default_ref(env)


async def test_env_override_wins_over_default_path(env, monkeypatch):
    p = _mk_ref(env, "custom.mp3")
    monkeypatch.setenv("XIAOYOU_TTS_DEFAULT_REF_WAV", str(p))
    await _run(env, {"speaker_wav": "default"})
    assert _kw(env)["reference_audio"] == str(p)


async def test_digit_token_picks_sorted_candidate(env):
    _mk_ref(env, "b.mp3", b"ID3b")
    _mk_ref(env, "a.mp3", b"ID3a")
    await _run(env, {"speaker_wav": "2"})
    assert _kw(env)["reference_audio"].endswith("b.mp3")


async def test_digit_token_out_of_range_uses_default(env):
    _mk_ref(env, "a.mp3", b"ID3a")
    await _run(env, {"speaker_wav": "9"})
    assert _kw(env)["reference_audio"] == _default_ref(env)


async def test_digit_token_without_ref_dir_uses_default(env):
    await _run(env, {"speaker_wav": "1"})
    assert _kw(env)["reference_audio"] == _default_ref(env)


async def test_digit_token_listdir_error_uses_default(env):
    """ref_audio/female 是文件而非目录 → listdir 抛错 → 走 except 回退。"""
    d = env.root / "ref_audio" / "female"
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_bytes(b"not a dir")
    await _run(env, {"speaker_wav": "1"})
    assert _kw(env)["reference_audio"] == _default_ref(env)


async def test_missing_path_falls_back_to_ref_audio_female(env):
    """给的是绝对路径但不存在 → 用 basename 去 ref_audio/female 找同名文件。"""
    p = _mk_ref(env, "custom.mp3")
    await _run(env, {"reference_audio": str(env.tmp / "elsewhere" / "custom.mp3")})
    assert _kw(env)["reference_audio"] == str(p)


async def test_missing_ref_with_default_present_uses_default(env):
    _mk_ref(env, "ref_calm.wav", _wav_bytes())
    await _run(env, {"speaker_wav": str(env.tmp / "nope.wav")})
    assert _kw(env)["reference_audio"] == _default_ref(env)


async def test_non_string_ref_currently_raises_type_error(env):
    """speaker_wav 传非字符串（int）时当前会崩：isinstance 守卫跳过归一化，
    随后 os.path.basename(int) 抛 TypeError（已单列报告，未改源码）。"""
    _mk_ref(env, "ref_calm.wav", _wav_bytes())
    with pytest.raises(TypeError):
        await _run(env, {"speaker_wav": 123})


async def test_no_ref_param_uses_default(env):
    await _run(env, {})
    assert _kw(env)["reference_audio"] == _default_ref(env)
    assert _kw(env)["prompt_text"] is None
