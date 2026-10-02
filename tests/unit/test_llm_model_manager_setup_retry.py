#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``llm_model_manager.py`` 的候选重试、``_build_cpp_llm_config`` 与
``_patch_llama_cpp_internals`` 专项测试。

本文件是 ``test_llm_model_manager_setup.py`` 按关注点拆出的第二部分：
只放「候选遍历 / OOM 与 TypeError 重试 / CUDA 回退」以及两个独立小函数。
``setup_python_llm`` 的早退分支与配置装配见前者。

约束（与前者一致）：
- 纯 mock：``Llama`` 用假类替换，绝不加载真实模型；``llama_cpp`` / ``torch``
  通过注入假 ``sys.modules`` 控制；不访问网络；
- 配置读取 patch 源模块 ``config.integrated_config.get_settings``（函数体内
  import）；资源管理器 patch 源模块 ``core.resource_manager.get_resource_manager``；
  模块级名字（``check_memory_pressure`` 等）patch 被测模块自身；
- 文件 IO 一律落 tmp_path；不依赖真实时间流逝，不 sleep。
"""

from __future__ import annotations

import contextlib
import sys
import types

import pytest

import core.services.scheduler.model.llm_model_manager as llmm
from core.services.scheduler.model.llm_model_manager import LLMModelManager
from core.services.scheduler.utils.resource_utils import MemoryPressureResult


# --------------------------------------------------------------------------- #
# 替身与工具
# --------------------------------------------------------------------------- #


class _FakeLlama:
    """假 Llama：记录构造 kwargs 即可。"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _make_llama(handler, calls):
    """返回记录调用的 Llama 工厂；``handler(index, kwargs)`` 决定返回/抛错。"""

    def _factory(**kwargs):
        calls.append(dict(kwargs))
        return handler(len(calls) - 1, kwargs)

    return _factory


def _mem(percent=10.0, is_pressure=False, threshold=97.0, has_gpu=False):
    return MemoryPressureResult(
        percent=percent, is_pressure=is_pressure, threshold=threshold, has_gpu=has_gpu
    )


def _settings(**over):
    from types import SimpleNamespace
    base = dict(
        force_cpu_inference=False,
        skip_memory_check_on_llm_load=False,
        use_mmap=False,
        ram_mirror_offload=False,
        vram_reserve_mb=0,
        tts_gpu_min_free_mb=1200,
        dynamic_kv_offload=True,
    )
    base.update(over)
    return SimpleNamespace(model=SimpleNamespace(**base))


@contextlib.contextmanager
def _sys_modules(name, module):
    """临时替换 sys.modules[name]（键不存在也能用）。"""
    sentinel = object()
    old = sys.modules.get(name, sentinel)
    sys.modules[name] = module
    try:
        yield
    finally:
        if old is sentinel:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = old


@pytest.fixture()
def manager():
    mgr = LLMModelManager()
    yield mgr
    ex = getattr(mgr, "_llm_executor", None)
    if ex is not None:
        ex.shutdown(wait=False)


@pytest.fixture()
def gguf(tmp_path):
    """写一个文件头合法的假 GGUF 文件（不加载，仅过格式校验）。"""
    p = tmp_path / "model.gguf"
    p.write_bytes(b"GGUF" + b"\x00" * 8)
    return str(p)


def _patch_env(
    monkeypatch,
    *,
    mem,
    settings=None,
    settings_raises=False,
    llama=None,
    rm_calls=None,
    rm_boom=False,
):
    """安装通用 patch：Llama / patch 记录器 / 内存检查 / 设置 / 资源管理器。"""
    patch_calls: list = []
    monkeypatch.setattr(
        llmm, "_patch_llama_cpp_internals", lambda: patch_calls.append("patch")
    )
    monkeypatch.setattr(llmm, "Llama", llama if llama is not None else _FakeLlama)
    monkeypatch.setattr(llmm, "check_memory_pressure", lambda: mem)

    if settings_raises:
        def _boom():
            raise RuntimeError("settings unavailable")

        monkeypatch.setattr("config.integrated_config.get_settings", _boom)
    elif settings is not None:
        monkeypatch.setattr(
            "config.integrated_config.get_settings", lambda: settings
        )

    rc = rm_calls if rm_calls is not None else []

    class _RM:
        def mark_model_loaded(self, name, loaded):
            rc.append((name, loaded))

    if rm_boom:
        def _rm_factory():
            raise RuntimeError("resource manager unavailable")
    else:
        def _rm_factory():
            return _RM()

    monkeypatch.setattr("core.resource_manager.get_resource_manager", _rm_factory)
    return {"patch": patch_calls, "rm": rc}


# --------------------------------------------------------------------------- #
# setup_python_llm —— 候选重试与错误分支
# --------------------------------------------------------------------------- #


def test_setup_oom_retries_next_candidate(manager, monkeypatch, gguf):
    """首个候选 OOM 时继续下一个候选（正数层数 -> 折半）。"""

    def _handler(index, kwargs):
        if index == 0:
            raise RuntimeError("out of memory")
        return _FakeLlama(**kwargs)

    llama_calls: list = []
    _patch_env(
        monkeypatch,
        mem=_mem(),
        settings=_settings(),
        llama=_make_llama(_handler, llama_calls),
    )
    inst = manager.setup_python_llm(
        {"model_path": gguf, "n_gpu_layers": 20, "max_context_size": 1024}
    )
    assert inst is not None
    assert llama_calls[0]["n_gpu_layers"] == 20
    assert llama_calls[1]["n_gpu_layers"] == 10


def test_setup_all_candidates_oom_sets_error(manager, monkeypatch, gguf):
    """所有候选都 OOM：遍历完 17 个候选后置空 llm 并记录错误。"""

    def _handler(index, kwargs):
        raise RuntimeError("out of memory")

    llama_calls: list = []
    _patch_env(
        monkeypatch,
        mem=_mem(),
        settings=_settings(),
        llama=_make_llama(_handler, llama_calls),
    )
    out = manager.setup_python_llm(
        {"model_path": gguf, "max_context_size": 4096, "n_gpu_layers": -1}
    )
    assert out is None
    assert manager.llm is None
    assert manager._last_llm_load_error == "out of memory"
    assert len(llama_calls) == 17


def test_setup_duplicate_candidate_is_skipped(manager, monkeypatch, gguf):
    """候选去重：重复的 (1024,0,128) 第二次被 continue 跳过。"""

    def _handler(index, kwargs):
        raise RuntimeError("out of memory")

    llama_calls: list = []
    _patch_env(
        monkeypatch,
        mem=_mem(),
        settings=_settings(),
        llama=_make_llama(_handler, llama_calls),
    )
    out = manager.setup_python_llm(
        {"model_path": gguf, "force_cpu": True, "max_context_size": 1024,
         "max_batch_size": 128}
    )
    assert out is None
    assert len(llama_calls) == 1


def test_setup_typeerror_retry_removes_keyword(manager, monkeypatch, gguf):
    """TypeError 提示 unexpected keyword 时删除该键后重试。"""

    def _handler(index, kwargs):
        if index == 0:
            raise TypeError(
                "Llama.__init__() got an unexpected keyword argument 'flash_attn'"
            )
        return _FakeLlama(**kwargs)

    llama_calls: list = []
    _patch_env(
        monkeypatch,
        mem=_mem(),
        settings=_settings(),
        llama=_make_llama(_handler, llama_calls),
    )
    inst = manager.setup_python_llm({"model_path": gguf})
    assert inst is not None
    assert "flash_attn" in llama_calls[0]
    assert "flash_attn" not in llama_calls[1]


def test_setup_unmatched_typeerror_breaks(manager, monkeypatch, gguf):
    """TypeError 不匹配任何可删键时向上抛出，最终被外层捕获。"""

    def _handler(index, kwargs):
        raise TypeError("got an unexpected keyword argument 'nope'")

    llama_calls: list = []
    _patch_env(
        monkeypatch,
        mem=_mem(),
        settings=_settings(),
        llama=_make_llama(_handler, llama_calls),
    )
    out = manager.setup_python_llm({"model_path": gguf})
    assert out is None
    assert len(llama_calls) == 1
    assert "nope" in manager._last_llm_load_error


def test_setup_cuda_backend_error_switches_to_cpu(manager, monkeypatch, gguf):
    """CUDA 后端错误：置 _python_force_cpu 并把 gpu_config 层数清零后跳出。"""

    def _handler(index, kwargs):
        raise RuntimeError("CUDA error: device not found")

    llama_calls: list = []
    _patch_env(
        monkeypatch,
        mem=_mem(),
        settings=_settings(),
        llama=_make_llama(_handler, llama_calls),
    )
    manager.set_config({"model_path": gguf})
    out = manager.setup_python_llm({"model_path": gguf, "n_gpu_layers": 20})
    assert out is None
    assert manager._python_force_cpu is True
    assert manager._gpu_config["n_gpu_layers"] == 0
    assert len(llama_calls) == 1


def test_setup_unexpected_error_sets_last_error(manager, monkeypatch, gguf):
    """参数解析阶段抛错时由外层 except 记录错误。"""
    _patch_env(monkeypatch, mem=_mem(), settings=_settings())
    out = manager.setup_python_llm({"model_path": gguf, "max_context_size": "abc"})
    assert out is None
    assert "invalid literal" in manager._last_llm_load_error


# --------------------------------------------------------------------------- #
# _build_cpp_llm_config
# --------------------------------------------------------------------------- #


def test_build_cpp_llm_config_delegates(manager, monkeypatch):
    """_build_cpp_llm_config 委托给 CPPConfigBuilder.build_llm_config。"""
    seen: list = []

    class _Builder:
        @staticmethod
        def build_llm_config(cfg):
            seen.append(cfg)
            return {"built": True}

    monkeypatch.setattr(
        "core.services.scheduler.client.cpp_config_builder.CPPConfigBuilder", _Builder
    )
    cfg = {"k": 1}
    assert manager._build_cpp_llm_config(cfg) == {"built": True}
    assert seen == [cfg]


# --------------------------------------------------------------------------- #
# _patch_llama_cpp_internals
# --------------------------------------------------------------------------- #


def _internals_module(model_cls):
    internals = types.ModuleType("llama_cpp._internals")
    internals.LlamaModel = model_cls
    pkg = types.ModuleType("llama_cpp")
    pkg._internals = internals
    return pkg, internals


def test_patch_internals_already_patched_returns_early(monkeypatch):
    """已打过补丁时直接返回，不重复处理。"""
    monkeypatch.setattr(llmm, "_LLAMA_CPP_INTERNALS_PATCHED", True)
    llmm._patch_llama_cpp_internals()
    assert llmm._LLAMA_CPP_INTERNALS_PATCHED is True


def test_patch_internals_missing_module_is_silent(monkeypatch):
    """llama_cpp 不存在时静默跳过，仅置标志位。"""
    monkeypatch.setattr(llmm, "_LLAMA_CPP_INTERNALS_PATCHED", False)
    with _sys_modules("llama_cpp", None), _sys_modules("llama_cpp._internals", None):
        llmm._patch_llama_cpp_internals()
    assert llmm._LLAMA_CPP_INTERNALS_PATCHED is True


def test_patch_internals_llama_model_none(monkeypatch):
    """LlamaModel 为 None 时跳过内部修补。"""
    monkeypatch.setattr(llmm, "_LLAMA_CPP_INTERNALS_PATCHED", False)
    pkg, internals = _internals_module(None)
    with _sys_modules("llama_cpp", pkg), _sys_modules("llama_cpp._internals", internals):
        llmm._patch_llama_cpp_internals()
    assert llmm._LLAMA_CPP_INTERNALS_PATCHED is True


def test_patch_internals_model_without_hooks(monkeypatch):
    """LlamaModel 无 close / __del__ 时不打任何补丁。"""

    class _NoHooks:
        pass

    monkeypatch.setattr(llmm, "_LLAMA_CPP_INTERNALS_PATCHED", False)
    pkg, internals = _internals_module(_NoHooks)
    with _sys_modules("llama_cpp", pkg), _sys_modules("llama_cpp._internals", internals):
        llmm._patch_llama_cpp_internals()
    assert not hasattr(_NoHooks, "close")
    assert llmm._LLAMA_CPP_INTERNALS_PATCHED is True


def test_patch_internals_wraps_close_and_del(monkeypatch):
    """同时存在 close / __del__ 时两者都被安全包装。"""
    record: list = []

    def _orig_close(self):
        record.append("orig_close")
        return "close-result"

    def _orig_del(self):
        record.append("orig_del")
        return "del-result"

    cls = type("LlamaModel", (), {"close": _orig_close, "__del__": _orig_del})
    monkeypatch.setattr(llmm, "_LLAMA_CPP_INTERNALS_PATCHED", False)
    pkg, internals = _internals_module(cls)
    with _sys_modules("llama_cpp", pkg), _sys_modules("llama_cpp._internals", internals):
        llmm._patch_llama_cpp_internals()

    obj = cls()  # 无 sampler -> 应被补 None
    assert cls.close(obj) == "close-result"
    assert obj.sampler is None
    assert record == ["orig_close"]

    obj2 = cls()
    obj2.sampler = "keep"  # 已有 sampler -> 不覆盖
    assert cls.close(obj2) == "close-result"
    assert obj2.sampler == "keep"

    obj3 = cls()
    assert cls.__del__(obj3) == "del-result"
    assert record == ["orig_close", "orig_close", "orig_del"]


def test_patch_internals_safe_close_swallows_attribute_error(monkeypatch):
    """_safe_close 内部 AttributeError 被吞掉返回 None。"""

    def _orig_close(self):
        raise AttributeError("no sampler")

    cls = type("LlamaModel", (), {"close": _orig_close})
    monkeypatch.setattr(llmm, "_LLAMA_CPP_INTERNALS_PATCHED", False)
    pkg, internals = _internals_module(cls)
    with _sys_modules("llama_cpp", pkg), _sys_modules("llama_cpp._internals", internals):
        llmm._patch_llama_cpp_internals()
    assert cls.close(cls()) is None


def test_patch_internals_safe_del_falls_back_to_close(monkeypatch):
    """_safe_del 中原始 __del__ 抛错时回退调用 close。"""
    calls: list = []

    def _orig_del(self):
        raise RuntimeError("del boom")

    def _close(self):
        calls.append("close")

    cls = type("LlamaModel", (), {"close": _close, "__del__": _orig_del})
    monkeypatch.setattr(llmm, "_LLAMA_CPP_INTERNALS_PATCHED", False)
    pkg, internals = _internals_module(cls)
    with _sys_modules("llama_cpp", pkg), _sys_modules("llama_cpp._internals", internals):
        llmm._patch_llama_cpp_internals()
    obj = cls()  # 持有引用，避免临时对象被 GC 再次触发 __del__
    assert cls.__del__(obj) is None
    assert calls == ["close"]


def test_patch_internals_safe_del_double_failure_returns_none(monkeypatch):
    """__del__ 与 close 都抛错时返回 None。"""

    def _orig_del(self):
        raise RuntimeError("del boom")

    def _close(self):
        raise RuntimeError("close boom")

    cls = type("LlamaModel", (), {"close": _close, "__del__": _orig_del})
    monkeypatch.setattr(llmm, "_LLAMA_CPP_INTERNALS_PATCHED", False)
    pkg, internals = _internals_module(cls)
    with _sys_modules("llama_cpp", pkg), _sys_modules("llama_cpp._internals", internals):
        llmm._patch_llama_cpp_internals()
    obj = cls()  # 持有引用，避免临时对象被 GC 再次触发 __del__
    assert cls.__del__(obj) is None
