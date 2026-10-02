# -*- coding: utf-8 -*-
"""core/voice/tts_generation.py 单元测试（二）：prompt_text 解析（不含 STT）。

覆盖 `generate_tts_with_async` 中 prompt_text 的四种来源：显式入参、参考音频同名
`.txt` / `.lab` 旁挂文件、进程内 `_tts_prompt_text_cache`、以及磁盘
`tts_prompt_text/<md5>.txt` 缓存；外加缓存目录建不出来的降级分支。

纯 mock：不加载模型、不合成语音、不发网络请求，文件 IO 只落 tmp_path。
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
    """假 settings：只保留被测代码实际读取的字段。"""
    tts = types.SimpleNamespace(
        auto_prompt_text=auto, auto_prompt_text_from_ref=auto_from_ref
    )
    return types.SimpleNamespace(
        model=types.SimpleNamespace(cache_dir=cache_dir),
        voice=types.SimpleNamespace(tts=tts),
    )


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


class _Logger:
    """记录日志调用的假 logger（项目日志不传播到 caplog，只能自己收）。"""

    def __init__(self):
        self.records = []

    def _recorder(self, level):
        def _log(msg, *args, **kwargs):
            self.records.append((level, str(msg)))

        return _log

    def __getattr__(self, name):
        return self._recorder(name)


@pytest.fixture
def env(monkeypatch, tmp_path):
    """把项目根 / 配置 / TTS manager 全部重定向到临时目录与假对象。"""
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


def _mk_ref(env, name="ref.mp3", data=b"ID3"):
    d = env.root / "ref_audio" / "female"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(data)
    return p


def _digest(path) -> str:
    """prompt 磁盘缓存的文件名（md5 of 绝对路径）。"""
    return hashlib.md5(os.path.abspath(str(path)).encode("utf-8")).hexdigest()


async def _run(env, params, text="你好"):
    return await tg.generate_tts_with_async(text, params)


def _kw(env):
    return env.mgr.bytes_calls[0][1]


# --------------------------------------------------------------------------
# 1. prompt_text 来源
# --------------------------------------------------------------------------
async def test_prompt_text_from_params_wins(env):
    p = _mk_ref(env)
    await _run(env, {"speaker_wav": str(p), "prompt_text": "直接给定"})
    assert _kw(env)["prompt_text"] == "直接给定"


async def test_prompt_text_from_txt_sidecar_and_cached(env):
    p = _mk_ref(env)
    p.with_suffix(".txt").write_text("旁白文本", encoding="utf-8")
    await _run(env, {"speaker_wav": str(p)})
    assert _kw(env)["prompt_text"] == "旁白文本"
    assert list(tg._tts_prompt_text_cache.values()) == ["旁白文本"]


async def test_prompt_text_from_lab_sidecar(env):
    p = _mk_ref(env)
    p.with_suffix(".lab").write_text("lab文本", encoding="utf-8")
    await _run(env, {"speaker_wav": str(p)})
    assert _kw(env)["prompt_text"] == "lab文本"


async def test_prompt_sidecar_read_error_is_ignored(env):
    p = _mk_ref(env)
    p.with_suffix(".txt").mkdir()  # 目录 → open 抛 IsADirectoryError → 忽略
    await _run(env, {"speaker_wav": str(p)})
    assert _kw(env)["prompt_text"] is None


async def test_prompt_text_cache_hit_short_circuits(env):
    p = _mk_ref(env)
    abs_p = os.path.abspath(str(p))
    key = f"{abs_p}|{os.path.getmtime(abs_p):.6f}"
    tg._tts_prompt_text_cache[key] = "缓存文本"
    await _run(env, {"speaker_wav": str(p)})
    assert _kw(env)["prompt_text"] == "缓存文本"


async def test_prompt_text_from_prompt_cache_file(env):
    cache = env.tmp / "cache"
    env.mp.setattr(tg, "get_settings", lambda: _settings(cache_dir=str(cache)))
    p = _mk_ref(env)
    d = cache / "tts_prompt_text"
    d.mkdir(parents=True)
    (d / f"{_digest(p)}.txt").write_text("磁盘缓存文本", encoding="utf-8")
    await _run(env, {"speaker_wav": str(p)})
    assert _kw(env)["prompt_text"] == "磁盘缓存文本"


async def test_relative_cache_dir_resolved_under_project_root(env):
    env.mp.setattr(tg, "get_settings", lambda: _settings(cache_dir="relcache"))
    p = _mk_ref(env)
    d = env.root / "relcache" / "tts_prompt_text"
    d.mkdir(parents=True)
    (d / f"{_digest(p)}.txt").write_text("相对缓存", encoding="utf-8")
    await _run(env, {"speaker_wav": str(p)})
    assert _kw(env)["prompt_text"] == "相对缓存"


async def test_empty_cache_dir_defaults_to_cache_name(env):
    env.mp.setattr(tg, "get_settings", lambda: _settings(cache_dir=""))
    p = _mk_ref(env)
    d = env.root / "cache" / "tts_prompt_text"
    d.mkdir(parents=True)
    (d / f"{_digest(p)}.txt").write_text("默认缓存名", encoding="utf-8")
    await _run(env, {"speaker_wav": str(p)})
    assert _kw(env)["prompt_text"] == "默认缓存名"


async def test_prompt_cache_dir_create_failure_skips_file(env, monkeypatch):
    cache = env.tmp / "cache"
    env.mp.setattr(tg, "get_settings", lambda: _settings(cache_dir=str(cache)))
    real = os.makedirs

    def _fake(path, *a, **k):
        if "tts_prompt_text" in str(path):
            raise OSError("denied")
        return real(path, *a, **k)

    monkeypatch.setattr(tg.os, "makedirs", _fake)
    p = _mk_ref(env)
    await _run(env, {"speaker_wav": str(p)})
    assert _kw(env)["prompt_text"] is None


async def test_ref_mtime_error_uses_zero(env, monkeypatch):
    p = _mk_ref(env)
    p.with_suffix(".txt").write_text("旁白", encoding="utf-8")
    real = os.path.getmtime

    def _fake(path):
        if str(path).endswith("ref.mp3"):
            raise OSError("no mtime")
        return real(path)

    monkeypatch.setattr(tg.os.path, "getmtime", _fake)
    await _run(env, {"speaker_wav": str(p)})
    assert _kw(env)["prompt_text"] == "旁白"


async def test_auto_disabled_logs_skip(env):
    p = _mk_ref(env)
    await _run(env, {"speaker_wav": str(p)})
    assert _kw(env)["prompt_text"] is None
    assert any("跳过 STT 提示文本生成" in msg for _, msg in env.log.records)
