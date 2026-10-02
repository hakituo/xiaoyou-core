#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``llm_model_manager.py`` 的 ``setup_python_llm`` 早退分支与配置装配专项测试。

本文件按关注点拆分：只放「早退分支」与「成功路径 / 配置装配」两部分。
内存压力分支见 ``test_llm_model_manager_pressure.py``；候选重试、
``_build_cpp_llm_config`` 与 ``_patch_llama_cpp_internals`` 见
``test_llm_model_manager_setup_retry.py``。

约束：
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
from types import SimpleNamespace

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


def _ok(index, kwargs):
    return _FakeLlama(**kwargs)


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
# setup_python_llm —— 早退分支
# --------------------------------------------------------------------------- #


def test_setup_returns_none_without_llama(manager, monkeypatch):
    """llama_cpp 未安装（Llama 为 None）时直接返回 None。"""
    monkeypatch.setattr(llmm, "Llama", None)
    assert manager.setup_python_llm({"model_path": "x.gguf"}) is None


def test_setup_empty_model_path_sets_error(manager, monkeypatch):
    """model_path 为空时记录错误并置空 llm。"""
    env = _patch_env(monkeypatch, mem=_mem())
    assert manager.setup_python_llm({}) is None
    assert manager.llm is None
    assert manager._last_llm_load_error == "本地模型路径为空"
    assert env["patch"] == ["patch"]
    assert env["rm"] == [("llm_engine", False)]


def test_setup_non_str_model_path_sets_error(manager, monkeypatch):
    """model_path 非字符串时同样判为无效。"""
    _patch_env(monkeypatch, mem=_mem())
    assert manager.setup_python_llm({"model_path": 123}) is None
    assert manager._last_llm_load_error == "本地模型路径为空"


def test_setup_nonexistent_path_sets_error(manager, monkeypatch):
    """文件不存在时记录错误。"""
    _patch_env(monkeypatch, mem=_mem())
    assert manager.setup_python_llm({"model_path": "C:/nope/none.gguf"}) is None
    assert manager.llm is None
    assert "不存在" in manager._last_llm_load_error


def test_setup_nonexistent_path_return_instance(manager, monkeypatch):
    """return_instance=True 时不应写 self.llm。"""
    _patch_env(monkeypatch, mem=_mem())
    out = manager.setup_python_llm(
        {"model_path": "C:/nope/none.gguf"}, return_instance=True
    )
    assert out is None
    assert manager.llm is None


def test_setup_bad_gguf_header(manager, monkeypatch, tmp_path):
    """GGUF 文件头非法时记录错误并置空 llm。"""
    p = tmp_path / "bad.gguf"
    p.write_bytes(b"XXXX" + b"\x00" * 8)
    _patch_env(monkeypatch, mem=_mem())
    assert manager.setup_python_llm({"model_path": str(p)}) is None
    assert manager.llm is None
    assert "GGUF" in manager._last_llm_load_error


def test_setup_gguf_read_error(manager, monkeypatch, tmp_path):
    """以目录冒充 .gguf 时读取抛错，被捕获为「读取本地模型文件失败」。"""
    d = tmp_path / "dir.gguf"
    d.mkdir()
    _patch_env(monkeypatch, mem=_mem())
    assert manager.setup_python_llm({"model_path": str(d)}) is None
    assert "读取本地模型文件失败" in manager._last_llm_load_error


# --------------------------------------------------------------------------- #
# setup_python_llm —— 成功加载与参数分支
# --------------------------------------------------------------------------- #


def test_setup_success_sets_llm_and_updates_config(manager, monkeypatch, gguf):
    """成功路径：返回实例、写入 self.llm、回写 gpu_config、标记资源已加载。"""
    llama_calls: list = []
    env = _patch_env(
        monkeypatch,
        mem=_mem(),
        settings=_settings(),
        llama=_make_llama(_ok, llama_calls),
    )
    manager.set_config({"model_path": gguf})
    inst = manager.setup_python_llm({"model_path": gguf})

    assert isinstance(inst, _FakeLlama)
    assert manager.llm is inst
    assert manager._gpu_config["max_context_size"] == 4096
    assert manager._last_llm_load_error is None
    assert env["rm"] == [("llm_engine", False), ("llm_engine", True)]
    assert llama_calls[0]["n_gpu_layers"] == -1


def test_setup_return_instance_skips_state_and_marking(manager, monkeypatch, gguf):
    """return_instance=True 时不写 self.llm、不标记资源。"""
    llama_calls: list = []
    env = _patch_env(
        monkeypatch,
        mem=_mem(),
        settings=_settings(),
        llama=_make_llama(_ok, llama_calls),
    )
    inst = manager.setup_python_llm({"model_path": gguf}, return_instance=True)
    assert isinstance(inst, _FakeLlama)
    assert manager.llm is None
    assert env["rm"] == []


def test_setup_high_percent_clamps_batch(manager, monkeypatch, gguf):
    """非压力但占用 >=90% 时把 n_batch 收敛到 256。"""
    llama_calls: list = []
    _patch_env(
        monkeypatch,
        mem=_mem(percent=95.0, is_pressure=False, threshold=97.0, has_gpu=False),
        settings=_settings(),
        llama=_make_llama(_ok, llama_calls),
    )
    inst = manager.setup_python_llm({"model_path": gguf, "max_batch_size": 4096})
    assert inst is not None
    assert llama_calls[0]["n_batch"] == 256


def test_setup_force_cpu_inference_from_settings(manager, monkeypatch, gguf):
    """settings.model.force_cpu_inference=True 时 n_gpu_layers 归零。"""
    llama_calls: list = []
    _patch_env(
        monkeypatch,
        mem=_mem(),
        settings=_settings(force_cpu_inference=True),
        llama=_make_llama(_ok, llama_calls),
    )
    manager.setup_python_llm({"model_path": gguf, "n_gpu_layers": 33})
    assert llama_calls[0]["n_gpu_layers"] == 0


def test_setup_python_force_cpu_flag(manager, monkeypatch, gguf):
    """self._python_force_cpu=True 时 n_gpu_layers 归零。"""
    llama_calls: list = []
    _patch_env(
        monkeypatch, mem=_mem(), settings=_settings(), llama=_make_llama(_ok, llama_calls)
    )
    manager._python_force_cpu = True
    manager.setup_python_llm({"model_path": gguf, "n_gpu_layers": 12})
    assert llama_calls[0]["n_gpu_layers"] == 0


def test_setup_config_force_cpu_flag(manager, monkeypatch, gguf):
    """config.force_cpu=True 时 n_gpu_layers 归零。"""
    llama_calls: list = []
    _patch_env(
        monkeypatch, mem=_mem(), settings=_settings(), llama=_make_llama(_ok, llama_calls)
    )
    manager.setup_python_llm({"model_path": gguf, "force_cpu": True, "n_gpu_layers": 12})
    assert llama_calls[0]["n_gpu_layers"] == 0


def test_setup_resource_manager_unavailable_is_ignored(manager, monkeypatch, gguf):
    """资源管理器前后两次标记都抛错时静默忽略，仍能成功加载。"""
    llama_calls: list = []
    _patch_env(
        monkeypatch,
        mem=_mem(),
        settings=_settings(),
        llama=_make_llama(_ok, llama_calls),
        rm_boom=True,
    )
    inst = manager.setup_python_llm({"model_path": gguf})
    assert isinstance(inst, _FakeLlama)
    assert manager.llm is inst


def test_setup_settings_unavailable_uses_fallbacks(manager, monkeypatch, gguf):
    """get_settings 全程抛错时，各 except 分支回退到 config 默认值。"""
    llama_calls: list = []
    _patch_env(
        monkeypatch,
        mem=_mem(),
        settings_raises=True,
        llama=_make_llama(_ok, llama_calls),
    )
    inst = manager.setup_python_llm({"model_path": gguf, "n_gpu_layers": 0})
    assert inst is not None
    assert llama_calls[0]["offload_kqv"] is True


def test_setup_settings_model_none(manager, monkeypatch, gguf):
    """settings.model 为 None 时跳过动态 KV 读取，仍能加载。"""
    llama_calls: list = []
    _patch_env(
        monkeypatch,
        mem=_mem(),
        settings=SimpleNamespace(model=None),
        llama=_make_llama(_ok, llama_calls),
    )
    assert manager.setup_python_llm({"model_path": gguf}) is not None


def test_setup_use_mmap_config_error_falls_back(manager, monkeypatch, gguf):
    """config.get('use_mmap') 抛错时回退为 False。"""

    class _ExplodingConfig(dict):
        def get(self, key, default=None):
            if key == "use_mmap":
                raise RuntimeError("use_mmap boom")
            return super().get(key, default)

    llama_calls: list = []
    _patch_env(
        monkeypatch, mem=_mem(), settings=_settings(), llama=_make_llama(_ok, llama_calls)
    )
    inst = manager.setup_python_llm(_ExplodingConfig({"model_path": gguf}))
    assert inst is not None
    assert llama_calls[0]["use_mmap"] is False


def test_setup_ram_mirror_offload_forces_no_mmap(manager, monkeypatch, gguf):
    """ram_mirror_offload=True 时传给 resolve_use_mmap 的第二参为真。"""
    seen: list = []
    monkeypatch.setattr(
        llmm, "resolve_use_mmap", lambda u, r, n: (seen.append((u, r, n)) or False)
    )
    llama_calls: list = []
    _patch_env(
        monkeypatch,
        mem=_mem(),
        settings=_settings(ram_mirror_offload=True),
        llama=_make_llama(_ok, llama_calls),
    )
    manager.setup_python_llm({"model_path": gguf})
    assert seen[0][1] is True
    assert llama_calls[0]["use_mmap"] is False


def test_setup_insufficient_vram_disables_offload_kqv(manager, monkeypatch, gguf):
    """显存余量不足时自动把 KV Cache 放回 CPU（offload_kqv=False）。"""
    monkeypatch.setattr(llmm, "get_cuda_free_mb", lambda: 100)
    llama_calls: list = []
    _patch_env(
        monkeypatch,
        mem=_mem(has_gpu=True),
        settings=_settings(vram_reserve_mb=2000, tts_gpu_min_free_mb=1200),
        llama=_make_llama(_ok, llama_calls),
    )
    manager.setup_python_llm(
        {"model_path": gguf, "n_gpu_layers": 20, "offload_kqv": True}
    )
    assert llama_calls[0]["offload_kqv"] is False


def test_setup_vram_check_skipped_when_free_is_none(manager, monkeypatch, gguf):
    """get_cuda_free_mb 返回 None（非 int）时跳过 KV 卸载判定。"""
    monkeypatch.setattr(llmm, "get_cuda_free_mb", lambda: None)
    llama_calls: list = []
    _patch_env(
        monkeypatch,
        mem=_mem(has_gpu=True),
        settings=_settings(vram_reserve_mb=9999),
        llama=_make_llama(_ok, llama_calls),
    )
    manager.setup_python_llm({"model_path": gguf, "n_gpu_layers": 20})
    assert llama_calls[0]["offload_kqv"] is True


def test_setup_flash_attn_and_offload_disabled(manager, monkeypatch, gguf):
    """flash_attn / offload_kqv 显式关闭时透传 False。"""
    llama_calls: list = []
    _patch_env(
        monkeypatch, mem=_mem(), settings=_settings(), llama=_make_llama(_ok, llama_calls)
    )
    manager.setup_python_llm(
        {"model_path": gguf, "flash_attn": False, "offload_kqv": False}
    )
    assert llama_calls[0]["flash_attn"] is False
    assert llama_calls[0]["offload_kqv"] is False


def test_setup_flash_attn_forced_off_on_cpu(manager, monkeypatch, gguf):
    """CPU 推理（force_cpu）时即使 flash_attn=True 也应为 False。"""
    llama_calls: list = []
    _patch_env(
        monkeypatch, mem=_mem(), settings=_settings(), llama=_make_llama(_ok, llama_calls)
    )
    manager.setup_python_llm({"model_path": gguf, "force_cpu": True, "flash_attn": True})
    assert llama_calls[0]["flash_attn"] is False


def test_setup_n_ubatch_from_config(manager, monkeypatch, gguf):
    """n_ubatch 取 config 值并与 n_batch 取小。"""
    llama_calls: list = []
    _patch_env(
        monkeypatch, mem=_mem(), settings=_settings(), llama=_make_llama(_ok, llama_calls)
    )
    manager.setup_python_llm({"model_path": gguf, "n_ubatch": 64, "max_batch_size": 512})
    assert llama_calls[0]["n_ubatch"] == 64


def test_setup_zero_gpu_layers_nondict_config(manager, monkeypatch, gguf):
    """CPU 推理且 _gpu_config 非 dict：不写 prev、不回写配置。"""
    llama_calls: list = []
    _patch_env(
        monkeypatch, mem=_mem(), settings=_settings(), llama=_make_llama(_ok, llama_calls)
    )
    manager._gpu_config = None
    inst = manager.setup_python_llm({"model_path": gguf, "force_cpu": True})
    assert inst is not None
    assert llama_calls[0]["n_gpu_layers"] == 0
    assert manager._prev_n_gpu_layers is None
    assert manager._gpu_config is None

