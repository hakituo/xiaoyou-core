"""multimodal/stt_connector.py 单元测试（三）：两种模型加载器。

对应源码：`_load_faster_whisper_model`、`_load_paraformer_model`。

⚠️ `_load_paraformer_model` 在 ImportError 时会**尝试 `pip install modelscope`**。
本文件用 `subprocess.check_call` 替身覆盖该回退路径 —— **只记录调用、绝不真的执行**。
"""

from __future__ import annotations

import subprocess
import sys
import types
from types import SimpleNamespace

import pytest

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


def _install_fake_modelscope(monkeypatch, *, pipeline=None):
    """把假的 modelscope 包塞进 sys.modules，覆盖「已装 modelscope」的成功路径。"""
    ms = types.ModuleType("modelscope")
    ms_pipelines = types.ModuleType("modelscope.pipelines")
    ms_pipelines.pipeline = pipeline or (lambda **kw: ("MS_MODEL", kw))
    ms_utils = types.ModuleType("modelscope.utils")
    ms_const = types.ModuleType("modelscope.utils.constant")
    ms_const.Tasks = SimpleNamespace(auto_speech_recognition="asr-task")
    ms.pipelines = ms_pipelines
    ms.utils = ms_utils
    for name, mod in (
        ("modelscope", ms),
        ("modelscope.pipelines", ms_pipelines),
        ("modelscope.utils", ms_utils),
        ("modelscope.utils.constant", ms_const),
    ):
        monkeypatch.setitem(sys.modules, name, mod)


# --------------------------------------------------------------------------
# 1. _load_faster_whisper_model
# --------------------------------------------------------------------------


def test_load_faster_whisper_cpu_uses_int8(monkeypatch):
    """CPU 上必须用 int8（float16 在 CPU 上不可用）。"""
    connector = _bare()
    captured = {}

    class _WhisperModel:
        def __init__(self, size, device=None, compute_type=None, download_root=None):
            captured.update(
                size=size, device=device, compute_type=compute_type, download_root=download_root
            )

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = _WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)

    connector._load_faster_whisper_model()

    assert captured["device"] == "cpu"
    assert captured["compute_type"] == "int8"
    assert captured["download_root"] == "models/x"
    assert connector.model is not None


def test_load_faster_whisper_gpu_uses_float16(monkeypatch):
    connector = _bare()
    connector.device = "cuda"
    captured = {}

    class _WhisperModel:
        def __init__(self, size, device=None, compute_type=None, download_root=None):
            captured.update(compute_type=compute_type)

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = _WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)

    connector._load_faster_whisper_model()

    assert captured["compute_type"] == "float16"


def test_load_faster_whisper_failure_reraises(monkeypatch):
    """加载失败必须向上抛（调用方 `_load_model` 再兜底）。"""
    connector = _bare()

    class _WhisperModel:
        def __init__(self, *a, **kw):
            raise RuntimeError("显存不足")

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = _WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)

    with pytest.raises(RuntimeError, match="显存不足"):
        connector._load_faster_whisper_model()


# --------------------------------------------------------------------------
# 2. _load_paraformer_model（含 pip 回退路径）
# --------------------------------------------------------------------------


def test_load_paraformer_success(monkeypatch):
    connector = _bare("paraformer")
    _install_fake_modelscope(monkeypatch)

    connector._load_paraformer_model()

    assert connector.modelscope_model is not None


def test_load_paraformer_import_error_then_pip_install_succeeds(monkeypatch):
    """未装 modelscope → pip install → 重试成功。pip 只记录，绝不真的执行。"""
    connector = _bare("paraformer")
    pip_calls = []

    def _fake_check_call(args, timeout=None):
        pip_calls.append((args, timeout))
        _install_fake_modelscope(monkeypatch)  # 模拟「装好了」

    monkeypatch.setattr(subprocess, "check_call", _fake_check_call)

    connector._load_paraformer_model()

    assert pip_calls, "应触发一次 pip install"
    assert pip_calls[0][1] == 180, "pip install 必须带 timeout（防网络异常阻塞）"
    assert connector.modelscope_model is not None


def test_load_paraformer_pip_timeout_raises(monkeypatch):
    """pip 超时必须抛出 TimeoutExpired（而不是静默继续）。"""
    connector = _bare("paraformer")

    def _timeout(args, timeout=None):
        raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

    monkeypatch.setattr(subprocess, "check_call", _timeout)

    with pytest.raises(subprocess.TimeoutExpired):
        connector._load_paraformer_model()


def test_load_paraformer_pip_ok_but_import_still_fails(monkeypatch):
    """pip 装完仍导不进来时，抛异常而不是留下半初始化状态。"""
    connector = _bare("paraformer")
    monkeypatch.setattr(subprocess, "check_call", lambda *a, **kw: None)

    with pytest.raises(Exception):
        connector._load_paraformer_model()

    assert connector.modelscope_model is None
