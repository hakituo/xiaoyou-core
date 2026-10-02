"""multimodal/stt_connector.py 单元测试（一）：构造与配置解析。

策略：
- 全程替身：绝不加载真实模型、绝不联网、**绝不触发 `pip install modelscope`**。
- 临时目录一律指向 tmp_path（走 `TEMP_AUDIO_DIR` 环境变量），不碰仓库真实目录。

对应源码：`STTConnector.__init__`。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from multimodal import stt_connector as sc
from multimodal.stt_connector import STTConnector


def _fake_torch(cuda_available: bool):
    """最小 torch 替身：只暴露 `cuda.is_available()`。"""
    return SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: cuda_available))


def _noop_loader(self):  # noqa: ANN001
    """`_load_model` 的空替身：避免构造时真的去加载模型。"""
    return None


def _build(monkeypatch, tmp_path, model_type="faster-whisper", model_path="models/x"):
    """构造一个「不加载真实模型」的 STTConnector。"""
    monkeypatch.setenv("TEMP_AUDIO_DIR", str(tmp_path / "temp_audio"))
    monkeypatch.setattr(STTConnector, "_load_model", _noop_loader)
    return STTConnector(model_type=model_type, model_path=model_path)


def test_init_creates_temp_dir_from_env(monkeypatch, tmp_path):
    """临时目录取自 TEMP_AUDIO_DIR，且构造时就会被创建。"""
    temp_dir = tmp_path / "my_audio"
    monkeypatch.setenv("TEMP_AUDIO_DIR", str(temp_dir))
    monkeypatch.setattr(STTConnector, "_load_model", _noop_loader)

    connector = STTConnector(model_type="faster-whisper", model_path="models/x")

    assert connector.temp_audio_dir == str(temp_dir)
    assert temp_dir.is_dir(), "构造时应创建临时音频目录"


def test_init_prefers_explicit_arguments(monkeypatch, tmp_path):
    """显式传入的 model_type / model_path 优先于环境变量。"""
    monkeypatch.setenv("TEMP_AUDIO_DIR", str(tmp_path))
    monkeypatch.setenv("ASR_MODEL_TYPE", "env-type")
    monkeypatch.setenv("ASR_MODEL_PATH", "env-path")
    monkeypatch.setattr(STTConnector, "_load_model", _noop_loader)

    connector = STTConnector(model_type="whisper", model_path="/abs/path")

    assert connector.model_type == "whisper"
    assert connector.model_path == "/abs/path"


def test_init_falls_back_to_env_vars(monkeypatch, tmp_path):
    """未传参时回落到环境变量。"""
    monkeypatch.setenv("TEMP_AUDIO_DIR", str(tmp_path))
    monkeypatch.setenv("ASR_MODEL_TYPE", "env-type")
    monkeypatch.setenv("ASR_MODEL_PATH", "/env/path")
    monkeypatch.setattr(STTConnector, "_load_model", _noop_loader)

    connector = STTConnector()

    assert connector.model_type == "env-type"
    assert connector.model_path == "/env/path"


@pytest.mark.parametrize("prefix", ["models", "data", "config", "output"])
def test_init_joins_project_root_for_known_relative_prefix(monkeypatch, tmp_path, prefix):
    """相对路径且首段是 models/data/config/output 时，拼到项目根下。"""
    monkeypatch.setenv("TEMP_AUDIO_DIR", str(tmp_path))
    monkeypatch.setattr(sc, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(STTConnector, "_load_model", _noop_loader)

    connector = STTConnector(model_type="faster-whisper", model_path=f"{prefix}/sub")

    assert connector.model_path == str(tmp_path / prefix / "sub")


def test_init_keeps_absolute_model_path(monkeypatch, tmp_path):
    """绝对路径原样保留。"""
    abs_path = str(tmp_path / "elsewhere" / "model")
    monkeypatch.setenv("TEMP_AUDIO_DIR", str(tmp_path))
    monkeypatch.setattr(sc, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(STTConnector, "_load_model", _noop_loader)

    connector = STTConnector(model_type="faster-whisper", model_path=abs_path)

    assert connector.model_path == abs_path


def test_init_keeps_relative_path_outside_prefix_list(monkeypatch, tmp_path):
    """首段不在白名单里的相对路径不拼接（保持原样）。"""
    monkeypatch.setenv("TEMP_AUDIO_DIR", str(tmp_path))
    monkeypatch.setattr(sc, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(STTConnector, "_load_model", _noop_loader)

    connector = STTConnector(model_type="faster-whisper", model_path="custom/model")

    assert connector.model_path == "custom/model"


def test_init_device_is_cpu_when_torch_missing(monkeypatch, tmp_path):
    """torch 不可用时设备回落 cpu。"""
    monkeypatch.setattr(sc, "torch", None)

    connector = _build(monkeypatch, tmp_path)

    assert connector.device == "cpu"


def test_init_device_is_cuda_when_available(monkeypatch, tmp_path):
    """torch 有 CUDA 时设备为 cuda。"""
    monkeypatch.setattr(sc, "torch", _fake_torch(True))

    connector = _build(monkeypatch, tmp_path)

    assert connector.device == "cuda"


def test_init_calls_load_model(monkeypatch, tmp_path):
    """构造末尾会调用一次 _load_model。"""
    monkeypatch.setenv("TEMP_AUDIO_DIR", str(tmp_path))
    calls = []
    monkeypatch.setattr(STTConnector, "_load_model", lambda self: calls.append(1))

    STTConnector(model_type="faster-whisper", model_path="models/x")

    assert calls == [1], "构造必须触发一次模型加载"


def test_init_swallows_path_resolution_error(monkeypatch, tmp_path):
    """路径解析抛异常时静默忽略，构造照常完成。"""
    monkeypatch.setenv("TEMP_AUDIO_DIR", str(tmp_path))
    monkeypatch.setattr(STTConnector, "_load_model", _noop_loader)

    def _boom(*args, **kwargs):
        raise RuntimeError("Path 炸了")

    monkeypatch.setattr(sc, "Path", _boom)

    connector = sc.STTConnector(model_type="faster-whisper", model_path="models/x")

    assert connector.model_path == "models/x", "解析失败时应保留原值"
    assert connector.processor is None
