"""core/voice/engines/qwen3_tts_engine.py —— 生命周期与设备迁移单元测试。

覆盖 ``__init__`` / ``_spawn_batch_task`` / ``_resolve_model_path`` / ``initialize`` /
``handle_resource_pressure`` / ``move_to_cpu`` / ``move_to_gpu`` / ``shutdown`` 与模块级
可选依赖的 import 兜底。

**绝不加载真实模型**：``torch`` / ``faster_qwen3_tts`` / ``qwen_tts`` 一律以替身注入
``sys.modules``；不下载权重、不使用 GPU、不发起网络请求，文件 IO 落在 ``tmp_path``。
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
from concurrent.futures import ThreadPoolExecutor

import pytest

import core.voice.engines.qwen3_tts_engine as mod
from core.voice.engines.qwen3_tts_engine import Qwen3TTSEngine


class _RecordingLogger:
    """模块级 logger 替身（真实 logger 的 propagate=False，不便用 caplog）。"""

    def __init__(self):
        self.records = []

    def messages(self, level=None):
        return [m for lv, m in self.records if level is None or lv == level]

    def _bind(level):
        def _log(self, msg, *args, **kwargs):
            self.records.append((level, msg))
        return _log

    debug, info, warning, error = (_bind("debug"), _bind("info"),
                                   _bind("warning"), _bind("error"))


class _SettingsStub:
    def __init__(self, model="", reference_audio=None, tts_vram_threshold_mb=0):
        self.voice = types.SimpleNamespace(
            tts=types.SimpleNamespace(model=model),
            reference_audio=reference_audio,
            tts_vram_threshold_mb=tts_vram_threshold_mb,
        )


class _RMStub:
    def __init__(self):
        self.handlers = []

    def register_resource_handler(self, *args):
        self.handlers.append(args)


def _install_torch(monkeypatch, *, available=True, name="NVIDIA GeForce RTX 4090",
                   capability=(8, 9), with_ipc_collect=True):
    """注入假 torch；返回 (empty_cache 调用记录, ipc_collect 调用记录)。"""
    empty, ipc = [], []
    cuda = types.SimpleNamespace(
        is_available=lambda: available,
        get_device_name=lambda idx: name,
        get_device_capability=lambda idx: capability,
        empty_cache=lambda: empty.append(1),
    )
    if with_ipc_collect:
        cuda.ipc_collect = lambda: ipc.append(1)
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(
        cuda=cuda, bfloat16="bf16", float16="fp16", float32="fp32"))
    return empty, ipc


def _install_faster(monkeypatch, *, exc=None):
    """注入假 ``faster_qwen3_tts`` 模块；返回 from_pretrained 调用记录。"""
    record = []

    class _Model:
        predictor_graph = object()

        def __init__(self, path):
            self.path = path

    class _FasterQwen3TTS:
        @staticmethod
        def from_pretrained(path, **kwargs):
            record.append((path, kwargs))
            if exc is not None:
                raise exc
            return _Model(path)

    module = types.ModuleType("faster_qwen3_tts")
    module.FasterQwen3TTS = _FasterQwen3TTS
    monkeypatch.setitem(sys.modules, "faster_qwen3_tts", module)
    return record


def _install_qwen_tts(monkeypatch, *, exc=None):
    """注入假 ``qwen_tts`` 模块；返回 from_pretrained 调用记录。"""
    record = []

    class Qwen3TTSModel:
        @staticmethod
        def from_pretrained(path, **kwargs):
            record.append((path, kwargs))
            if exc is not None:
                raise exc
            return object()

    module = types.ModuleType("qwen_tts")
    module.Qwen3TTSModel = Qwen3TTSModel
    monkeypatch.setitem(sys.modules, "qwen_tts", module)
    return record


def _patch_config(monkeypatch, *, model="", model_dir="models", reference_audio=None):
    monkeypatch.setattr(mod, "get_settings", lambda: _SettingsStub(
        model=model, reference_audio=reference_audio))
    monkeypatch.setattr(mod, "get_config", lambda *a, **kw: model_dir)


async def _drain(rounds=4):
    """让出事件循环若干轮，用于观察 fire-and-forget 任务的完成回调。"""
    for _ in range(rounds):
        await asyncio.sleep(0)


@pytest.fixture
def engine():
    eng = Qwen3TTSEngine()
    yield eng
    if eng._executor is not None:
        eng._executor.shutdown(wait=False)


class TestInit:
    def test_defaults_and_override(self):
        eng = Qwen3TTSEngine()
        try:
            assert eng.model_path is None
            assert eng._model is None
            assert eng.current_device == "cpu"
            assert eng._is_generating is False
            assert eng.initialized is False
            assert isinstance(eng._executor, ThreadPoolExecutor)
            assert (eng._batch_queue, eng._batch_results) == ([], {})
            assert (eng._batch_timer, eng._batch_max_wait) == (None, 0.05)
            assert eng._batch_max_size == 4
            assert eng._batch_tasks == set()
            assert type(eng._load_lock).__name__ == "LazyAsyncLock"
            assert type(eng._batch_lock).__name__ == "LazyAsyncLock"
        finally:
            eng._executor.shutdown(wait=False)
        custom = Qwen3TTSEngine(model_path="some/model")
        try:
            assert custom.model_path == "some/model"
        finally:
            custom._executor.shutdown(wait=False)


class TestSpawnBatchTask:
    async def test_success_removes_task_without_error(self, engine, monkeypatch):
        rec = _RecordingLogger()
        monkeypatch.setattr(mod, "logger", rec)

        async def _ok():
            return 1

        engine._spawn_batch_task(_ok())
        assert len(engine._batch_tasks) == 1
        await _drain()
        assert engine._batch_tasks == set()
        assert rec.messages("error") == []

    async def test_exception_is_logged_and_task_removed(self, engine, monkeypatch):
        rec = _RecordingLogger()
        monkeypatch.setattr(mod, "logger", rec)

        async def _boom():
            raise ValueError("kaboom")

        engine._spawn_batch_task(_boom())
        await _drain()
        assert engine._batch_tasks == set()
        assert any("批处理任务异常" in m for m in rec.messages("error"))

    async def test_cancelled_task_is_silent(self, engine, monkeypatch):
        rec = _RecordingLogger()
        monkeypatch.setattr(mod, "logger", rec)

        async def _never():
            await asyncio.Event().wait()

        engine._spawn_batch_task(_never())
        task = next(iter(engine._batch_tasks))
        task.cancel()
        await asyncio.wait([task])  # 取消类断言不 await 已 cancel 的任务
        await _drain()
        assert task.cancelled()
        assert engine._batch_tasks == set()
        assert rec.messages("error") == []


class TestResolveModelPath:
    def _patch(self, monkeypatch, tmp_path, *, model_hint="", model_dir="models"):
        monkeypatch.setattr(mod, "get_settings",
                            lambda: _SettingsStub(model=model_hint))
        monkeypatch.setattr(mod, "get_config", lambda *a, **kw: model_dir)
        monkeypatch.setattr(mod, "get_project_root", lambda: tmp_path)

    def test_absolute_path_returns_existence(self, engine, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        target = tmp_path / "abs_model"
        target.mkdir()
        engine.model_path = str(target)
        assert engine._resolve_model_path() == (str(target), True)
        missing = str(tmp_path / "nope")
        engine.model_path = missing
        assert engine._resolve_model_path() == (missing, False)

    def test_relative_path_candidates(self, engine, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        engine.model_path = os.path.join("rel", "m")
        expected = os.path.join(str(tmp_path), "rel", "m")
        # 未创建时兜底到第一个候选
        assert engine._resolve_model_path() == (expected, False)
        (tmp_path / "rel" / "m").mkdir(parents=True)
        assert engine._resolve_model_path() == (expected, True)

    def test_hint_absolute_found(self, engine, monkeypatch, tmp_path):
        target = tmp_path / "hint_abs"
        target.mkdir()
        self._patch(monkeypatch, tmp_path, model_hint=str(target))
        assert engine._resolve_model_path() == (str(target), True)

    @pytest.mark.parametrize("subdir", [(), ("models",), ("models", "tts")])
    def test_hint_relative_found_at_various_depths(self, engine, monkeypatch, tmp_path,
                                                   subdir):
        target = tmp_path.joinpath(*subdir) / "myhint"
        target.mkdir(parents=True)
        self._patch(monkeypatch, tmp_path, model_hint="myhint")
        assert engine._resolve_model_path() == (str(target), True)

    @pytest.mark.parametrize("hint", ["", "default", "gpt_sovits", "qwen3", "QWEN3"])
    def test_ignored_hint_values_use_default_candidates(self, engine, monkeypatch,
                                                        tmp_path, hint):
        self._patch(monkeypatch, tmp_path, model_hint=hint)
        assert engine._resolve_model_path() == (
            os.path.join(str(tmp_path), "models", "Qwen3-TTS-12Hz-0.6B-Base"), False)

    def test_default_candidate_found(self, engine, monkeypatch, tmp_path):
        target = tmp_path / "models" / "Qwen3-TTS-12Hz-0.6B-Base"
        target.mkdir(parents=True)
        self._patch(monkeypatch, tmp_path)
        assert engine._resolve_model_path() == (str(target), True)

    @pytest.mark.parametrize("model_dir", ["", None])
    def test_empty_model_dir_falls_back_to_models(self, engine, monkeypatch, tmp_path,
                                                  model_dir):
        target = tmp_path / "models" / "Qwen3-TTS"
        target.mkdir(parents=True)
        self._patch(monkeypatch, tmp_path, model_dir=model_dir)
        assert engine._resolve_model_path() == (str(target), True)


class TestInitialize:
    @pytest.fixture
    def prepared(self, engine, monkeypatch, tmp_path):
        _patch_config(monkeypatch)
        monkeypatch.setattr(engine, "_resolve_model_path", lambda: (str(tmp_path), True))
        calls = []
        monkeypatch.setattr(mod, "_ensure_sox_mock", lambda: calls.append(1))
        return calls

    async def test_already_initialized_returns_early(self, engine, prepared, monkeypatch):
        engine.initialized = True
        _install_torch(monkeypatch)
        assert await engine.initialize() is None
        assert prepared == []  # 未走到 _ensure_sox_mock

    async def test_missing_path_logs_warning(self, engine, monkeypatch, tmp_path):
        rec = _RecordingLogger()
        monkeypatch.setattr(mod, "logger", rec)
        _patch_config(monkeypatch)
        monkeypatch.setattr(engine, "_resolve_model_path",
                            lambda: (str(tmp_path / "missing"), False))
        monkeypatch.setattr(mod, "_ensure_sox_mock", lambda: None)
        monkeypatch.setattr(mod, "get_resource_manager", None)
        _install_torch(monkeypatch, available=False)
        _install_qwen_tts(monkeypatch)
        await engine.initialize()
        assert any("model path not found" in m for m in rec.messages("warning"))

    @pytest.mark.parametrize("name,capability,expected", [
        ("NVIDIA GeForce RTX 5090", (10, 0), "Blackwell"),
        ("NVIDIA H100", (9, 0), "Hopper"),
        ("NVIDIA GeForce RTX 4090", (8, 9), "Ada Lovelace"),
        ("NVIDIA GeForce RTX 4060", (8, 6), "Ada Lovelace"),
        ("NVIDIA A100", (8, 0), "Ampere"),
        ("NVIDIA T4", (7, 5), "Unknown"),
    ])
    async def test_faster_path_arch_detection(self, engine, prepared, monkeypatch,
                                              name, capability, expected):
        rec = _RecordingLogger()
        monkeypatch.setattr(mod, "logger", rec)
        monkeypatch.setattr(mod, "get_resource_manager", None)
        _install_torch(monkeypatch, name=name, capability=capability)
        _install_faster(monkeypatch)
        await engine.initialize()
        assert engine.current_device == "cuda"
        assert engine.initialized is True
        assert hasattr(engine._model, "predictor_graph")
        assert any(f"{expected}架构" in m for m in rec.messages("info"))

    async def test_registers_with_resource_manager(self, engine, prepared, monkeypatch):
        rm = _RMStub()
        monkeypatch.setattr(mod, "get_resource_manager", lambda: rm)
        monkeypatch.setattr(mod, "ResourcePriority",
                            types.SimpleNamespace(MEDIUM="medium"))
        _install_torch(monkeypatch)
        _install_faster(monkeypatch)
        await engine.initialize()
        assert rm.handlers == [
            ("gpu_memory", "medium", engine.handle_resource_pressure)]

    async def test_fallback_to_original_model_on_cuda(self, engine, prepared,
                                                      monkeypatch):
        rec = _RecordingLogger()
        monkeypatch.setattr(mod, "logger", rec)
        monkeypatch.setattr(mod, "get_resource_manager", None)
        _install_torch(monkeypatch, available=True)
        _install_faster(monkeypatch, exc=RuntimeError("faster boom"))
        qwen_calls = _install_qwen_tts(monkeypatch)
        await engine.initialize()
        assert engine.current_device == "cuda"
        assert qwen_calls[0][1] == {
            "device_map": "cuda:0", "dtype": "bf16", "attn_implementation": "sdpa"}
        assert any("FasterQwen3-TTS不可用" in m for m in rec.messages("warning"))

    async def test_fallback_to_original_model_on_cpu(self, engine, prepared,
                                                     monkeypatch):
        monkeypatch.setattr(mod, "get_resource_manager", None)
        _install_torch(monkeypatch, available=False)
        qwen_calls = _install_qwen_tts(monkeypatch)
        await engine.initialize()
        assert engine.current_device == "cpu"
        assert qwen_calls[0][1] == {
            "device_map": "cpu", "dtype": "fp32", "attn_implementation": "sdpa"}

    async def test_all_loads_fail_cleans_up_and_raises(self, engine, prepared,
                                                       monkeypatch):
        rec = _RecordingLogger()
        monkeypatch.setattr(mod, "logger", rec)
        monkeypatch.setattr(mod, "get_resource_manager", None)
        empty, ipc = _install_torch(monkeypatch, available=True)
        _install_faster(monkeypatch, exc=RuntimeError("faster boom"))
        _install_qwen_tts(monkeypatch, exc=RuntimeError("qwen boom"))
        with pytest.raises(RuntimeError, match="qwen boom"):
            await engine.initialize()
        assert (engine._model, engine.initialized) == (None, False)
        assert (empty, ipc) == ([1], [1])
        assert any("所有TTS模型加载均失败" in m for m in rec.messages("error"))

    async def test_all_loads_fail_without_cuda_skips_cleanup(self, engine, prepared,
                                                             monkeypatch):
        monkeypatch.setattr(mod, "get_resource_manager", None)
        empty, ipc = _install_torch(monkeypatch, available=False,
                                    with_ipc_collect=False)
        _install_qwen_tts(monkeypatch, exc=RuntimeError("qwen boom"))
        with pytest.raises(RuntimeError, match="qwen boom"):
            await engine.initialize()
        assert (empty, ipc) == ([], [])


class TestHandleResourcePressure:
    @pytest.fixture
    def moved(self, engine, monkeypatch):
        record = []

        async def _move():
            record.append(1)
            return True

        monkeypatch.setattr(engine, "move_to_cpu", _move)
        return record

    async def test_release_on_cuda_moves_to_cpu(self, engine, moved):
        engine.current_device, engine._is_generating = "cuda", False
        await engine.handle_resource_pressure("release")
        assert moved == [1]

    @pytest.mark.parametrize("action,device,generating", [
        ("release", "cpu", False), ("release", "cuda", True), ("recover", "cuda", False)])
    async def test_noop_cases(self, engine, moved, action, device, generating):
        engine.current_device, engine._is_generating = device, generating
        await engine.handle_resource_pressure(action)
        assert moved == []


class TestMoveDevice:
    async def test_move_to_cpu_already_cpu(self, engine, monkeypatch):
        _install_torch(monkeypatch)
        assert await engine.move_to_cpu() is True

    @pytest.mark.parametrize("available,expect_empty", [(True, [1]), (False, [])])
    async def test_move_to_cpu_reload(self, engine, monkeypatch, tmp_path, available,
                                      expect_empty):
        rec = _RecordingLogger()
        monkeypatch.setattr(mod, "logger", rec)
        engine.current_device, engine.model_path = "cuda", str(tmp_path)
        empty, _ = _install_torch(monkeypatch, available=available)
        qwen_calls = _install_qwen_tts(monkeypatch)
        assert await engine.move_to_cpu() is True
        assert engine.current_device == "cpu"
        assert empty == expect_empty
        assert qwen_calls == [(str(tmp_path), {
            "device_map": "cpu", "dtype": "fp32", "attn_implementation": "sdpa"})]
        assert any("不支持CPU模式" in m for m in rec.messages("info"))

    async def test_move_to_gpu_early_returns(self, engine, monkeypatch):
        _install_torch(monkeypatch, available=False)
        assert await engine.move_to_gpu() is False
        _install_torch(monkeypatch, available=True)
        engine.current_device = "cuda"
        assert await engine.move_to_gpu() is True

    async def test_move_to_gpu_reload(self, engine, monkeypatch, tmp_path):
        engine.current_device, engine.model_path = "cpu", str(tmp_path)
        empty, _ = _install_torch(monkeypatch, available=True)
        faster_calls = _install_faster(monkeypatch)
        assert await engine.move_to_gpu() is True
        assert engine.current_device == "cuda"
        assert empty == [1]
        assert faster_calls == [(str(tmp_path), {})]


class TestShutdown:
    async def test_shutdown_variants(self, engine):
        class _Exec:
            def __init__(self):
                self.shutdown_calls = []

            def shutdown(self, wait=True):
                self.shutdown_calls.append(wait)

        exec_stub = _Exec()
        engine._executor = exec_stub
        engine._model = object()
        engine.initialized = True
        await engine.shutdown()
        assert engine._model is None
        assert exec_stub.shutdown_calls == [False]
        assert engine.initialized is False

        engine._executor = None
        engine.initialized = True
        await engine.shutdown()
        assert engine._executor is None
        assert engine.initialized is False


def _load_probe(monkeypatch, blocked_names):
    """在独立命名空间重新执行被测模块源码，仅拦截指定模块名的 import。"""
    import builtins
    import importlib.util
    from pathlib import Path

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name in blocked_names:
            raise ImportError(f"blocked {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    spec = importlib.util.spec_from_file_location(
        "_qwen3_tts_engine_import_probe", Path(mod.__file__))
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    return probe


class TestModuleImportGuard:
    def test_soundfile_missing(self, monkeypatch):
        assert _load_probe(monkeypatch, {"soundfile"}).sf is None

    def test_resource_lock_missing(self, monkeypatch):
        probe = _load_probe(monkeypatch, {"core.utils.resource_lock"})
        assert probe.get_resource_lock is None

    def test_resource_manager_missing(self, monkeypatch):
        probe = _load_probe(monkeypatch, {"core.resource_manager"})
        assert probe.get_resource_manager is None
        assert probe.ResourcePriority is None
