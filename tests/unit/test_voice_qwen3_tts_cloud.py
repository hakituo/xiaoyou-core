"""core/voice/qwen3_tts_cloud.py 单元测试。

覆盖范围：
- ``Qwen3TTSCloudEngine.__init__``：api_key 优先级（参数 > 环境变量）、默认参数、告警/信息日志
- ``initialize`` / ``_get_session`` / ``_close_session`` / ``shutdown``：会话创建、复用、重建与关闭各分支
- ``synthesize``：请求载荷构建、声音克隆（参考音频存在/缺失、参考文本有无）、
  instruct 指令与 optimize_instructions、HTTP 错误、任务 FAILED、
  音频 URL 下载（成功/失败）、Base64（str / 嵌套 dict / 原始 bytes）、旧格式兼容、
  无音频数据报错、自动初始化、异常透传
- ``_encode_audio_to_base64``：各扩展名 MIME 映射、文件缺失异常
- ``synthesize_bytes``：成功返回 WAV 字节、失败返回 None
- ``get_status``：已初始化 / 未初始化两种状态

全部使用纯替身（伪造 aiohttp 会话与日志器）与本地生成的 WAV 字节，
绝不真实请求云端 TTS 服务；同步测试 + ``asyncio.run`` 风格。
"""

from __future__ import annotations

import asyncio
import base64
import io

import numpy as np
import pytest
import soundfile as sf

from core.voice import qwen3_tts_cloud as qc


# ============================================================
# 替身：aiohttp 会话 / 响应 / 日志器
# ============================================================

class _FakeTimeout:
    """``aiohttp.ClientTimeout`` 替身，仅记录 total。"""

    def __init__(self, **kwargs):
        self.kwargs = dict(kwargs)
        self.total = kwargs.get("total")


class _FakeResponse:
    """HTTP 响应替身：status / text() / json() / read() 全部可控。"""

    def __init__(self, *, status=200, text="", json_data=None, body=b""):
        self.status = status
        self._text = text
        self._json = json_data
        self._body = body

    async def text(self):
        return self._text

    async def json(self):
        return self._json

    async def read(self):
        return self._body


class _FakeRequestCM:
    """``session.post(...)`` / ``session.get(...)`` 返回的异步上下文管理器。"""

    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    """aiohttp.ClientSession 替身：支持 post/get、async with、close 与 closed 状态。"""

    def __init__(self, *, response=None, get_response=None, post_exc=None,
                 get_exc=None, **kwargs):
        self._response = response
        self._get_response = get_response
        self._post_exc = post_exc
        self._get_exc = get_exc
        self.init_kwargs = dict(kwargs)
        self.closed = False
        self.close_calls = 0
        self.post_calls = []
        self.get_calls = []

    def post(self, url, json=None):
        self.post_calls.append({"url": url, "json": json})
        if self._post_exc is not None:
            raise self._post_exc
        return _FakeRequestCM(self._response)

    def get(self, url):
        self.get_calls.append(url)
        if self._get_exc is not None:
            raise self._get_exc
        return _FakeRequestCM(self._get_response)

    async def close(self):
        self.close_calls += 1
        self.closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.closed = True
        return False


class _FakeAiohttp:
    """aiohttp 模块替身，暴露 ClientTimeout 与 ClientSession 工厂。"""

    def __init__(self, session_factory):
        self._session_factory = session_factory
        self.timeout_calls = []

    def ClientTimeout(self, **kwargs):
        self.timeout_calls.append(dict(kwargs))
        return _FakeTimeout(**kwargs)

    def ClientSession(self, **kwargs):
        return self._session_factory(**kwargs)


class _RecordingLogger:
    """模块级 logger 替身（真实 logger 的 propagate=False，不便用 caplog）。"""

    def __init__(self):
        self.records = []

    def _log(self, level, msg):
        self.records.append((level, msg))

    def debug(self, msg, *args, **kwargs):
        self._log("debug", msg)

    def info(self, msg, *args, **kwargs):
        self._log("info", msg)

    def warning(self, msg, *args, **kwargs):
        self._log("warning", msg)

    def error(self, msg, *args, **kwargs):
        self._log("error", msg)

    def messages(self, level=None):
        return [m for lv, m in self.records if level is None or lv == level]


# ============================================================
# 工具：本地 WAV 字节、引擎装配
# ============================================================

def _wav_bytes(samples: int = 2400, sample_rate: int = 24000) -> bytes:
    """生成一段合法的 WAV 字节（纯本地，无网络）。"""
    buf = io.BytesIO()
    sf.write(buf, np.zeros(samples, dtype=np.float32), sample_rate, format="WAV")
    return buf.getvalue()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def _make_engine(monkeypatch, *, initialized=True, api_key="sk-test",
                 model="qwen3-tts-flash", response=None, post_exc=None,
                 download_response=None, get_exc=None):
    """装配一个注入替身 aiohttp 的引擎。

    返回 ``(engine, main_sessions, download_sessions, ns)``：
    带 timeout/headers 的会话创建（主会话）进 main_sessions，
    无参创建（音频下载会话）进 download_sessions。
    """
    main_sessions = []
    download_sessions = []

    def factory(**kwargs):
        if kwargs:  # _get_session 传入 timeout/headers -> 主会话
            sess = _FakeSession(response=response, post_exc=post_exc, **kwargs)
            main_sessions.append(sess)
        else:  # aiohttp.ClientSession() 无参 -> 下载会话
            sess = _FakeSession(get_response=download_response, get_exc=get_exc)
            download_sessions.append(sess)
        return sess

    ns = _FakeAiohttp(factory)
    monkeypatch.setattr(qc, "aiohttp", ns)

    engine = qc.Qwen3TTSCloudEngine(api_key=api_key, model=model)
    engine.initialized = initialized
    if initialized:
        engine.session = factory(timeout=None, headers={})
    return engine, main_sessions, download_sessions, ns


def _ok_audio_response(*, audio_field, output_extra=None):
    """构造一个 status=200、携带指定 audio 字段的成功响应。"""
    output = {"audio": audio_field}
    if output_extra:
        output.update(output_extra)
    return _FakeResponse(json_data={"output": output})


# ============================================================
# __init__
# ============================================================

def test_init_defaults_and_inheritance(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    engine = qc.Qwen3TTSCloudEngine(api_key="sk-abc")

    assert isinstance(engine, qc.TTSEngine)
    assert engine.api_key == "sk-abc"
    assert engine.model == "qwen3-tts-flash"
    assert engine.base_url.startswith("https://dashscope.aliyuncs.com/")
    assert engine.timeout == 300
    assert engine.session is None
    assert engine.initialized is False
    assert engine.default_voice == "Cherry"
    assert engine.default_language == "Chinese"
    assert engine.default_speed == 1.0
    assert engine.default_volume == 1.0


def test_init_reads_api_key_from_env(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-env")
    engine = qc.Qwen3TTSCloudEngine()
    assert engine.api_key == "sk-env"


def test_init_param_overrides_env(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-env")
    engine = qc.Qwen3TTSCloudEngine(api_key="sk-param")
    assert engine.api_key == "sk-param"


def test_init_custom_model_and_base_url(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    engine = qc.Qwen3TTSCloudEngine(
        api_key="k",
        model="qwen3-tts-instruct-flash",
        base_url="http://localhost/tts",
    )
    assert engine.model == "qwen3-tts-instruct-flash"
    assert engine.base_url == "http://localhost/tts"


def test_init_without_key_logs_warning_only(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    rec = _RecordingLogger()
    monkeypatch.setattr(qc, "logger", rec)

    engine = qc.Qwen3TTSCloudEngine()

    assert engine.api_key is None
    assert any("API Key not found" in m for m in rec.messages("warning"))
    assert rec.messages("info") == []


def test_init_with_key_logs_info(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    rec = _RecordingLogger()
    monkeypatch.setattr(qc, "logger", rec)

    engine = qc.Qwen3TTSCloudEngine(api_key="sk-x", model="qwen3-tts-flash")

    assert any(engine.model in m for m in rec.messages("info"))
    assert rec.messages("warning") == []


# ============================================================
# initialize / _get_session / _close_session / shutdown
# ============================================================

def test_get_session_builds_headers_and_reuses(monkeypatch):
    engine, main_sessions, _, ns = _make_engine(monkeypatch, initialized=False)
    engine.session = None

    s1 = asyncio.run(engine._get_session())
    assert s1 is main_sessions[0]
    assert s1.init_kwargs["headers"]["Authorization"] == "Bearer sk-test"
    assert s1.init_kwargs["headers"]["Content-Type"] == "application/json"
    assert s1.init_kwargs["timeout"].total == 300
    assert ns.timeout_calls == [{"total": 300}]

    # 未关闭 -> 复用同一会话，不再创建
    s2 = asyncio.run(engine._get_session())
    assert s2 is s1
    assert len(main_sessions) == 1

    # 已关闭 -> 重建新会话
    s1.closed = True
    s3 = asyncio.run(engine._get_session())
    assert s3 is not s1
    assert len(main_sessions) == 2


def test_initialize_creates_session_and_is_idempotent(monkeypatch):
    engine, main_sessions, _, _ = _make_engine(monkeypatch, initialized=False)
    engine.session = None

    asyncio.run(engine.initialize())
    assert engine.initialized is True
    assert len(main_sessions) == 1

    asyncio.run(engine.initialize())
    assert len(main_sessions) == 1  # 已初始化 -> 不重建


def test_close_session_branches(monkeypatch):
    engine, _, _, _ = _make_engine(monkeypatch, initialized=False)

    # session 为 None -> 空操作
    engine.session = None
    asyncio.run(engine._close_session())
    assert engine.session is None

    # 打开状态 -> 关闭并置空
    opened = _FakeSession()
    engine.session = opened
    asyncio.run(engine._close_session())
    assert opened.closed is True
    assert opened.close_calls == 1
    assert engine.session is None

    # 已关闭 -> 不重复关闭、也不置空
    already = _FakeSession()
    already.closed = True
    engine.session = already
    asyncio.run(engine._close_session())
    assert already.close_calls == 0
    assert engine.session is already


def test_shutdown_closes_session_and_resets_flag(monkeypatch):
    engine, _, _, _ = _make_engine(monkeypatch, initialized=True)
    sess = engine.session

    asyncio.run(engine.shutdown())

    assert sess.closed is True
    assert engine.session is None
    assert engine.initialized is False


# ============================================================
# get_status
# ============================================================

def test_get_status_not_initialized(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    engine, _, _, _ = _make_engine(monkeypatch, initialized=False, api_key=None)
    engine.session = None

    status = engine.get_status()

    assert status["status"] == "not_initialized"
    assert status["init_state"] == "not_initialized"
    assert status["model"] == "qwen3-tts-flash"
    assert status["api_key_configured"] is False
    assert status["session_active"] is False
    assert status["default_voice"] == "Cherry"
    assert status["supports_voice_cloning"] is True


def test_get_status_initialized_with_active_session(monkeypatch):
    engine, _, _, _ = _make_engine(monkeypatch, initialized=True)

    status = engine.get_status()

    assert status["status"] == "initialized"
    assert status["init_state"] == "initialized"
    assert status["api_key_configured"] is True
    assert status["session_active"] is True


# ============================================================
# synthesize：正常路径与载荷
# ============================================================

def test_synthesize_base64_success_returns_float32(monkeypatch):
    wav = _wav_bytes()
    engine, _, _, _ = _make_engine(
        monkeypatch,
        response=_ok_audio_response(audio_field={"data": _b64(wav)}),
    )

    audio = asyncio.run(engine.synthesize("你好"))

    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert len(audio) == 2400

    call = engine.session.post_calls[0]
    assert call["url"] == engine.base_url
    payload = call["json"]
    assert payload["model"] == "qwen3-tts-flash"
    assert payload["input"]["text"] == "你好"
    assert payload["input"]["voice"] == "Cherry"
    assert payload["input"]["language_type"] == "Chinese"


def test_synthesize_auto_initializes_and_applies_overrides(monkeypatch):
    wav = _wav_bytes()
    engine, main_sessions, _, _ = _make_engine(
        monkeypatch,
        initialized=False,
        response=_ok_audio_response(audio_field={"data": _b64(wav)}),
    )
    engine.session = None

    audio = asyncio.run(
        engine.synthesize("hi", voice="Bob", language="English", speed=1.5, volume=0.8)
    )

    assert engine.initialized is True
    assert len(audio) == 2400
    payload = main_sessions[0].post_calls[0]["json"]
    assert payload["input"]["voice"] == "Bob"
    assert payload["input"]["language_type"] == "English"


def test_synthesize_voice_cloning_with_ref_audio_and_text(monkeypatch, tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(_wav_bytes())
    engine, _, _, _ = _make_engine(
        monkeypatch,
        response=_ok_audio_response(audio_field={"data": _b64(_wav_bytes())}),
    )

    asyncio.run(engine.synthesize("克隆", ref_audio_path=str(ref), ref_text="参考文本"))

    payload = engine.session.post_calls[0]["json"]
    assert payload["input"]["ref_audio"].startswith("data:audio/wav;base64,")
    assert payload["input"]["ref_text"] == "参考文本"


def test_synthesize_voice_cloning_without_ref_text(monkeypatch, tmp_path):
    ref = tmp_path / "ref.mp3"
    ref.write_bytes(b"\x00\x01\x02")
    engine, _, _, _ = _make_engine(
        monkeypatch,
        response=_ok_audio_response(audio_field={"data": _b64(_wav_bytes())}),
    )

    asyncio.run(engine.synthesize("克隆", ref_audio_path=str(ref)))

    payload = engine.session.post_calls[0]["json"]
    assert payload["input"]["ref_audio"].startswith("data:audio/mpeg;base64,")
    assert "ref_text" not in payload["input"]


def test_synthesize_missing_ref_audio_is_ignored(monkeypatch, tmp_path):
    engine, _, _, _ = _make_engine(
        monkeypatch,
        response=_ok_audio_response(audio_field={"data": _b64(_wav_bytes())}),
    )

    asyncio.run(engine.synthesize("x", ref_audio_path=str(tmp_path / "nope.wav")))

    assert "ref_audio" not in engine.session.post_calls[0]["json"]["input"]


def test_synthesize_instructions_for_instruct_model_with_optimize(monkeypatch):
    engine, _, _, _ = _make_engine(
        monkeypatch,
        model="qwen3-tts-instruct-flash",
        response=_ok_audio_response(audio_field={"data": _b64(_wav_bytes())}),
    )

    asyncio.run(
        engine.synthesize("x", instructions="用开心的语气", optimize_instructions=True)
    )

    payload = engine.session.post_calls[0]["json"]
    assert payload["input"]["instructions"] == "用开心的语气"
    assert payload["input"]["optimize_instructions"] is True


def test_synthesize_instructions_for_instruct_model_without_optimize(monkeypatch):
    engine, _, _, _ = _make_engine(
        monkeypatch,
        model="qwen3-tts-instruct-flash",
        response=_ok_audio_response(audio_field={"data": _b64(_wav_bytes())}),
    )

    asyncio.run(engine.synthesize("x", instructions="用开心的语气"))

    payload = engine.session.post_calls[0]["json"]
    assert payload["input"]["instructions"] == "用开心的语气"
    assert "optimize_instructions" not in payload["input"]


def test_synthesize_instructions_ignored_for_non_instruct_model(monkeypatch):
    engine, _, _, _ = _make_engine(
        monkeypatch,
        model="qwen3-tts-flash",
        response=_ok_audio_response(audio_field={"data": _b64(_wav_bytes())}),
    )

    asyncio.run(engine.synthesize("x", instructions="不该出现"))

    assert "instructions" not in engine.session.post_calls[0]["json"]["input"]


# ============================================================
# synthesize：错误分支
# ============================================================

def test_synthesize_raises_on_http_error(monkeypatch):
    engine, _, _, _ = _make_engine(
        monkeypatch,
        response=_FakeResponse(status=400, text="bad request"),
    )

    with pytest.raises(RuntimeError, match="Qwen3-TTS API Error: 400"):
        asyncio.run(engine.synthesize("x"))


def test_synthesize_raises_on_task_failed(monkeypatch):
    engine, _, _, _ = _make_engine(
        monkeypatch,
        response=_FakeResponse(
            json_data={"output": {"task_status": "FAILED", "error_msg": "boom"}}
        ),
    )

    with pytest.raises(RuntimeError, match="task failed: boom"):
        asyncio.run(engine.synthesize("x"))


def test_synthesize_raises_when_no_audio_found(monkeypatch):
    engine, _, _, _ = _make_engine(
        monkeypatch,
        response=_FakeResponse(json_data={"output": {}}),
    )

    with pytest.raises(RuntimeError, match="No audio URL or data found"):
        asyncio.run(engine.synthesize("x"))


def test_synthesize_reraises_unexpected_exception(monkeypatch):
    rec = _RecordingLogger()
    monkeypatch.setattr(qc, "logger", rec)
    engine, _, _, _ = _make_engine(
        monkeypatch,
        post_exc=ConnectionError("network down"),
    )

    with pytest.raises(ConnectionError, match="network down"):
        asyncio.run(engine.synthesize("x"))

    assert any("synthesis failed" in m for m in rec.messages("error"))


# ============================================================
# synthesize：音频 URL 下载
# ============================================================

def test_synthesize_downloads_audio_from_url(monkeypatch):
    wav = _wav_bytes()
    engine, _, downloads, _ = _make_engine(
        monkeypatch,
        response=_FakeResponse(
            json_data={"output": {"audio": {"url": "http://cdn.example/a.wav"}}}
        ),
        download_response=_FakeResponse(status=200, body=wav),
    )

    audio = asyncio.run(engine.synthesize("x"))

    assert len(audio) == 2400
    assert downloads[0].get_calls == ["http://cdn.example/a.wav"]


def test_synthesize_raises_when_download_fails(monkeypatch):
    engine, _, _, _ = _make_engine(
        monkeypatch,
        response=_FakeResponse(
            json_data={"output": {"audio": {"url": "http://cdn.example/a.wav"}}}
        ),
        download_response=_FakeResponse(status=404),
    )

    with pytest.raises(RuntimeError, match="Failed to download audio: 404"):
        asyncio.run(engine.synthesize("x"))


# ============================================================
# synthesize：旧格式与多种 Base64 结构
# ============================================================

def test_synthesize_legacy_audio_url_field(monkeypatch):
    wav = _wav_bytes()
    engine, _, downloads, _ = _make_engine(
        monkeypatch,
        response=_FakeResponse(
            json_data={"output": {"audio_url": "http://cdn.example/legacy.wav", "audio": ""}}
        ),
        download_response=_FakeResponse(status=200, body=wav),
    )

    audio = asyncio.run(engine.synthesize("x"))

    assert len(audio) == 2400
    assert downloads[0].get_calls == ["http://cdn.example/legacy.wav"]


def test_synthesize_legacy_base64_string(monkeypatch):
    engine, _, _, _ = _make_engine(
        monkeypatch,
        response=_FakeResponse(json_data={"output": {"audio": _b64(_wav_bytes())}}),
    )

    audio = asyncio.run(engine.synthesize("x"))

    assert len(audio) == 2400


def test_synthesize_nested_dict_base64(monkeypatch):
    engine, _, _, _ = _make_engine(
        monkeypatch,
        response=_ok_audio_response(
            audio_field={"data": {"data": _b64(_wav_bytes())}}
        ),
    )

    audio = asyncio.run(engine.synthesize("x"))

    assert len(audio) == 2400


def test_synthesize_raw_bytes_data(monkeypatch):
    engine, _, _, _ = _make_engine(
        monkeypatch,
        response=_ok_audio_response(audio_field={"data": _wav_bytes()}),
    )

    audio = asyncio.run(engine.synthesize("x"))

    assert len(audio) == 2400


# ============================================================
# _encode_audio_to_base64
# ============================================================

@pytest.mark.parametrize(
    ("ext", "mime"),
    [
        (".wav", "audio/wav"),
        (".mp3", "audio/mpeg"),
        (".flac", "audio/flac"),
        (".aac", "audio/aac"),
        (".ogg", "audio/wav"),  # 未映射扩展名 -> 兜底 audio/wav
    ],
)
def test_encode_audio_mime_types(monkeypatch, tmp_path, ext, mime):
    path = tmp_path / f"ref{ext}"
    payload = b"\x00\x01\x02\x03"
    path.write_bytes(payload)
    engine, _, _, _ = _make_engine(monkeypatch, initialized=True)

    data = asyncio.run(engine._encode_audio_to_base64(str(path)))

    assert data == f"data:{mime};base64,{_b64(payload)}"


def test_encode_audio_missing_file_raises(monkeypatch, tmp_path):
    rec = _RecordingLogger()
    monkeypatch.setattr(qc, "logger", rec)
    engine, _, _, _ = _make_engine(monkeypatch, initialized=True)

    with pytest.raises(FileNotFoundError):
        asyncio.run(engine._encode_audio_to_base64(str(tmp_path / "missing.wav")))

    assert any("Failed to encode audio" in m for m in rec.messages("error"))


# ============================================================
# synthesize_bytes
# ============================================================

def test_synthesize_bytes_returns_wav(monkeypatch):
    engine, _, _, _ = _make_engine(monkeypatch, initialized=True)

    async def _fake_synthesize(text, ref_audio_path=None, ref_text=None, **kwargs):
        return np.linspace(-0.5, 0.5, 2400, dtype=np.float32)

    monkeypatch.setattr(engine, "synthesize", _fake_synthesize)

    out = asyncio.run(engine.synthesize_bytes("hi"))

    assert isinstance(out, bytes)
    assert out[:4] == b"RIFF"
    data, sample_rate = sf.read(io.BytesIO(out), dtype="float32")
    assert sample_rate == 24000
    assert len(data) == 2400


def test_synthesize_bytes_returns_none_on_failure(monkeypatch):
    rec = _RecordingLogger()
    monkeypatch.setattr(qc, "logger", rec)
    engine, _, _, _ = _make_engine(
        monkeypatch,
        initialized=True,
        post_exc=ConnectionError("net down"),
    )

    out = asyncio.run(engine.synthesize_bytes("hi"))

    assert out is None
    assert any("synthesize_bytes failed" in m for m in rec.messages("error"))
