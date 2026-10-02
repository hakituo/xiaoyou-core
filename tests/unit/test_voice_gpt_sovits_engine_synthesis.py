"""core/voice/engines/gpt_sovits_engine.py —— 合成与关闭单元测试。

覆盖 ``synthesize`` / ``_synthesize_impl`` / ``synthesize_bytes`` / ``shutdown``。

全部用假 session 替换 aiohttp，不发起真实网络请求；文件 IO 落在 ``tmp_path``。
"""

from __future__ import annotations

import logging
import os
from types import SimpleNamespace

import aiohttp
import numpy as np
import pytest

import core.voice.engines.gpt_sovits_engine as mod
from core.voice.engines.gpt_sovits_engine import GPTSoVITSEngine


class FakeResponse:
    def __init__(self, status=200, text="", body=b""):
        self.status, self._text, self._body = status, text, body

    async def text(self):
        return self._text

    async def read(self):
        return self._body


class _Ctx:
    def __init__(self, resp=None, exc=None):
        self._resp, self._exc = resp, exc

    async def __aenter__(self):
        if self._exc is not None:
            raise self._exc
        return self._resp

    async def __aexit__(self, *exc_info):
        return False


class FakeSession:
    def __init__(self, get_plan=None):
        self.get_calls = []
        self._get_plan = list(get_plan or [])

    def get(self, url, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        item = self._get_plan.pop(0) if self._get_plan else FakeResponse()
        return _Ctx(exc=item) if isinstance(item, BaseException) else _Ctx(item)


class _ClosableSession:
    def __init__(self, closed=False, close_exc=None):
        self.closed, self.close_calls, self._close_exc = closed, 0, close_exc

    async def close(self):
        self.close_calls += 1
        if self._close_exc is not None:
            raise self._close_exc


class _FakeLock:
    def __init__(self):
        self.calls = []

    def acquire(self, name, reject_if_full=False):
        self.calls.append((name, reject_if_full))
        return _Ctx(object())


class _FakeSoundFile:
    """假 soundfile：只实现 read。"""

    def __init__(self, data=None, samplerate=32000, exc=None):
        self._data, self._samplerate, self._exc = data, samplerate, exc

    def read(self, file_obj):
        if self._exc is not None:
            raise self._exc
        return self._data, self._samplerate


class _VoiceStub:
    def __init__(self, reference_audio=None):
        self.reference_audio = reference_audio


class _SettingsStub:
    def __init__(self, reference_audio=None):
        self.voice = _VoiceStub(reference_audio)


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def engine():
    return GPTSoVITSEngine()


@pytest.fixture
def log_records():
    """挂 handler 到被测模块 logger（该 logger propagate=False，caplog 抓不到）。"""
    handler = _ListHandler()
    mod.logger.addHandler(handler)
    yield handler.records
    mod.logger.removeHandler(handler)


def _patch_session(monkeypatch, session):
    async def _fake(_engine):
        return session

    monkeypatch.setattr(mod, "get_cloud_tts_session", _fake)


def _patch_settings(monkeypatch, reference_audio=None):
    monkeypatch.setattr(mod, "get_settings", lambda: _SettingsStub(reference_audio))


def _patch_runtime(monkeypatch, *, frozen=False, executable="C:/app/python.exe",
                   meipass=None, root=None):
    fake_sys = SimpleNamespace(frozen=frozen, executable=executable)
    if meipass is not None:
        fake_sys._MEIPASS = meipass
    monkeypatch.setattr(mod, "sys", fake_sys)
    if root is not None:
        monkeypatch.setattr(mod, "get_project_root", lambda: root)


def _spy_bytes(engine, monkeypatch, result=b"RIFF", exc=None):
    """把 synthesize_bytes 换成记录调用的替身（_synthesize_impl 的下游协作者）。"""
    calls = []

    async def _fake(text, **kwargs):
        calls.append((text, kwargs))
        if exc is not None:
            raise exc
        return result

    monkeypatch.setattr(engine, "synthesize_bytes", _fake)
    return calls


def _setup_bytes(engine, monkeypatch, *, get_plan=None, reference_audio=None,
                 lock=False, root=None, frozen=False, executable="C:/app/python.exe",
                 meipass=None):
    """synthesize_bytes 的通用环境：假 session + 设置 + 资源锁。"""
    session = FakeSession(get_plan=get_plan)
    _patch_session(monkeypatch, session)
    _patch_settings(monkeypatch, reference_audio)
    _patch_runtime(monkeypatch, frozen=frozen, executable=executable, meipass=meipass,
                   root=root)
    lock_obj = _FakeLock() if lock else None
    monkeypatch.setattr(mod, "get_resource_lock", (lambda: lock_obj) if lock else None)
    return session, lock_obj


class TestSynthesize:
    async def test_sets_and_clears_flag(self, engine, monkeypatch):
        expected = np.array([0.1, 0.2], dtype=np.float32)
        observed = []

        async def _impl(text, **kwargs):
            observed.append(engine._is_generating)
            return expected

        monkeypatch.setattr(engine, "_synthesize_impl", _impl)
        result = await engine.synthesize("你好", speed=1.1)
        assert result is expected
        assert observed == [True]          # 合成期间为 True
        assert engine._is_generating is False  # finally 复位

    async def test_flag_reset_on_failure(self, engine, monkeypatch):
        async def _impl(text, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(engine, "_synthesize_impl", _impl)
        with pytest.raises(RuntimeError, match="boom"):
            await engine.synthesize("你好")
        assert engine._is_generating is False


class TestSynthesizeImpl:
    @pytest.fixture(autouse=True)
    def _decode_ok(self, monkeypatch):
        monkeypatch.setattr(mod, "sf", _FakeSoundFile(np.array([1, 2, 3], dtype=np.int16)))

    async def test_returns_float32_and_forwards_kwargs(self, engine, monkeypatch, tmp_path):
        _patch_settings(monkeypatch, "ref.wav")
        _patch_runtime(monkeypatch, root=str(tmp_path))
        calls = _spy_bytes(engine, monkeypatch)

        result = await engine._synthesize_impl("你好", speed=1.3)

        assert result.dtype == np.float32
        assert result.tolist() == [1.0, 2.0, 3.0]
        assert calls == [("你好", {"speed": 1.3})]

    @pytest.mark.parametrize("kwargs", [
        {"lang": "en"}, {"text_lang": "ja"}, {"text_language": "ko"},
        {"lang": "en", "text_lang": "ja"}, {},
    ])
    async def test_language_resolution_branches(self, engine, monkeypatch, tmp_path, kwargs):
        _patch_settings(monkeypatch, "ref.wav")
        _patch_runtime(monkeypatch, root=str(tmp_path))
        calls = _spy_bytes(engine, monkeypatch)
        engine.default_lang = "fr"

        result = await engine._synthesize_impl("hi", **kwargs)

        assert result.shape == (3,)
        assert calls[0][0] == "hi"

    async def test_optional_params_passthrough(self, engine, monkeypatch, tmp_path):
        _patch_settings(monkeypatch, "ref.wav")
        _patch_runtime(monkeypatch, root=str(tmp_path))
        calls = _spy_bytes(engine, monkeypatch)

        await engine._synthesize_impl("hi", batch_size=3, speed_factor=1.2, pitch=2,
                                      prompt_text="pt", prompt_lang="ja")

        assert calls[0][1] == {"batch_size": 3, "speed_factor": 1.2, "pitch": 2,
                               "prompt_text": "pt", "prompt_lang": "ja"}

    async def test_none_optional_params_kept_in_raw_kwargs(self, engine, monkeypatch,
                                                           tmp_path):
        _patch_settings(monkeypatch, "ref.wav")
        _patch_runtime(monkeypatch, root=str(tmp_path))
        calls = _spy_bytes(engine, monkeypatch)

        await engine._synthesize_impl("hi", batch_size=None, speed_factor=None, pitch=None)

        # 注意：本方法构造的 params 未被使用，原始 kwargs（含 None）直接透传下游。
        assert calls[0][1] == {"batch_size": None, "speed_factor": None, "pitch": None}

    # ---------- 非 frozen 路径解析（通过 warning 日志观察解析结果）----------

    @pytest.mark.parametrize("ref_audio,ref_kw,expected_tail", [
        (None, None, ("ref_audio", "female", "ref_calm.wav")),
        ("ref.wav", None, ("ref.wav",)),
        (None, "custom/ref.wav", ("custom", "ref.wav")),
    ])
    async def test_non_frozen_ref_resolution(self, engine, monkeypatch, tmp_path,
                                             log_records, ref_audio, ref_kw, expected_tail):
        _patch_settings(monkeypatch, ref_audio)
        _patch_runtime(monkeypatch, root=str(tmp_path))
        _spy_bytes(engine, monkeypatch)

        kwargs = {} if ref_kw is None else {"ref_audio_path": ref_kw}
        await engine._synthesize_impl("hi", **kwargs)

        if ref_kw is not None:
            expected = os.path.abspath(os.path.join(str(tmp_path), *expected_tail))
        else:
            expected = os.path.join(str(tmp_path), *expected_tail)
        assert any(f"does not exist locally: {expected}" in r.getMessage()
                   for r in log_records)

    async def test_existing_ref_audio_does_not_warn(self, engine, monkeypatch, tmp_path,
                                                    log_records):
        ref = tmp_path / "ref.wav"
        ref.write_bytes(b"x")
        _patch_settings(monkeypatch, None)
        _patch_runtime(monkeypatch, root=str(tmp_path))
        _spy_bytes(engine, monkeypatch)

        await engine._synthesize_impl("hi", ref_audio_path=str(ref))

        assert not any("does not exist locally" in r.getMessage() for r in log_records)

    # ---------- frozen（EXE）路径解析 ----------

    async def test_frozen_external_ref_wins(self, engine, monkeypatch, tmp_path, log_records):
        (tmp_path / "ref.wav").write_bytes(b"x")
        _patch_settings(monkeypatch, "ref.wav")
        _patch_runtime(monkeypatch, frozen=True, executable=str(tmp_path / "app.exe"))
        _spy_bytes(engine, monkeypatch)

        await engine._synthesize_impl("hi")
        assert not any("does not exist locally" in r.getMessage() for r in log_records)

    async def test_frozen_internal_ref_used(self, engine, monkeypatch, tmp_path, log_records):
        internal = tmp_path / "internal"
        internal.mkdir()
        (internal / "ref.wav").write_bytes(b"x")
        _patch_settings(monkeypatch, "ref.wav")
        _patch_runtime(monkeypatch, frozen=True, executable=str(tmp_path / "app.exe"),
                       meipass=str(internal))
        _spy_bytes(engine, monkeypatch)

        await engine._synthesize_impl("hi")
        assert not any("does not exist locally" in r.getMessage() for r in log_records)

    @pytest.mark.parametrize("ref_kw,expected_tail", [
        (None, ("ref_audio", "female", "ref_calm.wav")),
        ("rel.wav", ("rel.wav",)),
    ])
    async def test_frozen_fallback_and_relative(self, engine, monkeypatch, tmp_path,
                                                log_records, ref_kw, expected_tail):
        _patch_settings(monkeypatch, "ref.wav")
        _patch_runtime(monkeypatch, frozen=True, executable=str(tmp_path / "app.exe"))
        _spy_bytes(engine, monkeypatch)

        kwargs = {} if ref_kw is None else {"ref_audio_path": ref_kw}
        await engine._synthesize_impl("hi", **kwargs)

        expected = os.path.join(str(tmp_path), *expected_tail)
        assert any(f"does not exist locally: {expected}" in r.getMessage()
                   for r in log_records)

    # ---------- 错误分支 ----------

    async def test_empty_audio_raises(self, engine, monkeypatch, tmp_path):
        _patch_settings(monkeypatch, "ref.wav")
        _patch_runtime(monkeypatch, root=str(tmp_path))
        _spy_bytes(engine, monkeypatch, result=b"")

        with pytest.raises(RuntimeError, match="returned empty audio data"):
            await engine._synthesize_impl("hi")

    async def test_missing_soundfile_raises(self, engine, monkeypatch, tmp_path):
        _patch_settings(monkeypatch, "ref.wav")
        _patch_runtime(monkeypatch, root=str(tmp_path))
        _spy_bytes(engine, monkeypatch, result=b"RIFF")
        monkeypatch.setattr(mod, "sf", None)

        with pytest.raises(RuntimeError, match="soundfile library not installed"):
            await engine._synthesize_impl("hi")

    async def test_decode_failure_wrapped(self, engine, monkeypatch, tmp_path):
        _patch_settings(monkeypatch, "ref.wav")
        _patch_runtime(monkeypatch, root=str(tmp_path))
        _spy_bytes(engine, monkeypatch, result=b"RIFF")
        monkeypatch.setattr(mod, "sf", _FakeSoundFile(exc=ValueError("bad wav")))

        with pytest.raises(RuntimeError, match="Audio decoding failed") as info:
            await engine._synthesize_impl("hi")
        assert isinstance(info.value.__cause__, ValueError)


class TestSynthesizeBytes:
    @pytest.mark.parametrize("lock,body", [(True, b"WAVDATA"), (False, b"WAV")])
    async def test_success(self, engine, monkeypatch, tmp_path, lock, body):
        session, lock_obj = _setup_bytes(
            engine, monkeypatch, get_plan=[FakeResponse(200, body=body)],
            lock=lock, root=str(tmp_path))

        assert await engine.synthesize_bytes("你好", speed=1.5) == body
        params = session.get_calls[0]["params"]
        assert params["text"] == "你好" and params["text_lang"] == "zh"
        assert params["speed"] == 1.5 and params["top_k"] == 5
        assert session.get_calls[0]["url"] == engine.api_url
        assert (lock_obj.calls if lock_obj else []) == ([("TTS", True)] if lock else [])

    async def test_empty_body_returns_none(self, engine, monkeypatch, tmp_path):
        _setup_bytes(engine, monkeypatch, get_plan=[FakeResponse(200, body=b"")],
                     root=str(tmp_path))
        assert await engine.synthesize_bytes("hi") is None

    @pytest.mark.parametrize("lock,status,text", [
        (False, 500, "boom"), (True, 404, "missing"),
    ])
    async def test_non_200_raises_api_error(self, engine, monkeypatch, tmp_path,
                                            lock, status, text):
        _setup_bytes(engine, monkeypatch, get_plan=[FakeResponse(status, text=text)],
                     lock=lock, root=str(tmp_path))
        with pytest.raises(RuntimeError, match=f"GPT-SoVITS API Error: {status} - {text}"):
            await engine.synthesize_bytes("hi")

    async def test_connection_error_wrapped_and_cooldown(self, engine, monkeypatch, tmp_path):
        _setup_bytes(engine, monkeypatch,
                     get_plan=[aiohttp.ClientError("connection refused")], root=str(tmp_path))

        with pytest.raises(RuntimeError, match="服务未启动或不可用"):
            await engine.synthesize_bytes("hi")
        assert engine._control_unavailable_until > 0.0

    async def test_non_connection_error_reraised(self, engine, monkeypatch, tmp_path):
        _setup_bytes(engine, monkeypatch, get_plan=[ValueError("bad params")],
                     root=str(tmp_path))

        with pytest.raises(ValueError, match="bad params"):
            await engine.synthesize_bytes("hi")
        assert engine._control_unavailable_until == 0.0

    @pytest.mark.parametrize("kwargs,expected_lang", [
        ({}, "zh"), ({"lang": "en"}, "en"), ({"text_lang": "ja"}, "ja"),
        ({"text_language": "ko"}, "ko"),
    ])
    async def test_language_resolution(self, engine, monkeypatch, tmp_path, kwargs,
                                       expected_lang):
        session, _ = _setup_bytes(
            engine, monkeypatch, get_plan=[FakeResponse(200, body=b"W")], root=str(tmp_path))
        await engine.synthesize_bytes("hi", **kwargs)
        assert session.get_calls[0]["params"]["text_lang"] == expected_lang

    async def test_optional_params_included(self, engine, monkeypatch, tmp_path):
        session, _ = _setup_bytes(
            engine, monkeypatch, get_plan=[FakeResponse(200, body=b"W")], root=str(tmp_path))
        await engine.synthesize_bytes("hi", batch_size=2, speed_factor=0.9, pitch=1,
                                      prompt_text="p")
        params = session.get_calls[0]["params"]
        assert (params["batch_size"], params["speed_factor"], params["pitch"],
                params["prompt_text"]) == (2, 0.9, 1, "p")

    async def test_optional_params_none_dropped(self, engine, monkeypatch, tmp_path):
        session, _ = _setup_bytes(
            engine, monkeypatch, get_plan=[FakeResponse(200, body=b"W")], root=str(tmp_path))
        await engine.synthesize_bytes("hi", batch_size=None, speed_factor=None, pitch=None)
        params = session.get_calls[0]["params"]
        assert "batch_size" not in params and "speed_factor" not in params
        assert "pitch" not in params

    async def test_relative_ref_audio_absolutized(self, engine, monkeypatch, tmp_path):
        session, _ = _setup_bytes(
            engine, monkeypatch, get_plan=[FakeResponse(200, body=b"W")], root=str(tmp_path))
        await engine.synthesize_bytes("hi", ref_audio_path="custom/ref.wav")
        expected = os.path.abspath(os.path.join(str(tmp_path), "custom", "ref.wav"))
        assert session.get_calls[0]["params"]["ref_audio_path"] == expected

    async def test_non_frozen_relative_default_ref(self, engine, monkeypatch, tmp_path):
        session, _ = _setup_bytes(
            engine, monkeypatch, get_plan=[FakeResponse(200, body=b"W")],
            reference_audio="ref.wav", root=str(tmp_path))
        await engine.synthesize_bytes("hi")
        assert session.get_calls[0]["params"]["ref_audio_path"] == \
            os.path.join(str(tmp_path), "ref.wav")

    async def test_frozen_default_ref_resolution(self, engine, monkeypatch, tmp_path):
        session, _ = _setup_bytes(
            engine, monkeypatch, get_plan=[FakeResponse(200, body=b"W")],
            frozen=True, executable=str(tmp_path / "app.exe"))
        await engine.synthesize_bytes("hi")
        assert session.get_calls[0]["params"]["ref_audio_path"] == \
            os.path.join(str(tmp_path), "ref_audio", "female", "ref_calm.wav")

    async def test_frozen_relative_ref_uses_executable_dir(self, engine, monkeypatch, tmp_path):
        session, _ = _setup_bytes(
            engine, monkeypatch, get_plan=[FakeResponse(200, body=b"W")],
            reference_audio="ref.wav", frozen=True,
            executable=str(tmp_path / "app.exe"))
        await engine.synthesize_bytes("hi", ref_audio_path="rel.wav")
        assert session.get_calls[0]["params"]["ref_audio_path"] == \
            os.path.join(str(tmp_path), "rel.wav")

    @pytest.mark.parametrize("external_exists", [True, False])
    async def test_frozen_external_or_internal_ref(self, engine, monkeypatch, tmp_path,
                                                   external_exists):
        internal = tmp_path / "internal"
        internal.mkdir()
        (internal / "ref.wav").write_bytes(b"x")
        if external_exists:
            (tmp_path / "ref.wav").write_bytes(b"x")
        session, _ = _setup_bytes(
            engine, monkeypatch, get_plan=[FakeResponse(200, body=b"W")],
            reference_audio="ref.wav", frozen=True,
            executable=str(tmp_path / "app.exe"), meipass=str(internal))

        await engine.synthesize_bytes("hi")

        expected = tmp_path / "ref.wav" if external_exists else internal / "ref.wav"
        assert session.get_calls[0]["params"]["ref_audio_path"] == str(expected)


class TestShutdown:
    @pytest.mark.parametrize("closed,expected_close", [(False, 1), (True, 0)])
    async def test_closes_only_open_session(self, engine, closed, expected_close):
        session = _ClosableSession(closed=closed)
        engine._session, engine._session_loop, engine.initialized = session, object(), True

        await engine.shutdown()

        assert session.close_calls == expected_close
        assert engine._session is None and engine._session_loop is None
        assert engine.initialized is False

    async def test_no_session_is_noop(self, engine):
        engine._session = None
        await engine.shutdown()
        assert engine._session is None and engine.initialized is False

    async def test_close_failure_swallowed(self, engine):
        engine._session = _ClosableSession(close_exc=RuntimeError("close boom"))
        await engine.shutdown()
        assert engine._session is None and engine._session_loop is None
