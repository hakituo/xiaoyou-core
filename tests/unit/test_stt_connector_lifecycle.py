"""multimodal/stt_connector.py 单元测试（二）：模型分发与资源清理。

对应源码：`_load_model`（按 model_type 分发）、`close`、`__aenter__` / `__aexit__`。

策略：全程替身，不加载真实模型；异步代码用「同步测试函数 + asyncio.run(...)」。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from multimodal import stt_connector as sc
from multimodal.stt_connector import STTConnector


def _noop_loader(self):  # noqa: ANN001
    return None


def _build(monkeypatch, tmp_path, model_type="faster-whisper", model_path="models/x"):
    monkeypatch.setenv("TEMP_AUDIO_DIR", str(tmp_path / "temp_audio"))
    monkeypatch.setattr(STTConnector, "_load_model", _noop_loader)
    return STTConnector(model_type=model_type, model_path=model_path)


def _bare(model_type="faster-whisper"):
    """绕过 __init__ 造一个裸实例，专供 `_load_model` 单测使用。

    注意：不能像 `_build` 那样把 `_load_model` 整体打桩 —— 那样被测方法本身就是空的。
    """
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
# 1. _load_model：按 model_type 分发
# --------------------------------------------------------------------------


def test_load_model_dispatches_faster_whisper(monkeypatch):
    connector = _bare("Faster-Whisper")
    called = []
    monkeypatch.setattr(STTConnector, "_load_faster_whisper_model", lambda self: called.append(1))

    connector._load_model()

    assert called == [1], "大小写不敏感，应分发到 faster-whisper 加载器"


def test_load_model_dispatches_whisper(monkeypatch):
    connector = _bare("whisper")
    built = {}

    class _Processor:
        @staticmethod
        def from_pretrained(path):
            built["processor_path"] = path
            return "PROC"

    class _Model:
        @staticmethod
        def from_pretrained(path):
            built["model_path"] = path
            return SimpleNamespace(to=lambda device: built.setdefault("device", device))

    monkeypatch.setattr(sc, "WhisperProcessor", _Processor)
    monkeypatch.setattr(sc, "WhisperForConditionalGeneration", _Model)

    connector._load_model()

    assert built["processor_path"] == "models/x"
    assert built["model_path"] == "models/x"
    assert built["device"] == connector.device
    assert connector.processor == "PROC"


def test_load_model_dispatches_paraformer(monkeypatch):
    connector = _bare("paraformer")
    called = []
    monkeypatch.setattr(STTConnector, "_load_paraformer_model", lambda self: called.append(1))

    connector._load_model()

    assert called == [1]


def test_load_model_unknown_type_falls_back_to_faster_whisper(monkeypatch):
    """未知类型：记 error、把 model_type 改成 faster-whisper 后重新加载。"""
    connector = _bare("no-such-model")
    called = []
    monkeypatch.setattr(STTConnector, "_load_faster_whisper_model", lambda self: called.append(1))

    connector._load_model()

    assert connector.model_type == "faster-whisper"
    assert called == [1], "未知类型应回落到 faster-whisper 加载器"


def test_load_model_exception_resets_all_handles(monkeypatch):
    """加载抛异常时三个句柄都置 None，不向上抛。"""
    connector = _bare("faster-whisper")
    connector.processor = "P"
    connector.modelscope_model = "M"

    def _boom(self):
        raise RuntimeError("加载炸了")

    monkeypatch.setattr(STTConnector, "_load_faster_whisper_model", _boom)

    connector._load_model()

    assert connector.processor is None
    assert connector.model is None
    assert connector.modelscope_model is None


# --------------------------------------------------------------------------
# 2. close / 异步上下文管理器
# --------------------------------------------------------------------------


def test_close_unloads_faster_whisper_and_removes_temp_dir(monkeypatch, tmp_path):
    connector = _build(monkeypatch, tmp_path)
    connector.model = object()
    temp_dir = tmp_path / "temp_audio"
    (temp_dir / "a.wav").write_bytes(b"x")

    asyncio.run(connector.close())

    assert connector.model is None
    assert not temp_dir.exists(), "close 应清掉临时音频目录"


def test_close_unloads_whisper(monkeypatch, tmp_path):
    connector = _build(monkeypatch, tmp_path, model_type="whisper")
    connector.model = object()
    connector.processor = object()

    asyncio.run(connector.close())

    assert connector.model is None
    assert connector.processor is None


def test_close_unloads_paraformer(monkeypatch, tmp_path):
    connector = _build(monkeypatch, tmp_path, model_type="paraformer")
    connector.modelscope_model = object()

    asyncio.run(connector.close())

    assert connector.modelscope_model is None


def test_close_is_noop_without_loaded_model(monkeypatch, tmp_path):
    """未加载任何模型时 close 不应报错（且临时目录仍被清理）。"""
    connector = _build(monkeypatch, tmp_path)

    asyncio.run(connector.close())

    assert connector.model is None


def test_close_warns_when_rmtree_fails(monkeypatch, tmp_path):
    """rmtree 抛异常只记 warning，不向外抛。"""
    connector = _build(monkeypatch, tmp_path)

    def _boom(path):
        raise OSError("删不掉")

    monkeypatch.setattr(sc.shutil, "rmtree", _boom)

    asyncio.run(connector.close())  # 不应抛异常


def test_async_context_manager_closes_on_exit(monkeypatch, tmp_path):
    connector = _build(monkeypatch, tmp_path)
    connector.model = object()

    async def _run():
        async with connector as entered:
            assert entered is connector
            return connector.model

    asyncio.run(_run())

    assert connector.model is None, "__aexit__ 应调用 close()"


@pytest.mark.parametrize("model_type", ["faster-whisper", "whisper", "paraformer"])
def test_close_never_raises_for_any_type(monkeypatch, tmp_path, model_type):
    """三种模型类型下 close 都不应抛异常（含 torch 缺失的情况）。"""
    monkeypatch.setattr(sc, "torch", None)
    connector = _build(monkeypatch, tmp_path, model_type=model_type)

    asyncio.run(connector.close())
