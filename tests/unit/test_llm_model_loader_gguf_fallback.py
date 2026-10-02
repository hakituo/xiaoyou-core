"""ModelLoader 加载流程单测。

覆盖范围：``_load_gguf_model`` —— GPU 健康检查失败回退 CPU、层数校验告警、
psutil 报错回退、ctx 候选扩展、CUDA 缓存清理异常、n_gpu_layers 必定写 int。

llama_cpp / transformers / torch / psutil 全部以替身注入，不加载真实模型、
不使用 GPU、不发网络请求；所有文件 IO 落在 pytest 的 tmp_path 内。
"""
from __future__ import annotations

import core.modules.llm.model_loader as model_loader
from core.modules.llm.model_loader import ModelLoader


# --------------------------------------------------------------------------- #
# 替身
# --------------------------------------------------------------------------- #
class _Attrs:
    """极简属性容器：构造参数即属性，缺失属性走 AttributeError。"""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeSettings:
    """settings 替身：只需要 ``model`` 与 ``immune``。"""

    def __init__(self, model=None, immune=None):
        self.model = model if model is not None else _Attrs()
        self.immune = immune if immune is not None else _Attrs()


class _FakeModule:
    """LLMModule 替身，仅保留 ModelLoader 会读写的字段。"""

    def __init__(self, config=None, settings=None, **kwargs):
        self.config = {} if config is None else config
        self.settings = settings if settings is not None else _FakeSettings()
        self.text_model_path = ""
        self.is_gguf = False
        self.is_loaded = False
        self.llama_model = None
        self.model = None
        self.tokenizer = None
        self._last_load_error = None
        for key, value in kwargs.items():
            setattr(self, key, value)


class _BlockedResetModule(_FakeModule):
    """把 ``llama_model`` 赋值为 None 时抛错，用于覆盖清理阶段的 except pass。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._block_reset = True

    def __setattr__(self, name, value):
        if name == "llama_model" and value is None and self.__dict__.get("_block_reset"):
            raise RuntimeError("cannot reset llama_model")
        super().__setattr__(name, value)


class _RaisingUseMmap:
    """``use_mmap`` / ``ram_mirror_offload`` 访问抛错，其余属性缺失。"""

    def __getattr__(self, name):
        if name in ("use_mmap", "ram_mirror_offload"):
            raise RuntimeError(f"{name} boom")
        raise AttributeError(name)


class _FakePsutil:
    """psutil 替身：可控 virtual_memory().percent 或直接抛错。"""

    def __init__(self, percent=None, error=None):
        self._percent = percent
        self._error = error

    def virtual_memory(self):
        if self._error is not None:
            raise self._error
        return _Attrs(percent=self._percent)


class _FakeCuda:
    """torch.cuda 替身。"""

    def __init__(self, available=True, error=None, empty_cache_error=None):
        self._available = available
        self._error = error
        self._empty_cache_error = empty_cache_error
        self.empty_cache_calls = 0
        self.ipc_collect_calls = 0

    def is_available(self):
        if self._error is not None:
            raise self._error
        return self._available

    def empty_cache(self):
        self.empty_cache_calls += 1
        if self._empty_cache_error is not None:
            raise self._empty_cache_error

    def ipc_collect(self):
        self.ipc_collect_calls += 1


class _FakeTorch:
    """torch 替身，只提供被测代码会读到的属性。"""

    def __init__(self, available=True, error=None, empty_cache_error=None):
        self.cuda = _FakeCuda(
            available=available, error=error, empty_cache_error=empty_cache_error
        )
        self.float16 = "float16"
        self.bfloat16 = "bfloat16"
        self.float32 = "float32"


def _fake_llama_class(behavior, gpu_layers_value=0, gpu_layers_error=None, calls=None):
    """构造可控的 Llama 替身类。

    ``behavior(kwargs, call_index)`` 在 ``__init__`` 内执行，可抛异常模拟加载失败。
    """
    seen = [] if calls is None else calls

    class _FakeLlama:
        def __init__(self, **kwargs):
            seen.append(dict(kwargs))
            behavior(kwargs, len(seen) - 1)
            self.kwargs = kwargs

        def n_gpu_layers(self):
            if gpu_layers_error is not None:
                raise gpu_layers_error
            return gpu_layers_value

    _FakeLlama.calls = seen
    return _FakeLlama


_DEFAULT_PARAMS = {
    "flash_attn": True,
    "offload_kqv": True,
    "n_gpu_layers": 0,
    "n_ctx": 2048,
    "n_batch": 256,
}


def _loader():
    """构造一个只用于纯函数方法的 ModelLoader。"""
    return ModelLoader(_FakeModule())


def _gguf_loader(
    monkeypatch,
    *,
    module=None,
    mem_pressure=(False, 30.0),
    threshold=96.0,
    header=(True, ""),
    params=None,
    threads=4,
    candidates=None,
):
    """构造一个已替换掉所有外部协作者的 ModelLoader。

    默认 ``use_mmap=True``，因此 use_mmap 候选只有 (True,)，不依赖 psutil。
    """
    if module is None:
        module = _FakeModule(
            settings=_FakeSettings(model=_Attrs(use_mmap=True, ram_mirror_offload=False))
        )
    loader = ModelLoader(module)
    monkeypatch.setattr(model_loader, "patch_llama_cpp_internals", lambda: None)
    monkeypatch.setattr(loader, "_check_memory_pressure", lambda: mem_pressure)
    monkeypatch.setattr(loader, "_get_memory_block_threshold", lambda: threshold)
    monkeypatch.setattr(loader, "_verify_gguf_header", lambda path: header)
    monkeypatch.setattr(loader, "_get_model_params", lambda: dict(params or _DEFAULT_PARAMS))
    monkeypatch.setattr(loader, "_calculate_thread_count", lambda: threads)
    if candidates is not None:
        monkeypatch.setattr(
            model_loader, "expand_gpu_layer_candidates", lambda value: list(candidates)
        )
    return loader


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# _load_gguf_model —— GPU 健康检查与回退
# --------------------------------------------------------------------------- #

def test_gguf_gpu_health_check_failure_falls_back_to_cpu(monkeypatch):
    """GPU 健康检查失败 → 归零 n_gpu_layers 并重新走 load_sync。"""
    import core.modules.llm.gpu_manager as gpu_manager

    llama_cls = _fake_llama_class(lambda kwargs, index: None)
    monkeypatch.setattr(model_loader, "Llama", llama_cls)
    monkeypatch.setattr(model_loader, "get_torch", lambda: _FakeTorch(error=RuntimeError("cuda gone")))

    class _UnhealthyGPUManager:
        def __init__(self, module):
            self.module = module

        def health_check(self):
            return False

    monkeypatch.setattr(gpu_manager, "GPUManager", _UnhealthyGPUManager)

    config = {}
    module = _FakeModule(config=config, text_model_path="model.gguf")
    loader = _gguf_loader(
        monkeypatch, module=module, params=dict(_DEFAULT_PARAMS, n_gpu_layers=8),
        candidates=[8],
    )
    reload_calls = []
    monkeypatch.setattr(loader, "load_sync", lambda: reload_calls.append(1) or True)

    assert loader._load_gguf_model() is True
    assert reload_calls == [1]
    assert config["n_gpu_layers"] == 0
    assert module.is_loaded is True


def test_gguf_gpu_health_check_failure_and_reload_fails(monkeypatch):
    """GPU 健康检查失败且 CPU 重载也失败 → 返回 False。"""
    import core.modules.llm.gpu_manager as gpu_manager

    llama_cls = _fake_llama_class(lambda kwargs, index: None)
    monkeypatch.setattr(model_loader, "Llama", llama_cls)

    class _UnhealthyGPUManager:
        def __init__(self, module):
            self.module = module

        def health_check(self):
            return False

    monkeypatch.setattr(gpu_manager, "GPUManager", _UnhealthyGPUManager)

    module = _FakeModule(text_model_path="model.gguf")
    loader = _gguf_loader(
        monkeypatch, module=module, params=dict(_DEFAULT_PARAMS, n_gpu_layers=8),
        candidates=[8],
    )
    monkeypatch.setattr(loader, "load_sync", lambda: False)

    assert loader._load_gguf_model() is False
    assert module.is_loaded is False


def test_gguf_gpu_health_check_exception_is_swallowed(monkeypatch):
    """GPU 健康检查自身抛异常 → 记录告警但整体仍算加载成功。"""
    import core.modules.llm.gpu_manager as gpu_manager

    llama_cls = _fake_llama_class(lambda kwargs, index: None)
    monkeypatch.setattr(model_loader, "Llama", llama_cls)

    class _ExplodingGPUManager:
        def __init__(self, module):
            self.module = module

        def health_check(self):
            raise RuntimeError("health check blew up")

    monkeypatch.setattr(gpu_manager, "GPUManager", _ExplodingGPUManager)

    module = _FakeModule(text_model_path="model.gguf")
    loader = _gguf_loader(
        monkeypatch, module=module, params=dict(_DEFAULT_PARAMS, n_gpu_layers=8),
        candidates=[8],
    )

    assert loader._load_gguf_model() is True
    assert module.is_loaded is True


def test_gguf_gpu_layer_verification_warning_is_swallowed(monkeypatch):
    """GPU 层数验证抛异常 → 仅告警，加载仍然成功。"""
    import core.modules.llm.gpu_manager as gpu_manager

    llama_cls = _fake_llama_class(
        lambda kwargs, index: None, gpu_layers_error=RuntimeError("no such method")
    )
    monkeypatch.setattr(model_loader, "Llama", llama_cls)

    class _HealthyGPUManager:
        def __init__(self, module):
            self.module = module

        def health_check(self):
            return True

    monkeypatch.setattr(gpu_manager, "GPUManager", _HealthyGPUManager)

    module = _FakeModule(text_model_path="model.gguf")
    loader = _gguf_loader(
        monkeypatch, module=module, params=dict(_DEFAULT_PARAMS, n_gpu_layers=8),
        candidates=[8],
    )

    assert loader._load_gguf_model() is True
    assert module.is_loaded is True


def test_gguf_use_mmap_fallback_when_psutil_errors(monkeypatch):
    """读内存占用抛异常 → use_mmap 候选退回单一 (True,)。"""
    llama_cls = _fake_llama_class(lambda kwargs, index: None)
    monkeypatch.setattr(model_loader, "Llama", llama_cls)
    monkeypatch.setattr(
        model_loader, "psutil", _FakePsutil(error=RuntimeError("no /proc"))
    )

    module = _FakeModule(
        settings=_FakeSettings(model=_Attrs(use_mmap=None, ram_mirror_offload=False)),
        text_model_path="model.gguf",
    )
    loader = _gguf_loader(monkeypatch, module=module, candidates=[0])

    assert loader._load_gguf_model() is True
    assert len(llama_cls.calls) == 1
    assert llama_cls.calls[0]["use_mmap"] is True


def test_gguf_expands_ctx_candidates_when_n_ctx_large(monkeypatch):
    """n_ctx > 2048 时额外追加低 n_ctx 候选，覆盖候选扩展分支。"""
    llama_cls = _fake_llama_class(lambda kwargs, index: None)
    monkeypatch.setattr(model_loader, "Llama", llama_cls)

    config = {}
    module = _FakeModule(config=config, text_model_path="model.gguf")
    loader = _gguf_loader(
        monkeypatch, module=module, params=dict(_DEFAULT_PARAMS, n_ctx=4096),
        candidates=[0],
    )

    assert loader._load_gguf_model() is True
    assert config["n_ctx"] == 4096
    assert len(llama_cls.calls) == 1


def test_gguf_cuda_cache_cleanup_errors_are_swallowed(monkeypatch):
    """CUDA 失败后的显存清理自身抛异常 → 吞掉后仍能继续降级到 CPU。"""
    def _behavior(kwargs, index):
        if index == 0:
            raise RuntimeError("ggml-cuda error: kernel launch failed")

    llama_cls = _fake_llama_class(_behavior)
    monkeypatch.setattr(model_loader, "Llama", llama_cls)
    broken_torch = _FakeTorch(
        available=True, empty_cache_error=RuntimeError("cache boom")
    )
    monkeypatch.setattr(model_loader, "get_torch", lambda: broken_torch)

    config = {}
    module = _FakeModule(config=config, text_model_path="model.gguf")
    loader = _gguf_loader(
        monkeypatch, module=module, params=dict(_DEFAULT_PARAMS, n_gpu_layers=8),
        candidates=[8, 0],
    )

    assert loader._load_gguf_model() is True
    assert config["n_gpu_layers"] == 0
    assert broken_torch.cuda.empty_cache_calls == 1


def test_gguf_success_always_writes_int_n_gpu_layers(monkeypatch):
    """成功路径必然把 config["n_gpu_layers"] 写成 int。

    这是 493 行 ``if cfg_layers is None`` 分支不可达的直接证据：
    即使调用前把该键预置成 None，成功分支也会用 int 覆盖它。
    """
    llama_cls = _fake_llama_class(lambda kwargs, index: None)
    monkeypatch.setattr(model_loader, "Llama", llama_cls)

    config = {"n_gpu_layers": None}
    module = _FakeModule(config=config, text_model_path="model.gguf")
    loader = _gguf_loader(monkeypatch, module=module, candidates=[0])

    assert loader._load_gguf_model() is True
    assert isinstance(config["n_gpu_layers"], int)

