#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``core/services/scheduler/model/llm_model_manager.py`` 核心生命周期专项测试。

覆盖范围：``__init__`` / ``set_config`` / ``get_config`` / ``reload_llm`` /
``unload_llm`` / ``_unload_llm_locked`` / ``_get_cuda_free_mb_sync`` / ``shutdown``。

约束：
- 纯 mock：不加载真实模型、不初始化 CUDA、不访问网络；
- ``torch`` 通过注入假模块控制；``get_resource_manager`` / 模块级工具函数按
  被测模块自身名字 patch；
- 不依赖真实时间流逝，不 sleep；executor 用同步替身，绝不真起线程；
- 文件 IO 一律落 tmp_path。
"""

from __future__ import annotations

import concurrent.futures
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

import core.services.scheduler.model.llm_model_manager as llmm
from core.services.scheduler.model.llm_model_manager import LLMModelManager


# --------------------------------------------------------------------------- #
# 通用替身
# --------------------------------------------------------------------------- #


class _InlineExecutor:
    """同步执行 ``submit`` 的替身 executor，避免真起线程。"""

    def __init__(self) -> None:
        self.submitted: list = []
        self.shutdown_calls: list = []

    def submit(self, fn, *args, **kwargs):
        self.submitted.append((fn, args, kwargs))
        fut: concurrent.futures.Future = concurrent.futures.Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001 - 替身需要透传异常
            fut.set_exception(exc)
        return fut

    def shutdown(self, wait=True):  # noqa: D401 - 对齐 Executor 接口
        self.shutdown_calls.append(wait)


class _BoomExecutor:
    """``shutdown`` 抛异常的替身 executor。"""

    def shutdown(self, wait=True):
        raise RuntimeError("shutdown boom")


@pytest.fixture()
def manager():
    """构造真实实例，测试结束后回收真实 executor（未 submit 过则不产生线程）。"""
    mgr = LLMModelManager()
    yield mgr
    ex = getattr(mgr, "_llm_executor", None)
    if ex is not None:
        ex.shutdown(wait=False)


def _fake_torch(available: bool, calls: list):
    """构造假的 torch 模块，记录 cuda 调用。"""
    cuda = SimpleNamespace(
        is_available=lambda: available,
        empty_cache=lambda: calls.append("empty_cache"),
        ipc_collect=lambda: calls.append("ipc_collect"),
    )
    mod = types.ModuleType("torch")
    mod.cuda = cuda
    return mod


def _fake_resource_manager(calls: list, *, boom: bool = False):
    """构造假的 get_resource_manager 工厂。"""
    if boom:
        def _factory():
            raise RuntimeError("rm boom")
        return _factory

    class _RM:
        def mark_model_loaded(self, name, loaded):
            calls.append((name, loaded))

    return lambda: _RM()


# --------------------------------------------------------------------------- #
# __init__ / set_config / get_config
# --------------------------------------------------------------------------- #


def test_init_sets_defaults(manager):
    """__init__ 应初始化全部默认属性并创建单线程 executor。"""
    assert manager.llm is None
    assert manager._gpu_config is None
    assert manager._python_force_cpu is False
    assert manager._prev_n_gpu_layers is None
    assert manager._prev_n_ctx is None
    assert manager._prev_n_batch is None
    assert manager._prev_offload_kqv is None
    assert manager._last_llm_use_mmap is None
    assert manager._last_llm_load_error is None
    assert manager._last_llm_load_ts == 0.0
    assert isinstance(manager._llm_executor, ThreadPoolExecutor)
    # LazyAsyncLock 在无事件循环时也能构造
    assert manager._llm_setup_lock is not None


def test_set_and_get_config(manager):
    """set_config 存入、get_config 原样返回同一对象。"""
    assert manager.get_config() is None
    cfg = {"model_path": "a.gguf"}
    manager.set_config(cfg)
    assert manager.get_config() is cfg


# --------------------------------------------------------------------------- #
# reload_llm
# --------------------------------------------------------------------------- #


async def test_reload_llm_no_config_returns_early(manager, monkeypatch):
    """无配置时应直接返回，且不触发 TTS 卸载。"""
    events: list = []

    async def _offload(name):
        events.append(name)

    monkeypatch.setattr(llmm, "offload_tts_services", _offload)
    await manager.reload_llm()
    assert events == []


async def test_reload_llm_loads_when_missing(manager, monkeypatch):
    """有配置且 llm 为空时：先卸载 TTS，再在线程里调用 setup_python_llm。"""
    manager.set_config({"model_path": "a.gguf"})
    events: list = []

    async def _offload(name):
        events.append(("offload", name))

    def _setup(cfg):
        events.append(("setup", cfg))
        return object()

    monkeypatch.setattr(llmm, "offload_tts_services", _offload)
    monkeypatch.setattr(manager, "setup_python_llm", _setup)
    await manager.reload_llm()
    assert events == [
        ("offload", "LLMModelManager"),
        ("setup", {"model_path": "a.gguf"}),
    ]


async def test_reload_llm_skips_when_already_loaded(manager, monkeypatch):
    """已有实例时不应重复加载。"""
    manager.set_config({"model_path": "a.gguf"})
    manager.llm = object()
    setup_calls: list = []

    async def _offload(name):
        return None

    monkeypatch.setattr(llmm, "offload_tts_services", _offload)
    monkeypatch.setattr(manager, "setup_python_llm", lambda cfg: setup_calls.append(cfg))
    await manager.reload_llm()
    assert setup_calls == []


# --------------------------------------------------------------------------- #
# unload_llm / _unload_llm_locked
# --------------------------------------------------------------------------- #


async def test_unload_llm_delegates_to_locked(manager, monkeypatch):
    """unload_llm 在加锁后委托给 _unload_llm_locked。"""
    calls: list = []

    async def _locked():
        calls.append(True)

    monkeypatch.setattr(manager, "_unload_llm_locked", _locked)
    await manager.unload_llm()
    assert calls == [True]


async def test_unload_locked_without_llm_returns_early(manager, monkeypatch):
    """llm 为空时直接返回，不提交卸载任务。"""
    ex = _InlineExecutor()
    monkeypatch.setattr(manager, "_llm_executor", ex)
    await manager._unload_llm_locked()
    assert ex.submitted == []
    assert manager.llm is None


async def test_unload_locked_closes_and_frees_cuda(manager, monkeypatch):
    """有实例且 CUDA 可用：close 被调用、显存被回收、资源管理器被标记。"""
    ex = _InlineExecutor()
    monkeypatch.setattr(manager, "_llm_executor", ex)
    closed: list = []

    class _LLM:
        def close(self):
            closed.append(True)

    manager.llm = _LLM()
    cuda_calls: list = []
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(True, cuda_calls))
    rm_calls: list = []
    monkeypatch.setattr(
        "core.resource_manager.get_resource_manager",
        _fake_resource_manager(rm_calls),
    )

    await manager._unload_llm_locked()

    assert closed == [True]
    assert manager.llm is None
    assert cuda_calls == ["empty_cache", "ipc_collect"]
    assert rm_calls == [("llm_engine", False)]
    assert len(ex.submitted) == 1


async def test_unload_locked_cuda_unavailable_skips_cache(manager, monkeypatch):
    """CUDA 不可用时不调用 empty_cache / ipc_collect。"""
    ex = _InlineExecutor()
    monkeypatch.setattr(manager, "_llm_executor", ex)
    manager.llm = object()
    cuda_calls: list = []
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(False, cuda_calls))
    monkeypatch.setattr(
        "core.resource_manager.get_resource_manager",
        _fake_resource_manager([]),
    )

    await manager._unload_llm_locked()
    assert manager.llm is None
    assert cuda_calls == []


async def test_unload_locked_torch_import_error_is_ignored(manager, monkeypatch):
    """torch 导入失败（sys.modules 置 None）时应静默跳过显存回收。"""
    ex = _InlineExecutor()
    monkeypatch.setattr(manager, "_llm_executor", ex)
    manager.llm = object()
    monkeypatch.setitem(sys.modules, "torch", None)
    rm_calls: list = []
    monkeypatch.setattr(
        "core.resource_manager.get_resource_manager",
        _fake_resource_manager(rm_calls),
    )

    await manager._unload_llm_locked()
    assert manager.llm is None
    assert rm_calls == [("llm_engine", False)]


async def test_unload_locked_llm_without_close(manager, monkeypatch):
    """实例没有 close 属性时跳过关闭，但仍置空引用。"""
    ex = _InlineExecutor()
    monkeypatch.setattr(manager, "_llm_executor", ex)
    manager.llm = SimpleNamespace()  # 无 close
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setattr(
        "core.resource_manager.get_resource_manager",
        _fake_resource_manager([]),
    )

    await manager._unload_llm_locked()
    assert manager.llm is None


async def test_unload_locked_close_raises_is_ignored(manager, monkeypatch):
    """close 抛异常时被吞掉，实例仍被置空。"""
    ex = _InlineExecutor()
    monkeypatch.setattr(manager, "_llm_executor", ex)

    class _BadLLM:
        def close(self):
            raise RuntimeError("close boom")

    manager.llm = _BadLLM()
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setattr(
        "core.resource_manager.get_resource_manager",
        _fake_resource_manager([]),
    )

    await manager._unload_llm_locked()
    assert manager.llm is None


async def test_unload_locked_resource_manager_error_is_ignored(manager, monkeypatch):
    """资源管理器不可用时静默忽略。"""
    ex = _InlineExecutor()
    monkeypatch.setattr(manager, "_llm_executor", ex)
    manager.llm = object()
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setattr(
        "core.resource_manager.get_resource_manager",
        _fake_resource_manager([], boom=True),
    )

    await manager._unload_llm_locked()
    assert manager.llm is None


# --------------------------------------------------------------------------- #
# _get_cuda_free_mb_sync / shutdown
# --------------------------------------------------------------------------- #


def test_get_cuda_free_mb_sync_delegates(manager, monkeypatch):
    """_get_cuda_free_mb_sync 应直接转发模块级 get_cuda_free_mb 的返回值。"""
    monkeypatch.setattr(llmm, "get_cuda_free_mb", lambda: 8192)
    assert manager._get_cuda_free_mb_sync() == 8192


def test_get_cuda_free_mb_sync_none(manager, monkeypatch):
    """底层返回 None 时同样透传 None。"""
    monkeypatch.setattr(llmm, "get_cuda_free_mb", lambda: None)
    assert manager._get_cuda_free_mb_sync() is None


def test_shutdown_closes_executor(manager, monkeypatch):
    """shutdown 调用 executor.shutdown(wait=False) 并置空引用。"""
    ex = _InlineExecutor()
    monkeypatch.setattr(manager, "_llm_executor", ex)
    manager.shutdown()
    assert ex.shutdown_calls == [False]
    assert manager._llm_executor is None


def test_shutdown_is_idempotent(manager, monkeypatch):
    """第二次 shutdown 因引用已空而成为 no-op。"""
    ex = _InlineExecutor()
    monkeypatch.setattr(manager, "_llm_executor", ex)
    manager.shutdown()
    manager.shutdown()
    assert ex.shutdown_calls == [False]


def test_shutdown_swallows_executor_error(manager, monkeypatch):
    """executor.shutdown 抛异常时应被吞掉，引用仍被置空。"""
    monkeypatch.setattr(manager, "_llm_executor", _BoomExecutor())
    manager.shutdown()
    assert manager._llm_executor is None
