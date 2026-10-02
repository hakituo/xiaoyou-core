"""core/voice/stt_engine.py 单元测试。

覆盖范围：
- ``STTEngine`` 抽象基类的 ``initialize`` / ``transcribe`` / ``shutdown``
- ``DummySTTEngine.transcribe``
- ``HuggingFaceSTTEngine`` 的初始化（成功 / CUDA 回退 / 加载失败）、转写（正常 / 空语言 /
  异常降级）、``move_to_cpu`` / ``move_to_gpu``
- ``FasterWhisperSTTEngine`` 的加载（路径命中 / 按 size 下载 / 依赖缺失 / 加载失败）、
  转写（未初始化 / 模型缺失 / 显存压力回退 / C++ VAD 预处理 / 异常）、
  ``unload_model`` / ``move_to_cpu`` / ``move_to_gpu``
- ``CloudSTTEngine`` 的构造回退、URL 归一化四种形态、200 / 非 200 / 异常三条路径
- ``STTManager`` 单例、provider 分发、旧配置兼容、资源管理器注册的逐层降级、
  资源压力回调、卸载 / 搬移 / 获取引擎 / 转写 / 关闭，以及 ``get_stt_manager`` 工厂

全部使用替身：不加载 whisper / torch / transformers / faster_whisper 真实模型，
不发网络请求，不读真实音频（音频用极小的假 bytes）。
"""

from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.util
import sys
import types

import numpy as np
import pytest

import core.voice.stt_engine as m


# ============================================================
# 通用替身：日志 / 资源锁 / torch / 配置 / 引擎
# ============================================================

class _AcquireCM:
    """``get_resource_lock().acquire(name)`` 返回的异步上下文管理器替身。"""

    def __init__(self, record=None, name=None):
        self._record = record
        self._name = name

    async def __aenter__(self):
        if self._record is not None:
            self._record.append(self._name)
        return self

    async def __aexit__(self, *exc):
        return False


class _ResourceLockStub:
    """全局资源锁替身。"""

    def __init__(self, record=None):
        self._record = record if record is not None else []

    def acquire(self, requestor):
        return _AcquireCM(self._record, requestor)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """隔离单例与全局锁，避免用例间污染。"""
    monkeypatch.setattr(m.STTManager, "_instance", None)
    monkeypatch.setattr(m, "get_resource_lock", lambda: _ResourceLockStub())
    monkeypatch.setattr(m, "_HAS_CPP_AUDIO", False)
    monkeypatch.setattr(m, "audio_processor_py", None)


def _fake_torch(*, cuda_available=False, cuda_raises=False):
    """构造替身 torch 模块，避免真实 CUDA 探测。"""
    mod = types.ModuleType("torch")

    def _is_available():
        if cuda_raises:
            raise RuntimeError("CUDA 探测失败")
        return cuda_available

    mod.cuda = types.SimpleNamespace(
        is_available=_is_available, empty_cache=lambda: None
    )
    return mod


def _install(monkeypatch, name, module):
    """把假模块塞进 ``sys.modules``，测试结束后由 monkeypatch 自动还原。"""
    monkeypatch.setitem(sys.modules, name, module)


def _fresh_exec():
    """在独立命名空间里重新执行本模块源码，用于覆盖 import 期的条件分支。

    coverage 按「文件 + 行号」统计，exec 出来的代码同样会被计入，
    因此这里可以在不污染 ``core.voice.stt_engine`` 模块对象的前提下，
    把 import 期的 try/except 两条腿都走一遍。
    """
    spec = importlib.util.spec_from_file_location("_stt_engine_probe", m.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ============================================================
# 抽象基类 / Dummy
# ============================================================

class TestBaseEngine:
    """``STTEngine`` 基类与 ``DummySTTEngine``。"""

    def test_base_initialize_and_shutdown_toggle_flag(self):
        engine = m.STTEngine()

        assert engine.initialized is False
        asyncio.run(engine.initialize())
        assert engine.initialized is True
        asyncio.run(engine.shutdown())
        assert engine.initialized is False

    def test_base_transcribe_raises_not_implemented(self):
        engine = m.STTEngine()

        with pytest.raises(NotImplementedError):
            asyncio.run(engine.transcribe(b"\x00\x01"))

    def test_dummy_transcribe_returns_mock_text(self):
        engine = m.DummySTTEngine()
        result = asyncio.run(engine.transcribe(b"12345"))

        assert result["text"] == "这是一段模拟的转录文本"
        assert result["segments"] == []
        assert result["language"] == "zh"


# ============================================================
# import 期的可选依赖探测分支
# ============================================================

class TestImportTimeBranches:
    """模块顶部两组可选依赖探测的「命中 / 缺失」两种状态。"""

    def test_cpp_audio_available_sets_flag(self, monkeypatch):
        fake = types.ModuleType("audio_processor_py")
        fake.__spec__ = importlib.machinery.ModuleSpec("audio_processor_py", None)
        monkeypatch.setitem(sys.modules, "audio_processor_py", fake)

        probe = _fresh_exec()

        assert probe._HAS_CPP_AUDIO is True
        assert probe.audio_processor_py is fake

    def test_cpp_audio_probe_exception_degrades(self, monkeypatch):
        # 无 __spec__ 的模块会让 find_spec 抛 ValueError，走外层 except 降级
        monkeypatch.setitem(
            sys.modules, "audio_processor_py", types.ModuleType("audio_processor_py")
        )

        probe = _fresh_exec()

        assert probe._HAS_CPP_AUDIO is False
        assert probe.audio_processor_py is None

    def test_resource_manager_import_error_degrades(self, monkeypatch):
        fake = types.ModuleType("core.resource_manager")

        def _getattr(name):
            raise ImportError(f"cannot import name {name!r}")

        fake.__getattr__ = _getattr
        monkeypatch.setitem(sys.modules, "core.resource_manager", fake)

        probe = _fresh_exec()

        assert probe.get_resource_manager is None
        assert probe.ResourcePriority is None
        assert probe.ResourceType is None


# ============================================================
# HuggingFaceSTTEngine
# ============================================================

class _HFProcessorStub:
    """WhisperProcessor 替身：可调用、可解码、可生成 decoder prompt。"""

    def __init__(self, decode_text="你好世界"):
        self.decode_text = decode_text
        self.decoder_calls = []
        self.batch_decode_calls = []

    @classmethod
    def from_pretrained(cls, path):
        inst = cls()
        inst.model_path = path
        return inst

    def __call__(self, y, sampling_rate=16000, return_tensors="pt"):
        features = types.SimpleNamespace(
            to=lambda device: types.SimpleNamespace(device=device)
        )
        return types.SimpleNamespace(input_features=features)

    def get_decoder_prompt_ids(self, language=None, task=None):
        self.decoder_calls.append((language, task))
        return [[1, 2, 3]]

    def batch_decode(self, ids, skip_special_tokens=True):
        self.batch_decode_calls.append((ids, skip_special_tokens))
        return [self.decode_text]


class _HFModelStub:
    """WhisperForConditionalGeneration 替身。"""

    def __init__(self, *, raise_generate=False, raise_load=False):
        self.raise_generate = raise_generate
        self.raise_load = raise_load
        self.device = None
        self.moved = []

    @classmethod
    def from_pretrained(cls, path):
        return cls()

    def to(self, device):
        self.device = device
        return self

    def cpu(self):
        self.moved.append("cpu")

    def cuda(self):
        self.moved.append("cuda")

    def generate(self, input_features, forced_decoder_ids=None):
        if self.raise_generate:
            raise RuntimeError("generate 失败")
        return [[11, 12, 13]]


def _install_transformers(monkeypatch, *, processor=None, model=None,
                          raise_load=False):
    """注入假 transformers 模块。"""
    mod = types.ModuleType("transformers")

    class _Proc:
        @classmethod
        def from_pretrained(cls, path):
            if raise_load:
                raise RuntimeError("processor 加载失败")
            return processor

    class _Model:
        @classmethod
        def from_pretrained(cls, path):
            if raise_load:
                raise RuntimeError("model 加载失败")
            return model

    mod.WhisperProcessor = _Proc
    mod.WhisperForConditionalGeneration = _Model
    _install(monkeypatch, "transformers", mod)


def _install_librosa(monkeypatch, *, y=None, sr=16000):
    mod = types.ModuleType("librosa")

    def _load(stream, sr=16000):
        return (np.zeros(8, dtype=np.float32) if y is None else y), sr

    mod.load = _load
    _install(monkeypatch, "librosa", mod)


class TestHuggingFaceEngine:
    """HuggingFaceSTTEngine 的初始化、转写与设备搬移。"""

    def test_initialize_success(self, monkeypatch):
        processor = _HFProcessorStub()
        model = _HFModelStub()
        _install_transformers(monkeypatch, processor=processor, model=model)
        _install(monkeypatch, "torch", _fake_torch(cuda_available=False))

        engine = m.HuggingFaceSTTEngine(model_path="some/model", device="cpu")
        asyncio.run(engine.initialize())

        assert engine.initialized is True
        assert engine.processor is processor
        assert engine.model is model
        assert model.device == "cpu"

    def test_initialize_early_return_when_already_initialized(self, monkeypatch):
        engine = m.HuggingFaceSTTEngine(model_path="x", device="cpu")
        engine.initialized = True

        # 不注入 transformers：若走了加载路径必然 ImportError
        asyncio.run(engine.initialize())

        assert engine.initialized is True
        assert engine.model is None

    def test_initialize_cuda_falls_back_to_cpu(self, monkeypatch):
        processor = _HFProcessorStub()
        model = _HFModelStub()
        _install_transformers(monkeypatch, processor=processor, model=model)
        _install(monkeypatch, "torch", _fake_torch(cuda_available=False))

        engine = m.HuggingFaceSTTEngine(model_path="x", device="cuda")
        asyncio.run(engine.initialize())

        assert engine.device == "cpu"
        assert engine.initialized is True

    def test_initialize_failure_propagates_and_stays_uninitialized(self, monkeypatch):
        _install_transformers(monkeypatch, raise_load=True)
        _install(monkeypatch, "torch", _fake_torch())

        engine = m.HuggingFaceSTTEngine(model_path="x", device="cpu")
        with pytest.raises(RuntimeError):
            asyncio.run(engine.initialize())

        assert engine.initialized is False

    def test_transcribe_not_initialized(self):
        engine = m.HuggingFaceSTTEngine(model_path="x", device="cpu")

        result = asyncio.run(engine.transcribe(b"audio"))

        assert result == {"text": "", "error": "Model not initialized"}

    def test_transcribe_success_forces_language(self, monkeypatch):
        processor = _HFProcessorStub(decode_text="识别结果")
        model = _HFModelStub()
        _install_librosa(monkeypatch)
        engine = m.HuggingFaceSTTEngine(model_path="x", device="cpu")
        engine.processor = processor
        engine.model = model
        engine.initialized = True

        result = asyncio.run(engine.transcribe(b"fake-audio", language="en"))

        assert result["text"] == "识别结果"
        assert result["language"] == "en"
        assert processor.decoder_calls == [("en", "transcribe")]

    def test_transcribe_without_language_skips_decoder_prompt(self, monkeypatch):
        processor = _HFProcessorStub(decode_text="auto")
        model = _HFModelStub()
        _install_librosa(monkeypatch)
        engine = m.HuggingFaceSTTEngine(model_path="x", device="cpu")
        engine.processor = processor
        engine.model = model
        engine.initialized = True

        result = asyncio.run(engine.transcribe(b"fake-audio", language=""))

        assert result["text"] == "auto"
        # language 为空 -> forced_decoder_ids 保持 None，不调用 get_decoder_prompt_ids
        assert processor.decoder_calls == []

    def test_transcribe_exception_returns_error(self, monkeypatch):
        processor = _HFProcessorStub()
        model = _HFModelStub(raise_generate=True)
        _install_librosa(monkeypatch)
        engine = m.HuggingFaceSTTEngine(model_path="x", device="cpu")
        engine.processor = processor
        engine.model = model
        engine.initialized = True

        result = asyncio.run(engine.transcribe(b"fake-audio"))

        assert result["text"] == ""
        assert "generate 失败" in result["error"]

    def test_move_to_cpu_moves_model_and_clears_cache(self, monkeypatch):
        _install(monkeypatch, "torch", _fake_torch(cuda_available=True))
        engine = m.HuggingFaceSTTEngine(model_path="x", device="cuda")
        engine.model = _HFModelStub()

        asyncio.run(engine.move_to_cpu())

        assert engine.model.moved == ["cpu"]

    def test_move_to_cpu_skips_when_already_on_cpu(self):
        engine = m.HuggingFaceSTTEngine(model_path="x", device="cpu")
        engine.model = _HFModelStub()

        asyncio.run(engine.move_to_cpu())

        assert engine.model.moved == []

    def test_move_to_gpu_success(self, monkeypatch):
        _install(monkeypatch, "torch", _fake_torch(cuda_available=True))
        engine = m.HuggingFaceSTTEngine(model_path="x", device="cpu")
        engine.model = _HFModelStub()

        moved = asyncio.run(engine.move_to_gpu())

        assert moved is True
        assert engine.device == "cuda"
        assert engine.model.moved == ["cuda"]

    def test_move_to_gpu_returns_false_when_cuda_unavailable(self, monkeypatch):
        _install(monkeypatch, "torch", _fake_torch(cuda_available=False))
        engine = m.HuggingFaceSTTEngine(model_path="x", device="cpu")
        engine.model = _HFModelStub()

        moved = asyncio.run(engine.move_to_gpu())

        assert moved is False
        assert engine.device == "cpu"

    def test_move_to_gpu_swallows_exception(self, monkeypatch):
        _install(monkeypatch, "torch", _fake_torch(cuda_raises=True))
        engine = m.HuggingFaceSTTEngine(model_path="x", device="cpu")
        engine.model = _HFModelStub()

        moved = asyncio.run(engine.move_to_gpu())

        assert moved is False

    def test_move_to_gpu_noop_without_model(self):
        engine = m.HuggingFaceSTTEngine(model_path="x", device="cpu")

        assert asyncio.run(engine.move_to_gpu()) is False


# ============================================================
# FasterWhisperSTTEngine
# ============================================================

class _FWWhisperModelStub:
    """faster_whisper.WhisperModel 替身，同时支持加载与转写。"""

    def __init__(self, *args, **kwargs):
        self.ctor_args = args
        self.ctor_kwargs = kwargs

    def transcribe(self, audio, beam_size=5, language="zh", vad_filter=True,
                   vad_parameters=None):
        segments = [types.SimpleNamespace(text=" 你好"), types.SimpleNamespace(text="世界 ")]
        return iter(segments), types.SimpleNamespace(language="zh")


def _install_faster_whisper(monkeypatch, *, raise_load=False, model_cls=None):
    mod = types.ModuleType("faster_whisper")

    if model_cls is not None:
        mod.WhisperModel = model_cls
    else:
        class _WhisperModel(_FWWhisperModelStub):
            def __init__(self, *args, **kwargs):
                if raise_load:
                    raise RuntimeError("WhisperModel 加载失败")
                super().__init__(*args, **kwargs)

        mod.WhisperModel = _WhisperModel

    _install(monkeypatch, "faster_whisper", mod)


def _install_missing_faster_whisper(monkeypatch):
    """注入一个访问 ``WhisperModel`` 时抛 ModuleNotFoundError 的假模块。"""
    mod = types.ModuleType("faster_whisper")

    def _getattr(name):
        raise ModuleNotFoundError(
            "No module named 'faster_whisper'", name="faster_whisper"
        )

    mod.__getattr__ = _getattr
    _install(monkeypatch, "faster_whisper", mod)


def _install_pydub(monkeypatch, *, raise_on_load=False):
    mod = types.ModuleType("pydub")

    class AudioSegment:
        @classmethod
        def from_file(cls, f):
            if raise_on_load:
                raise RuntimeError("pydub 解析失败")
            return cls()

        def set_frame_rate(self, rate):
            return self

        def set_channels(self, channels):
            return self

        def set_sample_width(self, width):
            return self

        def get_array_of_samples(self):
            return [1, 2, 3, 4]

    mod.AudioSegment = AudioSegment
    _install(monkeypatch, "pydub", mod)


def _install_audio_processor(monkeypatch, cleaned):
    mod = types.ModuleType("audio_processor_py")
    record = {}

    class AudioVAD:
        def __init__(self, sample_rate=16000, energy_threshold=0.05):
            record["sample_rate"] = sample_rate
            record["energy_threshold"] = energy_threshold

        def remove_silence(self, samples, frame_ms=30):
            record["frame_ms"] = frame_ms
            return cleaned

    mod.AudioVAD = AudioVAD
    _install(monkeypatch, "audio_processor_py", mod)
    monkeypatch.setattr(m, "_HAS_CPP_AUDIO", True)
    monkeypatch.setattr(m, "audio_processor_py", mod)
    return record


class TestFasterWhisperLoad:
    """FasterWhisper 模型加载相关分支。"""

    def test_initialize_early_return(self, monkeypatch):
        engine = m.FasterWhisperSTTEngine()
        engine.initialized = True
        called = []
        monkeypatch.setattr(engine, "_load_model", lambda: called.append(1))

        asyncio.run(engine.initialize())

        assert called == []

    def test_initialize_success_uses_size_download(self, monkeypatch, tmp_path):
        _install_faster_whisper(monkeypatch)
        _install(monkeypatch, "torch", _fake_torch(cuda_available=False))
        import core.utils.common as common_mod
        monkeypatch.setattr(common_mod, "get_project_root", lambda: tmp_path)

        engine = m.FasterWhisperSTTEngine(model_size="small", device="cpu")
        asyncio.run(engine.initialize())

        assert engine.initialized is True
        assert isinstance(engine.model, _FWWhisperModelStub)
        # 未命中 model.bin -> 按 size 加载并带 download_root
        assert engine.model.ctor_args == ("small",)
        assert "download_root" in engine.model.ctor_kwargs

    def test_load_model_prefers_local_model_bin(self, monkeypatch, tmp_path):
        _install_faster_whisper(monkeypatch)
        _install(monkeypatch, "torch", _fake_torch(cuda_available=False))
        target = tmp_path / "models" / "faster-whisper"
        target.mkdir(parents=True)
        (target / "model.bin").write_bytes(b"x")
        import core.utils.common as common_mod
        monkeypatch.setattr(common_mod, "get_project_root", lambda: tmp_path)

        engine = m.FasterWhisperSTTEngine(model_size="small", device="cpu")
        asyncio.run(engine.initialize())

        assert engine.model.ctor_args == (str(target),)

    def test_load_model_clears_previous_model_reference(self, monkeypatch, tmp_path):
        _install_faster_whisper(monkeypatch)
        _install(monkeypatch, "torch", _fake_torch(cuda_available=True))
        import core.utils.common as common_mod
        monkeypatch.setattr(common_mod, "get_project_root", lambda: tmp_path)

        engine = m.FasterWhisperSTTEngine(model_size="small", device="cpu")
        engine.model = object()  # 触发清理旧模型分支
        asyncio.run(engine.initialize())

        assert isinstance(engine.model, _FWWhisperModelStub)

    def test_load_model_swallows_error_while_clearing_previous_model(
        self, monkeypatch, tmp_path
    ):
        _install_faster_whisper(monkeypatch)
        # torch 探测抛错 -> 清理旧模型时的内层 except 命中并 pass
        _install(monkeypatch, "torch", _fake_torch(cuda_raises=True))
        import core.utils.common as common_mod
        monkeypatch.setattr(common_mod, "get_project_root", lambda: tmp_path)

        engine = m.FasterWhisperSTTEngine(model_size="small", device="cpu")
        engine.model = object()
        asyncio.run(engine.initialize())

        assert isinstance(engine.model, _FWWhisperModelStub)

    def test_load_model_cuda_falls_back_to_cpu(self, monkeypatch, tmp_path):
        _install_faster_whisper(monkeypatch)
        _install(monkeypatch, "torch", _fake_torch(cuda_available=False))
        import core.utils.common as common_mod
        monkeypatch.setattr(common_mod, "get_project_root", lambda: tmp_path)

        engine = m.FasterWhisperSTTEngine(
            model_size="small", device="cuda", compute_type="float16"
        )
        asyncio.run(engine.initialize())

        assert engine.device == "cpu"
        assert engine.compute_type == "int8"

    def test_load_model_missing_dependency_logs_and_raises(self, monkeypatch, tmp_path):
        _install_missing_faster_whisper(monkeypatch)
        _install(monkeypatch, "torch", _fake_torch())

        engine = m.FasterWhisperSTTEngine(model_size="small", device="cpu")
        with pytest.raises(ModuleNotFoundError):
            asyncio.run(engine.initialize())

        assert engine.initialized is False

    def test_load_model_failure_reraises(self, monkeypatch, tmp_path):
        _install_faster_whisper(monkeypatch, raise_load=True)
        _install(monkeypatch, "torch", _fake_torch())
        import core.utils.common as common_mod
        monkeypatch.setattr(common_mod, "get_project_root", lambda: tmp_path)

        engine = m.FasterWhisperSTTEngine(model_size="small", device="cpu")
        with pytest.raises(RuntimeError):
            asyncio.run(engine.initialize())

        assert engine.initialized is False


class TestFasterWhisperTranscribe:
    """FasterWhisper 转写分支。"""

    def test_transcribe_not_initialized(self):
        engine = m.FasterWhisperSTTEngine()

        result = asyncio.run(engine.transcribe(b"audio"))

        assert result == {"text": "", "error": "引擎未初始化"}

    def test_transcribe_model_missing(self):
        engine = m.FasterWhisperSTTEngine()
        engine.initialized = True
        engine.model = None

        result = asyncio.run(engine.transcribe(b"audio"))

        assert result == {"text": "", "error": "模型未加载"}

    def test_transcribe_success_strips_text(self):
        engine = m.FasterWhisperSTTEngine()
        engine.initialized = True
        engine.model = _FWWhisperModelStub()

        result = asyncio.run(engine.transcribe(b"audio", language="zh"))

        assert result["text"] == "你好世界"
        assert result["language"] == "zh"
        assert result["success"] is True

    def test_transcribe_exception_returns_error(self):
        class _BadModel:
            def transcribe(self, audio, **kwargs):
                raise RuntimeError("转写崩了")

        engine = m.FasterWhisperSTTEngine()
        engine.initialized = True
        engine.model = _BadModel()

        result = asyncio.run(engine.transcribe(b"audio"))

        assert result["text"] == ""
        assert "转写崩了" in result["error"]

    def test_transcribe_uses_cpp_vad_when_available(self, monkeypatch):
        cleaned = np.zeros(4, dtype=np.int16)
        _install_audio_processor(monkeypatch, cleaned)
        _install_pydub(monkeypatch)

        engine = m.FasterWhisperSTTEngine()
        engine.initialized = True
        engine.model = _FWWhisperModelStub()

        result = asyncio.run(engine.transcribe(b"audio"))

        assert result["success"] is True

    def test_transcribe_cpp_vad_swallows_processing_error(self, monkeypatch):
        cleaned = np.zeros(4, dtype=np.int16)
        _install_audio_processor(monkeypatch, cleaned)
        # pydub 解析失败 -> 内层 except pass，回退到原始 audio_input
        _install_pydub(monkeypatch, raise_on_load=True)

        engine = m.FasterWhisperSTTEngine()
        engine.initialized = True
        engine.model = _FWWhisperModelStub()

        result = asyncio.run(engine.transcribe(b"audio"))

        assert result["success"] is True

    def test_transcribe_cpp_vad_empty_cleaned_keeps_original(self, monkeypatch):
        cleaned = np.zeros(0, dtype=np.int16)
        _install_audio_processor(monkeypatch, cleaned)
        _install_pydub(monkeypatch)

        engine = m.FasterWhisperSTTEngine()
        engine.initialized = True
        engine.model = _FWWhisperModelStub()

        result = asyncio.run(engine.transcribe(b"audio"))

        assert result["success"] is True

    def test_transcribe_gpu_pressure_falls_back_to_cpu(self, monkeypatch, tmp_path):
        _install_faster_whisper(monkeypatch)
        _install(monkeypatch, "torch", _fake_torch(cuda_available=False))
        import core.utils.common as common_mod
        monkeypatch.setattr(common_mod, "get_project_root", lambda: tmp_path)

        class _Monitor:
            def is_resource_pressure(self, resource_type):
                return True

        class _RM:
            monitor = _Monitor()

        monkeypatch.setattr(m, "get_resource_manager", lambda: _RM())

        engine = m.FasterWhisperSTTEngine(model_size="small", device="cuda")
        engine.initialized = True
        engine.model = _FWWhisperModelStub()

        result = asyncio.run(engine.transcribe(b"audio"))

        assert result["device_fallback"] == "cpu"
        assert result["success"] is True
        assert engine.device == "cpu"

    def test_transcribe_gpu_without_pressure_stays_gpu(self, monkeypatch):
        class _Monitor:
            def is_resource_pressure(self, resource_type):
                return False

        class _RM:
            monitor = _Monitor()

        monkeypatch.setattr(m, "get_resource_manager", lambda: _RM())

        engine = m.FasterWhisperSTTEngine(device="cuda")
        engine.initialized = True
        engine.model = _FWWhisperModelStub()

        result = asyncio.run(engine.transcribe(b"audio"))

        assert result["success"] is True
        assert "device_fallback" not in result


class TestFasterWhisperLifecycle:
    """卸载与设备搬移。"""

    def test_unload_model_releases_resources(self, monkeypatch):
        _install(monkeypatch, "torch", _fake_torch(cuda_available=True))
        engine = m.FasterWhisperSTTEngine()
        engine.initialized = True
        engine.model = _FWWhisperModelStub()

        asyncio.run(engine.unload_model())

        assert engine.model is None
        assert engine.initialized is False

    def test_unload_model_noop_without_model(self):
        engine = m.FasterWhisperSTTEngine()
        engine.initialized = True

        asyncio.run(engine.unload_model())

        assert engine.initialized is True

    def test_move_to_cpu_returns_early_when_already_cpu(self, monkeypatch):
        engine = m.FasterWhisperSTTEngine(device="cpu")
        called = []
        monkeypatch.setattr(engine, "_load_model", lambda: called.append(1))

        asyncio.run(engine.move_to_cpu())

        assert called == []

    def test_move_to_cpu_reloads_when_on_gpu(self, monkeypatch, tmp_path):
        _install_faster_whisper(monkeypatch)
        _install(monkeypatch, "torch", _fake_torch(cuda_available=False))
        import core.utils.common as common_mod
        monkeypatch.setattr(common_mod, "get_project_root", lambda: tmp_path)

        engine = m.FasterWhisperSTTEngine(device="cuda", compute_type="float16")
        asyncio.run(engine.move_to_cpu())

        assert engine.device == "cpu"
        assert engine.compute_type == "int8"
        assert isinstance(engine.model, _FWWhisperModelStub)

    def test_move_to_gpu_returns_early_when_already_cuda(self, monkeypatch):
        engine = m.FasterWhisperSTTEngine(device="cuda")
        called = []
        monkeypatch.setattr(engine, "_load_model", lambda: called.append(1))

        asyncio.run(engine.move_to_gpu())

        assert called == []

    def test_move_to_gpu_without_cuda_stays_cpu(self, monkeypatch):
        _install(monkeypatch, "torch", _fake_torch(cuda_available=False))
        engine = m.FasterWhisperSTTEngine(device="cpu")

        asyncio.run(engine.move_to_gpu())

        assert engine.device == "cpu"
        assert engine.model is None

    def test_move_to_gpu_success(self, monkeypatch, tmp_path):
        _install_faster_whisper(monkeypatch)
        _install(monkeypatch, "torch", _fake_torch(cuda_available=True))
        import core.utils.common as common_mod
        monkeypatch.setattr(common_mod, "get_project_root", lambda: tmp_path)

        engine = m.FasterWhisperSTTEngine(device="cpu")
        asyncio.run(engine.move_to_gpu())

        assert engine.device == "cuda"
        assert engine.compute_type == "float16"

    def test_move_to_gpu_failure_rolls_back_to_cpu(self, monkeypatch, tmp_path):
        _install_faster_whisper(monkeypatch, raise_load=True)
        _install(monkeypatch, "torch", _fake_torch(cuda_available=True))
        import core.utils.common as common_mod
        monkeypatch.setattr(common_mod, "get_project_root", lambda: tmp_path)

        engine = m.FasterWhisperSTTEngine(device="cpu")
        asyncio.run(engine.move_to_gpu())

        assert engine.device == "cpu"
        assert engine.compute_type == "int8"


# ============================================================
# CloudSTTEngine
# ============================================================

def _make_aiohttp(*, status=200, json_payload=None, text_payload="",
                  raise_post=False, raise_session=False):
    """构造替身 aiohttp 模块，返回 (模块, 会话列表)。"""
    sessions = []
    mod = types.ModuleType("aiohttp")

    class FormData:
        def __init__(self):
            self.fields = []

        def add_field(self, name, value, **kwargs):
            self.fields.append((name, value, kwargs))

    class _Resp:
        def __init__(self):
            self.status = status

        async def json(self):
            return json_payload

        async def text(self):
            return text_payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class _Session:
        def __init__(self):
            self.posts = []
            sessions.append(self)

        async def __aenter__(self):
            if raise_session:
                raise RuntimeError("会话创建失败")
            return self

        async def __aexit__(self, *exc):
            return False

        def post(self, url, data=None, headers=None):
            self.posts.append({"url": url, "data": data, "headers": headers})
            if raise_post:
                raise RuntimeError("请求发送失败")
            return _Resp()

    mod.FormData = FormData
    mod.ClientSession = _Session
    return mod, sessions


class TestCloudEngine:
    """CloudSTTEngine 的构造、URL 归一化与三种响应路径。"""

    def test_ctor_without_api_key_warns(self, monkeypatch):
        monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        engine = m.CloudSTTEngine(api_key=None)

        assert engine.api_key is None

    def test_ctor_falls_back_to_env_api_key(self, monkeypatch):
        monkeypatch.setenv("SILICONFLOW_API_KEY", "env-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        engine = m.CloudSTTEngine(api_key=None)

        assert engine.api_key == "env-key"

    def test_initialize_is_idempotent(self):
        engine = m.CloudSTTEngine(api_key="k")
        asyncio.run(engine.initialize())
        asyncio.run(engine.initialize())

        assert engine.initialized is True

    def test_transcribe_without_api_key(self, monkeypatch):
        monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        engine = m.CloudSTTEngine(api_key=None)

        result = asyncio.run(engine.transcribe(b"audio"))

        assert result == {"text": "", "error": "API Key missing"}

    @pytest.mark.parametrize(
        "base_url,expected",
        [
            ("https://x/v1/audio/transcriptions", "https://x/v1/audio/transcriptions"),
            ("https://x/v1", "https://x/v1/audio/transcriptions"),
            ("https://x", "https://x/v1/audio/transcriptions"),
            ("https://x/", "https://x/"),
        ],
    )
    def test_transcribe_url_normalization(self, monkeypatch, base_url, expected):
        mod, sessions = _make_aiohttp(
            status=200, json_payload={"text": "ok", "segments": [{"a": 1}]}
        )
        _install(monkeypatch, "aiohttp", mod)

        engine = m.CloudSTTEngine(api_key="k", base_url=base_url, model="whisper-1")
        result = asyncio.run(engine.transcribe(b"audio", language="zh"))

        assert sessions[0].posts[0]["url"] == expected
        assert result["text"] == "ok"
        assert result["segments"] == [{"a": 1}]
        assert result["language"] == "zh"

    def test_transcribe_success_without_language_uses_auto(self, monkeypatch):
        mod, sessions = _make_aiohttp(status=200, json_payload={"text": "hi"})
        _install(monkeypatch, "aiohttp", mod)

        engine = m.CloudSTTEngine(
            api_key="k", base_url="https://x/v1/audio/transcriptions"
        )
        result = asyncio.run(engine.transcribe(b"audio"))

        assert result["language"] == "auto"
        # 未传 language -> 不添加该表单字段
        field_names = [f[0] for f in sessions[0].posts[0]["data"].fields]
        assert "language" not in field_names

    def test_transcribe_non_200_returns_api_error(self, monkeypatch):
        mod, _ = _make_aiohttp(status=429, text_payload="rate limited")
        _install(monkeypatch, "aiohttp", mod)

        engine = m.CloudSTTEngine(
            api_key="k", base_url="https://x/v1/audio/transcriptions"
        )
        result = asyncio.run(engine.transcribe(b"audio"))

        assert result == {"text": "", "error": "API Error: 429"}

    def test_transcribe_post_exception_returns_error(self, monkeypatch):
        mod, _ = _make_aiohttp(raise_post=True)
        _install(monkeypatch, "aiohttp", mod)

        engine = m.CloudSTTEngine(
            api_key="k", base_url="https://x/v1/audio/transcriptions"
        )
        result = asyncio.run(engine.transcribe(b"audio"))

        assert result["text"] == ""
        assert "请求发送失败" in result["error"]

    def test_transcribe_session_exception_returns_error(self, monkeypatch):
        mod, _ = _make_aiohttp(raise_session=True)
        _install(monkeypatch, "aiohttp", mod)

        engine = m.CloudSTTEngine(
            api_key="k", base_url="https://x/v1/audio/transcriptions"
        )
        result = asyncio.run(engine.transcribe(b"audio"))

        assert result["text"] == ""
        assert "会话创建失败" in result["error"]


# ============================================================
# STTManager
# ============================================================

class _STTConfigStub:
    def __init__(self, provider="local", model=None, base_url=None, api_key=None):
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.api_key = api_key


class _VoiceStub:
    def __init__(self, stt, stt_engine):
        self.stt = stt
        self.stt_engine = stt_engine


class _SettingsStub:
    def __init__(self, stt, stt_engine="faster_whisper"):
        self.voice = _VoiceStub(stt, stt_engine)


def _engine_cls(record, name, *, fail=False):
    """生成记录调用痕迹的引擎替身类。"""

    class _Engine:
        def __init__(self, **kwargs):
            record.append({"engine": name, "ctor": kwargs})
            self.initialized = False

        async def initialize(self):
            if fail:
                raise RuntimeError(f"{name} 初始化失败")
            self.initialized = True
            record.append({"engine": name, "initialized": True})

        async def transcribe(self, audio_data, **kwargs):
            record.append({"engine": name, "transcribe": (audio_data, kwargs)})
            return {"text": f"{name}-text"}

        async def shutdown(self):
            record.append({"engine": name, "shutdown": True})

    _Engine.__name__ = name
    return _Engine


class _RMStub:
    """资源管理器替身。"""

    def __init__(self, *, raise_register=False, raise_handler=False):
        self.models = []
        self.handlers = []
        self._raise_register = raise_register
        self._raise_handler = raise_handler

    def register_model(self, **kwargs):
        self.models.append(kwargs)
        if self._raise_register:
            raise RuntimeError("注册模型失败")

    def register_resource_handler(self, *args):
        self.handlers.append(args)
        if self._raise_handler:
            raise RuntimeError("注册处理器失败")


def _make_manager(monkeypatch, *, provider="local", model=None, base_url=None,
                  api_key=None, stt_engine="faster_whisper"):
    monkeypatch.setattr(
        m,
        "get_settings",
        lambda: _SettingsStub(
            _STTConfigStub(provider, model, base_url, api_key), stt_engine
        ),
    )
    return m.STTManager()


def _patch_engines(monkeypatch, *, hf=None, fw=None, cloud=None):
    if hf is not None:
        monkeypatch.setattr(m, "HuggingFaceSTTEngine", hf)
    if fw is not None:
        monkeypatch.setattr(m, "FasterWhisperSTTEngine", fw)
    if cloud is not None:
        monkeypatch.setattr(m, "CloudSTTEngine", cloud)


class TestSTTManagerSingleton:
    """单例与幂等。"""

    def test_repeated_construction_returns_same_instance(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            m, "get_settings", lambda: calls.append(1) or _SettingsStub(_STTConfigStub())
        )

        first = m.STTManager()
        second = m.STTManager()

        assert first is second
        assert calls == [1]

    def test_get_stt_manager_returns_singleton(self, monkeypatch):
        monkeypatch.setattr(m, "get_settings", lambda: _SettingsStub(_STTConfigStub()))

        assert m.get_stt_manager() is m.get_stt_manager()


class TestSTTManagerInitialize:
    """provider 分发与回退。"""

    def test_initialize_early_return(self, monkeypatch):
        manager = _make_manager(monkeypatch)
        manager.initialized = True
        manager.engine = "sentinel"

        asyncio.run(manager.initialize())

        assert manager.engine == "sentinel"

    def test_local_prefers_hf_model_when_present(self, monkeypatch):
        record = []
        monkeypatch.setattr(m.os.path, "exists", lambda p: "whisper-small" in str(p))
        _patch_engines(monkeypatch, hf=_engine_cls(record, "HF"))
        monkeypatch.setattr(m, "get_resource_manager", None)

        manager = _make_manager(monkeypatch, provider="local")
        asyncio.run(manager.initialize())

        assert manager.initialized is True
        assert isinstance(manager.engine, m.HuggingFaceSTTEngine)

    def test_local_falls_back_to_faster_whisper(self, monkeypatch):
        record = []
        monkeypatch.setattr(m.os.path, "exists", lambda p: False)
        _patch_engines(
            monkeypatch,
            hf=_engine_cls(record, "HF", fail=True),
            fw=_engine_cls(record, "FW"),
        )
        monkeypatch.setattr(m, "get_resource_manager", None)

        manager = _make_manager(monkeypatch, provider="local", model="small")
        asyncio.run(manager.initialize())

        assert manager.initialized is True
        assert type(manager.engine).__name__ == "FW"
        assert any(e["engine"] == "FW" and e.get("initialized") for e in record)

    def test_local_all_engines_fail_falls_back_to_dummy(self, monkeypatch):
        record = []
        monkeypatch.setattr(m.os.path, "exists", lambda p: False)
        _patch_engines(
            monkeypatch,
            hf=_engine_cls(record, "HF", fail=True),
            fw=_engine_cls(record, "FW", fail=True),
        )

        manager = _make_manager(monkeypatch, provider="local")
        asyncio.run(manager.initialize())

        assert isinstance(manager.engine, m.DummySTTEngine)
        assert manager.initialized is True

    def test_local_hf_present_but_failing_then_fw_succeeds(self, monkeypatch):
        record = []
        monkeypatch.setattr(m.os.path, "exists", lambda p: True)
        _patch_engines(
            monkeypatch,
            hf=_engine_cls(record, "HF", fail=True),
            fw=_engine_cls(record, "FW"),
        )
        monkeypatch.setattr(m, "get_resource_manager", None)

        manager = _make_manager(monkeypatch, provider="local")
        asyncio.run(manager.initialize())

        assert type(manager.engine).__name__ == "FW"

    def test_legacy_cloud_engine_overrides_local_provider(self, monkeypatch):
        record = []
        _patch_engines(monkeypatch, cloud=_engine_cls(record, "Cloud"))

        manager = _make_manager(
            monkeypatch, provider="local", stt_engine="siliconflow"
        )
        asyncio.run(manager.initialize())

        assert type(manager.engine).__name__ == "Cloud"
        assert manager.initialized is True

    def test_siliconflow_defaults_model_and_base_url(self, monkeypatch):
        record = []
        _patch_engines(monkeypatch, cloud=_engine_cls(record, "Cloud"))

        manager = _make_manager(monkeypatch, provider="siliconflow", model=None)
        asyncio.run(manager.initialize())

        ctor = record[0]["ctor"]
        assert ctor["model"] == "FunAudioLLM/SenseVoiceSmall"
        assert ctor["base_url"] == "https://api.siliconflow.cn/v1/audio/transcriptions"

    def test_siliconflow_default_placeholder_model_is_replaced(self, monkeypatch):
        record = []
        _patch_engines(monkeypatch, cloud=_engine_cls(record, "Cloud"))

        manager = _make_manager(monkeypatch, provider="siliconflow", model="default")
        asyncio.run(manager.initialize())

        assert record[0]["ctor"]["model"] == "FunAudioLLM/SenseVoiceSmall"

    def test_openai_defaults_model_and_base_url(self, monkeypatch):
        record = []
        _patch_engines(monkeypatch, cloud=_engine_cls(record, "Cloud"))

        manager = _make_manager(monkeypatch, provider="openai", model=None)
        asyncio.run(manager.initialize())

        ctor = record[0]["ctor"]
        assert ctor["model"] == "whisper-1"
        assert ctor["base_url"] == "https://api.openai.com/v1/audio/transcriptions"

    def test_cloud_provider_keeps_explicit_config(self, monkeypatch):
        record = []
        _patch_engines(monkeypatch, cloud=_engine_cls(record, "Cloud"))

        manager = _make_manager(
            monkeypatch,
            provider="cloud",
            model="my-model",
            base_url="https://custom/v1",
            api_key="k",
        )
        asyncio.run(manager.initialize())

        ctor = record[0]["ctor"]
        assert ctor == {"api_key": "k", "base_url": "https://custom/v1", "model": "my-model"}

    def test_unknown_provider_falls_back_to_dummy(self, monkeypatch):
        manager = _make_manager(monkeypatch, provider="something-else")
        asyncio.run(manager.initialize())

        assert isinstance(manager.engine, m.DummySTTEngine)


class TestSTTManagerResourceRegistration:
    """资源管理器注册的逐层降级。"""

    def test_register_skipped_without_resource_manager(self, monkeypatch):
        monkeypatch.setattr(m, "get_resource_manager", None)
        manager = _make_manager(monkeypatch)

        manager._register_resource_manager()

        assert manager.engine is None

    def test_register_model_failure_is_swallowed(self, monkeypatch):
        rm = _RMStub(raise_register=True)
        monkeypatch.setattr(m, "get_resource_manager", lambda: rm)
        manager = _make_manager(monkeypatch)

        manager._register_resource_manager()  # 不应抛出

        assert len(rm.models) == 1

    def test_register_handler_failure_is_swallowed(self, monkeypatch):
        rm = _RMStub(raise_handler=True)
        monkeypatch.setattr(m, "get_resource_manager", lambda: rm)
        manager = _make_manager(monkeypatch)

        manager._register_resource_manager()  # 内层 except 吞掉

        assert len(rm.handlers) == 1

    def test_register_success_records_model_and_handler(self, monkeypatch):
        rm = _RMStub()
        monkeypatch.setattr(m, "get_resource_manager", lambda: rm)
        manager = _make_manager(monkeypatch)

        manager._register_resource_manager()

        assert rm.models[0]["model_id"] == "stt_engine"
        assert rm.models[0]["model_type"] == "stt"
        assert rm.handlers[0][0] == "gpu_memory"


class TestSTTManagerBehavior:
    """资源压力回调、卸载、搬移、获取引擎、转写与关闭。"""

    def test_handle_resource_pressure_release_moves_to_cpu(self, monkeypatch):
        manager = _make_manager(monkeypatch)
        calls = []

        class _Engine:
            async def move_to_cpu(self):
                calls.append("cpu")

        manager.engine = _Engine()
        asyncio.run(manager.handle_resource_pressure("Release"))

        assert calls == ["cpu"]

    def test_handle_resource_pressure_recover_is_noop(self, monkeypatch):
        manager = _make_manager(monkeypatch)
        calls = []

        class _Engine:
            async def move_to_cpu(self):
                calls.append("cpu")

        manager.engine = _Engine()
        asyncio.run(manager.handle_resource_pressure("recover"))
        asyncio.run(manager.handle_resource_pressure("restore"))

        assert calls == []

    def test_handle_resource_pressure_other_action_is_noop(self, monkeypatch):
        manager = _make_manager(monkeypatch)

        asyncio.run(manager.handle_resource_pressure(None))
        asyncio.run(manager.handle_resource_pressure("unknown"))

        assert manager.engine is None

    def test_unload_model_calls_engine(self, monkeypatch):
        manager = _make_manager(monkeypatch)
        calls = []

        class _Engine:
            async def unload_model(self):
                calls.append("unload")

        manager.engine = _Engine()
        manager.initialized = True
        asyncio.run(manager.unload_model())

        assert calls == ["unload"]
        assert manager.initialized is False

    def test_unload_model_noop_without_engine(self, monkeypatch):
        manager = _make_manager(monkeypatch)
        manager.engine = None

        asyncio.run(manager.unload_model())

        assert manager.initialized is False

    def test_unload_model_noop_when_engine_lacks_method(self, monkeypatch):
        manager = _make_manager(monkeypatch)
        manager.engine = object()

        asyncio.run(manager.unload_model())

        assert manager.initialized is False

    def test_move_to_cpu_and_gpu_delegate(self, monkeypatch):
        manager = _make_manager(monkeypatch)
        calls = []

        class _Engine:
            async def move_to_cpu(self):
                calls.append("cpu")

            async def move_to_gpu(self):
                calls.append("gpu")

        manager.engine = _Engine()
        asyncio.run(manager.move_to_cpu())
        asyncio.run(manager.move_to_gpu())

        assert calls == ["cpu", "gpu"]

    def test_move_noop_without_engine(self, monkeypatch):
        manager = _make_manager(monkeypatch)
        manager.engine = None

        asyncio.run(manager.move_to_cpu())
        asyncio.run(manager.move_to_gpu())

        assert manager.engine is None

    def test_get_engine_initializes_lazily(self, monkeypatch):
        manager = _make_manager(monkeypatch, provider="something-else")

        engine = asyncio.run(manager.get_engine())

        assert isinstance(engine, m.DummySTTEngine)
        assert manager.initialized is True

    def test_transcribe_delegates_to_engine(self, monkeypatch):
        manager = _make_manager(monkeypatch, provider="something-else")

        result = asyncio.run(manager.transcribe(b"audio", language="zh"))

        assert result["text"] == "这是一段模拟的转录文本"

    def test_shutdown_clears_state(self, monkeypatch):
        manager = _make_manager(monkeypatch)
        calls = []

        class _Engine:
            async def shutdown(self):
                calls.append("shutdown")

        manager.engine = _Engine()
        manager.initialized = True
        asyncio.run(manager.shutdown())

        assert calls == ["shutdown"]
        assert manager.initialized is False

    def test_shutdown_without_engine(self, monkeypatch):
        manager = _make_manager(monkeypatch)
        manager.engine = None
        manager.initialized = True

        asyncio.run(manager.shutdown())

        assert manager.initialized is False
