"""multimodal/stt_connector.py 单元测试（七）：对外转录入口。

对应源码：`transcribe_audio_file` / `transcribe_audio_data` / `batch_transcribe`。

策略：文件读写一律落在 tmp_path；模型调用用替身；异步用 asyncio.run(...)。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from multimodal import stt_connector as sc
from multimodal.stt_connector import STTConnector


class _FakeAudio:
    """最小 AudioSegment 替身。"""

    def __init__(self, samples=(1, 2, 3)):
        self._samples = list(samples)

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


class _FakeProcessor:
    def __init__(self, text="转录文本"):
        self._text = text

    def __call__(self, samples, sampling_rate=None, return_tensors=None):  # noqa: ANN001
        return SimpleNamespace(input_features=SimpleNamespace(to=lambda device: "FEATURES"))

    def batch_decode(self, ids, skip_special_tokens=False):  # noqa: ANN001
        return [self._text]


class _FakeFasterWhisperModel:
    def __init__(self, texts=("你好", "世界"), language="zh"):
        self._texts = texts
        self._language = language

    def transcribe(self, source, **kwargs):
        return [SimpleNamespace(text=t) for t in self._texts], SimpleNamespace(
            language=self._language
        )


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


async def _noop_async(self):  # noqa: ANN001
    return None


def _async_value(value):
    async def _coro():
        return value

    return _coro()


def _async_raise(exc):
    async def _coro():
        raise exc

    return _coro()


def _patch_loaded(monkeypatch):
    """跳过惰性加载，并把 AudioSegment 换成替身。"""
    monkeypatch.setattr(STTConnector, "_ensure_model_loaded", _noop_async)
    monkeypatch.setattr(sc, "AudioSegment", SimpleNamespace(from_file=lambda *a, **kw: _FakeAudio()))


# --------------------------------------------------------------------------
# 1. transcribe_audio_file
# --------------------------------------------------------------------------


def test_transcribe_audio_file_faster_whisper(monkeypatch, tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    connector = _bare(temp_dir=str(tmp_path))
    _patch_loaded(monkeypatch)
    connector.model = _FakeFasterWhisperModel()

    result = asyncio.run(connector.transcribe_audio_file(str(audio), language="zh"))

    assert result["success"] is True
    assert result["model"] == "Faster-Whisper"
    assert result["text"] == "你好世界"
    assert result["speakers"] == []


def test_transcribe_audio_file_whisper(monkeypatch, tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    connector = _bare("whisper", temp_dir=str(tmp_path))
    _patch_loaded(monkeypatch)
    connector.processor = _FakeProcessor("W")
    connector.model = SimpleNamespace(generate=lambda features, **kw: "IDS")

    result = asyncio.run(connector.transcribe_audio_file(str(audio)))

    assert result["model"] == "Whisper"
    assert result["text"] == "W"


def test_transcribe_audio_file_paraformer(monkeypatch, tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    connector = _bare("paraformer", temp_dir=str(tmp_path))
    _patch_loaded(monkeypatch)
    connector.modelscope_model = lambda path: {"text": "P"}

    result = asyncio.run(connector.transcribe_audio_file(str(audio)))

    assert result["model"] == "Paraformer"
    assert result["language"] == "zh-CN"


def test_transcribe_audio_file_missing_file_raises(monkeypatch, tmp_path):
    connector = _bare(temp_dir=str(tmp_path))
    _patch_loaded(monkeypatch)

    with pytest.raises(FileNotFoundError):
        asyncio.run(connector.transcribe_audio_file(str(tmp_path / "nope.wav")))


def test_transcribe_audio_file_truncates_when_max_duration(monkeypatch, tmp_path):
    """给了 max_duration 就截断并另存临时文件，且返回的 audio_path 指向它。"""
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    connector = _bare(temp_dir=str(tmp_path))
    _patch_loaded(monkeypatch)
    connector.model = _FakeFasterWhisperModel()

    result = asyncio.run(connector.transcribe_audio_file(str(audio), max_duration=5))

    assert result["audio_path"].endswith("temp_audio.wav")
    assert Path(result["audio_path"]).exists()


def test_transcribe_audio_file_unsupported_type_raises(monkeypatch, tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    connector = _bare("no-such-type", temp_dir=str(tmp_path))
    _patch_loaded(monkeypatch)

    with pytest.raises(Exception, match="音频转录失败"):
        asyncio.run(connector.transcribe_audio_file(str(audio)))


def test_transcribe_audio_file_wraps_inner_error(monkeypatch, tmp_path):
    """内层异常被包成统一文案后抛出。"""
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    connector = _bare(temp_dir=str(tmp_path))
    _patch_loaded(monkeypatch)

    class _Boom:
        def transcribe(self, *a, **kw):
            raise RuntimeError("底层炸了")

    connector.model = _Boom()

    with pytest.raises(Exception, match="音频转录失败"):
        asyncio.run(connector.transcribe_audio_file(str(audio)))


# --------------------------------------------------------------------------
# 2. transcribe_audio_data
# --------------------------------------------------------------------------


def test_transcribe_audio_data_writes_then_removes_temp(monkeypatch, tmp_path):
    """临时文件写盘 → 转录 → finally 清理。"""
    connector = _bare(temp_dir=str(tmp_path))
    _patch_loaded(monkeypatch)
    seen_paths = []
    monkeypatch.setattr(
        STTConnector,
        "transcribe_audio_file",
        lambda self, path, **kw: seen_paths.append(path) or _async_value({"text": "ok"}),
    )

    result = asyncio.run(connector.transcribe_audio_data(b"\x00\x01", format="wav"))

    assert result == {"text": "ok"}
    assert seen_paths, "应把数据写到临时文件后走文件转录"
    assert not Path(seen_paths[0]).exists(), "finally 应删除临时文件"


def test_transcribe_audio_data_cleanup_failure_is_warned(monkeypatch, tmp_path):
    """删除临时文件失败只记 warning，不掩盖转录结果。"""
    connector = _bare(temp_dir=str(tmp_path))
    _patch_loaded(monkeypatch)
    monkeypatch.setattr(
        STTConnector, "transcribe_audio_file", lambda self, path, **kw: _async_value({"text": "ok"})
    )

    def _boom(path):
        raise OSError("被占用")

    monkeypatch.setattr(sc.os, "remove", _boom)

    assert asyncio.run(connector.transcribe_audio_data(b"\x00")) == {"text": "ok"}


# --------------------------------------------------------------------------
# 3. batch_transcribe
# --------------------------------------------------------------------------


def test_batch_transcribe_aggregates_success_and_failure(monkeypatch, tmp_path):
    """单个文件失败不影响其它文件，结果按输入顺序聚合。"""
    connector = _bare(temp_dir=str(tmp_path))

    def _transcribe(self, path, language="auto", **kw):
        if "bad" in path:
            return _async_raise(RuntimeError("坏了"))
        return _async_value({"text": path})

    monkeypatch.setattr(STTConnector, "transcribe_audio_file", _transcribe)

    results = asyncio.run(connector.batch_transcribe(["a.wav", "bad.wav", "c.wav"]))

    assert [r["success"] for r in results] == [True, False, True]
    assert results[1]["error"] == "坏了"
    assert results[0]["file"] == "a.wav"


def test_batch_transcribe_respects_concurrency_limit(monkeypatch, tmp_path):
    """并发上限通过 Semaphore 生效：同一时刻最多 N 个在跑。"""
    connector = _bare(temp_dir=str(tmp_path))
    running = []
    peak = []

    async def _transcribe(self, path, language="auto", **kw):
        running.append(path)
        peak.append(len(running))
        await asyncio.sleep(0)
        running.remove(path)
        return {"text": path}

    monkeypatch.setattr(STTConnector, "transcribe_audio_file", _transcribe)

    results = asyncio.run(connector.batch_transcribe(["a", "b", "c", "d"], concurrency_limit=2))

    assert len(results) == 4
    assert max(peak) <= 2, "并发数不应超过 concurrency_limit"


def test_batch_transcribe_empty_list():
    connector = _bare()

    assert asyncio.run(connector.batch_transcribe([])) == []
