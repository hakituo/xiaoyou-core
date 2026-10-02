"""core/voice/engines/qwen3_tts_engine.py —— 单次合成与 numpy 封装单元测试。

覆盖 ``_do_synthesize``（参考音频解析 / 语言映射 / 资源锁 / 生成标志复位）与
``synthesize``（WAV 字节 → float32 数组的封装）。

**绝不加载真实模型**：模型对象由替身提供（``generate_voice_clone`` 返回可控的 numpy
小数组），``ThreadPoolExecutor`` 换成就地执行的替身；不下载权重、不使用 GPU、不发起
网络请求，文件 IO 全部落在 ``tmp_path``。
"""
from __future__ import annotations

import concurrent.futures
import io
import os

import numpy as np
import pytest

import core.voice.engines.qwen3_tts_engine as mod
from core.voice.engines.qwen3_tts_engine import Qwen3TTSEngine

# `soundfile` 属 voice 可选 extra（pyproject.toml），CI 只跑 `uv sync --extra dev` 不装它。
# 缺依赖时整体跳过而不是失败（与 test_tts_manager_core.py 同口径）。
sf = pytest.importorskip("soundfile", exc_type=ImportError,
                         reason="soundfile 属 voice 可选 extra，CI 未安装")


class _RecordingLogger:
    """模块级 logger 替身（真实 logger 的 propagate=False，不便用 caplog）。"""

    def __init__(self):
        self.records = []

    def messages(self, level=None):
        return [m for lv, m in self.records if level is None or lv == level]

    def _bind(level):
        def _log(self, msg, *args, **kwargs):
            self.records.append((level, msg))
        return _log

    debug, info, warning, error = (_bind("debug"), _bind("info"),
                                   _bind("warning"), _bind("error"))


class _SettingsStub:
    def __init__(self, reference_audio=None, tts_vram_threshold_mb=0):
        import types
        self.voice = types.SimpleNamespace(
            reference_audio=reference_audio,
            tts_vram_threshold_mb=tts_vram_threshold_mb,
        )


class _InlineExecutor:
    """就地执行的 executor 替身：submit 立即同步跑完，避免真实线程与竞态。"""

    def __init__(self):
        self.shutdown_calls = []

    def submit(self, fn, *args, **kwargs):
        future = concurrent.futures.Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # 需原样透传给调用方
            future.set_exception(exc)
        return future

    def shutdown(self, wait=True):
        self.shutdown_calls.append(wait)


class _FakeModel:
    """TTS 模型替身：记录 generate_voice_clone 入参，返回可控音频。"""

    def __init__(self, *, faster=False, wavs=None, sr=24000, exc=None):
        self.calls = []
        self._wavs = wavs if wavs is not None else [np.zeros(240, dtype=np.float32)]
        self._sr, self._exc = sr, exc
        if faster:
            self.predictor_graph = object()

    def generate_voice_clone(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._wavs, self._sr


class _FakeResourceLock:
    """全局资源锁替身：记录 acquire 入参并进入/退出异步上下文。"""

    def __init__(self, record):
        self._record = record

    def acquire(self, requestor, *, reject_if_full=False):
        self._record.append((requestor, reject_if_full))
        return self

    async def __aenter__(self):
        self._record.append("enter")
        return self

    async def __aexit__(self, *exc_info):
        self._record.append("exit")
        return False


def _wav_bytes(samples=240, sample_rate=24000, value=0.5):
    buf = io.BytesIO()
    sf.write(buf, np.full(samples, value, dtype=np.float32), sample_rate,
             format="WAV")
    return buf.getvalue()


@pytest.fixture
def engine():
    eng = Qwen3TTSEngine()
    eng._executor = _InlineExecutor()
    yield eng


class TestDoSynthesize:
    @pytest.fixture
    def env(self, engine, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "get_project_root", lambda: tmp_path)
        monkeypatch.setattr(mod, "get_resource_lock", None)
        return engine

    def _settings(self, monkeypatch, reference_audio=None):
        monkeypatch.setattr(mod, "get_settings",
                            lambda: _SettingsStub(reference_audio=reference_audio))

    async def test_default_reference_audio_and_xvec_fallback(self, env, monkeypatch,
                                                             tmp_path):
        rec = _RecordingLogger()
        monkeypatch.setattr(mod, "logger", rec)
        self._settings(monkeypatch, reference_audio=None)
        model = _FakeModel()
        env._model = model

        out = await env._do_synthesize("hello")

        assert out[:4] == b"RIFF"
        call = model.calls[0]
        assert call["ref_audio"] == str(
            tmp_path / "ref_audio" / "female" / "ref_calm.wav")
        assert call["language"] == "chinese"
        assert call["ref_text"] is None
        assert call["x_vector_only_mode"] is True
        assert (call["max_new_tokens"], call["repetition_penalty"]) == (4096, 1.1)
        assert (call["temperature"], call["top_p"]) == (0.7, 0.8)
        assert env._is_generating is False
        assert any("Switching to x_vector_only" in m
                   for m in rec.messages("warning"))

    @pytest.mark.parametrize("reference_audio", ["rel/ref.wav", "/abs/ref.wav"])
    async def test_reference_audio_path_normalisation(self, env, monkeypatch, tmp_path,
                                                      reference_audio):
        self._settings(monkeypatch, reference_audio=reference_audio)
        model = _FakeModel()
        env._model = model
        await env._do_synthesize("hi")
        want = reference_audio if os.path.isabs(reference_audio) else os.path.join(
            str(tmp_path), reference_audio)
        assert model.calls[0]["ref_audio"] == want

    @pytest.mark.parametrize("key", ["ref_audio_path", "reference_audio"])
    async def test_kwargs_reference_audio_overrides_default(self, env, monkeypatch,
                                                            tmp_path, key):
        self._settings(monkeypatch, reference_audio=str(tmp_path / "d.wav"))
        model = _FakeModel()
        env._model = model
        override = str(tmp_path / "o.wav")
        await env._do_synthesize("hi", **{key: override})
        assert model.calls[0]["ref_audio"] == override

    async def test_explicit_ref_text_passed_through(self, env, monkeypatch, tmp_path):
        self._settings(monkeypatch, reference_audio=str(tmp_path / "r.wav"))
        model = _FakeModel()
        env._model = model
        await env._do_synthesize("hi", ref_text="参考文本")
        assert model.calls[0]["ref_text"] == "参考文本"
        assert model.calls[0]["x_vector_only_mode"] is False

    async def test_ref_text_auto_loaded_from_txt(self, env, monkeypatch, tmp_path):
        rec = _RecordingLogger()
        monkeypatch.setattr(mod, "logger", rec)
        ref = tmp_path / "voice.wav"
        ref.write_bytes(_wav_bytes())
        ref.with_suffix(".txt").write_text("  自动加载的参考文本  ", encoding="utf-8")
        self._settings(monkeypatch, reference_audio=str(ref))
        model = _FakeModel()
        env._model = model

        await env._do_synthesize("hi")

        assert model.calls[0]["ref_text"] == "自动加载的参考文本"
        assert any("Auto-loaded ref_text" in m for m in rec.messages("info"))

    async def test_ref_text_read_failure_falls_back_to_xvec(self, env, monkeypatch,
                                                            tmp_path):
        ref = tmp_path / "voice.wav"
        ref.write_bytes(_wav_bytes())
        (tmp_path / "voice.txt").mkdir()  # 目录：open() 必抛异常，被 except 吞掉
        self._settings(monkeypatch, reference_audio=str(ref))
        model = _FakeModel()
        env._model = model

        await env._do_synthesize("hi")

        assert model.calls[0]["ref_text"] is None
        assert model.calls[0]["x_vector_only_mode"] is True

    async def test_x_vector_only_mode_skips_txt_and_warning(self, env, monkeypatch,
                                                            tmp_path):
        rec = _RecordingLogger()
        monkeypatch.setattr(mod, "logger", rec)
        ref = tmp_path / "voice.wav"
        ref.write_bytes(_wav_bytes())
        ref.with_suffix(".txt").write_text("不该被读取", encoding="utf-8")
        self._settings(monkeypatch, reference_audio=str(ref))
        model = _FakeModel()
        env._model = model

        await env._do_synthesize("hi", x_vector_only_mode=True)

        assert model.calls[0]["ref_text"] is None
        assert model.calls[0]["x_vector_only_mode"] is True
        assert (rec.messages("warning"), rec.messages("info")) == ([], [])

    @pytest.mark.parametrize("kwargs,expected", [
        ({"language": "zh"}, "chinese"),
        ({"language": "EN"}, "english"),
        ({"language": "mixed"}, "auto"),
        ({"language": "auto"}, "auto"),
        ({"language": "klingon"}, "klingon"),
        ({"text_lang": "ja"}, "japanese"),
    ])
    async def test_language_mapping(self, env, monkeypatch, tmp_path, kwargs, expected):
        self._settings(monkeypatch, reference_audio=str(tmp_path / "r.wav"))
        model = _FakeModel()
        env._model = model
        await env._do_synthesize("hi", **kwargs)
        assert model.calls[0]["language"] == expected

    async def test_faster_model_uses_xvec_only_param(self, env, monkeypatch, tmp_path):
        self._settings(monkeypatch, reference_audio=str(tmp_path / "r.wav"))
        model = _FakeModel(faster=True)
        env._model = model
        await env._do_synthesize("hi")
        assert model.calls[0]["xvec_only"] is True
        assert "x_vector_only_mode" not in model.calls[0]

    async def test_resource_lock_is_acquired(self, env, monkeypatch, tmp_path):
        self._settings(monkeypatch, reference_audio=str(tmp_path / "r.wav"))
        record = []
        monkeypatch.setattr(mod, "get_resource_lock",
                            lambda: _FakeResourceLock(record))
        env._model = _FakeModel()
        out = await env._do_synthesize("hi")
        assert out[:4] == b"RIFF"
        assert record == [("TTS", True), "enter", "exit"]

    async def test_inference_error_resets_generating_flag(self, env, monkeypatch,
                                                          tmp_path):
        self._settings(monkeypatch, reference_audio=str(tmp_path / "r.wav"))
        env._model = _FakeModel(exc=RuntimeError("infer fail"))
        with pytest.raises(RuntimeError, match="infer fail"):
            await env._do_synthesize("hi")
        assert env._is_generating is False


class TestSynthesize:
    async def test_empty_results_when_soundfile_missing_or_bytes_falsy(
            self, engine, monkeypatch):
        monkeypatch.setattr(mod, "sf", None)
        assert (await engine.synthesize("x")).size == 0

        async def _none(text, **kwargs):
            return None

        monkeypatch.setattr(mod, "sf", sf)
        monkeypatch.setattr(engine, "synthesize_bytes", _none)
        out = await engine.synthesize("x")
        assert out.dtype == np.float32
        assert out.size == 0

    async def test_decodes_wav_bytes_to_float32(self, engine, monkeypatch):
        payload = _wav_bytes(samples=240)

        async def _bytes(text, **kwargs):
            return payload

        monkeypatch.setattr(engine, "synthesize_bytes", _bytes)
        out = await engine.synthesize("x")
        assert out.dtype == np.float32
        assert out.shape == (240,)

    async def test_end_to_end_with_fake_model(self, engine, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "get_project_root", lambda: tmp_path)
        monkeypatch.setattr(mod, "get_settings",
                            lambda: _SettingsStub(reference_audio=None))
        monkeypatch.setattr(mod, "get_resource_lock", None)
        engine.model_path = str(tmp_path)
        engine._model = _FakeModel(wavs=[np.full(240, 0.25, dtype=np.float32)])
        engine.current_device = "cuda"
        engine._batch_max_size = 1

        out = await engine.synthesize("hello")

        assert out.dtype == np.float32
        assert out.shape == (240,)
        assert float(out[0]) == pytest.approx(0.25, abs=1e-4)
