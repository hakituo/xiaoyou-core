"""core/voice/engines/gpt_sovits_engine.py —— 生命周期与权重控制单元测试。

覆盖 ``__init__`` / ``_is_connection_error_text`` / ``_log_unavailable`` /
``_get_session`` / ``initialize`` / ``handle_resource_pressure`` /
``_build_control_url`` / ``_resolve_local_path`` / ``_try_set_weights`` /
``set_gpt_weights`` / ``set_sovits_weights`` / ``move_to_cpu`` / ``move_to_gpu``，
以及模块级可选依赖的 import 兜底。

全部用假 session 替换 aiohttp，不发起真实网络请求；文件 IO 落在 ``tmp_path``。
"""

from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace

import aiohttp
import pytest

import core.voice.engines.gpt_sovits_engine as mod
from core.voice.engines.gpt_sovits_engine import GPTSoVITSEngine


class FakeResponse:
    """假响应：只暴露 status / text。"""

    def __init__(self, status=200, text=""):
        self.status, self._text = status, text

    async def text(self):
        return self._text


class _Ctx:
    """假异步上下文管理器，可携带「进入即抛出」的异常。"""

    def __init__(self, resp=None, exc=None):
        self._resp, self._exc = resp, exc

    async def __aenter__(self):
        if self._exc is not None:
            raise self._exc
        return self._resp

    async def __aexit__(self, *exc_info):
        return False


class FakeSession:
    """按预设序列返回响应，并记录每次调用 kwargs。"""

    def __init__(self, get_plan=None, post_plan=None):
        self.get_calls, self.post_calls = [], []
        self._get_plan = list(get_plan or [])
        self._post_plan = list(post_plan or [])

    def _dispatch(self, plan, calls, url, kwargs):
        calls.append({"url": url, **kwargs})
        item = plan.pop(0) if plan else FakeResponse()
        return _Ctx(exc=item) if isinstance(item, BaseException) else _Ctx(item)

    def get(self, url, **kwargs):
        return self._dispatch(self._get_plan, self.get_calls, url, kwargs)

    def post(self, url, **kwargs):
        return self._dispatch(self._post_plan, self.post_calls, url, kwargs)


class _VoiceStub:
    def __init__(self, gpt_model_path=None, sovits_model_path=None):
        self.gpt_model_path = gpt_model_path
        self.sovits_model_path = sovits_model_path


class _SettingsStub:
    def __init__(self, **voice_kwargs):
        self.voice = _VoiceStub(**voice_kwargs)


class _RMStub:
    def __init__(self):
        self.handlers = []

    def register_resource_handler(self, *args):
        self.handlers.append(args)


@pytest.fixture
def engine():
    return GPTSoVITSEngine()


def _patch_session(monkeypatch, session):
    async def _fake(_engine):
        return session

    monkeypatch.setattr(mod, "get_cloud_tts_session", _fake)


def _patch_settings(monkeypatch, **voice_kwargs):
    monkeypatch.setattr(mod, "get_settings", lambda: _SettingsStub(**voice_kwargs))


def _g0(session):
    return session.get_calls[0]


class TestInit:
    def test_defaults_and_overrides(self):
        eng = GPTSoVITSEngine()
        assert (eng.api_url, eng.default_lang, eng.sample_rate) == \
            ("http://127.0.0.1:9880/tts", "zh", 32000)
        assert (eng._session, eng._session_loop, eng._session_lock) == (None, None, None)
        assert (eng._control_unavailable_until, eng.current_device) == (0.0, "cpu")
        assert (eng._is_generating, eng._last_unavailable_log_ts) == (False, 0.0)
        assert (eng._unavailable_log_interval, eng.initialized) == (15.0, False)

        custom = GPTSoVITSEngine(api_url="http://h:1/x", default_lang="ja")
        assert (custom.api_url, custom.default_lang) == ("http://h:1/x", "ja")


class TestIsConnectionErrorText:
    @pytest.mark.parametrize("text,expected", [
        ("Cannot connect to host", True), ("connection refused", True),
        ("Connection error", True), ("Operation timed out", True),
        ("Request timeout", True), ("actively refused", True),
        ("无法连接服务器", True), ("请求超时", True),
        ("bad request", False), ("500 internal error", False),
        ("", False), (None, False),
    ])
    def test_classification(self, engine, text, expected):
        assert engine._is_connection_error_text(text) is expected


class TestLogUnavailable:
    def test_warning_then_debug_throttle(self, engine):
        engine._last_unavailable_log_ts = 0.0
        engine._log_unavailable("切换到 CPU", RuntimeError("x"))
        assert engine._last_unavailable_log_ts > 0.0  # 首次走 warning 分支

        marker = time.monotonic()
        engine._last_unavailable_log_ts = marker
        engine._log_unavailable("切换到 CPU", RuntimeError("x"))
        assert engine._last_unavailable_log_ts == marker  # 间隔内走 debug 分支


class TestGetSession:
    async def test_delegates_to_helper(self, engine, monkeypatch):
        sentinel, seen = object(), []

        async def _fake(eng):
            seen.append(eng)
            return sentinel

        monkeypatch.setattr(mod, "get_cloud_tts_session", _fake)
        assert await engine._get_session() is sentinel
        assert seen == [engine]


class TestInitialize:
    async def test_sets_configured_weights(self, engine, monkeypatch):
        _patch_settings(monkeypatch, gpt_model_path="g.ckpt", sovits_model_path="s.pth")
        monkeypatch.setattr(mod, "get_resource_manager", None)
        calls = []

        async def _gpt(p):
            calls.append(("gpt", p))

        async def _sovits(p):
            calls.append(("sovits", p))

        monkeypatch.setattr(engine, "set_gpt_weights", _gpt)
        monkeypatch.setattr(engine, "set_sovits_weights", _sovits)

        await engine.initialize()
        assert engine.initialized is True
        assert calls == [("gpt", "g.ckpt"), ("sovits", "s.pth")]

    @pytest.mark.parametrize("rm_available", [True, False])
    async def test_skips_weights_and_optionally_registers(self, engine, monkeypatch,
                                                          rm_available):
        _patch_settings(monkeypatch, gpt_model_path="", sovits_model_path=None)
        rm = _RMStub()
        monkeypatch.setattr(mod, "get_resource_manager", (lambda: rm) if rm_available else None)
        monkeypatch.setattr(mod, "ResourcePriority", SimpleNamespace(MEDIUM="medium"))
        calls = []
        monkeypatch.setattr(engine, "set_gpt_weights", lambda p: calls.append(p))
        monkeypatch.setattr(engine, "set_sovits_weights", lambda p: calls.append(p))

        await engine.initialize()

        assert engine.initialized is True
        assert calls == []  # 未配置权重不调用 setter
        expected = [("gpu_memory", "medium", engine.handle_resource_pressure)]
        assert rm.handlers == (expected if rm_available else [])


class TestHandleResourcePressure:
    @pytest.fixture
    def moved(self, engine, monkeypatch):
        record = []

        async def _move():
            record.append(1)
            return True

        monkeypatch.setattr(engine, "move_to_cpu", _move)
        return record

    async def test_release_on_cuda_moves(self, engine, moved):
        engine.current_device, engine._is_generating = "cuda", False
        await engine.handle_resource_pressure("release")
        assert moved == [1]

    @pytest.mark.parametrize("device,generating", [("cpu", False), (None, False),
                                                   ("cuda", True)])
    async def test_release_noop_cases(self, engine, moved, device, generating):
        engine.current_device, engine._is_generating = device, generating
        await engine.handle_resource_pressure("release")
        assert moved == []

    async def test_non_release_noop(self, engine, moved):
        engine.current_device = "cuda"
        await engine.handle_resource_pressure("recover")
        assert moved == []


class TestBuildControlUrl:
    @pytest.mark.parametrize("api_url,endpoint,expected", [
        ("http://127.0.0.1:9880/tts", "set_gpt_weights",
         "http://127.0.0.1:9880/set_gpt_weights"),
        ("http://127.0.0.1:9880/tts/", "/set_device",
         "http://127.0.0.1:9880/set_device"),
        ("http://host:9999", "ping", "http://host:9999/ping"),
        ("", "/set_device", "http://127.0.0.1:9880/set_device"),
        (None, "x", "http://127.0.0.1:9880/x"),
        ("http://127.0.0.1:9880/tts", "", "http://127.0.0.1:9880/"),
    ])
    def test_urls(self, engine, api_url, endpoint, expected):
        engine.api_url = api_url
        assert engine._build_control_url(endpoint) == expected


class TestResolveLocalPath:
    def test_empty(self, engine):
        assert engine._resolve_local_path("") == ""
        assert engine._resolve_local_path(None) == ""

    def test_absolute_normalized(self, engine, tmp_path):
        raw = str(tmp_path / "a" / ".." / "b")
        assert engine._resolve_local_path(raw) == os.path.normpath(raw)

    def test_relative_joined_with_cwd(self, engine):
        assert engine._resolve_local_path("rel/f.wav") == os.path.normpath(
            os.path.abspath(os.path.join(os.getcwd(), "rel/f.wav")))

    def test_tilde_expanded(self, engine):
        result = engine._resolve_local_path("~/probe.wav")
        assert os.path.isabs(result)
        assert result.endswith("probe.wav")


class TestTrySetWeights:
    async def _run(self, engine, monkeypatch, get_plan=None, post_plan=None):
        session = FakeSession(get_plan=get_plan, post_plan=post_plan)
        _patch_session(monkeypatch, session)
        ok = await engine._try_set_weights(
            endpoint="/set_gpt_weights", weights_path="w.ckpt", kind="GPT")
        return ok, session

    async def test_get_success(self, engine, monkeypatch):
        ok, session = await self._run(engine, monkeypatch, get_plan=[FakeResponse(200)])
        assert ok is True
        assert _g0(session)["url"] == "http://127.0.0.1:9880/set_gpt_weights"
        assert _g0(session)["params"] == {"weights_path": "w.ckpt"}
        assert session.post_calls == []

    @pytest.mark.parametrize("statuses", [[400, 404, 405, 422, 200], [400, 200]])
    async def test_get_candidate_scan_succeeds(self, engine, monkeypatch, statuses):
        # 400/404/405/422 属于参数名不对的候选：continue 到下一个候选
        ok, session = await self._run(
            engine, monkeypatch, get_plan=[FakeResponse(s) for s in statuses])
        assert ok is True
        assert len(session.get_calls) == len(statuses)

    async def test_get_connection_error_breaks(self, engine, monkeypatch):
        ok, session = await self._run(
            engine, monkeypatch, get_plan=[aiohttp.ClientError("Cannot connect to host")])
        assert ok is False
        assert len(session.get_calls) == 1  # break，不再试其余候选
        assert session.post_calls == []
        assert engine._control_unavailable_until > time.monotonic()

    async def test_cooldown_short_circuits(self, engine, monkeypatch):
        engine._control_unavailable_until = time.monotonic() + 100.0
        ok, session = await self._run(engine, monkeypatch)
        assert ok is False
        assert session.get_calls == [] and session.post_calls == []

    @pytest.mark.parametrize("get_plan,post_plan,expected,post_calls", [
        ([ValueError("bad")] * 5, [FakeResponse(200)], True, 1),
        ([FakeResponse(500, "boom")] * 5, [FakeResponse(200)], True, 1),
        ([FakeResponse(400)] * 5, [ValueError("bad json")] * 5, False, 5),
        ([FakeResponse(400)] * 5, [FakeResponse(400)] * 5, False, 5),
    ])
    async def test_post_stage(self, engine, monkeypatch, get_plan, post_plan,
                              expected, post_calls):
        # GET 全失败后进入 POST：成功 / 非连接错误 continue / 全失败三种走向
        ok, session = await self._run(engine, monkeypatch, get_plan=get_plan,
                                      post_plan=post_plan)
        assert ok is expected
        assert len(session.get_calls) == 5
        assert len(session.post_calls) == post_calls

    async def test_post_connection_error_breaks(self, engine, monkeypatch):
        ok, session = await self._run(
            engine, monkeypatch, get_plan=[FakeResponse(400)] * 5,
            post_plan=[aiohttp.ClientError("connection refused")])
        assert ok is False
        assert len(session.post_calls) == 1
        assert engine._control_unavailable_until > time.monotonic()

    async def test_cooldown_set_midflight_by_concurrent_task(self, engine, monkeypatch):
        """冷却窗口被并发任务在 await 点置位：走「非连接错误」的 error 分支。

        ``session.get`` 处会让出事件循环，并发的资源压力处理可能把
        ``_control_unavailable_until`` 推到未来；这里在假 session 首次 GET 时置位以
        确定性复现该竞态（覆盖 else 分支）。
        """
        class _Inject(FakeSession):
            def get(self, url, **kwargs):
                engine._control_unavailable_until = time.monotonic() + 15.0
                return super().get(url, **kwargs)

        session = _Inject(get_plan=[FakeResponse(400, "bad")] * 5)
        _patch_session(monkeypatch, session)
        ok = await engine._try_set_weights(
            endpoint="/set_gpt_weights", weights_path="w.ckpt", kind="GPT")
        assert ok is False
        assert session.post_calls == []  # 冷却中直接返回


WEIGHT_CASES = [("set_gpt_weights", "/set_gpt_weights", "GPT"),
                ("set_sovits_weights", "/set_sovits_weights", "SoVITS")]


class TestSetWeights:
    @pytest.mark.parametrize("method,endpoint,kind", WEIGHT_CASES)
    async def test_placeholders_ignored(self, engine, monkeypatch, method, endpoint, kind):
        calls = []

        async def _try(**kwargs):
            calls.append(kwargs)

        monkeypatch.setattr(engine, "_try_set_weights", _try)
        for value in ["", "default", "DEFAULT", None]:
            await getattr(engine, method)(value)
        assert calls == []

    @pytest.mark.parametrize("method,endpoint,kind", WEIGHT_CASES)
    async def test_existing_and_missing_paths(self, engine, monkeypatch, tmp_path,
                                              method, endpoint, kind):
        calls = []

        async def _try(**kwargs):
            calls.append(kwargs)
            return True

        monkeypatch.setattr(engine, "_try_set_weights", _try)
        existing = tmp_path / "w.bin"
        existing.write_bytes(b"x")
        missing = str(tmp_path / "missing.bin")

        await getattr(engine, method)(str(existing))
        await getattr(engine, method)(missing)

        assert calls == [
            {"endpoint": endpoint, "weights_path": os.path.normpath(str(existing)),
             "kind": kind},
            {"endpoint": endpoint, "weights_path": missing, "kind": kind},
        ]

    @pytest.mark.parametrize("method", ["set_gpt_weights", "set_sovits_weights"])
    async def test_resolution_failure_swallowed(self, engine, monkeypatch, method):
        def _boom(_p):
            raise OSError("bad path")

        monkeypatch.setattr(engine, "_resolve_local_path", _boom)
        await getattr(engine, method)("x")  # 不应抛异常
        assert engine._is_generating is False


class TestMoveDevice:
    @pytest.mark.parametrize("method,target,params", [
        ("move_to_cpu", "cpu", {"device": "cpu", "is_half": "false"}),
        ("move_to_gpu", "cuda", {"device": "cuda", "is_half": "true"}),
    ])
    async def test_success(self, engine, monkeypatch, method, target, params):
        session = FakeSession(get_plan=[FakeResponse(200)])
        _patch_session(monkeypatch, session)
        assert await getattr(engine, method)() is True
        assert engine.current_device == target
        assert _g0(session)["url"] == "http://127.0.0.1:9880/set_device"
        assert _g0(session)["params"] == params

    @pytest.mark.parametrize("method", ["move_to_cpu", "move_to_gpu"])
    @pytest.mark.parametrize("plan,cooldown", [
        ([FakeResponse(500, "no")], False),
        ([ValueError("x")], False),
    ])
    async def test_non_200_and_other_error(self, engine, monkeypatch, method, plan, cooldown):
        _patch_session(monkeypatch, FakeSession(get_plan=plan))
        assert await getattr(engine, method)() is False
        assert (engine._control_unavailable_until > 0.0) is cooldown

    @pytest.mark.parametrize("method,exc", [
        ("move_to_cpu", asyncio.TimeoutError()),
        ("move_to_gpu", asyncio.TimeoutError()),
        ("move_to_cpu", aiohttp.ClientError("Cannot connect to host")),
        ("move_to_gpu", aiohttp.ClientError("Cannot connect to host")),
        ("move_to_cpu", aiohttp.ClientError("Connection refused")),
        ("move_to_gpu", aiohttp.ClientError("Connection refused")),
    ])
    async def test_connection_like_error_sets_cooldown(self, engine, monkeypatch, method, exc):
        _patch_session(monkeypatch, FakeSession(get_plan=[exc]))
        assert await getattr(engine, method)() is False
        assert engine._control_unavailable_until > time.monotonic()

    @pytest.mark.parametrize("method", ["move_to_cpu", "move_to_gpu"])
    async def test_cooldown_short_circuits(self, engine, monkeypatch, method):
        engine._control_unavailable_until = time.monotonic() + 100.0
        session = FakeSession()
        _patch_session(monkeypatch, session)
        assert await getattr(engine, method)() is False
        assert session.get_calls == []

    async def test_move_to_gpu_already_cuda(self, engine, monkeypatch):
        engine.current_device = "cuda"
        session = FakeSession()
        _patch_session(monkeypatch, session)
        assert await engine.move_to_gpu() is True
        assert session.get_calls == []


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
        "_gpt_sovits_engine_import_probe", Path(mod.__file__))
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    return probe


class TestModuleImportGuard:
    def test_soundfile_missing(self, monkeypatch):
        assert _load_probe(monkeypatch, {"soundfile"}).sf is None

    def test_resource_lock_missing(self, monkeypatch):
        assert _load_probe(monkeypatch, {"core.utils.resource_lock"}).get_resource_lock is None

    def test_resource_manager_missing(self, monkeypatch):
        probe = _load_probe(monkeypatch, {"core.resource_manager"})
        assert probe.get_resource_manager is None
        assert probe.ResourcePriority is None
