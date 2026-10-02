"""core/utils/asyncio_accept_noise.py 单元测试。

覆盖四件事（都不依赖真实 socket/事件循环，跨平台可跑）：
1. 瞬态网络错误判定（含异常链、成环链）；
2. ``AcceptNoiseGuard`` 只抑制 accept 噪音，其它异常必须交回默认处理器；
3. 监听自愈只在"监听已全部关闭"时才真的重建；
4. accept 补丁：瞬态错误不关闭监听 socket，非瞬态错误保持原生行为。
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from core.utils import asyncio_accept_noise as mod

ACCEPT_FAILED = mod.ACCEPT_FAILED_MESSAGE
TASK_NEVER_RETRIEVED = mod.TASK_EXCEPTION_MESSAGE


class WinError(OSError):
    """带 ``winerror`` 的异常，跨平台稳定（避免依赖 OSError 4 参数形式）。"""

    def __init__(self, winerror):
        super().__init__(f"winerror={winerror}")
        self.winerror = winerror


class FakeSocket:
    def __init__(self, fileno=7):
        self._fileno = fileno
        self.closed = False

    def fileno(self):
        return self._fileno

    def close(self):
        self.closed = True
        self._fileno = -1


class FakeFuture:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self._callbacks = []

    def result(self):
        if self._error is not None:
            raise self._error
        return self._result

    def add_done_callback(self, callback):
        self._callbacks.append(callback)

    def fire(self):
        """模拟 future 完成，逐个调用已注册回调（与 asyncio 语义一致）。"""
        for callback in list(self._callbacks):
            callback(self)


class ScriptedProactor:
    """按脚本返回 accept 结果：异常直接抛，future 原样返回。"""

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = 0

    def accept(self, sock):
        self.calls += 1
        if not self.steps:
            raise AssertionError("accept 调用次数超出脚本预期")
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


class FakeLoop:
    """极简事件循环替身：只提供治理逻辑用到的接口。"""

    def __init__(self, script=None, debug=False):
        self._debug = debug
        self._accept_futures: dict[int, object] = {}
        self._proactor = ScriptedProactor(script or [])
        self.closed = False
        self.scheduled: list[tuple] = []
        self.exception_contexts: list[dict] = []
        self.default_handler_calls: list[dict] = []
        self.transports: list[tuple] = []
        self.tasks: list = []
        self.exception_handler = None

    # --- accept 循环用到的接口 ---
    def is_closed(self):
        return self.closed

    def call_soon(self, callback, *args):
        self.scheduled.append((callback, args))

    def call_exception_handler(self, context):
        self.exception_contexts.append(context)

    def _make_socket_transport(self, conn, protocol, extra=None, server=None):
        self.transports.append(("socket", conn, protocol, extra, server))

    def _make_ssl_transport(self, conn, protocol, sslcontext, **kwargs):
        self.transports.append(("ssl", conn, protocol, sslcontext, kwargs))

    # --- 异常处理器用到的接口 ---
    def get_exception_handler(self):
        return self.exception_handler

    def set_exception_handler(self, handler):
        self.exception_handler = handler

    def default_exception_handler(self, context):
        self.default_handler_calls.append(context)

    def create_task(self, coro):
        self.tasks.append(coro)
        return coro


def run_next_iteration(loop):
    """执行 loop.call_soon 排队的下一个回调（模拟事件循环跑一轮）。"""
    callback, args = loop.scheduled.pop(0)
    callback(*args)


def _drop_class_attr(cls, name):
    """删除类属性（类 ``__dict__`` 是 mappingproxy，不能直接 pop）。"""
    try:
        delattr(cls, name)
    except AttributeError:
        pass


class FakeListenerServer:
    """uvicorn Server 的替身：只需要 ``servers[].sockets[]``。"""

    def __init__(self, filenos):
        sockets = [FakeSocket(fileno) for fileno in filenos]
        self.servers = [type("FakeAsyncioServer", (), {"sockets": sockets})()]


class TestTransientNetworkError:
    def test_none_is_not_transient(self):
        assert mod.is_transient_network_error(None) is False

    def test_exception_without_winerror_is_not_transient(self):
        assert mod.is_transient_network_error(ValueError("boom")) is False

    @pytest.mark.parametrize(
        "winerror",
        [64, 995, 10038, 10053, 10054, 10058],
    )
    def test_known_winerrors_are_transient(self, winerror):
        assert mod.is_transient_network_error(WinError(winerror)) is True

    def test_other_winerror_is_not_transient(self):
        assert mod.is_transient_network_error(WinError(10022)) is False

    def test_match_through_cause_chain(self):
        outer = OSError("wrapped")
        outer.__cause__ = WinError(64)
        assert mod.is_transient_network_error(outer) is True

    def test_match_through_context_chain(self):
        outer = OSError("wrapped")
        outer.__context__ = WinError(10054)
        assert mod.is_transient_network_error(outer) is True

    def test_self_referencing_chain_terminates(self):
        err = WinError(10022)
        err.__cause__ = err
        assert mod.is_transient_network_error(err) is False


class TestAcceptNoiseGuard:
    def test_suppresses_task_exception_noise(self):
        loop = FakeLoop()
        guard = mod.AcceptNoiseGuard()
        guard.handle_exception(loop, {"message": TASK_NEVER_RETRIEVED, "exception": WinError(64)})

        assert loop.default_handler_calls == []
        assert loop.scheduled == []

    def test_accept_failure_noise_is_not_reported_to_default_handler(self):
        loop = FakeLoop()
        guard = mod.AcceptNoiseGuard(server=FakeListenerServer([7]), socket_factory=FakeSocket)
        guard.handle_exception(loop, {"message": ACCEPT_FAILED, "exception": WinError(64)})

        assert loop.default_handler_calls == []
        # 已安排一次"监听是否被关闭"的检查
        assert len(loop.scheduled) == 1

    def test_accept_failure_with_other_winerror_goes_to_default_handler(self):
        loop = FakeLoop()
        guard = mod.AcceptNoiseGuard()
        context = {"message": ACCEPT_FAILED, "exception": WinError(10022)}
        guard.handle_exception(loop, context)

        assert loop.default_handler_calls == [context]

    def test_unrelated_exception_goes_to_default_handler(self):
        loop = FakeLoop()
        guard = mod.AcceptNoiseGuard()
        context = {"message": "Fatal error on transport", "exception": RuntimeError("x")}
        guard.handle_exception(loop, context)

        assert loop.default_handler_calls == [context]

    def test_previous_handler_takes_precedence(self):
        loop = FakeLoop()
        previous_calls = []
        guard = mod.AcceptNoiseGuard(previous_handler=lambda lp, ctx: previous_calls.append(ctx))
        context = {"message": "some other error", "exception": RuntimeError("x")}
        guard.handle_exception(loop, context)

        assert previous_calls == [context]
        assert loop.default_handler_calls == []

    def test_recovery_is_skipped_when_no_server_or_factory(self):
        loop = FakeLoop()
        mod.AcceptNoiseGuard().schedule_listen_recovery(loop)
        assert loop.scheduled == []

    def test_recovery_check_skips_rebuild_when_listener_alive(self):
        loop = FakeLoop()
        guard = mod.AcceptNoiseGuard(server=FakeListenerServer([5]), socket_factory=FakeSocket)
        guard.handle_exception(loop, {"message": ACCEPT_FAILED, "exception": WinError(64)})

        callback, args = loop.scheduled.pop(0)
        callback(*args)

        assert loop.tasks == []

    def test_recovery_check_rebuilds_when_listener_closed(self):
        loop = FakeLoop()
        guard = mod.AcceptNoiseGuard(server=FakeListenerServer([-1]), socket_factory=FakeSocket)
        guard.handle_exception(loop, {"message": ACCEPT_FAILED, "exception": WinError(64)})

        callback, args = loop.scheduled.pop(0)
        callback(*args)

        assert len(loop.tasks) == 1
        loop.tasks[0].close()  # 测试里不执行重建协程，显式关闭避免告警

    def test_install_guard_wires_exception_handler(self, monkeypatch):
        monkeypatch.setattr(mod.sys, "platform", "win32")
        loop = asyncio.new_event_loop()
        try:
            previous = RuntimeErrorHandler()
            loop.set_exception_handler(previous)
            guard = mod.install_accept_noise_guard(loop)
            assert guard is not None
            assert loop.get_exception_handler() == guard.handle_exception
            assert guard.previous_handler is previous
        finally:
            loop.close()

    def test_install_guard_is_noop_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(mod.sys, "platform", "linux")
        loop = FakeLoop()
        assert mod.install_accept_noise_guard(loop) is None
        assert loop.get_exception_handler() is None


class RuntimeErrorHandler:
    """占位异常处理器，用于验证 guard 会记住原处理器。"""

    def __call__(self, loop, context):  # pragma: no cover - 不会被调用
        raise AssertionError("不应被调用")


class TestListenersAllClosed:
    def test_no_servers_returns_false(self):
        server = type("S", (), {"servers": []})()
        assert mod._listeners_all_closed(server) is False

    def test_sockets_none_returns_false(self):
        server = type("S", (), {"servers": [type("A", (), {"sockets": None})()]})()
        assert mod._listeners_all_closed(server) is False

    def test_all_closed_returns_true(self):
        assert mod._listeners_all_closed(FakeListenerServer([-1, -1])) is True

    def test_any_alive_returns_false(self):
        assert mod._listeners_all_closed(FakeListenerServer([-1, 5])) is False


class TestStartServingKeepListener:
    def test_transient_accept_error_keeps_listener_and_retries(self):
        transient = WinError(64)
        loop = FakeLoop(script=[transient, WinError(64)])
        sock = FakeSocket()

        mod.start_serving_keep_listener(loop, lambda: "protocol", sock)
        assert len(loop.scheduled) == 1

        run_next_iteration(loop)  # 第一次 accept → 瞬态错误
        assert loop._proactor.calls == 1
        assert sock.closed is False
        assert loop.exception_contexts == []
        # 循环没有中断：又排队了一轮
        assert len(loop.scheduled) == 1

        run_next_iteration(loop)  # 第二次 accept → 又是瞬态错误
        assert loop._proactor.calls == 2
        assert sock.closed is False
        assert loop.exception_contexts == []

    def test_future_error_path_keeps_listener(self):
        """accept 的 future 抛瞬态错误（真实报错路径）同样不关监听。"""
        passing = FakeFuture(result=("conn", ("127.0.0.1", 1)))
        loop = FakeLoop(script=[passing])
        sock = FakeSocket()

        mod.start_serving_keep_listener(loop, lambda: "protocol", sock)
        run_next_iteration(loop)  # 第一次 accept 成功挂上 future
        assert loop._accept_futures[sock.fileno()] is passing

        loop._proactor.steps.append(WinError(64))
        passing.fire()  # 连接就绪 → 下一轮 accept 抛瞬态错误

        assert sock.closed is False
        assert loop.exception_contexts == []

    def test_non_transient_error_reports_and_closes_listener(self):
        loop = FakeLoop(script=[WinError(10022)])
        sock = FakeSocket()

        mod.start_serving_keep_listener(loop, lambda: "protocol", sock)
        run_next_iteration(loop)

        assert sock.closed is True
        assert len(loop.exception_contexts) == 1
        assert loop.exception_contexts[0]["message"] == ACCEPT_FAILED

    def test_successful_accept_builds_transport(self):
        passing = FakeFuture(result=("conn", ("127.0.0.1", 4321)))
        loop = FakeLoop(script=[passing])
        sock = FakeSocket()

        mod.start_serving_keep_listener(loop, lambda: "protocol", sock)
        run_next_iteration(loop)
        loop._proactor.steps.append(FakeFuture(result=("c2", ("127.0.0.1", 4322))))

        passing.fire()

        assert loop.transports == [
            ("socket", "conn", "protocol", {"peername": ("127.0.0.1", 4321)}, None)
        ]
        assert sock.closed is False

    def test_only_one_accept_is_pending_at_a_time(self):
        """同一时刻只能挂一个 AcceptEx。

        原实现由 ``f.add_done_callback(loop)`` 驱动下一轮，``call_soon(loop)`` 只在
        启动时调一次。若改成"每轮都重排"，就会不等上一个 AcceptEx 完成而不断挂起
        新的，每个挂起带一个 accept socket + future + task —— 内存与句柄会一路涨到
        耗尽（本项目真实踩过这个坑）。
        """
        first = FakeFuture(result=("conn", ("127.0.0.1", 1)))
        second = FakeFuture(result=("c2", ("127.0.0.1", 2)))
        loop = FakeLoop(script=[first, second])
        sock = FakeSocket()

        mod.start_serving_keep_listener(loop, lambda: "protocol", sock)
        assert len(loop.scheduled) == 1

        run_next_iteration(loop)
        assert loop._proactor.calls == 1
        # 挂起成功后只等 future 回调，不得再自行排队
        assert loop.scheduled == []

        first.fire()
        assert loop._proactor.calls == 2
        assert loop.scheduled == []

    def test_transient_sync_failures_give_up_after_limit(self):
        """连连接都没等来就反复同步失败时，限次后上报并放弃（不忙循环）。"""
        limit = mod._MAX_CONSECUTIVE_SYNC_FAILURES
        loop = FakeLoop(script=[WinError(64)] * (limit + 2))
        sock = FakeSocket()

        mod.start_serving_keep_listener(loop, lambda: "protocol", sock)
        for _ in range(limit + 2):
            if not loop.scheduled:
                break
            run_next_iteration(loop)

        assert sock.closed is True
        assert len(loop.exception_contexts) == 1
        assert loop.exception_contexts[0]["message"] == ACCEPT_FAILED
        assert loop.scheduled == []

    def test_closed_loop_stops_accept_loop(self):
        loop = FakeLoop(script=[])
        loop.closed = True

        mod.start_serving_keep_listener(loop, lambda: "protocol", FakeSocket())
        run_next_iteration(loop)

        assert loop._proactor.calls == 0
        assert loop.scheduled == []

    def test_closed_listener_stops_accept_loop(self):
        """监听 socket 已关闭（server.close()）时结束循环，不在失效 socket 上空转。"""
        closed_sock = FakeSocket(fileno=-1)
        loop = FakeLoop(script=[WinError(10038)])

        mod.start_serving_keep_listener(loop, lambda: "protocol", closed_sock)
        run_next_iteration(loop)

        assert loop.exception_contexts == []
        assert loop.scheduled == []
        assert closed_sock.closed is False


class TestProactorPatch:
    def _setup(self, monkeypatch, platform):
        proactor_events = pytest.importorskip("asyncio.proactor_events")
        loop_cls = proactor_events.BaseProactorEventLoop
        monkeypatch.setattr(mod.sys, "platform", platform)
        # 宿主机若设了紧急开关，会让补丁静默跳过，测试必须显式清掉
        monkeypatch.delenv(mod.ENV_DISABLE_PATCH, raising=False)
        return loop_cls, loop_cls._start_serving

    def test_install_and_uninstall_round_trip(self, monkeypatch):
        loop_cls, original = self._setup(monkeypatch, "win32")
        had_flag = hasattr(loop_cls, mod._PATCH_FLAG)
        had_original = hasattr(loop_cls, mod._ORIGINAL_ATTR)
        try:
            assert mod.install_proactor_accept_patch() is True
            assert loop_cls._start_serving is mod._patched_start_serving
            # 幂等：重复安装不再叠加
            assert mod.install_proactor_accept_patch() is False
            assert loop_cls._start_serving is mod._patched_start_serving

            assert mod.uninstall_proactor_accept_patch() is True
            assert loop_cls._start_serving is original
        finally:
            loop_cls._start_serving = original
            if not had_flag:
                _drop_class_attr(loop_cls, mod._PATCH_FLAG)
            if not had_original:
                _drop_class_attr(loop_cls, mod._ORIGINAL_ATTR)

    def test_env_switch_disables_patch(self, monkeypatch):
        """紧急开关生效：跳过补丁，保留原生行为。"""
        loop_cls, original = self._setup(monkeypatch, "win32")
        monkeypatch.setenv(mod.ENV_DISABLE_PATCH, "1")
        try:
            assert mod.install_proactor_accept_patch() is False
            assert loop_cls._start_serving is original
        finally:
            loop_cls._start_serving = original

    def test_skips_patch_on_non_windows(self, monkeypatch):
        loop_cls, original = self._setup(monkeypatch, "linux")
        try:
            assert mod.install_proactor_accept_patch() is False
            assert loop_cls._start_serving is original
        finally:
            loop_cls._start_serving = original

    def test_skips_patch_when_signature_unexpected(self, monkeypatch):
        loop_cls, original = self._setup(monkeypatch, "win32")

        def unexpected(self, *args, **kwargs):  # pragma: no cover - 仅签名校验用
            return None

        monkeypatch.setattr(loop_cls, "_start_serving", unexpected)
        try:
            assert mod.install_proactor_accept_patch() is False
            assert loop_cls._start_serving is unexpected
        finally:
            loop_cls._start_serving = original


class TestRunServerWithGuard:
    def test_non_windows_delegates_to_server_run(self, monkeypatch):
        monkeypatch.setattr(mod.sys, "platform", "linux")
        calls = {}

        class Server:
            def run(self, sockets=None):
                calls["sockets"] = sockets
                return "delegated"

        assert mod.run_server_with_accept_noise_guard(Server(), sockets=["s"]) == "delegated"
        assert calls["sockets"] == ["s"]

    def test_windows_runs_with_guard_installed(self, monkeypatch):
        monkeypatch.setattr(mod.sys, "platform", "win32")
        monkeypatch.setattr(mod, "install_proactor_accept_patch", lambda: True)
        seen = {}

        class Server:
            async def serve(self, sockets=None):
                seen["sockets"] = sockets
                seen["handler"] = asyncio.get_running_loop().get_exception_handler()

        mod.run_server_with_accept_noise_guard(Server(), sockets=["s"])

        assert seen["sockets"] == ["s"]
        assert isinstance(getattr(seen["handler"], "__self__", None), mod.AcceptNoiseGuard)


def test_module_imports_on_all_platforms():
    """模块本身必须能在任何平台导入（非 Windows 只是不生效）。"""
    assert mod.ACCEPT_FAILED_MESSAGE == "Accept failed on a socket"
    assert 64 in mod.TRANSIENT_WINERRORS
    assert isinstance(sys.platform, str)
