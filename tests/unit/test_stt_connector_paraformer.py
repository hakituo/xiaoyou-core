"""multimodal/stt_connector.py 单元测试（六之二）：Paraformer 转录实现。

对应源码：`_transcribe_audio_with_paraformer`（wav 直通 / 非 wav 转码 / 结果兜底）。

策略：音频用假 AudioSegment；modelscope pipeline 用 lambda 替身，不加载真实模型。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from multimodal import stt_connector as sc
from multimodal.stt_connector import STTConnector


class _FakeAudio:
    """最小 AudioSegment 替身。"""

    def __init__(self, samples=(1, 2, 3)):
        self._samples = list(samples)
        self.frame_rates = []

    def set_frame_rate(self, rate):  # noqa: ANN001
        self.frame_rates.append(rate)
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


def _bare(temp_dir="unused"):
    obj = STTConnector.__new__(STTConnector)
    obj.model_type = "paraformer"
    obj.model_path = "models/x"
    obj.device = "cpu"
    obj.processor = None
    obj.model = None
    obj.modelscope_model = None
    obj.temp_audio_dir = temp_dir
    return obj


def _patch_audio(monkeypatch, audio=None):
    audio = audio or _FakeAudio()
    monkeypatch.setattr(sc, "AudioSegment", SimpleNamespace(from_file=lambda *a, **kw: audio))
    return audio


def test_paraformer_wav_skips_conversion(monkeypatch):
    """已是 wav 就不再转码，直接把路径交给 pipeline。"""
    connector = _bare()
    seen = []
    connector.modelscope_model = lambda path: seen.append(path) or {"text": "识别结果"}
    _patch_audio(monkeypatch)

    assert connector._transcribe_audio_with_paraformer("a.wav") == "识别结果"
    assert seen == ["a.wav"]


def test_paraformer_non_wav_is_converted(monkeypatch, tmp_path):
    """非 wav 先转成 16k 单声道 wav 再识别。"""
    connector = _bare(temp_dir=str(tmp_path))
    seen = []
    connector.modelscope_model = lambda path: seen.append(path) or {"text": "OK"}
    audio = _patch_audio(monkeypatch)

    connector._transcribe_audio_with_paraformer("a.mp3")

    assert seen and seen[0].endswith("temp_paraformer.wav"), "应先转码成 wav"
    assert audio.frame_rates == [16000], "转码时必须重采样到 16kHz"
    assert Path(seen[0]).exists()


def test_paraformer_uppercase_wav_suffix_is_treated_as_wav(monkeypatch):
    """后缀判断不区分大小写（.WAV 也走直通）。"""
    connector = _bare()
    seen = []
    connector.modelscope_model = lambda path: seen.append(path) or {"text": "OK"}
    _patch_audio(monkeypatch)

    connector._transcribe_audio_with_paraformer("A.WAV")

    assert seen == ["A.WAV"]


def test_paraformer_non_dict_result_is_stringified(monkeypatch):
    """modelscope 版本不同可能返回非 dict，需要 str() 兜底。"""
    connector = _bare()
    connector.modelscope_model = lambda path: ["原样", "列表"]
    _patch_audio(monkeypatch)

    assert connector._transcribe_audio_with_paraformer("a.wav") == "['原样', '列表']"


def test_paraformer_missing_text_key_returns_empty(monkeypatch):
    """dict 里没有 text 键时返回空串，而不是 KeyError。"""
    connector = _bare()
    connector.modelscope_model = lambda path: {"other": 1}
    _patch_audio(monkeypatch)

    assert connector._transcribe_audio_with_paraformer("a.wav") == ""


def test_paraformer_failure_reraises():
    connector = _bare()

    def _boom(path):
        raise RuntimeError("识别失败")

    connector.modelscope_model = _boom

    with pytest.raises(RuntimeError, match="识别失败"):
        connector._transcribe_audio_with_paraformer("a.wav")
