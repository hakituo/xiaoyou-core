"""multimodal/stt_connector.py 单元测试（四）：惰性加载 `_ensure_model_loaded`。

对应源码：`_ensure_model_loaded`（三种模型类型各自的「缺则加载 / 仍缺则兜底或报错」逻辑）。

策略：全程替身，不加载真实模型；异步代码用「同步测试函数 + asyncio.run(...)」。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from multimodal import stt_connector as sc
from multimodal.stt_connector import STTConnector


def _bare(model_type="faster-whisper"):
    obj = STTConnector.__new__(STTConnector)
    obj.model_type = model_type
    obj.model_path = "models/x"
    obj.device = "cpu"
    obj.processor = None
    obj.model = None
    obj.modelscope_model = None
    obj.temp_audio_dir = "unused"
    return obj


# --------------------------------------------------------------------------
# faster-whisper
# --------------------------------------------------------------------------


def test_ensure_faster_whisper_loads_when_absent(monkeypatch):
    connector = _bare()
    called = []
    monkeypatch.setattr(STTConnector, "_load_faster_whisper_model", lambda self: called.append(1))

    asyncio.run(connector._ensure_model_loaded())

    assert called == [1]


def test_ensure_faster_whisper_skips_when_present(monkeypatch):
    """已有模型时不应重复加载。"""
    connector = _bare()
    connector.model = object()
    called = []
    monkeypatch.setattr(STTConnector, "_load_faster_whisper_model", lambda self: called.append(1))

    asyncio.run(connector._ensure_model_loaded())

    assert called == [], "模型已在内存里就不该再加载一次"


# --------------------------------------------------------------------------
# whisper
# --------------------------------------------------------------------------


def test_ensure_whisper_loads_then_ok(monkeypatch):
    connector = _bare("whisper")
    called = []

    def _load(self):
        called.append(1)
        self.model = object()
        self.processor = object()

    monkeypatch.setattr(STTConnector, "_load_model", _load)

    asyncio.run(connector._ensure_model_loaded())

    assert called == [1]


def test_ensure_whisper_falls_back_to_default_model(monkeypatch):
    """第一次加载没拿到模型时，回落到 openai/whisper-small。"""
    connector = _bare("whisper")
    monkeypatch.setattr(STTConnector, "_load_model", lambda self: None)
    built = {}

    class _Processor:
        @staticmethod
        def from_pretrained(path):
            built["processor"] = path
            return "PROC"

    class _Model:
        @staticmethod
        def from_pretrained(path):
            built["model"] = path
            return SimpleNamespace(to=lambda device: built.setdefault("device", device))

    monkeypatch.setattr(sc, "WhisperProcessor", _Processor)
    monkeypatch.setattr(sc, "WhisperForConditionalGeneration", _Model)

    asyncio.run(connector._ensure_model_loaded())

    assert built["processor"] == "openai/whisper-small"
    assert built["model"] == "openai/whisper-small"
    assert connector.processor == "PROC"


def test_ensure_whisper_raises_when_default_fails(monkeypatch):
    connector = _bare("whisper")
    monkeypatch.setattr(STTConnector, "_load_model", lambda self: None)

    class _Boom:
        @staticmethod
        def from_pretrained(path):
            raise OSError("下载失败")

    monkeypatch.setattr(sc, "WhisperProcessor", _Boom)

    with pytest.raises(Exception, match="无法加载语音识别模型"):
        asyncio.run(connector._ensure_model_loaded())


def test_ensure_whisper_skips_when_both_handles_present(monkeypatch):
    """model 与 processor 都在时不重新加载。"""
    connector = _bare("whisper")
    connector.model = object()
    connector.processor = object()
    called = []
    monkeypatch.setattr(STTConnector, "_load_model", lambda self: called.append(1))

    asyncio.run(connector._ensure_model_loaded())

    assert called == []


# --------------------------------------------------------------------------
# paraformer
# --------------------------------------------------------------------------


def test_ensure_paraformer_loads(monkeypatch):
    connector = _bare("paraformer")
    called = []

    def _load(self):
        called.append(1)
        self.modelscope_model = object()

    monkeypatch.setattr(STTConnector, "_load_paraformer_model", _load)

    asyncio.run(connector._ensure_model_loaded())

    assert called == [1]


def test_ensure_paraformer_raises_when_still_absent(monkeypatch):
    connector = _bare("paraformer")
    monkeypatch.setattr(STTConnector, "_load_paraformer_model", lambda self: None)

    with pytest.raises(Exception, match="无法加载Paraformer"):
        asyncio.run(connector._ensure_model_loaded())


def test_ensure_paraformer_skips_when_present(monkeypatch):
    connector = _bare("paraformer")
    connector.modelscope_model = object()
    called = []
    monkeypatch.setattr(STTConnector, "_load_paraformer_model", lambda self: called.append(1))

    asyncio.run(connector._ensure_model_loaded())

    assert called == []


def test_ensure_unknown_type_is_noop(monkeypatch):
    """未知类型不进任何分支，直接返回（由 `_load_model` 负责回落）。"""
    connector = _bare("no-such-type")

    asyncio.run(connector._ensure_model_loaded())

    assert connector.model is None
