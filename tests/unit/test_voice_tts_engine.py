"""core/voice/tts_engine.py 单元测试。

覆盖范围：
- ``TTSManager`` 单例（``__new__`` 的 double-check、``__init__`` 幂等）与 ``get_tts_manager`` 工厂
- ``device`` 属性的 getter / setter 各回退分支
- ``initialize()`` 的 7 类 provider 分发、模型与 base_url 默认值、失败回退、「全失败不标记已初始化」
- ``_register_resource_manager_safely`` 的逐层安全降级
- ``handle_resource_pressure`` / ``move_to_cpu`` / ``move_to_gpu`` / ``_ensure_optimal_device``
- ``synthesize`` / ``synthesize_bytes`` 的连接错误回退与引擎还原
- ``shutdown`` / ``switch_engine``

全部使用替身引擎与桩配置：不加载 torch / qwen_tts，不创建真实资源管理器，不发网络请求。
"""

from __future__ import annotations

import sys

import numpy as np
import pytest

import core.resource_manager as resource_manager_mod
import core.voice.engines as engines_pkg
from core.voice import tts_engine as te


# ============================================================
# 桩：配置 / 引擎 / 资源管理器
# ============================================================

class _TTSConfigStub:
    """``settings.voice.tts`` 替身。``model_extra`` 模拟 pydantic v2 的额外字段容器。"""

    def __init__(self, provider="cloud", model=None, base_url=None, api_key="key",
                 model_extra=None, **attrs):
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.model_extra = dict(model_extra or {})
        for key, value in attrs.items():
            setattr(self, key, value)


class _VoiceStub:
    def __init__(self, tts_config, tts_engine):
        self.tts = tts_config
        self.tts_engine = tts_engine


class _SettingsStub:
    def __init__(self, tts_config, tts_engine="qwen3"):
        self.voice = _VoiceStub(tts_config, tts_engine)


def make_engine_cls(record, *, name="stub", fail_init=False, device="cpu",
                    move_cpu_result=True, move_gpu_result=True,
                    synth_result=None, synth_exc=None,
                    bytes_result=b"audio", bytes_exc=None,
                    has_move_cpu=True, has_move_gpu=True, has_bytes=True):
    """生成替身引擎类，行为由参数控制，调用痕迹写进 ``record``。"""

    class _Stub:
        def __init__(self, **kwargs):
            record.setdefault("ctor", []).append({"name": name, **kwargs})
            self.current_device = device

        async def initialize(self):
            if fail_init:
                raise RuntimeError(f"{name} 初始化失败")
            record.setdefault("initialized", []).append(name)

        async def shutdown(self):
            record.setdefault("shutdown", []).append(name)

        async def synthesize(self, text, **kwargs):
            record.setdefault("synthesize", []).append((name, text, kwargs))
            if synth_exc is not None:
                raise synth_exc
            if synth_result is not None:
                return synth_result
            return np.zeros(3, dtype=np.float32)

        if has_bytes:
            async def synthesize_bytes(self, text, **kwargs):
                record.setdefault("synthesize_bytes", []).append((name, text, kwargs))
                if bytes_exc is not None:
                    raise bytes_exc
                return bytes_result

        if has_move_cpu:
            async def move_to_cpu(self):
                record.setdefault("move_to_cpu", []).append(name)
                return move_cpu_result

        if has_move_gpu:
            async def move_to_gpu(self):
                record.setdefault("move_to_gpu", []).append(name)
                return move_gpu_result

    _Stub.__name__ = name
    return _Stub


class _MonitorStub:
    def __init__(self, pressure):
        self._pressure = pressure
        self.asked = []

    def is_resource_pressure(self, resource_type):
        self.asked.append(resource_type)
        return self._pressure


class _ResourceManagerStub:
    """资源管理器替身；``register_model_raises`` 用于覆盖注册失败被吞的分支。"""

    def __init__(self, *, pressure=False, free_mb=99999, register_model_raises=False,
                 raise_on_free_mb=False):
        self.monitor = _MonitorStub(pressure)
        self.models = []
        self.handlers = []
        self._free_mb = free_mb
        self._register_model_raises = register_model_raises
        self._raise_on_free_mb = raise_on_free_mb

    def register_model(self, **kwargs):
        self.models.append(kwargs)
        if self._register_model_raises:
            raise RuntimeError("注册模型失败")

    def register_resource_handler(self, *args):
        self.handlers.append(args)

    async def get_gpu_free_mb(self):
        if self._raise_on_free_mb:
            raise RuntimeError("显存查询失败")
        return self._free_mb


class _FakeTorch:
    """替身 torch，避免真实 CUDA 探测。"""

    def __init__(self, cuda_available):
        self.cuda = type("_Cuda", (), {"is_available": staticmethod(lambda: cuda_available)})


@pytest.fixture(autouse=True)
def _reset_singletons(monkeypatch):
    """每个用例前重置两处单例状态，避免用例间互相污染。"""
    monkeypatch.setattr(te.TTSManager, "_instance", None)
    monkeypatch.setattr(te, "_tts_manager_instance", None)


@pytest.fixture
def tts_config():
    return _TTSConfigStub()


@pytest.fixture
def manager(monkeypatch, tts_config):
    monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
    return te.TTSManager()


def _patch_engine(monkeypatch, name, engine_cls):
    """把 core.voice.engines 里的某个引擎类换成替身（函数体内 import 会重新查属性）。"""
    monkeypatch.setattr(engines_pkg, name, engine_cls)


# ============================================================
# 单例
# ============================================================

class TestSingleton:
    """单例与幂等：重复构造不能重复初始化。"""

    def test_repeated_construction_returns_same_instance(self, monkeypatch, tts_config):
        calls = []
        monkeypatch.setattr(te, "get_settings", lambda: calls.append(1) or _SettingsStub(tts_config))

        first = te.TTSManager()
        second = te.TTSManager()

        assert first is second
        # __init__ 幂等：第二次构造不能再读一次配置
        assert calls == [1]

    def test_new_double_check_returns_instance_appearing_under_lock(self, monkeypatch):
        """锁内二次确认分支：拿锁期间别人已建好实例时直接复用，不覆盖。

        注意 ``__new__`` 返回已存在实例后 Python 仍会调用 ``__init__``，
        所以这个「抢先建好的」实例必须带上 ``_initialized_manager`` 标记
        （真实场景里它本来就已经初始化过），否则会走进初始化流程。
        """
        existing = object.__new__(te.TTSManager)
        existing._initialized_manager = True

        class _Lock:
            def __enter__(self):
                te.TTSManager._instance = existing
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(te.TTSManager, "_instance_lock", _Lock())

        assert te.TTSManager() is existing

    def test_get_tts_manager_is_singleton(self, monkeypatch, tts_config):
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))

        assert te.get_tts_manager() is te.get_tts_manager()

    def test_get_tts_manager_double_check_under_lock(self, monkeypatch):
        """工厂函数锁内二次确认分支。"""
        existing = object.__new__(te.TTSManager)

        class _Lock:
            def __enter__(self):
                monkeypatch.setattr(te, "_tts_manager_instance", existing)
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(te, "_tts_manager_lock", _Lock())

        assert te.get_tts_manager() is existing


# ============================================================
# device 属性
# ============================================================

class TestDeviceProperty:
    """device getter 的三级回退与 setter 的归一化。"""

    def test_getter_prefers_engine_device(self, manager):
        manager.engine = type("_E", (), {"current_device": "cuda"})()
        manager.current_device = "cpu"

        assert manager.device == "cuda"

    def test_getter_falls_back_to_manager_when_engine_device_empty(self, manager):
        manager.engine = type("_E", (), {"current_device": ""})()
        manager.current_device = "cuda"

        assert manager.device == "cuda"

    def test_getter_falls_back_to_cpu_when_nothing_recorded(self, manager):
        assert manager.device == "cpu"

    def test_getter_ignores_engine_without_device_attr(self, manager):
        manager.engine = object()
        manager.current_device = "cuda"

        assert manager.device == "cuda"

    def test_setter_normalizes_and_blanks_to_none(self, manager):
        manager.device = "  CUDA "
        assert manager.current_device == "cuda"

        manager.device = ""
        assert manager.current_device is None

        manager.device = None
        assert manager.current_device is None


# ============================================================
# initialize：provider 分发
# ============================================================

class TestInitialize:
    """7 类 provider 的分发、默认值填充与失败回退。"""

    async def test_returns_early_when_already_initialized(self, manager, monkeypatch):
        record = {}
        _patch_engine(monkeypatch, "CloudTTSEngine", make_engine_cls(record))
        sentinel = object()
        manager.initialized = True
        manager.engine = sentinel

        await manager.initialize()

        assert manager.engine is sentinel
        assert "ctor" not in record

    async def test_legacy_tts_engine_overrides_local_provider(
        self, monkeypatch, tts_config
    ):
        """旧配置兼容：provider=local 但 tts_engine=cloud 时走云端分支。"""
        tts_config.provider = "local"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config, tts_engine="cloud"))
        record = {}
        _patch_engine(monkeypatch, "CloudTTSEngine", make_engine_cls(record, name="cloud"))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert record["ctor"][0]["name"] == "cloud"
        assert mgr.initialized is True

    @pytest.mark.parametrize("model", ["", "default", "qwen3"])
    async def test_local_default_provider_normalizes_placeholder_model(
        self, monkeypatch, tts_config, model
    ):
        """local/default/auto 且 model 是占位值时不传 model_path。"""
        tts_config.provider = "local"
        tts_config.model = model
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "Qwen3TTSEngine", make_engine_cls(record, name="qwen3"))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert record["ctor"] == [{"name": "qwen3", "model_path": None}]

    async def test_local_default_provider_passes_custom_model(self, monkeypatch, tts_config):
        tts_config.provider = "auto"
        tts_config.model = "Qwen3-TTS-12Hz-0.6B-Base"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "Qwen3TTSEngine", make_engine_cls(record, name="qwen3"))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert record["ctor"] == [{"name": "qwen3", "model_path": "Qwen3-TTS-12Hz-0.6B-Base"}]

    async def test_local_default_provider_failure_keeps_uninitialized(
        self, monkeypatch, tts_config
    ):
        """默认 Qwen3 初始化失败：engine 置空、记 last_error、且不标记已初始化。"""
        tts_config.provider = "local"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(
            monkeypatch, "Qwen3TTSEngine", make_engine_cls(record, name="qwen3", fail_init=True)
        )
        registered = []
        monkeypatch.setattr(
            te.TTSManager, "_register_resource_manager_safely",
            lambda self: registered.append(1),
        )

        mgr = te.TTSManager()
        await mgr.initialize()

        assert mgr.engine is None
        assert mgr.initialized is False
        assert "Qwen3-TTS初始化失败" in mgr.last_error
        # 失败路径也要注册资源管理器，供按需重试
        assert registered == [1]

    async def test_gpt_sovits_success(self, monkeypatch, tts_config):
        tts_config.provider = "gpt_sovits"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "GPTSoVITSEngine", make_engine_cls(record, name="gptsovits"))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert mgr.initialized is True
        assert record["initialized"] == ["gptsovits"]
        assert mgr.last_error is None

    async def test_gpt_sovits_failure_records_error(self, monkeypatch, tts_config):
        tts_config.provider = "gpt_sovits"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        _patch_engine(
            monkeypatch, "GPTSoVITSEngine",
            make_engine_cls({}, name="gptsovits", fail_init=True),
        )

        mgr = te.TTSManager()
        await mgr.initialize()

        assert mgr.engine is None
        assert "GPT-SoVITS初始化失败" in mgr.last_error

    async def test_qwen3_provider_success(self, monkeypatch, tts_config):
        tts_config.provider = "qwen3"
        tts_config.model = "gpt_sovits"  # 占位值也要归一化成 None
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "Qwen3TTSEngine", make_engine_cls(record, name="qwen3"))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert record["ctor"] == [{"name": "qwen3", "model_path": None}]
        assert mgr.initialized is True

    async def test_qwen3_local_prefix_provider_success(self, monkeypatch, tts_config):
        tts_config.provider = "local:qwen3"
        tts_config.model = "my-qwen"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "Qwen3TTSEngine", make_engine_cls(record, name="qwen3"))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert record["ctor"] == [{"name": "qwen3", "model_path": "my-qwen"}]

    async def test_qwen3_provider_failure_uses_dedicated_error_message(
        self, monkeypatch, tts_config
    ):
        tts_config.provider = "qwen3"
        tts_config.model = "my-qwen"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        _patch_engine(
            monkeypatch, "Qwen3TTSEngine", make_engine_cls({}, name="qwen3", fail_init=True)
        )

        mgr = te.TTSManager()
        await mgr.initialize()

        assert "qwen_tts 是否已安装且模型路径存在" in mgr.last_error

    @pytest.mark.parametrize("provider", ["f5", "f5-tts", "local:f5"])
    async def test_f5_provider_success(self, monkeypatch, tts_config, provider):
        tts_config.provider = provider
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "F5TTSEngine", make_engine_cls(record, name="f5"))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert record["initialized"] == ["f5"]

    async def test_f5_provider_failure_records_error(self, monkeypatch, tts_config):
        tts_config.provider = "f5"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        _patch_engine(monkeypatch, "F5TTSEngine", make_engine_cls({}, name="f5", fail_init=True))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert "f5-tts 是否已安装且模型已下载" in mgr.last_error

    async def test_cloud_provider_passes_through_config(self, monkeypatch, tts_config):
        """cloud/custom 不填默认值，原样透传（含 None）。"""
        tts_config.provider = "custom"
        tts_config.model = "my-model"
        tts_config.base_url = "https://example.com/speech"
        tts_config.api_key = "sk-1"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "CloudTTSEngine", make_engine_cls(record, name="cloud"))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert record["ctor"] == [{
            "name": "cloud",
            "api_key": "sk-1",
            "base_url": "https://example.com/speech",
            "model": "my-model",
        }]

    async def test_siliconflow_provider_fills_defaults(self, monkeypatch, tts_config):
        tts_config.provider = "siliconflow"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "CloudTTSEngine", make_engine_cls(record, name="cloud"))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert record["ctor"][0]["model"] == "fishaudio/fish-speech-1.5"
        assert record["ctor"][0]["base_url"] == "https://api.siliconflow.cn/v1/audio/speech"

    async def test_siliconflow_provider_keeps_explicit_values(self, monkeypatch, tts_config):
        tts_config.provider = "siliconflow"
        tts_config.model = "explicit-model"
        tts_config.base_url = "https://my.endpoint/speech"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "CloudTTSEngine", make_engine_cls(record, name="cloud"))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert record["ctor"][0]["model"] == "explicit-model"
        assert record["ctor"][0]["base_url"] == "https://my.endpoint/speech"

    async def test_openai_provider_fills_defaults(self, monkeypatch, tts_config):
        tts_config.provider = "openai"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "CloudTTSEngine", make_engine_cls(record, name="cloud"))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert record["ctor"][0]["model"] == "tts-1"
        assert record["ctor"][0]["base_url"] == "https://api.openai.com/v1/audio/speech"

    async def test_cloud_provider_failure_records_error(self, monkeypatch, tts_config):
        tts_config.provider = "cloud"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        _patch_engine(
            monkeypatch, "CloudTTSEngine", make_engine_cls({}, name="cloud", fail_init=True)
        )

        mgr = te.TTSManager()
        await mgr.initialize()

        assert "云端TTS引擎初始化失败" in mgr.last_error

    @pytest.mark.parametrize("provider", ["volcano", "volcengine", "字节"])
    async def test_volcano_provider_reads_extra_config(self, monkeypatch, tts_config, provider):
        """火山分支要从 model_extra 里取 appid / voice_map / key_map / resource_id。"""
        tts_config.provider = provider
        tts_config.model = "volcano-model"
        tts_config.api_key = "vk"
        tts_config.base_url = "https://volc.example"
        tts_config.model_extra = {
            "voice_map": {"zh_female": "voice-1"},
            "key_map": {"a": "b"},
            "resource_id": "volc.megatts.default",
        }
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "VolcanoTTSEngine", make_engine_cls(record, name="volcano"))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert record["ctor"] == [{
            "name": "volcano",
            "api_key": "vk",
            "appid": None,
            "model": "volcano-model",
            "voice_map": {"zh_female": "voice-1"},
            "key_map": {"a": "b"},
            "resource_id": "volc.megatts.default",
        }]

    async def test_volcano_appid_falls_back_to_attribute(self, monkeypatch, tts_config):
        """model_extra 里没有 appid 时，回退到配置对象上的 appid 属性。"""
        tts_config.provider = "volcano"
        tts_config.appid = "app-from-attr"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "VolcanoTTSEngine", make_engine_cls(record, name="volcano"))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert record["ctor"][0]["appid"] == "app-from-attr"

    async def test_volcano_resource_id_falls_back_to_attribute(self, monkeypatch, tts_config):
        tts_config.provider = "volcano"
        tts_config.resource_id = "volc.from.attr"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "VolcanoTTSEngine", make_engine_cls(record, name="volcano"))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert record["ctor"][0]["resource_id"] == "volc.from.attr"

    async def test_volcano_failure_records_error(self, monkeypatch, tts_config):
        tts_config.provider = "volcano"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        _patch_engine(
            monkeypatch, "VolcanoTTSEngine", make_engine_cls({}, name="volcano", fail_init=True)
        )

        mgr = te.TTSManager()
        await mgr.initialize()

        assert "火山引擎TTS初始化失败" in mgr.last_error

    async def test_unknown_provider_falls_back_to_qwen3(self, monkeypatch, tts_config):
        tts_config.provider = "nonsense"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "Qwen3TTSEngine", make_engine_cls(record, name="qwen3"))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert record["initialized"] == ["qwen3"]
        assert mgr.initialized is True

    async def test_unknown_provider_second_fallback_to_f5(self, monkeypatch, tts_config):
        """未知 provider：Qwen3 挂了还要再退一层到 F5。"""
        tts_config.provider = "nonsense"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(
            monkeypatch, "Qwen3TTSEngine", make_engine_cls(record, name="qwen3", fail_init=True)
        )
        _patch_engine(monkeypatch, "F5TTSEngine", make_engine_cls(record, name="f5"))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert record["initialized"] == ["f5"]
        assert mgr.initialized is True

    async def test_unknown_provider_all_fallbacks_fail(self, monkeypatch, tts_config):
        """两层回退都失败：engine 为空、last_error 提示「所有引擎回退均失败」。"""
        tts_config.provider = "nonsense"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        _patch_engine(monkeypatch, "Qwen3TTSEngine", make_engine_cls({}, name="q", fail_init=True))
        _patch_engine(monkeypatch, "F5TTSEngine", make_engine_cls({}, name="f", fail_init=True))

        mgr = te.TTSManager()
        await mgr.initialize()

        assert mgr.engine is None
        assert mgr.initialized is False
        assert "所有TTS引擎回退均失败" in mgr.last_error


# ============================================================
# 资源管理器注册
# ============================================================

class TestRegisterResourceManager:
    """注册失败一律降级，不能影响 TTS 主流程。"""

    def test_returns_when_resource_manager_unavailable(self, manager, monkeypatch):
        monkeypatch.setattr(te, "get_resource_manager", None)

        manager._register_resource_manager_safely()  # 不应抛异常

        assert manager.initialized is False

    def test_returns_when_resource_priority_unavailable(self, manager, monkeypatch):
        monkeypatch.setattr(te, "ResourcePriority", None)

        manager._register_resource_manager_safely()

        assert manager.initialized is False

    def test_registers_model_and_handler(self, manager, monkeypatch):
        rm = _ResourceManagerStub()
        monkeypatch.setattr(te, "get_resource_manager", lambda: rm)

        manager._register_resource_manager_safely()

        assert rm.models[0]["model_id"] == "tts_engine"
        assert rm.models[0]["model_type"] == "tts"
        assert rm.models[0]["instance"] is manager
        assert rm.handlers[0][0] == "gpu_memory"
        assert rm.handlers[0][2] == manager.handle_resource_pressure

    def test_register_model_failure_is_swallowed(self, manager, monkeypatch):
        """register_model 抛错要吞掉，但后面的 handler 注册仍要执行。"""
        rm = _ResourceManagerStub(register_model_raises=True)
        monkeypatch.setattr(te, "get_resource_manager", lambda: rm)

        manager._register_resource_manager_safely()

        assert len(rm.handlers) == 1

    def test_outer_failure_is_swallowed(self, manager, monkeypatch):
        def _boom():
            raise RuntimeError("资源管理器未初始化")

        monkeypatch.setattr(te, "get_resource_manager", _boom)

        manager._register_resource_manager_safely()

        assert manager.initialized is False


class TestModuleImportGuard:
    """``core.resource_manager`` 不可导入时，模块级兜底把两个名字降级为 None。

    这是 import 期分支，正常环境走不到。这里用**独立命名空间**重新执行模块源码
    （不 reload 真实模块，避免把已导入的类对象换掉），只拦 ``core.resource_manager``。
    """

    def test_names_degrade_to_none_when_resource_manager_unimportable(self, monkeypatch):
        import builtins
        import importlib.util
        from pathlib import Path

        real_import = builtins.__import__

        def _blocked(name, *args, **kwargs):
            if name == "core.resource_manager":
                raise ImportError("模拟 core.resource_manager 缺失")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _blocked)

        spec = importlib.util.spec_from_file_location(
            "_tts_engine_import_guard_probe", Path(te.__file__)
        )
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)

        assert probe.get_resource_manager is None
        assert probe.ResourcePriority is None


# ============================================================
# 资源压力与设备迁移
# ============================================================

class TestResourcePressure:
    """handle_resource_pressure 只对 release 生效，且不冒泡异常。"""

    async def test_release_moves_engine_to_cpu(self, manager):
        record = {}
        manager.engine = make_engine_cls(record, name="e")()
        manager.current_device = "cuda"

        await manager.handle_resource_pressure(" RELEASE ")

        assert manager.current_device == "cpu"
        assert record["move_to_cpu"] == ["e"]

    async def test_release_without_engine_is_noop(self, manager):
        manager.engine = None

        await manager.handle_resource_pressure("release")

        assert manager.current_device is None

    async def test_release_when_already_on_cpu_is_noop(self, manager):
        record = {}
        manager.engine = make_engine_cls(record, name="e")()
        manager.current_device = "cpu"

        await manager.handle_resource_pressure("release")

        assert "move_to_cpu" not in record

    @pytest.mark.parametrize("action", ["recover", "restore"])
    async def test_recover_is_noop(self, manager, action):
        record = {}
        manager.engine = make_engine_cls(record, name="e")()
        manager.current_device = "cpu"

        await manager.handle_resource_pressure(action)

        assert manager.current_device == "cpu"
        assert "move_to_cpu" not in record

    async def test_unknown_action_is_noop(self, manager):
        record = {}
        manager.engine = make_engine_cls(record, name="e")()
        manager.current_device = "cuda"

        await manager.handle_resource_pressure("something-else")

        assert manager.current_device == "cuda"
        assert "move_to_cpu" not in record


class TestMoveDevice:
    """move_to_cpu / move_to_gpu 的四种分支。"""

    async def test_move_to_cpu_without_engine(self, manager):
        manager.engine = None

        await manager.move_to_cpu()

        assert manager.current_device is None

    async def test_move_to_cpu_without_capability(self, manager):
        manager.engine = make_engine_cls({}, name="e", has_move_cpu=False)()
        manager.current_device = "cuda"

        await manager.move_to_cpu()

        assert manager.current_device == "cuda"

    async def test_move_to_cpu_reports_failure(self, manager):
        manager.engine = make_engine_cls({}, name="e", move_cpu_result=False)()
        manager.current_device = "cuda"

        await manager.move_to_cpu()

        assert manager.current_device == "cuda"

    async def test_move_to_cpu_success(self, manager):
        manager.engine = make_engine_cls({}, name="e")()
        manager.current_device = "cuda"

        await manager.move_to_cpu()

        assert manager.current_device == "cpu"

    async def test_move_to_gpu_without_engine(self, manager):
        manager.engine = None

        await manager.move_to_gpu()

        assert manager.current_device is None

    async def test_move_to_gpu_without_capability(self, manager):
        manager.engine = make_engine_cls({}, name="e", has_move_gpu=False)()
        manager.current_device = "cpu"

        await manager.move_to_gpu()

        assert manager.current_device == "cpu"

    async def test_move_to_gpu_reports_failure(self, manager):
        manager.engine = make_engine_cls({}, name="e", move_gpu_result=False)()
        manager.current_device = "cpu"

        await manager.move_to_gpu()

        assert manager.current_device == "cpu"

    async def test_move_to_gpu_success(self, manager):
        manager.engine = make_engine_cls({}, name="e")()
        manager.current_device = "cpu"

        await manager.move_to_gpu()

        assert manager.current_device == "cuda"


class TestEnsureOptimalDevice:
    """_ensure_optimal_device 的显存压力、CUDA 探测与阈值判断。"""

    async def test_noop_without_engine(self, manager):
        manager.engine = None

        await manager._ensure_optimal_device()

        assert manager.current_device is None

    async def test_resource_pressure_moves_to_cpu(self, manager, monkeypatch):
        record = {}
        manager.engine = make_engine_cls(record, name="e")()
        manager.current_device = "cuda"
        rm = _ResourceManagerStub(pressure=True)
        monkeypatch.setattr(resource_manager_mod, "get_resource_manager", lambda: rm)

        await manager._ensure_optimal_device()

        assert manager.current_device == "cpu"
        assert record["move_to_cpu"] == ["e"]

    async def test_resource_pressure_when_already_cpu_skips_move(self, manager, monkeypatch):
        record = {}
        manager.engine = make_engine_cls(record, name="e")()
        manager.current_device = "cpu"
        rm = _ResourceManagerStub(pressure=True)
        monkeypatch.setattr(resource_manager_mod, "get_resource_manager", lambda: rm)

        await manager._ensure_optimal_device()

        assert "move_to_cpu" not in record

    async def test_pressure_probe_failure_falls_through(self, manager, monkeypatch):
        """压力探测本身抛错时被吞掉，继续走正常选设备流程。"""
        record = {}
        manager.engine = make_engine_cls(record, name="e")()
        manager.current_device = "cuda"

        def _boom():
            raise RuntimeError("资源管理器不可用")

        monkeypatch.setattr(resource_manager_mod, "get_resource_manager", _boom)
        monkeypatch.setitem(sys.modules, "torch", _FakeTorch(False))

        await manager._ensure_optimal_device()

        assert manager.current_device == "cpu"

    async def test_no_cuda_moves_to_cpu(self, manager, monkeypatch):
        record = {}
        manager.engine = make_engine_cls(record, name="e")()
        manager.current_device = "cuda"
        monkeypatch.setattr(resource_manager_mod, "get_resource_manager", lambda: None)
        monkeypatch.setitem(sys.modules, "torch", _FakeTorch(False))

        await manager._ensure_optimal_device()

        assert manager.current_device == "cpu"
        assert record["move_to_cpu"] == ["e"]

    async def test_torch_import_failure_is_treated_as_no_cuda(self, manager, monkeypatch):
        """torch 导入失败按「无 CUDA」处理，退回 CPU。"""
        record = {}
        manager.engine = make_engine_cls(record, name="e")()
        manager.current_device = "cuda"
        monkeypatch.setattr(resource_manager_mod, "get_resource_manager", lambda: None)
        monkeypatch.setitem(sys.modules, "torch", None)  # import torch -> ImportError

        await manager._ensure_optimal_device()

        assert manager.current_device == "cpu"

    async def test_already_on_target_returns_early(self, manager, monkeypatch):
        record = {}
        manager.engine = make_engine_cls(record, name="e")()
        manager.current_device = "cpu"
        monkeypatch.setattr(resource_manager_mod, "get_resource_manager", lambda: None)
        monkeypatch.setitem(sys.modules, "torch", _FakeTorch(False))

        await manager._ensure_optimal_device()

        assert "move_to_cpu" not in record
        assert "move_to_gpu" not in record

    async def test_cuda_with_enough_free_memory_moves_to_gpu(self, manager, monkeypatch):
        record = {}
        manager.engine = make_engine_cls(record, name="e")()
        manager.current_device = "cpu"
        rm = _ResourceManagerStub(free_mb=8000)
        monkeypatch.setattr(resource_manager_mod, "get_resource_manager", lambda: rm)
        monkeypatch.setitem(sys.modules, "torch", _FakeTorch(True))
        monkeypatch.setattr(te, "get_config", lambda *a, **kw: 1200)

        await manager._ensure_optimal_device()

        assert manager.current_device == "cuda"
        assert record["move_to_gpu"] == ["e"]

    async def test_cuda_with_insufficient_free_memory_stays_on_cpu(self, manager, monkeypatch):
        record = {}
        manager.engine = make_engine_cls(record, name="e")()
        manager.current_device = "cuda"
        rm = _ResourceManagerStub(free_mb=100)
        monkeypatch.setattr(resource_manager_mod, "get_resource_manager", lambda: rm)
        monkeypatch.setitem(sys.modules, "torch", _FakeTorch(True))
        monkeypatch.setattr(te, "get_config", lambda *a, **kw: 1200)

        await manager._ensure_optimal_device()

        assert "move_to_gpu" not in record
        assert manager.current_device == "cuda"

    async def test_config_read_failure_falls_back_to_default_threshold(
        self, manager, monkeypatch
    ):
        """读阈值失败时按 1200MB 兜底：此时 100MB 空闲仍判定为不足。"""
        record = {}
        manager.engine = make_engine_cls(record, name="e")()
        manager.current_device = "cpu"
        rm = _ResourceManagerStub(free_mb=100)
        monkeypatch.setattr(resource_manager_mod, "get_resource_manager", lambda: rm)
        monkeypatch.setitem(sys.modules, "torch", _FakeTorch(True))

        def _boom(*args, **kwargs):
            raise RuntimeError("配置未初始化")

        monkeypatch.setattr(te, "get_config", _boom)

        await manager._ensure_optimal_device()

        assert "move_to_gpu" not in record
        assert manager.current_device == "cpu"

    async def test_non_integer_free_memory_skips_threshold_check(self, manager, monkeypatch):
        """显存读数不是 int（如 None）时跳过阈值判断，直接尝试上 GPU。"""
        record = {}
        manager.engine = make_engine_cls(record, name="e")()
        manager.current_device = "cpu"
        rm = _ResourceManagerStub(free_mb=None)
        monkeypatch.setattr(resource_manager_mod, "get_resource_manager", lambda: rm)
        monkeypatch.setitem(sys.modules, "torch", _FakeTorch(True))

        await manager._ensure_optimal_device()

        assert record["move_to_gpu"] == ["e"]
        assert manager.current_device == "cuda"

    async def test_cuda_without_gpu_capability_stays_on_cpu(self, manager, monkeypatch):
        """有 CUDA 但引擎不支持上 GPU：target 仍是 cpu，走 move_to_cpu。"""
        record = {}
        manager.engine = make_engine_cls(record, name="e", has_move_gpu=False)()
        manager.current_device = "cuda"
        monkeypatch.setattr(resource_manager_mod, "get_resource_manager", lambda: None)
        monkeypatch.setitem(sys.modules, "torch", _FakeTorch(True))

        await manager._ensure_optimal_device()

        assert manager.current_device == "cpu"
        assert record["move_to_cpu"] == ["e"]

    async def test_move_to_gpu_failure_keeps_recorded_device(self, manager, monkeypatch):
        record = {}
        manager.engine = make_engine_cls(record, name="e", move_gpu_result=False)()
        manager.current_device = "cpu"
        rm = _ResourceManagerStub(free_mb=8000)
        monkeypatch.setattr(resource_manager_mod, "get_resource_manager", lambda: rm)
        monkeypatch.setitem(sys.modules, "torch", _FakeTorch(True))
        monkeypatch.setattr(te, "get_config", lambda *a, **kw: 1200)

        await manager._ensure_optimal_device()

        assert manager.current_device == "cpu"

    async def test_free_memory_query_failure_is_swallowed(self, manager, monkeypatch):
        """查显存本身抛错时被外层 except 吞掉，跳过阈值判断直接尝试上 GPU。"""
        record = {}
        manager.engine = make_engine_cls(record, name="e")()
        manager.current_device = "cpu"
        rm = _ResourceManagerStub(raise_on_free_mb=True)
        monkeypatch.setattr(resource_manager_mod, "get_resource_manager", lambda: rm)
        monkeypatch.setitem(sys.modules, "torch", _FakeTorch(True))

        await manager._ensure_optimal_device()

        assert record["move_to_gpu"] == ["e"]
        assert manager.current_device == "cuda"


# ============================================================
# get_engine / synthesize
# ============================================================

class TestGetEngine:
    async def test_returns_engine_after_lazy_initialize(self, monkeypatch, tts_config):
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "CloudTTSEngine", make_engine_cls(record, name="cloud"))
        mgr = te.TTSManager()

        engine = await mgr.get_engine()

        assert engine is mgr.engine
        assert record["initialized"] == ["cloud"]

    async def test_returns_existing_engine_without_reinit(self, manager):
        sentinel = object()
        manager.initialized = True
        manager.engine = sentinel

        assert await manager.get_engine() is sentinel


class TestSynthesize:
    """synthesize 的空引擎、连接错误回退与非连接错误三条路径。"""

    @pytest.fixture(autouse=True)
    def _no_device_probe(self, monkeypatch):
        """设备迁移另有专测，这里隔离掉以免引入资源管理器依赖。"""
        async def _noop(self):
            return None

        monkeypatch.setattr(te.TTSManager, "_ensure_optimal_device", _noop)

    async def test_returns_empty_array_when_no_engine(self, manager):
        manager.initialized = True
        manager.engine = None
        manager.last_error = "没有可用引擎"

        result = await manager.synthesize("你好")

        assert result.shape == (0,)
        assert result.dtype == np.float32

    async def test_returns_engine_result(self, manager):
        expected = np.ones(5, dtype=np.float32)
        record = {}
        manager.initialized = True
        manager.engine = make_engine_cls(record, name="e", synth_result=expected)()

        result = await manager.synthesize("你好", speed=1.2)

        assert result is expected
        assert record["synthesize"] == [("e", "你好", {"speed": 1.2})]

    async def test_connection_error_falls_back_to_qwen3(self, manager, monkeypatch):
        record = {}
        manager.initialized = True
        manager.engine = make_engine_cls(
            record, name="cloud", synth_exc=RuntimeError("cannot connect to host")
        )()
        fallback_result = np.full(2, 0.5, dtype=np.float32)
        _patch_engine(
            monkeypatch, "Qwen3TTSEngine",
            make_engine_cls(record, name="qwen3", synth_result=fallback_result),
        )

        result = await manager.synthesize("你好")

        assert result is fallback_result
        assert manager.engine is not None
        assert record["initialized"] == ["qwen3"]

    async def test_connection_error_without_fallback_returns_empty(self, manager, monkeypatch):
        """回退引擎也起不来时，把原引擎放回去并返回空数组。"""
        record = {}
        original = make_engine_cls(
            record, name="cloud", synth_exc=RuntimeError("connection refused")
        )()
        manager.initialized = True
        manager.engine = original
        _patch_engine(
            monkeypatch, "Qwen3TTSEngine", make_engine_cls(record, name="qwen3", fail_init=True)
        )

        result = await manager.synthesize("你好")

        assert result.shape == (0,)
        assert manager.engine is original

    async def test_timeout_counts_as_connection_error(self, manager, monkeypatch):
        record = {}
        manager.initialized = True
        manager.engine = make_engine_cls(
            record, name="cloud", synth_exc=RuntimeError("Request Timeout")
        )()
        _patch_engine(monkeypatch, "Qwen3TTSEngine", make_engine_cls(record, name="qwen3"))

        result = await manager.synthesize("你好")

        assert result.shape == (3,)
        assert record["initialized"] == ["qwen3"]

    async def test_qwen3_connection_error_does_not_retry_itself(self, manager, monkeypatch):
        """当前引擎已经是 Qwen3 时不再自我回退，直接返回空数组。"""
        record = {}
        qwen_cls = make_engine_cls(
            record, name="qwen3", synth_exc=RuntimeError("cannot connect")
        )
        manager.initialized = True
        manager.engine = qwen_cls()
        _patch_engine(monkeypatch, "Qwen3TTSEngine", qwen_cls)

        result = await manager.synthesize("你好")

        assert result.shape == (0,)
        # 只调了一次 synthesize（原始那次），没有回退重试
        assert len(record["synthesize"]) == 1

    async def test_non_connection_error_returns_empty_without_fallback(self, manager, monkeypatch):
        record = {}
        manager.initialized = True
        manager.engine = make_engine_cls(
            record, name="e", synth_exc=ValueError("文本为空")
        )()
        fallback_calls = []
        _patch_engine(
            monkeypatch, "Qwen3TTSEngine",
            make_engine_cls(record, name="qwen3", fail_init=True),
        )

        result = await manager.synthesize("你好")

        assert result.shape == (0,)
        assert fallback_calls == []
        assert "initialized" not in record


class TestSynthesizeBytes:
    """synthesize_bytes 的 hasattr 分支与连接错误回退。"""

    @pytest.fixture(autouse=True)
    def _no_device_probe(self, monkeypatch):
        async def _noop(self):
            return None

        monkeypatch.setattr(te.TTSManager, "_ensure_optimal_device", _noop)

    async def test_returns_none_when_no_engine(self, manager):
        manager.initialized = True
        manager.engine = None

        assert await manager.synthesize_bytes("你好") is None

    async def test_returns_none_when_engine_lacks_bytes_api(self, manager):
        manager.initialized = True
        manager.engine = make_engine_cls({}, name="e", has_bytes=False)()

        assert await manager.synthesize_bytes("你好") is None

    async def test_returns_bytes_from_engine(self, manager):
        record = {}
        manager.initialized = True
        manager.engine = make_engine_cls(record, name="e", bytes_result=b"wav")()

        assert await manager.synthesize_bytes("你好") == b"wav"
        assert record["synthesize_bytes"] == [("e", "你好", {})]

    async def test_connection_error_falls_back_to_qwen3(self, manager, monkeypatch):
        record = {}
        manager.initialized = True
        manager.engine = make_engine_cls(
            record, name="cloud", bytes_exc=RuntimeError("cannot connect")
        )()
        _patch_engine(
            monkeypatch, "Qwen3TTSEngine",
            make_engine_cls(record, name="qwen3", bytes_result=b"fallback"),
        )

        result = await manager.synthesize_bytes("你好")

        assert result == b"fallback"
        assert record["initialized"] == ["qwen3"]

    async def test_connection_error_fallback_without_bytes_api_returns_none(
        self, manager, monkeypatch
    ):
        """回退引擎没有 synthesize_bytes 时返回 None（但引擎已被换掉）。"""
        record = {}
        manager.initialized = True
        manager.engine = make_engine_cls(
            record, name="cloud", bytes_exc=RuntimeError("connection refused")
        )()
        fallback_cls = make_engine_cls(record, name="qwen3", has_bytes=False)
        _patch_engine(monkeypatch, "Qwen3TTSEngine", fallback_cls)

        result = await manager.synthesize_bytes("你好")

        assert result is None
        assert isinstance(manager.engine, fallback_cls)

    async def test_connection_error_fallback_failure_restores_engine(
        self, manager, monkeypatch
    ):
        record = {}
        original = make_engine_cls(
            record, name="cloud", bytes_exc=RuntimeError("timeout")
        )()
        manager.initialized = True
        manager.engine = original
        _patch_engine(
            monkeypatch, "Qwen3TTSEngine",
            make_engine_cls(record, name="qwen3", fail_init=True),
        )

        result = await manager.synthesize_bytes("你好")

        assert result is None
        assert manager.engine is original

    async def test_non_connection_error_returns_none(self, manager, monkeypatch):
        record = {}
        manager.initialized = True
        manager.engine = make_engine_cls(
            record, name="e", bytes_exc=ValueError("坏参数")
        )()
        _patch_engine(monkeypatch, "Qwen3TTSEngine", make_engine_cls(record, name="qwen3"))

        assert await manager.synthesize_bytes("你好") is None
        assert "initialized" not in record


# ============================================================
# shutdown / switch_engine
# ============================================================

class TestShutdown:
    async def test_shuts_down_engine_and_clears_flag(self, manager):
        record = {}
        manager.engine = make_engine_cls(record, name="e")()
        manager.initialized = True

        await manager.shutdown()

        assert record["shutdown"] == ["e"]
        assert manager.initialized is False

    async def test_without_engine_still_clears_flag(self, manager):
        manager.engine = None
        manager.initialized = True

        await manager.shutdown()

        assert manager.initialized is False


class TestSwitchEngine:
    """switch_engine 的别名映射、幂等提示与重初始化。"""

    @pytest.mark.parametrize("provider", ["cloud", "volcano", "volcengine", "字节", "火山", "云端"])
    async def test_cloud_aliases_target_volcano(self, monkeypatch, tts_config, provider):
        tts_config.provider = "qwen3"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "VolcanoTTSEngine", make_engine_cls(record, name="volcano"))
        mgr = te.TTSManager()

        message = await mgr.switch_engine(provider)

        assert message == "已切换到火山引擎TTS"
        assert tts_config.provider == "volcano"

    @pytest.mark.parametrize("provider", ["local", "qwen3", "本地"])
    async def test_local_aliases_target_qwen3(self, monkeypatch, tts_config, provider):
        tts_config.provider = "cloud"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "Qwen3TTSEngine", make_engine_cls(record, name="qwen3"))
        mgr = te.TTSManager()

        message = await mgr.switch_engine(provider)

        assert message == "已切换到Qwen3本地TTS"
        assert tts_config.provider == "qwen3"

    async def test_unknown_target_returns_hint(self, monkeypatch, tts_config):
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        mgr = te.TTSManager()

        message = await mgr.switch_engine("nonsense")

        assert "未知的TTS类型" in message

    async def test_already_on_cloud_is_reported(self, monkeypatch, tts_config):
        tts_config.provider = "volcano"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        mgr = te.TTSManager()

        assert await mgr.switch_engine("cloud") == "当前已经是云端TTS"

    async def test_already_on_local_is_reported(self, monkeypatch, tts_config):
        tts_config.provider = "qwen3"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        mgr = te.TTSManager()

        assert await mgr.switch_engine("local") == "当前已经是本地TTS"

    async def test_switch_shuts_down_previous_engine(self, monkeypatch, tts_config):
        tts_config.provider = "qwen3"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "VolcanoTTSEngine", make_engine_cls(record, name="volcano"))
        mgr = te.TTSManager()
        mgr.engine = make_engine_cls(record, name="old")()
        mgr.initialized = True

        await mgr.switch_engine("cloud")

        assert record["shutdown"] == ["old"]
        assert record["initialized"] == ["volcano"]

    async def test_shutdown_failure_during_switch_is_swallowed(
        self, monkeypatch, tts_config
    ):
        """旧引擎关闭失败不能阻断切换。"""
        tts_config.provider = "qwen3"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        record = {}
        _patch_engine(monkeypatch, "VolcanoTTSEngine", make_engine_cls(record, name="volcano"))
        mgr = te.TTSManager()

        class _BadShutdown:
            async def shutdown(self):
                raise RuntimeError("关闭失败")

        mgr.engine = _BadShutdown()

        assert await mgr.switch_engine("cloud") == "已切换到火山引擎TTS"

    async def test_reinitialize_failure_is_reported(self, monkeypatch, tts_config):
        tts_config.provider = "qwen3"
        monkeypatch.setattr(te, "get_settings", lambda: _SettingsStub(tts_config))
        mgr = te.TTSManager()

        async def _boom():
            raise RuntimeError("引擎起不来")

        monkeypatch.setattr(mgr, "initialize", _boom)

        message = await mgr.switch_engine("cloud")

        assert message == "切换失败: 引擎起不来"
