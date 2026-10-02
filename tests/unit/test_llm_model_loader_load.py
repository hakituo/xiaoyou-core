"""ModelLoader 加载流程单测。

覆盖范围：``_verify_gguf_header`` / ``load_sync`` / ``_load_transformers_model``；
``_load_gguf_model`` 拆到 ``test_llm_model_loader_gguf.py`` 与同族 ``_gguf_fallback``。

llama_cpp / transformers / torch / psutil 全部以替身注入，不加载真实模型、
不使用 GPU、不发网络请求；所有文件 IO 落在 pytest 的 tmp_path 内。
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

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
# _verify_gguf_header
# --------------------------------------------------------------------------- #
def test_verify_gguf_header_accepts_correct_magic(tmp_path):
    """文件头为 b"GGUF" → 有效且无错误消息。"""
    path = tmp_path / "model.gguf"
    path.write_bytes(b"GGUF" + b"\x00" * 12)
    assert _loader()._verify_gguf_header(str(path)) == (True, "")


def test_verify_gguf_header_rejects_wrong_magic(tmp_path):
    """magic 不是 b"GGUF" → 无效并返回损坏提示。"""
    path = tmp_path / "model.gguf"
    path.write_bytes(b"XXXX" + b"\x00" * 12)
    valid, message = _loader()._verify_gguf_header(str(path))
    assert valid is False
    assert "GGUF模型文件头异常" in message


def test_verify_gguf_header_rejects_truncated_file(tmp_path):
    """文件短于 4 字节 → read(4) 拿到的不是 magic。"""
    path = tmp_path / "short.gguf"
    path.write_bytes(b"GG")
    valid, message = _loader()._verify_gguf_header(str(path))
    assert valid is False
    assert message


def test_verify_gguf_header_reports_missing_file(tmp_path):
    """文件不存在 → 走 except 分支返回读取失败。"""
    missing = tmp_path / "absent.gguf"
    valid, message = _loader()._verify_gguf_header(str(missing))
    assert valid is False
    assert "读取GGUF模型文件失败" in message


# --------------------------------------------------------------------------- #
# load_sync
# --------------------------------------------------------------------------- #
def test_load_sync_errors_when_model_missing(tmp_path):
    """路径不存在 → 记录 model_not_found 并返回 False。"""
    module = _FakeModule(text_model_path=str(tmp_path / "absent.gguf"))
    result = ModelLoader(module).load_sync()
    assert result is False
    assert module.is_gguf is True
    assert "模型路径不存在" in module._last_load_error


def test_load_sync_dispatches_to_gguf(tmp_path, monkeypatch):
    """以 .gguf 结尾且文件存在 → 走 _load_gguf_model。"""
    path = tmp_path / "model.gguf"
    path.write_bytes(b"GGUF")
    module = _FakeModule(text_model_path=str(path))
    loader = ModelLoader(module)
    monkeypatch.setattr(loader, "_load_gguf_model", lambda: True)
    assert loader.load_sync() is True
    assert module.is_gguf is True
    assert module._last_load_error is None


def test_load_sync_dispatches_to_transformers(tmp_path, monkeypatch):
    """非 .gguf 且文件存在 → 走 _load_transformers_model。"""
    path = tmp_path / "model.bin"
    path.write_bytes(b"binary")
    module = _FakeModule(text_model_path=str(path))
    loader = ModelLoader(module)
    monkeypatch.setattr(loader, "_load_transformers_model", lambda: True)
    assert loader.load_sync() is True
    assert module.is_gguf is False


def test_load_sync_maps_invalid_vector_subscript_error(tmp_path, monkeypatch):
    """底层抛 invalid vector subscript → 使用专用错误消息。"""
    path = tmp_path / "model.gguf"
    path.write_bytes(b"GGUF")
    module = _FakeModule(text_model_path=str(path))
    loader = ModelLoader(module)

    def _boom():
        raise RuntimeError("invalid vector subscript")

    monkeypatch.setattr(loader, "_load_gguf_model", _boom)
    assert loader.load_sync() is False
    assert "invalid vector subscript" in module._last_load_error


def test_load_sync_maps_generic_error(tmp_path, monkeypatch):
    """其它异常 → 使用通用 load_failed 错误消息。"""
    path = tmp_path / "model.gguf"
    path.write_bytes(b"GGUF")
    module = _FakeModule(text_model_path=str(path))
    loader = ModelLoader(module)

    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(loader, "_load_gguf_model", _boom)
    assert loader.load_sync() is False
    assert "加载文本模型失败" in module._last_load_error


# --------------------------------------------------------------------------- #
# _load_transformers_model
# --------------------------------------------------------------------------- #
def test_transformers_returns_false_without_transformers(monkeypatch):
    """transformers 未安装 → 返回 False（仅写日志，不落 _last_load_error）。"""
    monkeypatch.setattr(model_loader, "AutoModelForCausalLM", None)
    module = _FakeModule(text_model_path="model_dir")
    assert ModelLoader(module)._load_transformers_model() is False
    assert module._last_load_error is None


def test_transformers_returns_false_without_torch(monkeypatch):
    """torch 不可用 → 返回 False（仅写日志，不落 _last_load_error）。"""
    monkeypatch.setattr(model_loader, "get_torch", lambda: None)
    module = _FakeModule(text_model_path="model_dir")
    assert ModelLoader(module)._load_transformers_model() is False
    assert module._last_load_error is None


def test_transformers_loads_model_and_tokenizer(monkeypatch):
    """正常路径：加载 tokenizer + model 并搬到 CPU。"""
    tokenizer_cls = MagicMock()
    tokenizer_cls.from_pretrained.return_value = "fake-tokenizer"
    model_cls = MagicMock()
    model_obj = MagicMock()
    model_obj.to.return_value = "model-on-cpu"
    model_cls.from_pretrained.return_value = model_obj

    monkeypatch.setattr(model_loader, "AutoTokenizer", tokenizer_cls)
    monkeypatch.setattr(model_loader, "AutoModelForCausalLM", model_cls)
    monkeypatch.setattr(model_loader, "get_torch", lambda: _FakeTorch())

    module = _FakeModule(text_model_path="model_dir", is_gguf=True)
    assert ModelLoader(module)._load_transformers_model() is True
    assert module.is_gguf is False
    assert module.tokenizer == "fake-tokenizer"
    assert module.model == "model-on-cpu"
    assert module.is_loaded is True

    tokenizer_cls.from_pretrained.assert_called_once_with(
        "model_dir", local_files_only=True
    )
    model_cls.from_pretrained.assert_called_once_with(
        "model_dir",
        low_cpu_mem_usage=True,
        local_files_only=True,
        torch_dtype="float32",
    )
    model_obj.to.assert_called_once_with("cpu")


# --------------------------------------------------------------------------- #
# 模块级可选依赖兜底
# --------------------------------------------------------------------------- #
def test_module_level_optional_imports_fall_back_to_none(monkeypatch):
    """psutil / transformers 缺失时，模块级 try-import 应落到 None 兜底。

    通过 ``sys.modules[name] = None`` 让 import 直接抛 ImportError，再用
    ``spec_from_file_location`` 把被测文件加载成**独立模块对象**执行，
    避免污染真实模块的全局状态。
    """
    import importlib.util

    probe_name = "core.modules.llm._model_loader_import_probe"
    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setitem(sys.modules, "transformers.models.auto.modeling_auto", None)
    monkeypatch.setitem(sys.modules, "transformers.models.auto.tokenization_auto", None)

    spec = importlib.util.spec_from_file_location(probe_name, model_loader.__file__)
    probe = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, probe_name, probe)
    spec.loader.exec_module(probe)

    assert probe.psutil is None
    assert probe.AutoModelForCausalLM is None
    assert probe.AutoTokenizer is None
    # 真实模块的全局状态不受探针影响
    assert model_loader.psutil is not None
    assert model_loader.AutoModelForCausalLM is not None
