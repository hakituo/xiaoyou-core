#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``llm_model_manager.py`` 的内存压力分支专项测试。

本文件是 ``test_llm_model_manager_setup.py`` 按关注点拆出的第三部分，只放
``setup_python_llm`` 里与 ``check_memory_pressure()`` 相关的分支：

- 有 GPU / 无 GPU 两种压力告警文案，最终都阻断加载；
- ``skip_memory_check_on_llm_load`` **当前不生效**的契约（见该用例 docstring）。

约束与同族文件一致：纯 mock，``check_memory_pressure`` patch 被测模块自身，
设置读取 patch 源模块 ``config.integrated_config.get_settings``。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import core.services.scheduler.model.llm_model_manager as llmm
from core.services.scheduler.model.llm_model_manager import LLMModelManager
from core.services.scheduler.utils.resource_utils import MemoryPressureResult


class _FakeLlama:
    """假 Llama：记录构造 kwargs 即可（本文件只需它「存在」以便走到内存检查）。"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _mem(percent=10.0, is_pressure=False, threshold=97.0, has_gpu=False):
    return MemoryPressureResult(
        percent=percent, is_pressure=is_pressure, threshold=threshold, has_gpu=has_gpu
    )


def _settings(**over):
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


def _patch_env(monkeypatch, *, mem, settings=None):
    """安装最小 patch：Llama / 内存检查 / 设置 / 资源管理器。"""
    monkeypatch.setattr(llmm, "_patch_llama_cpp_internals", lambda: None)
    # 不能 patch 成 None：Llama 缺失会在更前面就返回，走不到内存压力分支
    monkeypatch.setattr(llmm, "Llama", _FakeLlama)
    monkeypatch.setattr(llmm, "check_memory_pressure", lambda: mem)
    if settings is not None:
        monkeypatch.setattr(
            "config.integrated_config.get_settings", lambda: settings
        )

    class _RM:
        def mark_model_loaded(self, name, loaded):
            pass

    monkeypatch.setattr(
        "core.resource_manager.get_resource_manager", lambda: _RM()
    )


def test_setup_memory_pressure_with_gpu_blocks(manager, monkeypatch, gguf):
    """内存压力 + 有 GPU：先告警再阻断加载。"""
    _patch_env(
        monkeypatch,
        mem=_mem(percent=99.0, is_pressure=True, threshold=97.0, has_gpu=True),
        settings=_settings(),
    )
    assert manager.setup_python_llm({"model_path": gguf}) is None
    assert manager.llm is None
    assert "内存占用过高" in manager._last_llm_load_error


def test_setup_memory_pressure_without_gpu_blocks(manager, monkeypatch, gguf):
    """内存压力 + 无 GPU：告警文案不同，同样阻断。"""
    _patch_env(
        monkeypatch,
        mem=_mem(percent=99.0, is_pressure=True, threshold=97.0, has_gpu=False),
        settings=_settings(),
    )
    assert manager.setup_python_llm({"model_path": gguf}) is None
    assert "内存占用过高" in manager._last_llm_load_error


def test_skip_memory_check_config_is_ineffective(manager, monkeypatch, gguf):
    """契约测试：``skip_memory_check_on_llm_load=True`` 目前**不生效**。

    ``setup_python_llm`` 在第 256 行「``if mem_result.is_pressure:``」处
    **无条件** return None，而 ``skip_memory_check`` 要到第 298 行才被读取。
    因此只要处于内存压力，无论该配置如何都会被阻断；
    第 304-315 行那段「按 skip 标志决定保守参数 / 继续 GPU 推理」的分支
    也随之成为不可达代码。

    这条用例把「当前真实行为」钉死：将来若有人修好这个顺序（先读 skip 再判断），
    本用例会变红，提示需要同步处理那一段死代码。
    """
    _patch_env(
        monkeypatch,
        mem=_mem(percent=99.0, is_pressure=True, threshold=97.0, has_gpu=True),
        settings=_settings(skip_memory_check_on_llm_load=True),
    )
    assert manager.setup_python_llm({"model_path": gguf}) is None
    assert manager.llm is None
    # 命中的是「已阻止加载本地模型」，而不是下游那段 skip 分支
    assert "已阻止加载本地模型" in manager._last_llm_load_error
