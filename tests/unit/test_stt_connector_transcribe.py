"""multimodal/stt_connector.py 单元测试（六）：三个底层转录实现。

对应源码：`_transcribe_audio_with_faster_whisper` / `_transcribe_audio_with_whisper`
/ `_transcribe_audio_with_paraformer`。

策略：音频一律用假 AudioSegment，不读真实音频、不加载真实模型、不联网。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from multimodal import stt_connector as sc
from multimodal.stt_connector import STTConnector


# --------------------------------------------------------------------------
# 替身
# --------------------------------------------------------------------------


class _FakeAudio:
    """最小 AudioSegment 替身：支持链式设置、取样本、切片、导出。"""

    def __init__(self, samples=(1, 2, 3)):
        self._samples = list(samples)
        self.exported = []

    def set_frame_rate(self, rate):  # noqa: ANN001
        return self

    def set_channels(self, channels):  # noqa: ANN001
        return self

    def set_sample_width(self, width):  # noqa: ANN001
        return self

    def get_array_of_samples(self):
        return self._samples

    def __getitem__(self, item):  # noqa: ANN001
        return self

    def export(self, path, format=None):  # noqa: ANN001, A002
        Path(path).write_bytes(b"RIFF")
        self.exported.append(path)


class _FakeProcessor:
    """WhisperProcessor 替身：可调用 + 可 batch_decode。

    注意不能用 `SimpleNamespace(__call__=...)` —— 那不会让对象变成可调用。
    """

    def __init__(self, text="转录文本", features="FEATURES"):
        self._text = text
        self._features = features
        self.sampling_rates = []

    def __call__(self, samples, sampling_rate=None, return_tensors=None):  # noqa: ANN001
        self.sampling_rates.append(sampling_rate)
        return SimpleNamespace(input_features=SimpleNamespace(to=lambda device: self._features))

    def batch_decode(self, ids, skip_special_tokens=False):  # noqa: ANN001
        return [self._text]


class _Segment:
    def __init__(self, text):
        self.text = text


class _FakeFasterWhisperModel:
    """faster_whisper.WhisperModel 替身：记录入参并返回可控结果。"""

    def __init__(self, texts=("你好", "世界"), language="zh"):
        self.calls = []
        self._texts = texts
        self._language = language

    def transcribe(self, source, **kwargs):
        self.calls.append((source, kwargs))
        return [_Segment(t) for t in self._texts], SimpleNamespace(language=self._language)


def _fake_audiosegment(audio=None):
    audio = audio or _FakeAudio()
    return SimpleNamespace(from_file=lambda *a, **kw: audio)


def _bare(model_type="faster-whisper", temp_dir="unused"):
    obj = STTConnector.__new__(STTConnector)
    obj.model_type = model_type
    obj.model_path = "models/x"
    obj.device = "cpu"
    obj.processor = None
    obj.model = None
    obj.modelscope_model = None
    obj.temp_audio_dir = temp_dir
    return obj


# --------------------------------------------------------------------------
# 1. _transcribe_audio_with_faster_whisper
# --------------------------------------------------------------------------


def test_faster_whisper_falls_back_to_file_path(monkeypatch):
    """C++ VAD 不可用时直接传文件路径。"""
    monkeypatch.setattr(sc, "_HAS_CPP_AUDIO", False)
    connector = _bare()
    connector.model = _FakeFasterWhisperModel()

    result = connector._transcribe_audio_with_faster_whisper("a.wav", "zh")

    assert result == {"text": "你好世界", "confidence": 0.9, "detected_language": "zh"}
    assert connector.model.calls[0][0] == "a.wav", "应回落到文件路径"
    assert connector.model.calls[0][1]["language"] == "zh"


def test_faster_whisper_auto_language_passes_none(monkeypatch):
    """language='auto' 时要传 None 让模型自动检测。"""
    monkeypatch.setattr(sc, "_HAS_CPP_AUDIO", False)
    connector = _bare()
    connector.model = _FakeFasterWhisperModel()

    connector._transcribe_audio_with_faster_whisper("a.wav", "auto")

    assert connector.model.calls[0][1]["language"] is None


def test_faster_whisper_uses_cpp_vad_when_available(monkeypatch):
    """C++ VAD 可用时，传入的是去静音后的 numpy 数组而不是文件路径。"""
    monkeypatch.setattr(sc, "_HAS_CPP_AUDIO", True)
    monkeypatch.setattr(
        sc,
        "audio_processor_py",
        SimpleNamespace(AudioVAD=lambda **kw: SimpleNamespace(remove_silence=lambda s, frame_ms: [1, 2])),
    )
    monkeypatch.setattr(sc, "AudioSegment", _fake_audiosegment())
    connector = _bare()
    connector.model = _FakeFasterWhisperModel()

    connector._transcribe_audio_with_faster_whisper("a.wav", "zh")

    source = connector.model.calls[0][0]
    assert source != "a.wav", "应传数组而非路径"
    assert len(source) == 2


def test_faster_whisper_vad_empty_falls_back(monkeypatch):
    """VAD 去静音后为空时回落到文件路径（避免把空数组喂给模型）。"""
    monkeypatch.setattr(sc, "_HAS_CPP_AUDIO", True)
    monkeypatch.setattr(
        sc,
        "audio_processor_py",
        SimpleNamespace(AudioVAD=lambda **kw: SimpleNamespace(remove_silence=lambda s, frame_ms: [])),
    )
    monkeypatch.setattr(sc, "AudioSegment", _fake_audiosegment())
    connector = _bare()
    connector.model = _FakeFasterWhisperModel()

    connector._transcribe_audio_with_faster_whisper("a.wav", "zh")

    assert connector.model.calls[0][0] == "a.wav"


def test_faster_whisper_vad_exception_is_swallowed(monkeypatch):
    """VAD 预处理抛异常时静默回落，不影响转录。"""
    monkeypatch.setattr(sc, "_HAS_CPP_AUDIO", True)

    def _boom(**kw):
        raise RuntimeError("VAD 崩了")

    monkeypatch.setattr(sc, "audio_processor_py", SimpleNamespace(AudioVAD=_boom))
    monkeypatch.setattr(sc, "AudioSegment", _fake_audiosegment())
    connector = _bare()
    connector.model = _FakeFasterWhisperModel()

    connector._transcribe_audio_with_faster_whisper("a.wav", "zh")

    assert connector.model.calls[0][0] == "a.wav"


def test_faster_whisper_transcribe_failure_reraises():
    connector = _bare()

    class _Boom:
        def transcribe(self, *a, **kw):
            raise RuntimeError("推理失败")

    connector.model = _Boom()

    with pytest.raises(RuntimeError, match="推理失败"):
        connector._transcribe_audio_with_faster_whisper("a.wav", "zh")


# --------------------------------------------------------------------------
# 2. _transcribe_audio_with_whisper
# --------------------------------------------------------------------------


def test_whisper_transcribe_success(monkeypatch):
    connector = _bare("whisper")
    connector.processor = _FakeProcessor("转录文本")
    connector.model = SimpleNamespace(generate=lambda features, **kw: "IDS")
    monkeypatch.setattr(sc, "AudioSegment", _fake_audiosegment())

    result = connector._transcribe_audio_with_whisper("a.wav", "auto")

    assert result == {"text": "转录文本", "confidence": 0.9, "detected_language": "unknown"}


def test_whisper_transcribe_passes_language_when_specified(monkeypatch):
    """指定语言时要透传给 generate。"""
    connector = _bare("whisper")
    captured = {}

    def _generate(features, **kwargs):
        captured.update(kwargs)
        return "IDS"

    connector.processor = _FakeProcessor("文本")
    connector.model = SimpleNamespace(generate=_generate)
    monkeypatch.setattr(sc, "AudioSegment", _fake_audiosegment())

    result = connector._transcribe_audio_with_whisper("a.wav", "zh")

    assert captured == {"language": "zh"}
    assert result["detected_language"] == "zh"


def test_whisper_transcribe_resamples_to_16k_mono(monkeypatch):
    """输入音频必须被重采样到 16kHz 单声道。"""
    connector = _bare("whisper")
    audio = _FakeAudio()
    connector.processor = _FakeProcessor()
    connector.model = SimpleNamespace(generate=lambda features, **kw: "IDS")
    monkeypatch.setattr(sc, "AudioSegment", _fake_audiosegment(audio))

    connector._transcribe_audio_with_whisper("a.wav", "zh")

    assert connector.processor.sampling_rates == [16000]


def test_whisper_transcribe_failure_reraises(monkeypatch):
    connector = _bare("whisper")

    def _boom(*a, **kw):
        raise OSError("读文件失败")

    monkeypatch.setattr(sc, "AudioSegment", SimpleNamespace(from_file=_boom))

    with pytest.raises(OSError, match="读文件失败"):
        connector._transcribe_audio_with_whisper("a.wav", "zh")
