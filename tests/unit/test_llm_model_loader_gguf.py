"""ModelLoader 加载流程单测。

覆盖范围：``_load_gguf_model`` —— 基础路径与重试（无 llama_cpp / 内存压力 /
非法文件头 / use_mmap 去重 / TypeError 删键重试 / OOM 与加载失败持续尝试）。

llama_cpp / transformers / torch / psutil 全部以替身注入，不加载真实模型、
不使用 GPU、不发网络请求；所有文件 IO 落在 pytest 的 tmp_path 内。
"""
from __future__ import annotations

import sys
import types

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
# _load_gguf_model —— 基础路径与重试
# --------------------------------------------------------------------------- #

def test_gguf_returns_false_without_llama_cpp(monkeypatch):
    """llama_cpp 未安装 → 直接返回 False（仅写日志，不落 _last_load_error）。"""
    monkeypatch.setattr(model_loader, "Llama", None)
    module = _FakeModule(text_model_path="model.gguf")
    assert ModelLoader(module)._load_gguf_model() is False
    assert module._last_load_error is None


def test_gguf_blocked_by_memory_pressure(monkeypatch):
    """内存压力为真 → 阻止加载并写回内存错误。"""
    monkeypatch.setattr(model_loader, "Llama", object)
    loader = _gguf_loader(
        monkeypatch,
        module=_FakeModule(text_model_path="model.gguf"),
        mem_pressure=(True, 98.5),
        threshold=96.0,
    )
    assert loader._load_gguf_model() is False
    assert "系统内存占用过高" in loader.module._last_load_error


def test_gguf_returns_false_on_invalid_header(monkeypatch):
    """文件头校验失败 → 原样记录错误并返回 False。"""
    monkeypatch.setattr(model_loader, "Llama", object)
    loader = _gguf_loader(
        monkeypatch,
        module=_FakeModule(text_model_path="model.gguf"),
        header=(False, "bad header"),
    )
    assert loader._load_gguf_model() is False
    assert loader.module._last_load_error == "bad header"


def test_gguf_success_on_cpu_without_health_check(monkeypatch):
    """n_gpu_layers=0 且 llama_cpp 可导入 → 加载成功且跳过 GPU 健康检查。"""
    llama_cls = _fake_llama_class(lambda kwargs, index: None)
    monkeypatch.setattr(model_loader, "Llama", llama_cls)
    fake_llama_cpp = types.ModuleType("llama_cpp")
    fake_llama_cpp.__version__ = "0.0.0-test"
    fake_llama_cpp.__file__ = "<test>"
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_llama_cpp)

    config = {}
    module = _FakeModule(
        config=config,
        settings=_FakeSettings(model=_Attrs(use_mmap=True, ram_mirror_offload=False)),
        text_model_path="model.gguf",
    )
    loader = _gguf_loader(monkeypatch, module=module, candidates=[0])

    assert loader._load_gguf_model() is True
    assert module.is_loaded is True
    assert module.is_gguf is True
    assert config["n_ctx"] == 2048
    assert config["n_batch"] == 256
    assert config["n_gpu_layers"] == 0
    assert len(llama_cls.calls) == 1
    assert llama_cls.calls[0]["model_path"] == "model.gguf"


def test_gguf_dedupes_use_mmap_candidates(monkeypatch):
    """ram_mirror_offload 让两个 use_mmap 候选归一 → 第二个 key 被去重跳过。"""
    def _behavior(kwargs, index):
        if index == 0:
            raise RuntimeError("transient backend hiccup")

    llama_cls = _fake_llama_class(_behavior)
    monkeypatch.setattr(model_loader, "Llama", llama_cls)

    module = _FakeModule(
        settings=_FakeSettings(
            model=_Attrs(use_mmap=None, ram_mirror_offload=True)
        ),
        text_model_path="model.gguf",
    )
    monkeypatch.setattr(model_loader, "psutil", _FakePsutil(percent=50.0))
    loader = _gguf_loader(monkeypatch, module=module, candidates=[0])

    assert loader._load_gguf_model() is True
    # 第一次失败后，第二个 use_mmap 候选被 resolve 成同一 key 而跳过
    assert len(llama_cls.calls) == 2
    assert llama_cls.calls[0]["use_mmap"] is False
    assert llama_cls.calls[1]["use_mmap"] is False


def test_gguf_tolerates_settings_attribute_errors(monkeypatch):
    """settings.model 读 use_mmap / ram_mirror_offload 抛错 → 走默认值。"""
    llama_cls = _fake_llama_class(lambda kwargs, index: None)
    monkeypatch.setattr(model_loader, "Llama", llama_cls)
    monkeypatch.setattr(model_loader, "psutil", _FakePsutil(percent=50.0))

    module = _FakeModule(
        settings=_FakeSettings(model=_RaisingUseMmap()),
        text_model_path="model.gguf",
    )
    loader = _gguf_loader(monkeypatch, module=module, candidates=[0])

    assert loader._load_gguf_model() is True
    assert llama_cls.calls[0]["use_mmap"] is True


def test_gguf_retries_after_unexpected_keyword(monkeypatch):
    """TypeError 提示 unexpected keyword → 弹掉该参数后重试成功。"""
    def _behavior(kwargs, index):
        if index == 0:
            raise TypeError(
                "Llama.__init__() got an unexpected keyword argument 'flash_attn'"
            )

    llama_cls = _fake_llama_class(_behavior)
    monkeypatch.setattr(model_loader, "Llama", llama_cls)
    module = _FakeModule(text_model_path="model.gguf")
    loader = _gguf_loader(monkeypatch, module=module, candidates=[0])

    assert loader._load_gguf_model() is True
    assert len(llama_cls.calls) == 2
    assert "flash_attn" in llama_cls.calls[0]
    assert "flash_attn" not in llama_cls.calls[1]


def test_gguf_fails_when_typeerror_has_no_removable_keyword(monkeypatch):
    """TypeError 无法匹配可弹参数 → 直接抛出并被外层捕获，最终返回 False。"""
    def _behavior(kwargs, index):
        raise TypeError("unrelated TypeError from the backend")

    llama_cls = _fake_llama_class(_behavior)
    monkeypatch.setattr(model_loader, "Llama", llama_cls)
    monkeypatch.setattr(model_loader, "get_torch", lambda: None)

    module = _BlockedResetModule(text_model_path="model.gguf")
    loader = _gguf_loader(monkeypatch, module=module, candidates=[0])

    assert loader._load_gguf_model() is False
    assert "GGUF模型加载失败" in module._last_load_error
    assert module.is_loaded is False


def test_gguf_aborts_on_invalid_vector_subscript(monkeypatch):
    """加载抛 invalid vector subscript → 立即返回 False，不再尝试其它候选。"""
    def _behavior(kwargs, index):
        raise RuntimeError("invalid vector subscript at layer 3")

    llama_cls = _fake_llama_class(_behavior)
    monkeypatch.setattr(model_loader, "Llama", llama_cls)
    module = _FakeModule(text_model_path="model.gguf")
    loader = _gguf_loader(monkeypatch, module=module, candidates=[0])

    assert loader._load_gguf_model() is False
    assert "invalid vector subscript" in module._last_load_error
    assert len(llama_cls.calls) == 1


def test_gguf_cuda_backend_error_falls_back_to_cpu(monkeypatch):
    """GPU 加载触发 CUDA 后端错误 → 强制 CPU，跳过非零层候选后成功。"""
    def _behavior(kwargs, index):
        if int(kwargs["n_gpu_layers"]) != 0:
            raise RuntimeError("ggml-cuda error: failed to launch kernel")

    llama_cls = _fake_llama_class(_behavior)
    monkeypatch.setattr(model_loader, "Llama", llama_cls)
    fake_torch = _FakeTorch(available=True)
    monkeypatch.setattr(model_loader, "get_torch", lambda: fake_torch)

    config = {}
    module = _FakeModule(config=config, text_model_path="model.gguf")
    loader = _gguf_loader(
        monkeypatch, module=module, params=dict(_DEFAULT_PARAMS, n_gpu_layers=8),
        candidates=[8, 4, 0],
    )

    assert loader._load_gguf_model() is True
    assert config["n_gpu_layers"] == 0
    assert module.is_loaded is True
    assert fake_torch.cuda.empty_cache_calls >= 1
    # 8 层失败 → 4 层被 force_cpu_only 跳过 → 0 层成功
    assert [call["n_gpu_layers"] for call in llama_cls.calls] == [8, 0]


def test_gguf_oom_error_keeps_trying_then_fails(monkeypatch):
    """OOM 错误 → 继续尝试下一个候选，全部失败后返回 False。"""
    def _behavior(kwargs, index):
        raise RuntimeError("CUDA out of memory while allocating")

    llama_cls = _fake_llama_class(_behavior)
    monkeypatch.setattr(model_loader, "Llama", llama_cls)
    monkeypatch.setattr(model_loader, "psutil", _FakePsutil(percent=50.0))
    module = _FakeModule(text_model_path="model.gguf")
    loader = _gguf_loader(monkeypatch, module=module, candidates=[0])

    assert loader._load_gguf_model() is False
    # 2 个候选 × 2 个 use_mmap 取值，全部因 OOM 被 continue 跳过
    assert len(llama_cls.calls) == 4
    assert "GGUF模型加载失败" in module._last_load_error


def test_gguf_model_load_error_keeps_trying_then_fails(monkeypatch):
    """模型文件类加载错误 → 继续尝试下一个候选，全部失败后返回 False。"""
    def _behavior(kwargs, index):
        raise RuntimeError("failed to load model from file: bad tensor")

    llama_cls = _fake_llama_class(_behavior)
    monkeypatch.setattr(model_loader, "Llama", llama_cls)
    monkeypatch.setattr(model_loader, "psutil", _FakePsutil(percent=50.0))
    module = _FakeModule(text_model_path="model.gguf")
    loader = _gguf_loader(monkeypatch, module=module, candidates=[0])

    assert loader._load_gguf_model() is False
    assert len(llama_cls.calls) == 4

