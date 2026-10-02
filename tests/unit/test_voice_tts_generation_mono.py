# -*- coding: utf-8 -*-
"""core/voice/tts_generation.py 单元测试（四）：`_ensure_mono_ref_wav` 各分支。

`_ensure_mono_ref_wav` 是 `generate_tts_with_async` 内的嵌套函数，只能经由主流程
触达；它用到的 `soundfile` 属 `voice` 可选 extra，CI 只装 `--extra dev`，
故这里把假 `soundfile` 注入 `sys.modules`（本地/CI 行为一致），不真的读音频。

纯 mock：假 manager + 假 soundfile，文件 IO 只落 tmp_path。
"""

from __future__ import annotations

import hashlib
import io
import os
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


class _Mgr:
    """假 TTS manager：记录 synthesize_bytes 的调用参数。"""

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


class _FakeSf:
    """假 soundfile 模块：可控制 info.channels / read 结果 / write 行为。"""

    def __init__(self, channels=2, data=None, read_exc=None, write_noop=False):
        self.channels = channels
        self.data = data
        self.read_exc = read_exc
        self.write_noop = write_noop
        self.calls = {"info": 0, "read": 0, "write": 0}

    def info(self, path):
        self.calls["info"] += 1
        return types.SimpleNamespace(channels=self.channels)

    def read(self, path, **kwargs):
        self.calls["read"] += 1
        if self.read_exc is not None:
            raise self.read_exc
        data = self.data
        if data is None:
            data = np.zeros((64, 2), dtype="float32")
        return data, 16000

    def write(self, path, mono, sr, **kwargs):
        self.calls["write"] += 1
        if self.write_noop:
            return
        with open(path, "wb") as f:
            f.write(b"MONO")


@pytest.fixture
def env(monkeypatch, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    env = types.SimpleNamespace(root=root, tmp=tmp_path, mgr=_Mgr(), mp=monkeypatch)
    monkeypatch.setattr(tg, "_project_root", lambda: str(root))
    monkeypatch.setattr(tg, "_project_root_path", lambda: root)
    monkeypatch.setattr(tg, "_tts_prompt_text_cache", {})
    monkeypatch.setattr(tg, "now_str", lambda _fmt: "20260101_000000")
    monkeypatch.setattr(tg, "get_settings", lambda: _settings())

    async def _get():
        return env.mgr

    monkeypatch.setattr(cv, "get_tts_manager", _get)
    monkeypatch.setattr(crm, "get_resource_manager", lambda: None)
    monkeypatch.delenv("XIAOYOU_TTS_DEFAULT_REF_WAV", raising=False)
    monkeypatch.delenv("XIAOYOU_TTS_AUTO_PROMPT_TEXT", raising=False)
    return env


def _use_sf(env, **kwargs) -> _FakeSf:
    sf = _FakeSf(**kwargs)
    env.mp.setitem(sys.modules, "soundfile", sf)
    return sf


def _mk_ref(env, name="ref_calm.wav", data=None):
    d = env.root / "ref_audio" / "female"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(_wav_bytes() if data is None else data)
    return p


def _cache_root(env, cache_dir):
    """复刻被测代码里 cache_root 的解析口径。"""
    return cache_dir if os.path.isabs(cache_dir) else str(env.root / cache_dir)


def _expected_out(env, ref, mtime, cache_dir="cache"):
    digest = hashlib.md5(f"{os.path.abspath(str(ref))}|{mtime:.6f}".encode("utf-8")).hexdigest()
    return os.path.join(_cache_root(env, cache_dir), "tts_ref_mono", f"{digest}_mono.wav")


async def _ref_audio(env, params):
    await tg.generate_tts_with_async("你好", params)
    return env.mgr.bytes_calls[0][1]["reference_audio"]


# --------------------------------------------------------------------------
# 1. 直接原样返回的分支
# --------------------------------------------------------------------------
async def test_mono_ref_nonexistent_path_returned_as_is(env):
    missing = str(env.tmp / "nope.wav")
    assert await _ref_audio(env, {"speaker_wav": missing}) == missing


async def test_mono_ref_non_wav_extension_returned_as_is(env):
    _use_sf(env)
    p = _mk_ref(env, "ref.mp3", b"ID3")
    assert await _ref_audio(env, {"speaker_wav": str(p)}) == str(p)


@pytest.mark.parametrize("channels", [1, None])
async def test_mono_ref_single_channel_returned_as_is(env, channels):
    sf = _use_sf(env, channels=channels)
    p = _mk_ref(env)
    assert await _ref_audio(env, {"speaker_wav": str(p)}) == str(p)
    assert sf.calls["info"] == 1


async def test_mono_ref_missing_soundfile_returned_as_is(env):
    env.mp.setitem(sys.modules, "soundfile", None)  # import 直接失败
    p = _mk_ref(env)
    assert await _ref_audio(env, {"speaker_wav": str(p)}) == str(p)


# --------------------------------------------------------------------------
# 2. 转换 / 缓存分支
# --------------------------------------------------------------------------
async def test_mono_ref_multichannel_converted_to_new_file(env):
    sf = _use_sf(env, channels=2)
    p = _mk_ref(env)
    got = await _ref_audio(env, {"speaker_wav": str(p)})
    assert got == _expected_out(env, p, os.path.getmtime(os.path.abspath(str(p))))
    assert os.path.exists(got)
    assert sf.calls == {"info": 1, "read": 1, "write": 1}


async def test_mono_ref_existing_converted_cache_is_reused(env):
    sf = _use_sf(env, channels=2)
    p = _mk_ref(env)
    out = _expected_out(env, p, os.path.getmtime(os.path.abspath(str(p))))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(b"CACHED")
    assert await _ref_audio(env, {"speaker_wav": str(p)}) == out
    assert sf.calls["read"] == 0  # 命中缓存，不再解码


async def test_mono_ref_empty_audio_returns_original(env):
    _use_sf(env, channels=2, data=np.zeros((0, 2), dtype="float32"))
    p = _mk_ref(env)
    assert await _ref_audio(env, {"speaker_wav": str(p)}) == str(p)


async def test_mono_ref_write_produced_nothing_returns_original(env):
    _use_sf(env, channels=2, write_noop=True)
    p = _mk_ref(env)
    assert await _ref_audio(env, {"speaker_wav": str(p)}) == str(p)


# --------------------------------------------------------------------------
# 3. 异常 / 路径解析分支
# --------------------------------------------------------------------------
async def test_mono_ref_makedirs_failure_returns_original(env, monkeypatch):
    _use_sf(env, channels=2)
    p = _mk_ref(env)
    real = os.makedirs

    def _fake(path, *a, **k):
        if "tts_ref_mono" in str(path):
            raise OSError("denied")
        return real(path, *a, **k)

    monkeypatch.setattr(tg.os, "makedirs", _fake)
    assert await _ref_audio(env, {"speaker_wav": str(p)}) == str(p)


async def test_mono_ref_getmtime_error_uses_zero(env, monkeypatch):
    _use_sf(env, channels=2)
    p = _mk_ref(env)
    real = os.path.getmtime

    def _fake(path):
        if str(path).endswith("ref_calm.wav"):
            raise OSError("no mtime")
        return real(path)

    monkeypatch.setattr(tg.os.path, "getmtime", _fake)
    got = await _ref_audio(env, {"speaker_wav": str(p)})
    assert got == _expected_out(env, p, 0.0)
    assert os.path.exists(got)


async def test_mono_ref_relative_cache_dir_under_project_root(env):
    env.mp.setattr(tg, "get_settings", lambda: _settings(cache_dir="relcache"))
    _use_sf(env, channels=2)
    p = _mk_ref(env)
    mtime = os.path.getmtime(os.path.abspath(str(p)))
    got = await _ref_audio(env, {"speaker_wav": str(p)})
    assert got == _expected_out(env, p, mtime, cache_dir="relcache")
    assert os.path.exists(got)
