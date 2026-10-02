"""ModelLoader 核心逻辑单测。

覆盖范围：``__init__`` / ``_get_memory_block_threshold`` / ``_check_memory_pressure``
/ ``_calculate_thread_count`` / ``_get_model_params``。

全部依赖以替身注入：不加载真实模型、不使用 GPU、不发网络请求、不写仓库内文件。
"""
from __future__ import annotations

import os

from core.modules.llm.model_loader import ModelLoader


class _Attrs:
    """极简属性容器：构造参数即属性，缺失属性走 AttributeError。"""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Raising:
    """任意属性访问都抛 RuntimeError，用于覆盖 getattr 的 except 兜底分支。"""

    def __getattr__(self, name):
        raise RuntimeError(f"attr {name} boom")


class _NoEmergencyThreshold:
    """``llm_load_memory_block_threshold`` 缺失（→ None），

    而 ``memory_emergency_threshold`` 访问时抛 RuntimeError。
    """

    def __getattr__(self, name):
        if name == "memory_emergency_threshold":
            raise RuntimeError("memory_emergency_threshold boom")
        raise AttributeError(name)


class _PartialRaisingModel:
    """仅 ``force_cpu_inference`` 抛 RuntimeError，其余属性缺失走默认值。"""

    def __getattr__(self, name):
        if name == "force_cpu_inference":
            raise RuntimeError("force_cpu_inference boom")
        raise AttributeError(name)


class _FakeSettings:
    """settings 替身：只需要 ``model`` 与 ``immune`` 两个子配置。"""

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


def _loader(config=None, settings=None, **kwargs):
    """构造一个挂了替身 module 的 ModelLoader。"""
    return ModelLoader(_FakeModule(config=config, settings=settings, **kwargs))


# --------------------------------------------------------------------------- #
# __init__
# --------------------------------------------------------------------------- #
def test_init_keeps_module_reference():
    """__init__ 只保存 module 引用，不做其他副作用。"""
    module = _FakeModule()
    loader = ModelLoader(module)
    assert loader.module is module


# --------------------------------------------------------------------------- #
# _get_memory_block_threshold
# --------------------------------------------------------------------------- #
def test_threshold_uses_dedicated_key_when_present():
    """优先取 llm_load_memory_block_threshold。"""
    settings = _FakeSettings(immune=_Attrs(llm_load_memory_block_threshold=95.5))
    assert _loader(settings=settings)._get_memory_block_threshold() == 95.5


def test_threshold_falls_back_to_emergency_threshold():
    """专用键缺失（getattr 默认 None）时回退 memory_emergency_threshold。"""
    settings = _FakeSettings(immune=_Attrs(memory_emergency_threshold=88.0))
    assert _loader(settings=settings)._get_memory_block_threshold() == 88.0


def test_threshold_uses_97_when_emergency_lookup_raises():
    """专用键缺失且 emergency 键访问抛异常 → 兜底 97.0。"""
    settings = _FakeSettings(immune=_NoEmergencyThreshold())
    assert _loader(settings=settings)._get_memory_block_threshold() == 97.0


def test_threshold_uses_97_when_all_getattr_raises():
    """两次 getattr 都抛非 AttributeError 异常 → 兜底 97.0。"""
    settings = _FakeSettings(immune=_Raising())
    assert _loader(settings=settings)._get_memory_block_threshold() == 97.0


def test_threshold_uses_97_when_value_not_floatable():
    """取到的值无法转 float（如字符串）→ 兜底 97.0。"""
    settings = _FakeSettings(immune=_Attrs(llm_load_memory_block_threshold="abc"))
    assert _loader(settings=settings)._get_memory_block_threshold() == 97.0


# --------------------------------------------------------------------------- #
# _check_memory_pressure
# --------------------------------------------------------------------------- #
class _FakePsutil:
    """psutil 替身：可控 virtual_memory().percent 或直接抛错。"""

    def __init__(self, percent=None, error=None):
        self._percent = percent
        self._error = error

    def virtual_memory(self):
        if self._error is not None:
            raise self._error
        return _Attrs(percent=self._percent)


def test_memory_pressure_false_when_plenty_of_memory(monkeypatch):
    """内存占用低于阈值 → (False, 实际占用)。"""
    import core.modules.llm.model_loader as model_loader

    monkeypatch.setattr(model_loader, "psutil", _FakePsutil(percent=41.5))
    loader = _loader(settings=_FakeSettings(immune=_Attrs(memory_emergency_threshold=96.0)))
    assert loader._check_memory_pressure() == (False, 41.5)


def test_memory_pressure_true_when_over_threshold(monkeypatch):
    """内存占用达到阈值 → (True, 实际占用)。"""
    import core.modules.llm.model_loader as model_loader

    monkeypatch.setattr(model_loader, "psutil", _FakePsutil(percent=99.0))
    loader = _loader(settings=_FakeSettings(immune=_Attrs(memory_emergency_threshold=96.0)))
    assert loader._check_memory_pressure() == (True, 99.0)


def test_memory_pressure_returns_false_without_psutil(monkeypatch):
    """psutil 未安装（None）→ (False, 0.0)。"""
    import core.modules.llm.model_loader as model_loader

    monkeypatch.setattr(model_loader, "psutil", None)
    assert _loader()._check_memory_pressure() == (False, 0.0)


def test_memory_pressure_swallows_psutil_error(monkeypatch):
    """取内存数据抛异常 → 走 except，返回 (False, 0.0)。"""
    import core.modules.llm.model_loader as model_loader

    monkeypatch.setattr(
        model_loader, "psutil", _FakePsutil(error=RuntimeError("no /proc"))
    )
    assert _loader()._check_memory_pressure() == (False, 0.0)


# --------------------------------------------------------------------------- #
# _calculate_thread_count
# --------------------------------------------------------------------------- #
def test_thread_count_prefers_explicit_config():
    """config.n_threads 为正整数时直接采用，不读 cpu_count。"""
    loader = _loader(config={"n_threads": 8})
    assert loader._calculate_thread_count() == 8


def test_thread_count_accepts_numeric_string_config():
    """config.n_threads 为数字字符串时也能转换。"""
    loader = _loader(config={"n_threads": "6"})
    assert loader._calculate_thread_count() == 6


def test_thread_count_uses_cpu_count_minus_two(monkeypatch):
    """未配置线程数 → 物理核数 - 2。"""
    monkeypatch.setattr(os, "cpu_count", lambda: 10)
    assert _loader()._calculate_thread_count() == 8


def test_thread_count_never_below_one(monkeypatch):
    """核数过小时保底 1 线程。"""
    monkeypatch.setattr(os, "cpu_count", lambda: 1)
    assert _loader()._calculate_thread_count() == 1


def test_thread_count_defaults_to_four_without_cpu_info(monkeypatch):
    """cpu_count 返回 None → 兜底 4。"""
    monkeypatch.setattr(os, "cpu_count", lambda: None)
    assert _loader()._calculate_thread_count() == 4


def test_thread_count_defaults_to_four_when_cpu_count_raises(monkeypatch):
    """cpu_count 抛异常 → 兜底 4。"""

    def _boom():
        raise OSError("no cpu info")

    monkeypatch.setattr(os, "cpu_count", _boom)
    assert _loader()._calculate_thread_count() == 4


def test_thread_count_falls_back_when_config_value_invalid(monkeypatch):
    """config.n_threads 无法转 int → 视为 0，再走 cpu_count 分支。"""
    monkeypatch.setattr(os, "cpu_count", lambda: 6)
    assert _loader(config={"n_threads": "many"})._calculate_thread_count() == 4


def test_thread_count_falls_back_when_config_not_mapping():
    """config.get 本身抛异常 → desired 归零后走 cpu_count（真实核数，不做数值断言）。"""
    class _BadConfig(dict):
        def get(self, key, default=None):
            raise RuntimeError("config boom")

    value = _loader(config=_BadConfig())._calculate_thread_count()
    assert value >= 1


# --------------------------------------------------------------------------- #
# _get_model_params
# --------------------------------------------------------------------------- #
def test_model_params_reads_everything_from_config():
    """config 提供全部键时全部以 config 为准。"""
    config = {
        "flash_attn": True,
        "offload_kqv": True,
        "n_gpu_layers": 12,
        "n_ctx": 4096,
        "n_batch": 256,
    }
    params = _loader(config=config)._get_model_params()
    assert params == {
        "flash_attn": True,
        "offload_kqv": True,
        "n_gpu_layers": 12,
        "n_ctx": 4096,
        "n_batch": 256,
        "force_cpu": False,
    }


def test_model_params_falls_back_to_settings_model():
    """config 为空时全部读 settings.model。"""
    settings = _FakeSettings(
        model=_Attrs(
            flash_attn=True,
            offload_kqv=False,
            n_gpu_layers=5,
            n_ctx=2048,
            n_batch=128,
        )
    )
    params = _loader(config={}, settings=settings)._get_model_params()
    assert params == {
        "flash_attn": True,
        "offload_kqv": False,
        "n_gpu_layers": 5,
        "n_ctx": 2048,
        "n_batch": 128,
        "force_cpu": False,
    }


def test_model_params_treats_explicit_none_as_missing():
    """config 里显式 None 视同缺失，回退 settings.model。"""
    settings = _FakeSettings(
        model=_Attrs(flash_attn=True, offload_kqv=True, n_ctx=1024, n_batch=64)
    )
    config = {"flash_attn": None, "offload_kqv": None}
    params = _loader(config=config, settings=settings)._get_model_params()
    assert params["flash_attn"] is True
    assert params["offload_kqv"] is True
    assert params["n_ctx"] == 1024


def test_model_params_force_cpu_overrides_gpu_layers():
    """force_cpu_inference=True → n_gpu_layers 归零并写回 config。"""
    settings = _FakeSettings(model=_Attrs(force_cpu_inference=True, n_gpu_layers=20))
    config = {"n_gpu_layers": 20}
    params = _loader(config=config, settings=settings)._get_model_params()
    assert params["force_cpu"] is True
    assert params["n_gpu_layers"] == 0
    assert config["n_gpu_layers"] == 0


def test_model_params_swallows_force_cpu_lookup_error():
    """读 force_cpu_inference 抛异常 → 视为 False，其余走默认值。"""
    settings = _FakeSettings(model=_PartialRaisingModel())
    params = _loader(config={}, settings=settings)._get_model_params()
    assert params["force_cpu"] is False
    assert params["n_gpu_layers"] == -1
    assert params["n_ctx"] == 4096
    assert params["n_batch"] == 512


def test_model_params_caps_n_ctx_at_8192():
    """n_ctx 超过 8192 时被截断到 8192。"""
    params = _loader(config={"n_ctx": 16384, "n_batch": 64})._get_model_params()
    assert params["n_ctx"] == 8192


def test_model_params_derives_n_batch_from_ctx_when_unset():
    """settings.n_batch 为 None → min(512, n_ctx)。"""
    settings = _FakeSettings(model=_Attrs(n_ctx=256, n_batch=None))
    params = _loader(config={}, settings=settings)._get_model_params()
    assert params["n_batch"] == 256


def test_model_params_derives_n_batch_when_non_positive():
    """settings.n_batch <= 0 → min(512, n_ctx)。"""
    settings = _FakeSettings(model=_Attrs(n_ctx=3000, n_batch=0))
    params = _loader(config={}, settings=settings)._get_model_params()
    assert params["n_batch"] == 512


def test_model_params_uses_ctx_when_config_ctx_falsy():
    """config.n_ctx 为 0（falsy）→ 回退 settings.n_ctx。"""
    settings = _FakeSettings(model=_Attrs(n_ctx=3000, n_batch=128))
    params = _loader(config={"n_ctx": 0}, settings=settings)._get_model_params()
    assert params["n_ctx"] == 3000


def test_model_params_clamps_n_batch_to_n_ctx():
    """config.n_batch 大于 n_ctx 时被压到 n_ctx。"""
    params = _loader(config={"n_ctx": 1024, "n_batch": 4096})._get_model_params()
    assert params["n_ctx"] == 1024
    assert params["n_batch"] == 1024
