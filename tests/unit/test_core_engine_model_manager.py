#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``core/core_engine/model_manager.py`` 专项单元测试。

目标：用**纯 mock / 替身**覆盖 ModelManager 与 ModelInfo 的主流程和主要分支。

约束：
- 绝不加载真实模型、绝不初始化 CUDA / 显存、绝不访问网络；
- 需要 transformers / diffusers 的地方全部注入假的 ``sys.modules`` 模块；
- 不依赖真实流逝时间，不 ``sleep``，随机/时钟相关的断言一律只看「是否被赋值」。

模块是单例（``ModelManager._instance`` + ``_initialized``），用例通过
``_bare_manager()`` 绕过 ``__init__`` 直接构造裸实例，并在 autouse fixture
里前后重置单例状态，避免跨用例共享可变全局状态。
"""

from __future__ import annotations

import os
import pathlib
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.core_engine.model_manager as mm
from core.contracts import DeviceType, ModelRuntimeState
from core.core_engine.model_manager import ModelInfo, ModelManager


# --------------------------------------------------------------------------- #
# 通用替身与工具
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _isolate_singleton():
    """每个用例前后都重置 ModelManager 单例，避免跨用例污染。"""
    ModelManager._instance = None
    ModelManager._initialized = False
    mm._model_manager = None
    yield
    ModelManager._instance = None
    ModelManager._initialized = False
    mm._model_manager = None


def _bare_manager() -> ModelManager:
    """构造一个不经 ``__init__`` 的 ModelManager 裸实例。

    跳过 ``__init__`` 可以避免真实硬件探测与模型目录扫描的副作用，
    同时保证实例属性与生产代码一致。
    """
    ModelManager._instance = None
    ModelManager._initialized = False
    mgr = ModelManager.__new__(ModelManager)
    mgr._models = {}
    mgr._registered_models = {}
    mgr._processors = {}
    mgr._model_locks = {}
    mgr._global_lock = threading.RLock()
    mgr._max_models = 5
    mgr._memory_threshold = 0.7
    mgr._gpu_memory_threshold = 0.8
    mgr._pinned_models = set()
    mgr.system_resources = {}
    return mgr


def _fake_torch(available: bool = False, props=None, props_error: Exception = None):
    """构造假的 torch 替身，``cuda.is_available`` 完全由参数控制（不碰真实 CUDA）。"""
    calls = {"empty_cache": 0}

    def _get_props(index):
        if props_error is not None:
            raise props_error
        return props

    def _empty_cache():
        calls["empty_cache"] += 1

    cuda = SimpleNamespace(
        is_available=lambda: available,
        get_device_properties=_get_props,
        empty_cache=_empty_cache,
    )
    return SimpleNamespace(cuda=cuda, float16="float16", calls=calls)


def _fake_psutil():
    """构造假的 psutil 替身。"""
    memory = SimpleNamespace(
        total=16 * 1024**3, available=8 * 1024**3, percent=50.0
    )
    return SimpleNamespace(
        cpu_percent=lambda interval=None: 12.5,
        virtual_memory=lambda: memory,
        cpu_count=lambda: 8,
    )


def _fake_os(exists=(), isfile=(), abspath=None):
    """构造一个只覆盖 model_manager 所需接口的假 ``os`` 模块。

    ``exists`` / ``isfile`` 既可以传集合（成员判定），也可以传可调用对象。
    """
    exists_fn = exists if callable(exists) else (lambda p, _s=set(exists): p in _s)
    isfile_fn = isfile if callable(isfile) else (lambda p, _s=set(isfile): p in _s)
    return SimpleNamespace(
        path=SimpleNamespace(
            dirname=os.path.dirname,
            join=os.path.join,
            abspath=abspath or os.path.abspath,
            exists=exists_fn,
            isfile=isfile_fn,
            splitext=os.path.splitext,
            basename=os.path.basename,
        ),
        environ=os.environ,
        listdir=os.listdir,
    )


class _FakeFile:
    """假的 ``open`` 返回值：支持 with 语句与 ``read``。"""

    def __init__(self, content: str, error: Exception = None):
        self._content = content
        self._error = error

    def __call__(self, *args, **kwargs):
        if self._error is not None:
            raise self._error
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._content


class _Movable:
    """带 ``to()`` 的假模型对象，用于 offload / 移回 CPU 流程。"""

    def __init__(self, fail: bool = False):
        self.device = None
        self.fail = fail

    def to(self, device):
        if self.fail:
            raise RuntimeError("cannot move")
        self.device = device
        return self


class _OffloadPipe:
    """支持 ``enable_model_cpu_offload`` 的假 pipeline。"""

    def __init__(self, mode: str = "model"):
        self.mode = mode
        self.calls = []

    def enable_model_cpu_offload(self):
        if self.mode == "raise":
            raise RuntimeError("offload boom")
        self.calls.append("model")

    def enable_sequential_cpu_offload(self):
        self.calls.append("sequential")


class _SeqOnlyPipe:
    """只支持 ``enable_sequential_cpu_offload`` 的假 pipeline。"""

    def __init__(self):
        self.calls = []

    def enable_sequential_cpu_offload(self):
        self.calls.append("sequential")


def _fake_diffusers(with_single_file: bool = True, pipe=None):
    """构造假 diffusers 模块；返回 ``(module, record)``。"""
    record = {"calls": []}

    def _make_loader(kind):
        def _loader(path, **kwargs):
            record["calls"].append((kind, path, kwargs))
            if pipe is not None:
                return pipe
            return {"kind": kind, "path": path, "kwargs": kwargs}

        return staticmethod(_loader)

    attrs = {"from_pretrained": _make_loader("from_pretrained")}
    if with_single_file:
        attrs["from_single_file"] = _make_loader("from_single_file")
    else:
        attrs["from_ckpt"] = _make_loader("from_ckpt")

    pipeline_cls = type("StableDiffusionPipeline", (), attrs)
    module = types.ModuleType("diffusers")
    module.StableDiffusionPipeline = pipeline_cls
    return module, record


def _install_fake_transformers(monkeypatch, model_cls, tokenizer_cls):
    """把假的 transformers 模块树塞进 ``sys.modules``，避免真实加载。"""
    tf = types.ModuleType("transformers")
    tf.AutoModelForCausalLM = model_cls
    tf.AutoModelForVision2Seq = model_cls
    monkeypatch.setitem(sys.modules, "transformers", tf)
    monkeypatch.setitem(
        sys.modules, "transformers.models", types.ModuleType("transformers.models")
    )
    monkeypatch.setitem(
        sys.modules,
        "transformers.models.auto",
        types.ModuleType("transformers.models.auto"),
    )
    tok_mod = types.ModuleType("transformers.models.auto.tokenization_auto")
    tok_mod.AutoTokenizer = tokenizer_cls
    monkeypatch.setitem(
        sys.modules, "transformers.models.auto.tokenization_auto", tok_mod
    )


def _models_dir() -> str:
    """按生产代码的算法推导出仓库下的 models 目录。"""
    root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(mm.__file__)))
    )
    return os.path.join(root, "models")


_CLOUD_ENV_KEYS = (
    "DEEPSEEK_API_KEY",
    "SILICONFLOW_API_KEY",
    "ARK_API_KEY",
    "MINIMAX_API_KEY",
    "AVELINE_API_KEY",
    "AVELINE_MODEL",
    "XIAOYOU_TEXT_MODEL_PATH",
)


def _clear_cloud_env(monkeypatch):
    """清空云端注册相关环境变量，保证用例结果与宿主环境无关。"""
    for name in _CLOUD_ENV_KEYS:
        monkeypatch.delenv(name, raising=False)


def _cloud_settings(
    cloud_provider_keys=None,
    registered_cloud_providers=None,
    registered_cloud_models=None,
):
    """构造假的 settings 对象（只需 ``settings.model`` 这几个字段）。"""
    model = SimpleNamespace(
        cloud_provider_keys=cloud_provider_keys or {},
        registered_cloud_providers=registered_cloud_providers,
        registered_cloud_models=registered_cloud_models,
    )
    return SimpleNamespace(model=model)


def _patch_settings(monkeypatch, settings=None, raises: bool = False):
    """替换 ``config.integrated_config.get_settings``。"""
    import config.integrated_config as integrated_config

    def _get_settings():
        if raises:
            raise RuntimeError("settings boom")
        return settings

    monkeypatch.setattr(integrated_config, "get_settings", _get_settings)


# --------------------------------------------------------------------------- #
# ModelInfo
# --------------------------------------------------------------------------- #


def test_model_info_runtime_state_transitions():
    """runtime_state 应随 is_loaded / is_offloaded 组合变化。"""
    info = ModelInfo("m", "llm", "/m")
    assert info.runtime_state is ModelRuntimeState.UNLOADED
    assert info.is_loaded is False and info.is_offloaded is False

    info.is_loaded = True
    assert info.runtime_state is ModelRuntimeState.LOADED

    info.is_offloaded = True
    assert info.runtime_state is ModelRuntimeState.OFFLOADED


def test_model_info_device_type_mapping():
    """device_type 应识别 gpu/cuda/cpu，其余归为 UNKNOWN。"""
    info = ModelInfo("m", "llm", "/m")
    assert info.device_type is DeviceType.UNKNOWN  # device 为 None

    for raw in ("gpu", "GPU", " cuda "):
        info.device = raw
        assert info.device_type is DeviceType.GPU, raw

    info.device = "CPU"
    assert info.device_type is DeviceType.CPU

    info.device = "tpu"
    assert info.device_type is DeviceType.UNKNOWN


def test_model_info_to_dict_and_contract_dict():
    """两个序列化方法应输出契约字段，并正确处理空时间戳。"""
    info = ModelInfo("m", "llm", "/m")
    info.is_loaded = True
    info.device = "cuda"
    info.quantized = True
    info.load_time = 1.5
    info.last_used_time = 2.5

    data = info.to_dict()
    assert data["id"] == "m"
    assert data["name"] == "m"
    assert data["type"] == "llm"
    assert data["path"] == "/m"
    assert data["state"] == ModelRuntimeState.LOADED.value
    assert data["device"] == DeviceType.GPU.value
    assert data["is_loaded"] is True
    assert data["quantized"] is True
    assert data["load_time"] == 1.5
    assert data["last_used_time"] == 2.5

    contract = info.to_contract_dict()
    assert contract["model_id"] == "m"
    assert contract["model_type"] == "llm"
    assert contract["model_path"] == "/m"
    assert contract["state"] == ModelRuntimeState.LOADED.value
    assert contract["device"] == DeviceType.GPU.value
    assert contract["quantized"] is True
    assert contract["load_time"] == 1.5
    assert contract["last_used_time"] == 2.5

    # 空时间戳 → None；quantized 强制为 bool
    info.load_time = None
    info.last_used_time = None
    info.quantized = "yes"
    contract = info.to_contract_dict()
    assert contract["load_time"] is None
    assert contract["last_used_time"] is None
    assert contract["quantized"] is True


# --------------------------------------------------------------------------- #
# 单例 / 初始化
# --------------------------------------------------------------------------- #


def test_singleton_new_returns_same_instance():
    """__new__ 必须始终返回同一个实例。"""
    first = ModelManager.__new__(ModelManager)
    second = ModelManager.__new__(ModelManager)
    assert first is second


def test_init_sets_attributes_from_env_and_scans_once(monkeypatch):
    """__init__ 应从环境变量读取阈值，并且只扫描一次模型目录。"""
    monkeypatch.setenv("MAX_MODELS", "3")
    monkeypatch.setenv("MODEL_MEMORY_THRESHOLD", "0.55")
    monkeypatch.setenv("GPU_MEMORY_THRESHOLD", "0.9")
    monkeypatch.setattr(
        ModelManager, "_detect_hardware_resources", lambda self: {"cpu_count": 8}
    )
    scans = []
    monkeypatch.setattr(ModelManager, "scan_models", lambda self: scans.append(1))

    mgr = ModelManager()

    assert mgr._max_models == 3
    assert mgr._memory_threshold == 0.55
    assert mgr._gpu_memory_threshold == 0.9
    assert mgr.system_resources == {"cpu_count": 8}
    assert mgr._models == {}
    assert mgr._pinned_models == set()
    assert scans == [1]

    # 第二次构造应命中 _initialized 短路，不再重复初始化
    again = ModelManager()
    assert again is mgr
    assert scans == [1]


def test_get_model_manager_caches_singleton(monkeypatch):
    """get_model_manager 只应构造一次 ModelManager。"""
    created = []

    class _FakeManager:
        def __init__(self):
            created.append(self)

    monkeypatch.setattr(mm, "ModelManager", _FakeManager)
    monkeypatch.setattr(mm, "_model_manager", None)

    first = mm.get_model_manager()
    second = mm.get_model_manager()

    assert first is second
    assert len(created) == 1


def test_module_import_fallbacks_when_optional_deps_missing(monkeypatch):
    """torch / watchdog 缺失时模块应降级为 None / object（导入期兜底分支）。"""
    filename = os.path.abspath(mm.__file__)
    code = compile(Path(filename).read_text(encoding="utf-8"), filename, "exec")
    namespace = {"__name__": "core.core_engine.model_manager_probe", "__file__": filename}

    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "torch", None)
        patch.setitem(sys.modules, "watchdog.observers", None)
        patch.setitem(sys.modules, "watchdog.events", None)
        exec(code, namespace)

    assert namespace["torch"] is None
    assert namespace["_Observer"] is None
    assert namespace["_FSEH"] is object
    # 真实模块的 torch 未被破坏
    assert mm.torch is not None


# --------------------------------------------------------------------------- #
# 模型扫描
# --------------------------------------------------------------------------- #


def test_scan_models_skips_missing_models_dir(monkeypatch):
    """models 目录不存在时跳过 LLM/图像扫描，但仍注册云端客户端。"""
    mgr = _bare_manager()
    monkeypatch.setattr(mm, "os", _fake_os(exists=()))
    monkeypatch.delenv("XIAOYOU_TEXT_MODEL_PATH", raising=False)

    called = []
    monkeypatch.setattr(mgr, "_scan_llm_models", lambda d: called.append("llm"))
    monkeypatch.setattr(mgr, "_scan_image_models", lambda d: called.append("image"))
    monkeypatch.setattr(
        mgr, "_register_cloud_clients_from_llm_module", lambda: called.append("cloud")
    )

    mgr.scan_models()

    assert called == ["cloud"]
    assert mgr._models == {}


def test_scan_models_registers_env_model_path(monkeypatch):
    """XIAOYOU_TEXT_MODEL_PATH 指向文件/目录时应注册对应模型，并去重。"""
    models_dir = _models_dir()
    file_path = os.path.join(models_dir, "env-model.gguf")
    dir_path = os.path.join(models_dir, "env-dir")

    mgr = _bare_manager()
    monkeypatch.setattr(
        mm, "os", _fake_os(exists=[models_dir, file_path], isfile=[file_path])
    )
    scanned = []
    monkeypatch.setattr(mgr, "_scan_llm_models", lambda d: scanned.append(("llm", d)))
    monkeypatch.setattr(
        mgr, "_scan_image_models", lambda d: scanned.append(("image", d))
    )
    monkeypatch.setattr(
        mgr,
        "_register_cloud_clients_from_llm_module",
        lambda: scanned.append(("cloud", None)),
    )
    monkeypatch.setenv("XIAOYOU_TEXT_MODEL_PATH", file_path)

    mgr.scan_models()

    assert scanned == [("llm", models_dir), ("image", models_dir), ("cloud", None)]
    assert set(mgr._models) == {"env-model"}
    assert mgr._models["env-model"].model_path == file_path
    assert mgr._models["env-model"].quantized is True  # .gguf → 量化

    # 目录形态：用目录名做模型名；已注册时不覆盖
    mgr2 = _bare_manager()
    monkeypatch.setattr(mm, "os", _fake_os(exists=[models_dir, dir_path], isfile=()))
    monkeypatch.setattr(mgr2, "_scan_llm_models", lambda d: None)
    monkeypatch.setattr(mgr2, "_scan_image_models", lambda d: None)
    monkeypatch.setattr(mgr2, "_register_cloud_clients_from_llm_module", lambda: None)
    mgr2.register_model("env-dir", "llm", "pre-existing")
    monkeypatch.setenv("XIAOYOU_TEXT_MODEL_PATH", dir_path)

    mgr2.scan_models()

    assert mgr2._models["env-dir"].model_path == "pre-existing"


def test_scan_models_swallows_errors(monkeypatch):
    """扫描过程中的异常应被吞掉，不能冒泡。"""
    mgr = _bare_manager()

    def _boom(*args, **kwargs):
        raise OSError("no fs")

    monkeypatch.setattr(mm, "os", _fake_os(abspath=_boom))

    mgr.scan_models()  # 不应抛出

    assert mgr._models == {}


def test_scan_llm_models_registers_gguf_and_config_dirs(tmp_path):
    """LLM 扫描应登记 .gguf 文件与含 config.json 的目录，并跳过 mmproj。"""
    mgr = _bare_manager()
    llm_dir = tmp_path / "llm"
    llm_dir.mkdir()
    (llm_dir / "model-a.gguf").write_bytes(b"x")
    (llm_dir / "mmproj-vision.gguf").write_bytes(b"x")
    (llm_dir / "notes.txt").write_text("x", encoding="utf-8")
    nested = llm_dir / "nested-model"
    nested.mkdir()
    (nested / "config.json").write_text("{}", encoding="utf-8")
    (llm_dir / "empty-dir").mkdir()

    mgr._scan_llm_models(str(tmp_path))

    assert set(mgr._models) == {"model-a", "nested-model"}
    assert mgr._models["model-a"].model_type == "llm"
    assert mgr._models["model-a"].quantized is True
    assert mgr._models["nested-model"].quantized is False
    assert mgr._models["nested-model"].model_path == str(nested)

    # 重复扫描不应重复登记/覆盖
    mgr._scan_llm_models(str(tmp_path))
    assert set(mgr._models) == {"model-a", "nested-model"}

    # 目录不存在时直接返回
    empty_mgr = _bare_manager()
    empty_mgr._scan_llm_models(str(tmp_path / "missing"))
    assert empty_mgr._models == {}


def test_scan_image_models_registers_checkpoints_and_loras(tmp_path):
    """图像扫描应登记 check_point 与 lora，并跳过不支持的扩展名。"""
    mgr = _bare_manager()
    img_dir = tmp_path / "image"
    ckpt_dir = img_dir / "check_point"
    ckpt_dir.mkdir(parents=True)
    (ckpt_dir / "sd-base.safetensors").write_bytes(b"x")
    (ckpt_dir / "legacy.ckpt").write_bytes(b"x")
    (ckpt_dir / "ignore.bin").write_bytes(b"x")
    lora_dir = img_dir / "lora"
    lora_dir.mkdir()
    (lora_dir / "style.safetensors").write_bytes(b"x")
    (lora_dir / "raw.pt").write_bytes(b"x")

    mgr.register_model("sd-base", "image_gen", "pre-existing")
    mgr._scan_image_models(str(tmp_path))

    assert set(mgr._models) == {"sd-base", "legacy", "style"}
    assert mgr._models["sd-base"].model_path == "pre-existing"  # 去重
    assert mgr._models["legacy"].model_type == "image_gen"
    assert mgr._models["style"].model_type == "lora"

    # 没有任何图像目录时直接返回
    empty_mgr = _bare_manager()
    empty_mgr._scan_image_models(str(tmp_path / "nothing"))
    assert empty_mgr._models == {}


# --------------------------------------------------------------------------- #
# 云端模型注册
# --------------------------------------------------------------------------- #


def test_register_cloud_clients_legacy_env(monkeypatch):
    """传统环境变量方式应注册全部候选，并生成 cloud:provider:model 路径。"""
    mgr = _bare_manager()
    _clear_cloud_env(monkeypatch)
    for name in (
        "DEEPSEEK_API_KEY",
        "SILICONFLOW_API_KEY",
        "ARK_API_KEY",
        "AVELINE_API_KEY",
        "MINIMAX_API_KEY",
    ):
        monkeypatch.setenv(name, "key")
    monkeypatch.setenv("AVELINE_MODEL", " av1 , av2 ,")
    monkeypatch.setattr(mm, "is_debug_enabled", lambda module: True)
    _patch_settings(monkeypatch, _cloud_settings())

    mgr._register_cloud_clients_from_llm_module()

    expected = {
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "Kimi-K2.6",
        "DeepSeek-V3.2(sf)",
        "MiniMax-M2.5(sf)",
        "Qwen3-VL-32B",
        "Doubao-Seed-2.0",
        "av1",
        "av2",
        "MiniMax-M2.5",
        "MiniMax-M2-her",
    }
    assert set(mgr._models) == expected
    assert mgr._models["deepseek-v4-flash"].model_path == (
        "cloud:deepseek:deepseek-v4-flash"
    )
    assert mgr._models["Kimi-K2.6"].model_path == (
        "cloud:siliconflow:Pro/moonshotai/Kimi-K2.6"
    )
    assert mgr._models["MiniMax-M2.5"].model_path == "cloud:minimax:MiniMax-M2.5"
    assert all(info.model_type == "llm" for info in mgr._models.values())


def test_register_cloud_clients_respects_provider_and_model_whitelist(monkeypatch):
    """供应商白名单过滤整家；型号白名单只放行列表内型号。"""
    mgr = _bare_manager()
    _clear_cloud_env(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "key")
    monkeypatch.setenv("MINIMAX_API_KEY", "key")
    monkeypatch.setattr(mm, "is_debug_enabled", lambda module: True)
    _patch_settings(
        monkeypatch,
        _cloud_settings(
            registered_cloud_providers=[" DeepSeek ", "", "minimax"],
            registered_cloud_models={"deepseek": ["deepseek-v4-pro"]},
        ),
    )

    mgr._register_cloud_clients_from_llm_module()

    # siliconflow 整家被过滤；deepseek 只留白名单型号；
    # minimax 未配置型号白名单 → 放行全部型号
    assert set(mgr._models) == {"deepseek-v4-pro", "MiniMax-M2.5", "MiniMax-M2-her"}


def test_register_cloud_clients_ignores_invalid_model_whitelist(monkeypatch):
    """registered_cloud_models 非 dict 或为空时不应生效。"""
    mgr = _bare_manager()
    _clear_cloud_env(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key")
    monkeypatch.setattr(mm, "is_debug_enabled", lambda module: False)
    _patch_settings(
        monkeypatch,
        _cloud_settings(registered_cloud_models=["deepseek-v4-pro"]),
    )

    mgr._register_cloud_clients_from_llm_module()

    assert set(mgr._models) == {"deepseek-v4-flash", "deepseek-v4-pro"}


def test_register_cloud_clients_multi_key_dedupe_and_paths(monkeypatch):
    """多 API key 方式：按 key 别名生成显示名与路径，并对候选去重。"""
    mgr = _bare_manager()
    _clear_cloud_env(monkeypatch)
    mgr.register_model("shared-model", "llm", "cloud:deepseek:shared-model")
    # debug 打开：同时覆盖「重复候选跳过」与「发现多 API Key 供应商」的日志分支
    monkeypatch.setattr(mm, "is_debug_enabled", lambda module: True)
    _patch_settings(
        monkeypatch,
        _cloud_settings(
            cloud_provider_keys={
                "siliconflow": {
                    "default": SimpleNamespace(models=["shared-model", "only-default"]),
                    "key2": SimpleNamespace(models=["shared-model"]),
                }
            }
        ),
    )

    mgr._register_cloud_clients_from_llm_module()

    # 已存在同名模型 → 候选被去重，原注册不被覆盖
    assert mgr._models["shared-model"].model_path == "cloud:deepseek:shared-model"
    # default 别名不加后缀，路径为 cloud:provider:model
    assert mgr._models["only-default"].model_path == (
        "cloud:siliconflow:only-default"
    )
    # 非 default 别名加后缀，路径为 cloud:provider:alias:model
    assert mgr._models["shared-model (key2)"].model_path == (
        "cloud:siliconflow:key2:shared-model"
    )


def test_register_cloud_clients_skips_model_registered_concurrently(monkeypatch):
    """模拟注册期间模型被其他线程写入 _models 的竞态：应跳过而非覆盖。"""
    mgr = _bare_manager()
    _clear_cloud_env(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key")
    monkeypatch.setattr(mm, "is_debug_enabled", lambda module: True)
    _patch_settings(monkeypatch, _cloud_settings())

    original_register = mgr.register_model

    def _racy_register(model_name, model_type, model_path):
        original_register(model_name, model_type, model_path)
        if model_name == "deepseek-v4-flash":
            original_register(
                "deepseek-v4-pro", "llm", "cloud:deepseek:deepseek-v4-pro"
            )

    monkeypatch.setattr(mgr, "register_model", _racy_register)

    mgr._register_cloud_clients_from_llm_module()

    assert mgr._models["deepseek-v4-pro"].model_path == (
        "cloud:deepseek:deepseek-v4-pro"
    )
    assert set(mgr._models) == {"deepseek-v4-flash", "deepseek-v4-pro"}


def test_register_cloud_clients_handles_settings_failure(monkeypatch):
    """读取注册配置失败时应降级为「不注册」而不是抛出。"""
    mgr = _bare_manager()
    _clear_cloud_env(monkeypatch)
    monkeypatch.setattr(mm, "is_debug_enabled", lambda module: False)
    _patch_settings(monkeypatch, raises=True)

    mgr._register_cloud_clients_from_llm_module()

    assert mgr._models == {}


def test_register_cloud_clients_handles_bad_multi_key_config(monkeypatch):
    """多 API key 配置结构异常时应被内层 except 吞掉。"""

    class _BadKeyConfig:
        @property
        def models(self):
            raise RuntimeError("bad key config")

    mgr = _bare_manager()
    _clear_cloud_env(monkeypatch)
    monkeypatch.setattr(mm, "is_debug_enabled", lambda module: False)
    _patch_settings(
        monkeypatch,
        _cloud_settings(
            cloud_provider_keys={"siliconflow": {"default": _BadKeyConfig()}}
        ),
    )

    mgr._register_cloud_clients_from_llm_module()

    assert mgr._models == {}


def test_register_cloud_clients_swallows_outer_errors(monkeypatch):
    """注册阶段的意外异常应由最外层 except 吞掉。"""
    mgr = _bare_manager()
    _clear_cloud_env(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "key")
    monkeypatch.setattr(mm, "is_debug_enabled", lambda module: False)
    _patch_settings(monkeypatch, _cloud_settings())

    def _boom(*args, **kwargs):
        raise RuntimeError("register boom")

    monkeypatch.setattr(mgr, "register_model", _boom)

    mgr._register_cloud_clients_from_llm_module()  # 不应抛出

    assert mgr._models == {}


# --------------------------------------------------------------------------- #
# 硬件资源探测
# --------------------------------------------------------------------------- #


def test_detect_hardware_resources_without_gpu(monkeypatch):
    """无 GPU 时 has_gpu=False、gpu_usage=0、gpu 信息为空。"""
    mgr = _bare_manager()
    monkeypatch.setattr(mm, "psutil", _fake_psutil())
    monkeypatch.setattr(mm, "torch", None)
    monkeypatch.setattr(
        mm, "open", _FakeFile("", error=FileNotFoundError()), raising=False
    )

    result = mgr._detect_hardware_resources()

    assert result["cpu_count"] == 8
    assert result["cpu_usage"] == 12.5
    assert result["memory_total_gb"] == 16.0
    assert result["memory_available_gb"] == 8.0
    assert result["memory_usage"] == 50.0
    assert result["gpu_usage"] == 0
    assert result["has_gpu"] is False
    assert result["gpu"] == {}


def test_detect_hardware_resources_with_gpu_and_nvml(monkeypatch):
    """有 GPU 且 pynvml 可用时，应汇总型号、显存、利用率与 Jetson 标记。"""
    mgr = _bare_manager()
    monkeypatch.setattr(mm, "psutil", _fake_psutil())
    props = SimpleNamespace(name="FakeGPU", total_memory=24 * 1024**3)
    monkeypatch.setattr(mm, "torch", _fake_torch(available=True, props=props))
    monkeypatch.setattr(
        mm, "open", _FakeFile("NVIDIA Jetson Orin"), raising=False
    )

    pynvml = types.ModuleType("pynvml")
    pynvml.nvmlInit = lambda: None
    pynvml.nvmlShutdown = lambda: None
    pynvml.nvmlDeviceGetHandleByIndex = lambda index: "handle"
    pynvml.nvmlDeviceGetUtilizationRates = lambda handle: SimpleNamespace(gpu=42)
    monkeypatch.setitem(sys.modules, "pynvml", pynvml)

    result = mgr._detect_hardware_resources()

    assert result["has_gpu"] is True
    assert result["gpu_usage"] == 42
    assert result["gpu"]["name"] == "FakeGPU"
    assert result["gpu"]["total_memory_gb"] == 24.0
    assert result["gpu"]["is_jetson"] is True


def test_detect_hardware_resources_gpu_props_failure(monkeypatch):
    """读取 GPU 属性失败时只告警，has_gpu 仍为 True、gpu 信息为空。"""
    mgr = _bare_manager()
    monkeypatch.setattr(mm, "psutil", _fake_psutil())
    monkeypatch.setattr(
        mm,
        "torch",
        _fake_torch(available=True, props_error=RuntimeError("no props")),
    )
    monkeypatch.setattr(
        mm, "open", _FakeFile("", error=OSError()), raising=False
    )

    result = mgr._detect_hardware_resources()

    assert result["has_gpu"] is True
    assert result["gpu"] == {}
    assert result["gpu_usage"] == 0


def test_detect_hardware_resources_pynvml_failure(monkeypatch):
    """pynvml 初始化失败时 gpu_usage 保持 0，但不影响其余字段。"""
    mgr = _bare_manager()
    monkeypatch.setattr(mm, "psutil", _fake_psutil())
    props = SimpleNamespace(name="FakeGPU", total_memory=1024**3)
    monkeypatch.setattr(mm, "torch", _fake_torch(available=True, props=props))
    monkeypatch.setattr(mm, "open", _FakeFile("", error=OSError()), raising=False)

    pynvml = types.ModuleType("pynvml")

    def _nvml_init():
        raise RuntimeError("nvml boom")

    pynvml.nvmlInit = _nvml_init
    monkeypatch.setitem(sys.modules, "pynvml", pynvml)

    result = mgr._detect_hardware_resources()

    assert result["gpu_usage"] == 0
    assert result["gpu"]["name"] == "FakeGPU"


# --------------------------------------------------------------------------- #
# 模型统计
# --------------------------------------------------------------------------- #


def test_get_model_stats_counts_loaded_llm(monkeypatch):
    """已加载 LLM 存在时不应再走兜底探测。"""
    import core.voice as voice_pkg

    mgr = _bare_manager()
    for name, mtype, loaded in (
        ("a", "llm", True),
        ("b", "dashscope", False),
        ("c", "image_gen", False),
        ("d", "lora", False),
        ("e", "vision", False),
    ):
        mgr.register_model(name, mtype, "/" + name)
        mgr._models[name].is_loaded = loaded

    monkeypatch.setattr(
        voice_pkg, "_tts_manager_instance", SimpleNamespace(engine=object())
    )
    detect_calls = []
    monkeypatch.setattr(
        ModelManager,
        "_detect_active_llm",
        lambda self, active, loaded: detect_calls.append(1) or ("X", 9),
    )

    stats = mgr._get_model_stats()

    assert stats["models_total"] == 2  # llm + dashscope
    assert stats["models_loaded"] == 1
    assert stats["active_model"] == "a"
    assert stats["image_models_total"] == 2  # image_gen + lora
    assert stats["voices_total"] == 4
    assert detect_calls == []


def test_get_model_stats_falls_back_to_active_llm_detection(monkeypatch):
    """没有已加载 LLM 时应调用 _detect_active_llm 兜底。"""
    import core.voice as voice_pkg

    mgr = _bare_manager()
    mgr.register_model("a", "llm", "/a")
    monkeypatch.setattr(voice_pkg, "_tts_manager_instance", None)

    calls = []

    def _fake_detect(self, active_model, models_loaded):
        calls.append((active_model, models_loaded))
        return ("detected", 1)

    monkeypatch.setattr(ModelManager, "_detect_active_llm", _fake_detect)

    stats = mgr._get_model_stats()

    assert calls == [("None", 0)]
    assert stats["active_model"] == "detected"
    assert stats["models_loaded"] == 1
    assert stats["voices_total"] == 4


def test_get_model_stats_handles_voice_import_error(monkeypatch):
    """voice 模块缺少 TTS 单例时 voices_total 归零。"""
    import core.voice as voice_pkg

    mgr = _bare_manager()
    monkeypatch.delattr(voice_pkg, "_tts_manager_instance")

    stats = mgr._get_model_stats()

    assert stats["voices_total"] == 0
    assert stats["models_total"] == 0


def test_get_model_stats_swallows_errors(monkeypatch):
    """统计过程中出现异常时应返回已收集的部分数据而不是抛出。"""
    import core.voice as voice_pkg

    mgr = _bare_manager()
    monkeypatch.setattr(voice_pkg, "_tts_manager_instance", None)

    def _boom(self, active_model, models_loaded):
        raise RuntimeError("detect boom")

    monkeypatch.setattr(ModelManager, "_detect_active_llm", _boom)

    stats = mgr._get_model_stats()

    assert stats["models_total"] == 0
    assert stats["voices_total"] == 4


def test_detect_system_resources_merges_both_sources(monkeypatch):
    """detect_system_resources 应把硬件信息与模型统计合并成一份 dict。"""
    mgr = _bare_manager()
    monkeypatch.setattr(
        mgr, "_detect_hardware_resources", lambda: {"cpu_count": 8, "has_gpu": False}
    )
    monkeypatch.setattr(mgr, "_get_model_stats", lambda: {"models_total": 2})

    assert mgr.detect_system_resources() == {
        "cpu_count": 8,
        "has_gpu": False,
        "models_total": 2,
    }


# --------------------------------------------------------------------------- #
# 活跃模型探测
# --------------------------------------------------------------------------- #


def _patch_active_llm_deps(
    monkeypatch, cpp=None, llm=None, cpp_error: bool = False, llm_error: bool = False
):
    """替换 _detect_active_llm 依赖的 C++ 调度器与 LLM 模块工厂。"""
    import core.llm as llm_pkg
    import core.services.scheduler.cpp_scheduler_engine as cpp_mod

    def _cpp_factory():
        if cpp_error:
            raise RuntimeError("cpp boom")
        return cpp

    def _llm_factory():
        if llm_error:
            raise RuntimeError("llm boom")
        return llm

    monkeypatch.setattr(cpp_mod, "CPPSchedulerEngine", _cpp_factory)
    monkeypatch.setattr(llm_pkg, "get_llm_module", _llm_factory)


def test_detect_active_llm_without_backends(monkeypatch):
    """C++ 调度器未启用且无 LLM 模块时应原样返回。"""
    mgr = _bare_manager()
    _patch_active_llm_deps(
        monkeypatch, cpp=SimpleNamespace(enabled=False), llm=None
    )

    assert mgr._detect_active_llm("None", 0) == ("None", 0)


def test_detect_active_llm_from_cpp_gpu_config(monkeypatch):
    """C++ 调度器就绪时应标记已加载并采用其 GPU 配置里的模型路径。"""
    mgr = _bare_manager()
    cpp = SimpleNamespace(
        enabled=True,
        _gpu_worker_ready=True,
        llm=None,
        _gpu_config={"model_path": "cpp-model"},
    )
    _patch_active_llm_deps(monkeypatch, cpp=cpp, llm=None)

    assert mgr._detect_active_llm("None", 0) == ("cpp-model", 1)


def test_detect_active_llm_from_cpp_llm_without_gpu_config(monkeypatch):
    """C++ 调度器持有 LLM 实例但无 _gpu_config 时只标记已加载。"""
    mgr = _bare_manager()
    cpp = SimpleNamespace(enabled=True, _gpu_worker_ready=False, llm=object())
    _patch_active_llm_deps(monkeypatch, cpp=cpp, llm=None)

    assert mgr._detect_active_llm("None", 0) == ("None", 1)


def test_detect_active_llm_from_hybrid_module(monkeypatch):
    """hybrid LLM 模块应取已初始化的子模块（local 未就绪则取 cloud）。"""
    mgr = _bare_manager()
    status = {
        "type": "hybrid",
        "local": {"status": "uninitialized"},
        "cloud": {"init_state": "initialized", "model_path": "cloud-model"},
    }
    llm = SimpleNamespace(get_status=lambda: status)
    _patch_active_llm_deps(monkeypatch, cpp=SimpleNamespace(enabled=False), llm=llm)

    assert mgr._detect_active_llm("None", 0) == ("cloud-model", 1)


def test_detect_active_llm_prefers_current_model_name(monkeypatch):
    """已初始化模型 + get_current_model_name 时，应以当前模型名为准。"""
    mgr = _bare_manager()
    status = {"type": "local", "init_state": "initialized", "model_path": "local-model"}
    llm = SimpleNamespace(
        get_status=lambda: status, get_current_model_name=lambda: "current"
    )
    _patch_active_llm_deps(monkeypatch, cpp=SimpleNamespace(enabled=False), llm=llm)

    assert mgr._detect_active_llm("None", 0) == ("current", 1)


def test_detect_active_llm_non_hybrid_not_initialized(monkeypatch):
    """非 hybrid 且未初始化、当前模型名为 unknown 时不应改动入参。"""
    mgr = _bare_manager()
    status = {"type": "local", "status": "loading"}
    llm = SimpleNamespace(
        get_status=lambda: status, get_current_model_name=lambda: "unknown"
    )
    _patch_active_llm_deps(monkeypatch, cpp=SimpleNamespace(enabled=False), llm=llm)

    assert mgr._detect_active_llm("None", 0) == ("None", 0)


def test_detect_active_llm_swallows_errors(monkeypatch):
    """依赖构造失败时应静默返回入参。"""
    mgr = _bare_manager()
    _patch_active_llm_deps(monkeypatch, cpp_error=True)

    assert mgr._detect_active_llm("None", 0) == ("None", 0)


# --------------------------------------------------------------------------- #
# 注册 / 列表 / 锁
# --------------------------------------------------------------------------- #


def test_register_model_marks_gguf_and_skips_duplicates(monkeypatch):
    """register_model 应标记 .gguf 为量化，并拒绝覆盖已存在模型。"""
    mgr = _bare_manager()
    mgr.register_model("m", "llm", "/m.gguf")
    assert mgr._models["m"].quantized is True

    mgr.register_model("m", "image_gen", "/other")
    assert mgr._models["m"].model_type == "llm"
    assert mgr._models["m"].model_path == "/m.gguf"

    monkeypatch.setattr(mm, "is_debug_enabled", lambda module: True)
    mgr.register_model("n", "llm", "/n.bin")
    assert mgr._models["n"].quantized is False


def test_get_model_lock_is_stable_per_model():
    """同一模型应复用同一把锁，不同模型锁不同。"""
    mgr = _bare_manager()
    first = mgr._get_model_lock("a")
    second = mgr._get_model_lock("a")
    other = mgr._get_model_lock("b")

    assert first is second
    assert first is not other
    assert set(mgr._model_locks) == {"a", "b"}


def test_get_loaded_models_and_list_models():
    """已加载列表与列表接口应按加载状态 / 类型正确过滤。"""
    mgr = _bare_manager()
    mgr.register_model("a", "llm", "/a.gguf")
    mgr.register_model("b", "image_gen", "/b.safetensors")
    mgr._models["a"].is_loaded = True

    assert mgr.get_loaded_models() == ["a"]

    assert {item["id"] for item in mgr.list_models()} == {"a", "b"}
    llm_only = mgr.list_models("llm")
    assert [item["id"] for item in llm_only] == ["a"]
    assert llm_only[0]["state"] == ModelRuntimeState.LOADED.value
    assert llm_only[0]["quantized"] is True
    assert mgr.list_models("image_gen")[0]["id"] == "b"


# --------------------------------------------------------------------------- #
# 加载 / 卸载 / offload
# --------------------------------------------------------------------------- #


def test_load_model_raises_for_unregistered_model():
    """未注册模型应抛 ValueError。"""
    mgr = _bare_manager()
    with pytest.raises(ValueError, match="模型未注册"):
        mgr.load_model("missing")


def test_load_model_returns_loaded_instance_and_touches_last_used():
    """已加载模型应直接复用并刷新 last_used_time。"""
    mgr = _bare_manager()
    mgr.register_model("m", "llm", "/m")
    info = mgr._models["m"]
    info.is_loaded = True
    info.model_obj = "OBJ"

    assert mgr.load_model("m") == "OBJ"
    assert info.last_used_time is not None


def test_load_model_moves_offloaded_back_to_cpu():
    """已 offload 的模型应被移回 CPU 并清除 offload 标记。"""
    mgr = _bare_manager()
    mgr.register_model("m", "llm", "/m")
    info = mgr._models["m"]
    obj = _Movable()
    info.is_loaded = True
    info.is_offloaded = True
    info.model_obj = obj

    assert mgr.load_model("m") is obj
    assert obj.device == "cpu"
    assert info.is_offloaded is False
    assert info.last_used_time is not None


def test_load_model_offloaded_without_to_method():
    """模型对象不支持 .to() 时直接返回，保持 offload 标记不变。"""
    mgr = _bare_manager()
    mgr.register_model("m", "llm", "/m")
    info = mgr._models["m"]
    obj = object()
    info.is_loaded = True
    info.is_offloaded = True
    info.model_obj = obj

    assert mgr.load_model("m") is obj
    assert info.is_offloaded is True


def test_load_model_reloads_when_move_back_fails(monkeypatch):
    """移回 CPU 失败时应卸载并重新加载。"""
    mgr = _bare_manager()
    mgr.register_model("m", "llm", "/m")
    info = mgr._models["m"]
    info.is_loaded = True
    info.is_offloaded = True
    info.model_obj = _Movable(fail=True)
    monkeypatch.setattr(
        mgr, "_load_model_by_type", lambda name, **kwargs: ("NEW", "TOK")
    )

    assert mgr.load_model("m") == "NEW"
    assert info.is_loaded is True
    assert info.tokenizer_obj == "TOK"
    assert info.model_obj == "NEW"
    assert info.load_time is not None


def test_load_model_reuses_model_loaded_during_wait(monkeypatch):
    """模拟等待模型锁期间被其他线程加载完成：第二次检查应直接复用。"""
    mgr = _bare_manager()
    mgr.register_model("m", "llm", "/m")
    info = mgr._models["m"]
    obj = _Movable()
    real_get_lock = mgr._get_model_lock
    state = {"hooked": False}

    def _hook(name):
        lock = real_get_lock(name)
        if not state["hooked"]:
            state["hooked"] = True
            info.model_obj = obj
            info.is_loaded = True
        return lock

    monkeypatch.setattr(mgr, "_get_model_lock", _hook)

    assert mgr.load_model("m") is obj
    assert info.is_offloaded is False


def test_load_model_reuses_model_offloaded_during_wait(monkeypatch):
    """模拟等待期间模型被加载后又 offload：第二次检查应移回 CPU。"""
    mgr = _bare_manager()
    mgr.register_model("m", "llm", "/m")
    info = mgr._models["m"]
    obj = _Movable()
    real_get_lock = mgr._get_model_lock
    state = {"hooked": False}

    def _hook(name):
        lock = real_get_lock(name)
        if not state["hooked"]:
            state["hooked"] = True
            info.model_obj = obj
            info.is_loaded = True
            info.is_offloaded = True
        return lock

    monkeypatch.setattr(mgr, "_get_model_lock", _hook)

    assert mgr.load_model("m") is obj
    assert obj.device == "cpu"
    assert info.is_offloaded is False


def test_load_model_reloads_when_wait_offload_restore_fails(monkeypatch):
    """等待期间 offload 后移回 CPU 失败：应卸载并重新加载。"""
    mgr = _bare_manager()
    mgr.register_model("m", "llm", "/m")
    info = mgr._models["m"]
    real_get_lock = mgr._get_model_lock
    state = {"hooked": False}

    def _hook(name):
        lock = real_get_lock(name)
        if not state["hooked"]:
            state["hooked"] = True
            info.model_obj = _Movable(fail=True)
            info.is_loaded = True
            info.is_offloaded = True
        return lock

    monkeypatch.setattr(mgr, "_get_model_lock", _hook)
    monkeypatch.setattr(
        mgr, "_load_model_by_type", lambda name, **kwargs: ("RELOADED", "TOK")
    )

    assert mgr.load_model("m") == "RELOADED"
    assert info.is_loaded is True
    assert info.is_offloaded is False


def test_load_model_loads_and_propagates_failure(monkeypatch):
    """正常加载写入状态；加载失败应向上抛出且不改变 is_loaded。"""
    mgr = _bare_manager()
    mgr.register_model("m", "llm", "/m")
    info = mgr._models["m"]
    monkeypatch.setattr(
        mgr, "_load_model_by_type", lambda name, **kwargs: ("MODEL", "TOK")
    )

    assert mgr.load_model("m") == "MODEL"
    assert info.is_loaded is True
    assert info.model_obj == "MODEL"
    assert info.tokenizer_obj == "TOK"

    def _boom(name, **kwargs):
        raise RuntimeError("load boom")

    mgr2 = _bare_manager()
    mgr2.register_model("n", "llm", "/n")
    monkeypatch.setattr(mgr2, "_load_model_by_type", _boom)
    with pytest.raises(RuntimeError, match="load boom"):
        mgr2.load_model("n")
    assert mgr2._models["n"].is_loaded is False


def test_unload_model_clears_state_and_cuda_cache(monkeypatch):
    """卸载应清空模型/分词器引用并释放 CUDA 缓存。"""
    mgr = _bare_manager()
    mgr.register_model("m", "llm", "/m")
    info = mgr._models["m"]
    info.is_loaded = True
    info.is_offloaded = True
    info.model_obj = object()
    info.tokenizer_obj = object()
    fake_torch = _fake_torch(available=True)
    monkeypatch.setattr(mm, "torch", fake_torch)

    mgr.unload_model("m")

    assert info.is_loaded is False
    assert info.is_offloaded is False
    assert info.model_obj is None
    assert info.tokenizer_obj is None
    assert fake_torch.calls["empty_cache"] == 1


def test_unload_model_noop_paths():
    """未加载模型或未注册模型时卸载应为空操作。"""
    mgr = _bare_manager()
    mgr.register_model("m", "llm", "/m")

    mgr.unload_model("m")
    assert mgr._models["m"].is_loaded is False

    mgr.unload_model("missing")
    assert "missing" not in mgr._models


def test_offload_model_moves_to_cpu_and_frees_cache(monkeypatch):
    """offload 应把模型移到 CPU、置位标记并释放 CUDA 缓存。"""
    mgr = _bare_manager()
    mgr.register_model("m", "llm", "/m")
    info = mgr._models["m"]
    obj = _Movable()
    info.is_loaded = True
    info.model_obj = obj
    fake_torch = _fake_torch(available=True)
    monkeypatch.setattr(mm, "torch", fake_torch)

    mgr.offload_model("m")

    assert obj.device == "cpu"
    assert info.is_offloaded is True
    assert fake_torch.calls["empty_cache"] == 1


def test_offload_model_unloads_when_unsupported():
    """模型对象不支持 .to('cpu') 时应退化为卸载。"""
    mgr = _bare_manager()
    mgr.register_model("m", "llm", "/m")
    info = mgr._models["m"]
    info.is_loaded = True
    info.model_obj = object()

    mgr.offload_model("m")

    assert info.is_loaded is False
    assert info.model_obj is None


def test_offload_model_unloads_when_move_fails():
    """移回 CPU 抛异常时应退化为卸载。"""
    mgr = _bare_manager()
    mgr.register_model("m", "llm", "/m")
    info = mgr._models["m"]
    info.is_loaded = True
    info.model_obj = _Movable(fail=True)

    mgr.offload_model("m")

    assert info.is_loaded is False


def test_offload_model_noop_paths():
    """未注册 / 未加载 / model_obj 为空 / 已 offload 时均不应改动状态。"""
    mgr = _bare_manager()
    mgr.register_model("m", "llm", "/m")
    info = mgr._models["m"]

    mgr.offload_model("missing")  # 未注册
    mgr.offload_model("m")  # 未加载

    info.is_loaded = True
    info.model_obj = None
    mgr.offload_model("m")  # model_obj 为 None
    assert info.is_offloaded is False

    obj = _Movable()
    info.model_obj = obj
    info.is_offloaded = True
    mgr.offload_model("m")  # 已 offload
    assert obj.device is None


# --------------------------------------------------------------------------- #
# 按类型加载
# --------------------------------------------------------------------------- #


def test_load_model_by_type_dispatch(monkeypatch):
    """_load_model_by_type 应按类型分发到对应加载器。"""
    mgr = _bare_manager()
    mgr.register_model("llm1", "llm", "/llm")
    mgr.register_model("vis1", "vision", "/vis")
    mgr.register_model("vl1", "vl", "/vl")
    mgr.register_model("img1", "image_gen", "/img")
    mgr.register_model("bad", "audio", "/bad")

    seen = []
    monkeypatch.setattr(
        mgr,
        "_load_transformers_model",
        lambda path, kwargs, cls: seen.append((path, cls)) or (f"M:{cls}", "TOK"),
    )
    monkeypatch.setattr(
        mgr,
        "_load_image_gen_model",
        lambda path, kwargs: seen.append((path, "IMG")) or ("IMG-PIPE", None),
    )

    assert mgr._load_model_by_type("llm1") == ("M:AutoModelForCausalLM", "TOK")
    assert mgr._load_model_by_type("vis1") == ("M:AutoModelForVision2Seq", "TOK")
    assert mgr._load_model_by_type("vl1") == ("M:AutoModelForVision2Seq", "TOK")
    assert mgr._load_model_by_type("img1") == ("IMG-PIPE", None)
    assert seen == [
        ("/llm", "AutoModelForCausalLM"),
        ("/vis", "AutoModelForVision2Seq"),
        ("/vl", "AutoModelForVision2Seq"),
        ("/img", "IMG"),
    ]

    with pytest.raises(ValueError, match="不支持的模型类型"):
        mgr._load_model_by_type("bad")


def test_load_transformers_model_forces_cpu(monkeypatch):
    """transformers 加载应强制 CPU，并透传 model_kwargs。"""
    mgr = _bare_manager()
    record = {}

    class _Model:
        def __init__(self):
            self.moved_to = None

        def to(self, device):
            self.moved_to = device
            return self

    class _ModelCls:
        @staticmethod
        def from_pretrained(path, **kwargs):
            record["model_call"] = (path, kwargs)
            return _Model()

    class _Tok:
        @staticmethod
        def from_pretrained(path, **kwargs):
            record["tok_call"] = (path, kwargs)
            return "TOK"

    _install_fake_transformers(monkeypatch, _ModelCls, _Tok)

    model, tokenizer = mgr._load_transformers_model(
        "/m",
        {"model_kwargs": {"trust_remote_code": False}, "device": "cuda"},
        "AutoModelForCausalLM",
    )

    assert tokenizer == "TOK"
    assert model.moved_to == "cpu"
    assert record["tok_call"] == (
        "/m",
        {"trust_remote_code": True, "local_files_only": True},
    )
    assert record["model_call"] == ("/m", {"trust_remote_code": False})


def test_load_transformers_model_cpu_device_without_to(monkeypatch):
    """device 为 cpu 且模型无 .to() 时不走告警分支，原样返回。"""
    mgr = _bare_manager()

    class _ModelCls:
        @staticmethod
        def from_pretrained(path, **kwargs):
            return "RAW-MODEL"

    class _Tok:
        @staticmethod
        def from_pretrained(path, **kwargs):
            return "TOK"

    _install_fake_transformers(monkeypatch, _ModelCls, _Tok)

    model, tokenizer = mgr._load_transformers_model(
        "/m", {"device": "cpu"}, "AutoModelForCausalLM"
    )

    assert model == "RAW-MODEL"
    assert tokenizer == "TOK"


# --------------------------------------------------------------------------- #
# 图像生成模型加载
# --------------------------------------------------------------------------- #


def test_load_image_gen_model_requires_torch(monkeypatch, tmp_path):
    """未安装 torch 时应抛 ImportError。"""
    mgr = _bare_manager()
    module, _ = _fake_diffusers(with_single_file=True)
    monkeypatch.setitem(sys.modules, "diffusers", module)
    monkeypatch.setattr(mm, "torch", None)

    with pytest.raises(ImportError, match="未安装 torch"):
        mgr._load_image_gen_model(str(tmp_path / "m.ckpt"), {})


def test_load_image_gen_model_from_pretrained_dir(monkeypatch, tmp_path):
    """目录形态的模型应走 from_pretrained，并合并 model_kwargs。"""
    mgr = _bare_manager()
    module, record = _fake_diffusers(with_single_file=True)
    monkeypatch.setitem(sys.modules, "diffusers", module)
    monkeypatch.setattr(mm, "torch", _fake_torch(available=False))
    monkeypatch.setattr(mm, "os", _fake_os())

    pipe, tokenizer = mgr._load_image_gen_model(
        str(tmp_path / "dir-model"), {"model_kwargs": {"safety_checker": None}}
    )

    kind, path, kwargs = record["calls"][0]
    assert kind == "from_pretrained"
    assert path == str(tmp_path / "dir-model")
    assert kwargs["local_files_only"] is True
    assert kwargs["torch_dtype"] == "float16"
    assert kwargs["safety_checker"] is None
    assert tokenizer is None
    assert pipe == {"kind": "from_pretrained", "path": path, "kwargs": kwargs}


def test_load_image_gen_model_delegates_single_file(monkeypatch, tmp_path):
    """文件形态的模型应委托给 _load_image_gen_single_file。"""
    mgr = _bare_manager()
    module, _ = _fake_diffusers(with_single_file=True)
    monkeypatch.setitem(sys.modules, "diffusers", module)
    monkeypatch.setattr(mm, "torch", _fake_torch(available=False))
    model_path = str(tmp_path / "single.ckpt")
    monkeypatch.setattr(mm, "os", _fake_os(isfile=[model_path]))

    captured = {}

    def _fake_single(self, path, pipe_kwargs, kwargs):
        captured["path"] = path
        captured["pipe_kwargs"] = dict(pipe_kwargs)
        captured["kwargs"] = kwargs
        return "PIPE"

    monkeypatch.setattr(ModelManager, "_load_image_gen_single_file", _fake_single)

    pipe, tokenizer = mgr._load_image_gen_model(model_path, {"torch_dtype": "float32"})

    assert pipe == "PIPE"
    assert tokenizer is None
    assert captured["path"] == model_path
    assert captured["pipe_kwargs"]["torch_dtype"] == "float32"
    assert captured["pipe_kwargs"]["local_files_only"] is True


def test_load_image_gen_single_file_uses_sdxl_base_config(monkeypatch, tmp_path):
    """文件名含 sdxl/xl 且本地有 SDXL 基座时，应下发 config 指向基座。"""
    mgr = _bare_manager()
    module, record = _fake_diffusers(with_single_file=True)
    monkeypatch.setitem(sys.modules, "diffusers", module)
    monkeypatch.setattr(mm, "torch", None)
    monkeypatch.setattr(
        pathlib.Path,
        "exists",
        lambda self: str(self).endswith("stable-diffusion-xl-base-1.0"),
    )
    monkeypatch.setattr(mm, "os", _fake_os())

    model_path = str(tmp_path / "my_sdxl_model.safetensors")
    result = mgr._load_image_gen_single_file(model_path, {"local_files_only": True}, {})

    kind, path, kwargs = record["calls"][0]
    assert kind == "from_single_file"
    assert path == model_path
    assert kwargs["safety_checker"] is None
    assert kwargs["config"].endswith("stable-diffusion-xl-base-1.0")
    assert "original_config_file" not in kwargs
    assert result == {"kind": "from_single_file", "path": path, "kwargs": kwargs}


def test_load_image_gen_single_file_uses_sd15_config(monkeypatch, tmp_path):
    """非 SDXL 文件名且本地有 SD1.5 基座时，应下发 SD1.5 的 config。"""
    mgr = _bare_manager()
    module, record = _fake_diffusers(with_single_file=True)
    monkeypatch.setitem(sys.modules, "diffusers", module)
    monkeypatch.setattr(mm, "torch", None)
    monkeypatch.setattr(
        pathlib.Path,
        "exists",
        lambda self: str(self).endswith("stable-diffusion-v1-5"),
    )
    monkeypatch.setattr(mm, "os", _fake_os())

    model_path = str(tmp_path / "plain_model.safetensors")
    mgr._load_image_gen_single_file(model_path, {}, {})

    kwargs = record["calls"][0][2]
    assert kwargs["config"].endswith("stable-diffusion-v1-5")


def test_load_image_gen_single_file_finds_same_name_yaml(monkeypatch, tmp_path):
    """本地无基座时不下发 config；同名 yaml 应作为 original_config_file。"""
    mgr = _bare_manager()
    module, record = _fake_diffusers(with_single_file=True)
    monkeypatch.setitem(sys.modules, "diffusers", module)
    monkeypatch.setattr(mm, "torch", None)
    monkeypatch.setattr(pathlib.Path, "exists", lambda self: False)

    model_path = str(tmp_path / "foo.safetensors")
    same_name_yaml = os.path.splitext(model_path)[0] + ".yaml"
    monkeypatch.setattr(mm, "os", _fake_os(exists=[same_name_yaml]))

    pipe_kwargs = {}
    mgr._load_image_gen_single_file(model_path, pipe_kwargs, {})

    assert pipe_kwargs["original_config_file"] == same_name_yaml
    assert "config" not in record["calls"][0][2]


def test_load_image_gen_single_file_falls_back_to_ckpt(monkeypatch, tmp_path):
    """StableDiffusionPipeline 无 from_single_file 时应回退到 from_ckpt。"""
    mgr = _bare_manager()
    module, record = _fake_diffusers(with_single_file=False)
    monkeypatch.setitem(sys.modules, "diffusers", module)
    monkeypatch.setattr(mm, "torch", None)
    monkeypatch.setattr(pathlib.Path, "exists", lambda self: False)
    monkeypatch.setattr(mm, "os", _fake_os())

    result = mgr._load_image_gen_single_file(str(tmp_path / "a.ckpt"), {}, {})

    assert record["calls"][0][0] == "from_ckpt"
    assert result["kind"] == "from_ckpt"


def test_load_image_gen_single_file_enables_cpu_offload(monkeypatch, tmp_path):
    """有 CUDA 且 pipeline 支持时应启用 model cpu offload。"""
    mgr = _bare_manager()
    pipe = _OffloadPipe(mode="model")
    module, _ = _fake_diffusers(with_single_file=True, pipe=pipe)
    monkeypatch.setitem(sys.modules, "diffusers", module)
    monkeypatch.setattr(mm, "torch", _fake_torch(available=True))
    monkeypatch.setattr(pathlib.Path, "exists", lambda self: False)
    monkeypatch.setattr(mm, "os", _fake_os())

    result = mgr._load_image_gen_single_file(str(tmp_path / "a.ckpt"), {}, {})

    assert result is pipe
    assert pipe.calls == ["model"]


def test_load_image_gen_single_file_uses_sequential_offload(monkeypatch, tmp_path):
    """pipeline 不支持 model offload 时应退化为 sequential offload。"""
    mgr = _bare_manager()
    pipe = _SeqOnlyPipe()
    module, _ = _fake_diffusers(with_single_file=True, pipe=pipe)
    monkeypatch.setitem(sys.modules, "diffusers", module)
    monkeypatch.setattr(mm, "torch", _fake_torch(available=True))
    monkeypatch.setattr(pathlib.Path, "exists", lambda self: False)
    monkeypatch.setattr(mm, "os", _fake_os())

    result = mgr._load_image_gen_single_file(str(tmp_path / "a.ckpt"), {}, {})

    assert result is pipe
    assert pipe.calls == ["sequential"]


def test_load_image_gen_single_file_swallows_offload_error(monkeypatch, tmp_path):
    """启用 offload 抛异常时应只告警，仍返回 pipeline。"""
    mgr = _bare_manager()
    pipe = _OffloadPipe(mode="raise")
    module, _ = _fake_diffusers(with_single_file=True, pipe=pipe)
    monkeypatch.setitem(sys.modules, "diffusers", module)
    monkeypatch.setattr(mm, "torch", _fake_torch(available=True))
    monkeypatch.setattr(pathlib.Path, "exists", lambda self: False)
    monkeypatch.setattr(mm, "os", _fake_os())

    result = mgr._load_image_gen_single_file(str(tmp_path / "a.ckpt"), {}, {})

    assert result is pipe
    assert pipe.calls == []


def test_find_local_config_prefers_default_then_same_name(tmp_path):
    """_find_local_config 优先 v1-inference.yaml，其次同名 yaml，都没有则不写。"""
    default_yaml = tmp_path / "v1-inference.yaml"
    default_yaml.write_text("x", encoding="utf-8")
    model_path = str(tmp_path / "model.safetensors")

    kwargs = {}
    ModelManager._find_local_config(model_path, kwargs)
    assert kwargs["original_config_file"] == str(default_yaml)

    other = tmp_path / "sub"
    other.mkdir()
    same_name = other / "model.yaml"
    same_name.write_text("x", encoding="utf-8")
    kwargs2 = {}
    ModelManager._find_local_config(str(other / "model.safetensors"), kwargs2)
    assert kwargs2["original_config_file"] == str(same_name)

    empty = tmp_path / "empty"
    empty.mkdir()
    kwargs3 = {}
    ModelManager._find_local_config(str(empty / "none.safetensors"), kwargs3)
    assert kwargs3 == {}
