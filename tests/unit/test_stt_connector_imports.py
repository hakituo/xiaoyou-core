"""multimodal/stt_connector.py 的单元测试补强（四）：模块级可选依赖回退与 demo 入口。

模块级的 `try/except` 回退分支（torch / C++ 预处理器 / ASR 配置）只有在**特定导入条件**下
才会走到，正常 import 一次是覆盖不到的。做法：把模块源码在**全新命名空间**里 exec 一遍，
期间把导入条件打桩（见技能库 §3.6 的同类手法）。

`example_usage()` 与 `if __name__ == "__main__":` 也在这里覆盖。
"""

from __future__ import annotations

import asyncio
import builtins
import importlib.util
import runpy
import sys
import types
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

from multimodal import stt_connector as sc

_SRC = Path(sc.__file__).read_text(encoding="utf-8")


def _exec_fresh(monkeypatch, *, fail_torch=False, audio_present=False, audio_probe_raises=False,
                asr_raises=False):
    """在全新命名空间里重新执行模块源码，返回该命名空间。"""
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if fail_torch and name == "torch":
            raise ImportError("模拟未安装 torch")
        if audio_present and name == "audio_processor_py":
            mod = types.ModuleType("audio_processor_py")
            mod.AudioVAD = object
            return mod
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    if audio_present or audio_probe_raises:
        real_find_spec = importlib.util.find_spec

        def _fake_find_spec(name, *args, **kwargs):
            if name == "audio_processor_py":
                if audio_probe_raises:
                    raise RuntimeError("find_spec 炸了")
                return object()  # 非 None，表示「找得到」
            return real_find_spec(name, *args, **kwargs)

        monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)

    if asr_raises:
        import config.settings_adapters as sa

        def _boom():
            raise RuntimeError("配置读取失败")

        monkeypatch.setattr(sa, "get_asr_settings", _boom)

    namespace = {"__name__": "multimodal._stt_probe", "__file__": sc.__file__}
    exec(compile(_SRC, sc.__file__, "exec"), namespace)
    return namespace


# --------------------------------------------------------------------------
# 1. 模块级可选依赖回退
# --------------------------------------------------------------------------


def test_module_falls_back_when_torch_missing(monkeypatch, tmp_path):
    """torch 导入失败时置 None（而不是让整个模块导入失败）。"""
    monkeypatch.setenv("TEMP_AUDIO_DIR", str(tmp_path))

    namespace = _exec_fresh(monkeypatch, fail_torch=True)

    assert namespace["torch"] is None


def test_module_uses_cpp_audio_processor_when_present(monkeypatch, tmp_path):
    """C++ 预处理器存在时置 _HAS_CPP_AUDIO = True。"""
    monkeypatch.setenv("TEMP_AUDIO_DIR", str(tmp_path))

    namespace = _exec_fresh(monkeypatch, audio_present=True)

    assert namespace["_HAS_CPP_AUDIO"] is True


def test_module_falls_back_when_cpp_probe_raises(monkeypatch, tmp_path):
    """探测 C++ 模块本身抛异常时，整体回落成「没有」而不是崩溃。"""
    monkeypatch.setenv("TEMP_AUDIO_DIR", str(tmp_path))

    namespace = _exec_fresh(monkeypatch, audio_probe_raises=True)

    assert namespace["_HAS_CPP_AUDIO"] is False
    assert namespace["audio_processor_py"] is None


def test_module_falls_back_when_asr_settings_raises(monkeypatch, tmp_path):
    """ASR 配置读取失败时回落到默认模型路径与类型。"""
    monkeypatch.setenv("TEMP_AUDIO_DIR", str(tmp_path))

    namespace = _exec_fresh(monkeypatch, asr_raises=True)

    assert namespace["ASR_MODEL_TYPE"] == "faster-whisper"
    assert namespace["DEFAULT_MODEL_PATH"].endswith(str(Path("models") / "faster-whisper"))


# --------------------------------------------------------------------------
# 2. __init__ 的路径解析兜底
# --------------------------------------------------------------------------


def test_init_swallows_path_resolution_error(monkeypatch, tmp_path):
    """路径解析抛异常时静默忽略，构造照常完成。"""
    monkeypatch.setenv("TEMP_AUDIO_DIR", str(tmp_path))
    monkeypatch.setattr(sc.STTConnector, "_load_model", lambda self: None)

    def _boom(*args, **kwargs):
        raise RuntimeError("Path 炸了")

    monkeypatch.setattr(sc, "Path", _boom)

    connector = sc.STTConnector(model_type="faster-whisper", model_path="models/x")

    assert connector.model_path == "models/x", "解析失败时应保留原值"
    assert connector.processor is None


# --------------------------------------------------------------------------
# 3. demo 入口：example_usage / __main__
# --------------------------------------------------------------------------


class _FakeConnector:
    """example_usage 用的替身：异步上下文管理器 + 两个查询方法。"""

    def __init__(self):
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, *args):
        self.closed = True

    async def health_check(self):
        return True

    async def get_supported_languages(self):
        return ["zh-CN", "auto"]


def test_example_usage_runs_end_to_end(monkeypatch, capsys):
    fake = _FakeConnector()
    monkeypatch.setattr(sc, "STTConnector", lambda: fake)

    asyncio.run(sc.example_usage())

    out = capsys.readouterr().out
    assert "STT服务状态: 健康" in out
    assert "支持的语言" in out
    assert fake.closed is True, "async with 退出时应关闭连接器"


def test_example_usage_swallows_errors(monkeypatch, capsys):
    """demo 里的 try/except 会把异常打成一行提示，不向外抛。"""

    class _Bad(_FakeConnector):
        async def health_check(self):
            raise RuntimeError("服务挂了")

    monkeypatch.setattr(sc, "STTConnector", _Bad)

    asyncio.run(sc.example_usage())

    assert "错误:" in capsys.readouterr().out


def test_main_block_runs_example_usage(monkeypatch, tmp_path, capsys):
    """以 __main__ 身份重跑模块，覆盖文件末尾的 `asyncio.run(example_usage())`。

    新命名空间会重新定义 `STTConnector`，所以要把**它内部的协作者**换掉：
    模型加载走函数体内 `from faster_whisper import WhisperModel`，替换 sys.modules 即可。
    """
    monkeypatch.setenv("TEMP_AUDIO_DIR", str(tmp_path))

    fake_faster_whisper = types.ModuleType("faster_whisper")
    fake_faster_whisper.WhisperModel = lambda *a, **kw: SimpleNamespace(name="fake")
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_faster_whisper)
    monkeypatch.setitem(sys.modules, "audio_processor_py", None)

    with warnings.catch_warnings():
        # runpy 固有的「模块已在 sys.modules」提示，与本用例无关
        warnings.simplefilter("ignore", RuntimeWarning)
        runpy.run_module("multimodal.stt_connector", run_name="__main__")

    out = capsys.readouterr().out
    assert "STT服务状态" in out
