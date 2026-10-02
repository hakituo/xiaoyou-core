#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``core/interfaces/websocket/adapters/adapter.py`` 的核心单测。

覆盖目标：FastAPIWebSocketAdapter 的任务注册/取消、初始化/关闭、握手鉴权、
消息路由、演示生图、图像 payload 组装、资源状态广播，以及模块级单例函数。

「禁止 flaky」的做法：
- 不依赖真实时间：把 adapter 模块里的 ``asyncio`` 引用换成受控替身，
  由替身决定 ``sleep`` / ``wait_for`` 的行为，而不是真的等秒数；
- 不依赖真实模型/后端：全部下游协作者（WebSocket、Manager、Handlers、
  ResourceManager、Scheduler、ImageManager…）都用 Fake 对象或 monkeypatch 替换；
- 不跨用例共享全局状态：每个用例新建 adapter，模块单例在用例内单独重置。
"""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starlette.websockets import WebSocketDisconnect

from core.api.error_response import ErrorCode
from core.interfaces.websocket.adapters import adapter as adapter_module
from core.interfaces.websocket.adapters.adapter import (
    FastAPIWebSocketAdapter,
    get_fastapi_websocket_adapter,
    initialize_websocket_adapter,
    shutdown_websocket_adapter,
)
from core.utils.concurrency.async_locks import LazyAsyncLock


# ============================================================
# 基础协程工具
# ============================================================


async def _noop(*args, **kwargs):
    """通用空协程（可接受任意参数）。"""
    return None


async def _never():
    """永不完成的协程，用于制造“仍在进行中”的任务。"""
    await asyncio.Event().wait()


async def _drain(*tasks):
    """取消并回收任务，避免事件循环关闭时留下 pending task 告警。"""
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


_UNSET = object()


# ============================================================
# 测试替身
# ============================================================


class FakeWebSocket:
    """最小可用的 WebSocket 替身。

    ``receive_script`` 里的元素：普通 dict 直接返回；BaseException 实例则抛出。
    ``send_errors`` 按调用次序消费，元素为 None 表示该次发送成功。
    """

    def __init__(
        self,
        *,
        receive_script=None,
        query_params=None,
        headers=None,
        client_host="127.0.0.1",
        has_client=True,
        accept_error=None,
        close_error=None,
        send_errors=None,
        send_error=None,
    ):
        self._receive_script = list(receive_script or [])
        self.query_params = query_params
        self.headers = dict(headers or {})
        self.client = SimpleNamespace(host=client_host) if has_client else None
        self.accept_error = accept_error
        self.close_error = close_error
        self._send_errors = list(send_errors or [])
        self._send_error = send_error
        self.accepted = False
        self.close_calls = []
        self.sent = []

    async def accept(self):
        if self.accept_error is not None:
            raise self.accept_error
        self.accepted = True

    async def close(self, code=1000, reason=None):
        if self.close_error is not None:
            raise self.close_error
        self.close_calls.append((code, reason))

    async def send_json(self, payload):
        if self._send_error is not None:
            raise self._send_error
        if self._send_errors:
            exc = self._send_errors.pop(0)
            if exc is not None:
                raise exc
        self.sent.append(payload)

    async def receive_json(self):
        if not self._receive_script:
            raise WebSocketDisconnect(code=1000, reason="script exhausted")
        item = self._receive_script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeManager:
    """WebSocketManager 替身。"""

    def __init__(
        self,
        *,
        active_connections=0,
        connections=None,
        lock=None,
        stop_error=None,
        broadcast_error=None,
    ):
        self.connections = connections if connections is not None else {}
        self.connections_lock = lock if lock is not None else LazyAsyncLock()
        self._active_connections = active_connections
        self.stop_error = stop_error
        self.broadcast_error = broadcast_error
        self.initialized = False
        self.stopped = False
        self.added = []
        self.removed = []
        self.handled = []
        self.broadcasts = []

    async def initialize(self):
        self.initialized = True

    async def stop(self):
        self.stopped = True
        if self.stop_error is not None:
            raise self.stop_error

    async def add_connection(self, websocket, user_id=None, platform=None):
        self.added.append((websocket, user_id, platform))

    async def remove_connection(self, websocket):
        self.removed.append(websocket)

    async def handle_message(self, websocket, message):
        self.handled.append((websocket, message))

    async def broadcast(self, data):
        if self.broadcast_error is not None:
            raise self.broadcast_error
        self.broadcasts.append(data)

    def get_stats(self):
        return {"active_connections": self._active_connections}


class _RaisingDict(dict):
    """``get`` 必抛异常，用于覆盖心跳刷新失败分支。"""

    def get(self, *args, **kwargs):
        raise RuntimeError("connections.get boom")


class FakeHandlers:
    """MessageHandlers 替身，记录调用并可注入异常。"""

    def __init__(self, *, text_result=_UNSET, errors=None):
        self.calls = []
        self.text_result = (
            {"type": "text"} if text_result is _UNSET else text_result
        )
        self.errors = dict(errors or {})

    async def _invoke(self, name):
        self.calls.append(name)
        if name in self.errors:
            raise self.errors[name]
        if name == "handle_text_message":
            return self.text_result
        return None

    async def cleanup_websocket(self, websocket):
        self.calls.append("cleanup_websocket")

    async def handle_ping(self, websocket, message):
        return await self._invoke("handle_ping")

    async def handle_pong(self, websocket, message):
        return await self._invoke("handle_pong")

    async def handle_greeting_message(self, websocket, message, streaming):
        return await self._invoke("handle_greeting_message")

    async def handle_update_settings(self, websocket, message):
        return await self._invoke("handle_update_settings")

    async def handle_update_physiology(self, websocket, message):
        return await self._invoke("handle_update_physiology")

    async def handle_mobile_switch_model(self, websocket, message):
        return await self._invoke("handle_mobile_switch_model")

    async def handle_reconnect(self, websocket, message):
        return await self._invoke("handle_reconnect")

    async def handle_text_message(self, websocket, message):
        return await self._invoke("handle_text_message")

    async def handle_chat_message(self, websocket, message, streaming):
        return await self._invoke("handle_chat_message")


class FakeDemo:
    """DemoHandler 替身。"""

    def __init__(self):
        self.events = []
        self.pipelines = []

    async def send_demo_event(
        self, websocket, event, data, message_id, conversation_id, request_id=None
    ):
        self.events.append(
            {
                "event": event,
                "data": data,
                "message_id": message_id,
                "conversation_id": conversation_id,
                "request_id": request_id,
            }
        )

    async def generate_image_pipeline(self, **kwargs):
        self.pipelines.append(kwargs)
        return {"ok": True}


class FakeResourceLock:
    """GlobalResourceLock 替身。"""

    def __init__(self, *, status=None, acquire_error=None):
        self._status = dict(status or {"enabled": False})
        self._acquire_error = acquire_error
        self.acquire_calls = []

    def get_status(self):
        return dict(self._status)

    @asynccontextmanager
    async def acquire(self, requestor, *, reject_if_full=False):
        self.acquire_calls.append((requestor, reject_if_full))
        if self._acquire_error is not None:
            raise self._acquire_error
        yield


class FakeImageManager:
    """ImageManager 替身。"""

    def __init__(self, *, result=None, error=None):
        self.result = result if result is not None else {"success": True}
        self.error = error
        self.calls = []

    async def generate_image(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return dict(self.result)


def _make_adapter(*, initialized=True, manager=None, handlers=None, demo=None):
    """构造一个已注入替身的 adapter。"""
    adapter = FastAPIWebSocketAdapter()
    adapter.handlers = handlers if handlers is not None else FakeHandlers()
    adapter.demo = demo if demo is not None else FakeDemo()
    adapter.websocket_manager = manager
    adapter._initialized = initialized
    return adapter


def _asyncio_shim(monkeypatch, **overrides):
    """把 adapter 模块里的 ``asyncio`` 换成受控替身，避免改到全局 asyncio。"""
    shim = SimpleNamespace(
        Task=asyncio.Task,
        gather=asyncio.gather,
        wait_for=asyncio.wait_for,
        sleep=asyncio.sleep,
        create_task=asyncio.create_task,
        current_task=asyncio.current_task,
        iscoroutine=asyncio.iscoroutine,
    )
    for key, value in overrides.items():
        setattr(shim, key, value)
    monkeypatch.setattr(adapter_module, "asyncio", shim)
    return shim


# ============================================================
# 下游依赖 patch 工具
# ============================================================


def _patch_security(monkeypatch, *, bypass=True, loopback=True):
    import core.middleware.security as security

    monkeypatch.setattr(
        security, "is_loopback_auth_bypass_enabled", lambda: bypass
    )
    monkeypatch.setattr(security, "is_loopback_address", lambda host: loopback)


def _patch_settings(monkeypatch, *, token="", model=None):
    import config.integrated_config as cfg

    settings = SimpleNamespace(
        security=SimpleNamespace(web_access_token=token),
        model=model if model is not None else SimpleNamespace(),
    )
    monkeypatch.setattr(cfg, "get_settings", lambda: settings)
    return settings


def _patch_ws_debug(monkeypatch):
    """屏蔽握手调试日志的文件写入副作用。"""
    import core.utils.ws_handshake_debug as ws_debug

    monkeypatch.setattr(ws_debug, "log", MagicMock())
    monkeypatch.setattr(ws_debug, "log_exception", MagicMock())


def _patch_life_sim(monkeypatch, *, error=None):
    import core.services.life_simulation.service as life_mod

    class _FakeLifeSim:
        def __init__(self):
            self.interactions = []

        def update_interaction(self, **kwargs):
            if error is not None:
                raise error
            self.interactions.append(kwargs)

    fake = _FakeLifeSim()
    monkeypatch.setattr(life_mod, "get_life_simulation_service", lambda: fake)
    return fake


def _patch_resource_lock(monkeypatch, lock):
    import core.utils.concurrency.resource_lock as rl_mod

    monkeypatch.setattr(rl_mod, "get_resource_lock", lambda: lock)
    return lock


def _patch_image_manager(monkeypatch, manager):
    import core.image.image_manager as img_mod

    async def _get_manager():
        return manager

    monkeypatch.setattr(img_mod, "get_image_manager", _get_manager)
    return manager


def _image_model_settings():
    return SimpleNamespace(
        image_gen_width=512,
        image_gen_height=512,
        image_gen_steps=20,
        default_image_model="fake-model",
        text_path="",
        llm=SimpleNamespace(provider="local", model="fake-llm"),
    )


# ============================================================
# 聊天任务注册表
# ============================================================


class TestChatTaskRegistry:
    def test_get_ws_key_uses_object_id(self):
        adapter = FastAPIWebSocketAdapter()
        ws = FakeWebSocket()
        assert adapter._get_ws_key(ws) == id(ws)

    def test_register_creates_bucket_and_stores_task(self):
        adapter = FastAPIWebSocketAdapter()
        ws = FakeWebSocket()

        async def _run():
            task = asyncio.create_task(_never())
            try:
                await adapter._register_chat_task(ws, "m1", task)
                bucket = adapter._chat_tasks[adapter._get_ws_key(ws)]
                assert bucket["m1"] is task
            finally:
                await _drain(task)

        asyncio.run(_run())

    def test_register_reuses_existing_bucket(self):
        adapter = FastAPIWebSocketAdapter()
        ws = FakeWebSocket()

        async def _run():
            t1 = asyncio.create_task(_never())
            t2 = asyncio.create_task(_never())
            try:
                await adapter._register_chat_task(ws, "m1", t1)
                await adapter._register_chat_task(ws, "m2", t2)
                bucket = adapter._chat_tasks[adapter._get_ws_key(ws)]
                assert set(bucket) == {"m1", "m2"}
            finally:
                await _drain(t1, t2)

        asyncio.run(_run())

    def test_unregister_without_bucket_returns(self):
        adapter = FastAPIWebSocketAdapter()
        ws = FakeWebSocket()

        async def _run():
            await adapter._unregister_chat_task(ws, "missing")
            assert adapter._chat_tasks == {}

        asyncio.run(_run())

    def test_unregister_drops_empty_bucket(self):
        adapter = FastAPIWebSocketAdapter()
        ws = FakeWebSocket()

        async def _run():
            task = asyncio.create_task(_never())
            try:
                await adapter._register_chat_task(ws, "m1", task)
                await adapter._unregister_chat_task(ws, "m1")
                assert adapter._chat_tasks == {}
            finally:
                await _drain(task)

        asyncio.run(_run())

    def test_unregister_keeps_bucket_with_remaining_task(self):
        adapter = FastAPIWebSocketAdapter()
        ws = FakeWebSocket()

        async def _run():
            t1 = asyncio.create_task(_never())
            t2 = asyncio.create_task(_never())
            try:
                await adapter._register_chat_task(ws, "m1", t1)
                await adapter._register_chat_task(ws, "m2", t2)
                await adapter._unregister_chat_task(ws, "m1")
                bucket = adapter._chat_tasks[adapter._get_ws_key(ws)]
                assert set(bucket) == {"m2"}
            finally:
                await _drain(t1, t2)

        asyncio.run(_run())

    def test_unregister_unknown_message_id_keeps_bucket(self):
        adapter = FastAPIWebSocketAdapter()
        ws = FakeWebSocket()

        async def _run():
            task = asyncio.create_task(_never())
            try:
                await adapter._register_chat_task(ws, "m1", task)
                await adapter._unregister_chat_task(ws, "other")
                bucket = adapter._chat_tasks[adapter._get_ws_key(ws)]
                assert set(bucket) == {"m1"}
            finally:
                await _drain(task)

        asyncio.run(_run())

    def test_cancel_chat_tasks_cancels_pending(self, monkeypatch):
        adapter = FastAPIWebSocketAdapter()
        monkeypatch.setattr(adapter, "_request_stop_current_inference", _noop)
        ws = FakeWebSocket()

        async def _run():
            task = asyncio.create_task(_never())
            await adapter._register_chat_task(ws, "m1", task)
            await adapter._cancel_chat_tasks(ws)
            assert task.cancelled()
            assert adapter._chat_tasks == {}

        asyncio.run(_run())

    def test_cancel_chat_tasks_skips_done_and_non_task(self, monkeypatch):
        adapter = FastAPIWebSocketAdapter()
        monkeypatch.setattr(adapter, "_request_stop_current_inference", _noop)
        ws = FakeWebSocket()

        async def _run():
            done_task = asyncio.create_task(_noop())
            await done_task
            adapter._chat_tasks[adapter._get_ws_key(ws)] = {
                "done": done_task,
                "weird": "not-a-task",
            }
            await adapter._cancel_chat_tasks(ws)
            assert adapter._chat_tasks == {}
            assert done_task.done()

        asyncio.run(_run())

    def test_cancel_chat_tasks_timeout_is_logged(self, monkeypatch):
        adapter = FastAPIWebSocketAdapter()
        monkeypatch.setattr(adapter, "_request_stop_current_inference", _noop)

        async def _timeout_wait_for(awaitable, timeout=None):
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            raise asyncio.TimeoutError()

        _asyncio_shim(monkeypatch, wait_for=_timeout_wait_for)
        ws = FakeWebSocket()

        async def _run():
            task = asyncio.create_task(_never())
            await adapter._register_chat_task(ws, "m1", task)
            await adapter._cancel_chat_tasks(ws)
            # wait_for 被替身打断，任务只收到 cancel 请求、尚未真正结束。
            assert adapter._chat_tasks == {}
            await _drain(task)
            assert task.cancelled()

        asyncio.run(_run())


# ============================================================
# 停止推理 / 资源回收
# ============================================================


class TestRequestStopCurrentInference:
    def test_scheduler_engine_success(self, monkeypatch):
        adapter = FastAPIWebSocketAdapter()
        engine = SimpleNamespace(stop_calls=0)

        async def _stop():
            engine.stop_calls += 1

        engine.request_stop_current_inference = _stop

        import core.services.scheduler.cpp_scheduler_engine as sched_mod
        import core.resource_manager as rm_mod

        monkeypatch.setattr(sched_mod, "get_scheduler_engine", lambda *a, **k: engine)

        async def _no_pressure():
            return False

        monkeypatch.setattr(rm_mod, "is_system_under_memory_pressure", _no_pressure)

        asyncio.run(adapter._request_stop_current_inference())
        assert engine.stop_calls == 1

    def test_scheduler_engine_none_is_tolerated(self, monkeypatch):
        adapter = FastAPIWebSocketAdapter()

        import core.services.scheduler.cpp_scheduler_engine as sched_mod
        import core.resource_manager as rm_mod

        monkeypatch.setattr(sched_mod, "get_scheduler_engine", lambda *a, **k: None)

        async def _no_pressure():
            return False

        monkeypatch.setattr(rm_mod, "is_system_under_memory_pressure", _no_pressure)

        asyncio.run(adapter._request_stop_current_inference())

    def test_scheduler_import_error_is_swallowed(self, monkeypatch):
        adapter = FastAPIWebSocketAdapter()

        import core.services.scheduler.cpp_scheduler_engine as sched_mod
        import core.resource_manager as rm_mod

        def _boom(*args, **kwargs):
            raise ImportError("scheduler unavailable")

        monkeypatch.setattr(sched_mod, "get_scheduler_engine", _boom)

        async def _no_pressure():
            return False

        monkeypatch.setattr(rm_mod, "is_system_under_memory_pressure", _no_pressure)

        asyncio.run(adapter._request_stop_current_inference())

    def test_memory_pressure_triggers_optimize(self, monkeypatch):
        adapter = FastAPIWebSocketAdapter()

        import core.services.scheduler.cpp_scheduler_engine as sched_mod
        import core.resource_manager as rm_mod
        import core.utils.concurrency.async_tasks as tasks_mod

        monkeypatch.setattr(sched_mod, "get_scheduler_engine", lambda *a, **k: None)

        async def _pressure():
            return True

        optimize_calls = []

        class _FakeRm:
            async def optimize_resources(self):
                optimize_calls.append(True)

        async def _get_rm():
            return _FakeRm()

        monkeypatch.setattr(rm_mod, "is_system_under_memory_pressure", _pressure)
        monkeypatch.setattr(rm_mod, "get_global_resource_manager", _get_rm)

        spawned = []

        def _spawn(coro, *, name=""):
            spawned.append(name)
            coro.close()
            return None

        monkeypatch.setattr(tasks_mod, "spawn_bg_task", _spawn)

        asyncio.run(adapter._request_stop_current_inference())
        assert spawned == ["resource_optimize"]

    def test_memory_pressure_check_error_is_swallowed(self, monkeypatch):
        adapter = FastAPIWebSocketAdapter()

        import core.services.scheduler.cpp_scheduler_engine as sched_mod
        import core.resource_manager as rm_mod

        monkeypatch.setattr(sched_mod, "get_scheduler_engine", lambda *a, **k: None)

        async def _boom():
            raise RuntimeError("memory probe failed")

        monkeypatch.setattr(rm_mod, "is_system_under_memory_pressure", _boom)

        asyncio.run(adapter._request_stop_current_inference())


# ============================================================
# initialize / shutdown
# ============================================================


class TestInitialize:
    def test_already_initialized_returns_early(self, monkeypatch):
        adapter = FastAPIWebSocketAdapter()
        adapter._initialized = True
        called = []

        import core.interfaces.websocket.websocket_manager as wsm_mod

        monkeypatch.setattr(
            wsm_mod, "get_websocket_manager", lambda: called.append(1)
        )

        asyncio.run(adapter.initialize())
        assert called == []
        assert adapter.websocket_manager is None

    def test_initialize_success_wires_dependencies(self, monkeypatch):
        adapter = FastAPIWebSocketAdapter()
        manager = FakeManager()
        subscribed = []

        import core.interfaces.websocket.websocket_manager as wsm_mod
        import core.core_engine.event_bus as eb_mod
        import core.interfaces.websocket.adapters.demo as demo_mod

        monkeypatch.setattr(wsm_mod, "get_websocket_manager", lambda: manager)

        class _FakeBus:
            async def subscribe(self, topic, handler):
                subscribed.append((topic, handler))

        monkeypatch.setattr(eb_mod, "get_event_bus", lambda: _FakeBus())

        class _FakeDemoHandler:
            def __init__(self, adapter_):
                self.adapter = adapter_

        monkeypatch.setattr(demo_mod, "DemoHandler", _FakeDemoHandler)
        _patch_ws_debug(monkeypatch)

        asyncio.run(adapter.initialize())

        assert adapter._initialized is True
        assert adapter.websocket_manager is manager
        assert manager.initialized is True
        assert subscribed[0][0] == "resource.metrics_updated"
        assert subscribed[0][1] == adapter._handle_resource_update
        assert isinstance(adapter.demo, _FakeDemoHandler)

    def test_initialize_failure_reraises(self, monkeypatch):
        adapter = FastAPIWebSocketAdapter()

        import core.interfaces.websocket.websocket_manager as wsm_mod

        def _boom():
            raise RuntimeError("no manager")

        monkeypatch.setattr(wsm_mod, "get_websocket_manager", _boom)
        _patch_ws_debug(monkeypatch)

        with pytest.raises(RuntimeError, match="no manager"):
            asyncio.run(adapter.initialize())
        assert adapter._initialized is False

    def test_initialize_success_tolerates_debug_log_failure(self, monkeypatch):
        adapter = FastAPIWebSocketAdapter()
        manager = FakeManager()

        import core.interfaces.websocket.websocket_manager as wsm_mod
        import core.core_engine.event_bus as eb_mod
        import core.interfaces.websocket.adapters.demo as demo_mod
        import core.utils.ws_handshake_debug as ws_debug

        monkeypatch.setattr(wsm_mod, "get_websocket_manager", lambda: manager)

        class _FakeBus:
            async def subscribe(self, topic, handler):
                return None

        monkeypatch.setattr(eb_mod, "get_event_bus", lambda: _FakeBus())

        class _FakeDemoHandler:
            def __init__(self, adapter_):
                self.adapter = adapter_

        monkeypatch.setattr(demo_mod, "DemoHandler", _FakeDemoHandler)

        def _boom(*args, **kwargs):
            raise RuntimeError("debug log boom")

        monkeypatch.setattr(ws_debug, "log", _boom)

        asyncio.run(adapter.initialize())
        assert adapter._initialized is True

    def test_initialize_failure_tolerates_debug_log_failure(self, monkeypatch):
        adapter = FastAPIWebSocketAdapter()

        import core.interfaces.websocket.websocket_manager as wsm_mod
        import core.utils.ws_handshake_debug as ws_debug

        def _boom_manager():
            raise RuntimeError("no manager")

        def _boom_log(*args, **kwargs):
            raise RuntimeError("debug log boom")

        monkeypatch.setattr(wsm_mod, "get_websocket_manager", _boom_manager)
        monkeypatch.setattr(ws_debug, "log_exception", _boom_log)

        with pytest.raises(RuntimeError, match="no manager"):
            asyncio.run(adapter.initialize())
        assert adapter._initialized is False


class TestShutdown:
    def test_shutdown_without_manager(self):
        adapter = FastAPIWebSocketAdapter()
        adapter._initialized = True

        asyncio.run(adapter.shutdown())
        assert adapter._initialized is False

    def test_shutdown_stop_error_is_swallowed(self):
        manager = FakeManager(stop_error=RuntimeError("stop failed"))
        adapter = _make_adapter(manager=manager)

        asyncio.run(adapter.shutdown())
        assert manager.stopped is True
        assert adapter._initialized is False

    def test_shutdown_cancels_pending_tasks(self):
        manager = FakeManager()
        adapter = _make_adapter(manager=manager)
        ws = FakeWebSocket()

        async def _run():
            task = asyncio.create_task(_never())
            await adapter._register_chat_task(ws, "m1", task)
            await adapter.shutdown()
            assert task.cancelled()
            assert adapter._chat_tasks == {}

        asyncio.run(_run())

    def test_shutdown_task_cancel_timeout_is_logged(self, monkeypatch):
        adapter = _make_adapter(manager=FakeManager())
        ws = FakeWebSocket()

        async def _timeout_wait_for(awaitable, timeout=None):
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            raise asyncio.TimeoutError()

        _asyncio_shim(monkeypatch, wait_for=_timeout_wait_for)

        async def _run():
            task = asyncio.create_task(_never())
            await adapter._register_chat_task(ws, "m1", task)
            await adapter.shutdown()
            # wait_for 被替身打断，任务只收到 cancel 请求、尚未真正结束。
            assert adapter._chat_tasks == {}
            await _drain(task)
            assert task.cancelled()

        asyncio.run(_run())


# ============================================================
# handle_connection
# ============================================================


class TestHandleConnection:
    @staticmethod
    def _local_setup(monkeypatch, adapter, *, receive_script=None, **ws_kwargs):
        """构造一个走「本地连接免鉴权」路径的用例。"""
        monkeypatch.setattr(adapter, "_request_stop_current_inference", _noop)
        _patch_security(monkeypatch, bypass=True, loopback=True)
        _patch_settings(monkeypatch, token="")
        _patch_ws_debug(monkeypatch)
        ws = FakeWebSocket(receive_script=receive_script, **ws_kwargs)
        return ws

    @staticmethod
    def _remote_setup(monkeypatch, adapter, *, token="secret", **settings_kwargs):
        monkeypatch.setattr(adapter, "_request_stop_current_inference", _noop)
        _patch_security(monkeypatch, bypass=False, loopback=False)
        _patch_settings(monkeypatch, token=token, **settings_kwargs)
        _patch_ws_debug(monkeypatch)

    @staticmethod
    def _run_connection(adapter, ws):
        async def _run():
            await adapter.handle_connection(ws)
            # 让 fire-and-forget 的后台消息处理任务收尾，避免 loop 关闭告警。
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        asyncio.run(_run())

    def test_initialize_failure_closes_with_1013(self, monkeypatch):
        adapter = FastAPIWebSocketAdapter()
        adapter._initialized = False

        async def _boom():
            raise RuntimeError("init down")

        monkeypatch.setattr(adapter, "initialize", _boom)
        ws = FakeWebSocket()

        asyncio.run(adapter.handle_connection(ws))

        assert ws.accepted is False
        assert ws.close_calls == [(1013, "服务暂不可用，请稍后重试")]

    def test_initialize_failure_swallows_close_error(self, monkeypatch):
        adapter = FastAPIWebSocketAdapter()
        adapter._initialized = False

        async def _boom():
            raise RuntimeError("init down")

        monkeypatch.setattr(adapter, "initialize", _boom)
        ws = FakeWebSocket(close_error=RuntimeError("close failed"))

        asyncio.run(adapter.handle_connection(ws))
        assert ws.accepted is False

    def test_local_connection_skips_token_check(self, monkeypatch):
        manager = FakeManager()
        adapter = _make_adapter(manager=manager)
        ws = self._local_setup(
            monkeypatch,
            adapter,
            receive_script=[WebSocketDisconnect(code=1000, reason="bye")],
            query_params={"user_id": "u1", "platform": "Web", "client_id": "c1"},
        )

        self._run_connection(adapter, ws)

        assert ws.accepted is True
        assert ws.close_calls == []
        assert ws.user_id == "u1"
        assert ws.platform == "web"
        assert ws.client_id == "c1"
        assert manager.added == [(ws, "u1", "web")]
        assert manager.removed == [ws]
        assert "cleanup_websocket" in adapter.handlers.calls

    def test_missing_required_token_closes_1008(self, monkeypatch):
        adapter = _make_adapter(manager=FakeManager())
        self._remote_setup(monkeypatch, adapter, token="")
        ws = FakeWebSocket()

        self._run_connection(adapter, ws)

        assert ws.accepted is False
        assert ws.close_calls[0][0] == 1008
        assert "未配置访问令牌" in ws.close_calls[0][1]

    def test_settings_import_failure_treated_as_no_token(self, monkeypatch):
        adapter = _make_adapter(manager=FakeManager())
        monkeypatch.setattr(adapter, "_request_stop_current_inference", _noop)
        _patch_security(monkeypatch, bypass=False, loopback=False)
        _patch_ws_debug(monkeypatch)

        import config.integrated_config as cfg

        def _boom():
            raise RuntimeError("settings unavailable")

        monkeypatch.setattr(cfg, "get_settings", _boom)
        ws = FakeWebSocket()

        self._run_connection(adapter, ws)

        assert ws.close_calls[0][0] == 1008
        assert "未配置访问令牌" in ws.close_calls[0][1]

    def test_token_from_query_params_accepted(self, monkeypatch):
        adapter = _make_adapter(manager=FakeManager())
        self._remote_setup(monkeypatch, adapter)
        ws = FakeWebSocket(
            receive_script=[WebSocketDisconnect(code=1001)],
            query_params={"token": "secret"},
        )

        self._run_connection(adapter, ws)

        assert ws.accepted is True
        assert ws.close_calls == []

    def test_token_from_bearer_header_accepted(self, monkeypatch):
        adapter = _make_adapter(manager=FakeManager())
        self._remote_setup(monkeypatch, adapter)
        ws = FakeWebSocket(
            receive_script=[WebSocketDisconnect(code=1000)],
            query_params={},
            headers={"authorization": "Bearer secret"},
        )

        self._run_connection(adapter, ws)
        assert ws.accepted is True

    def test_token_from_internal_header_accepted(self, monkeypatch):
        adapter = _make_adapter(manager=FakeManager())
        self._remote_setup(monkeypatch, adapter)
        ws = FakeWebSocket(
            receive_script=[WebSocketDisconnect(code=1000)],
            query_params={},
            headers={"x-internal-token": "secret"},
        )

        self._run_connection(adapter, ws)
        assert ws.accepted is True

    def test_token_mismatch_closes_1008(self, monkeypatch):
        adapter = _make_adapter(manager=FakeManager())
        self._remote_setup(monkeypatch, adapter, token="secret")
        ws = FakeWebSocket(
            query_params={"token": "wrong", "user_id": "u9"},
            headers={},
        )

        self._run_connection(adapter, ws)

        assert ws.accepted is False
        assert ws.close_calls == [(1008, "未授权的 WebSocket 访问")]

    def test_query_params_none_falls_back_to_attributes(self, monkeypatch):
        manager = FakeManager()
        adapter = _make_adapter(manager=manager)
        self._remote_setup(monkeypatch, adapter)
        ws = FakeWebSocket(
            receive_script=[WebSocketDisconnect(code=1000)],
            query_params=None,
            headers={"x-internal-token": "secret"},
            has_client=False,
        )
        ws.user_id = "attr-user"
        ws.platform = "Android"

        self._run_connection(adapter, ws)

        assert ws.accepted is True
        assert ws.user_id == "attr-user"
        assert ws.platform == "android"
        assert manager.added[0][1] == "attr-user"

    def test_blank_identity_fields_become_unknown(self, monkeypatch):
        adapter = _make_adapter(manager=None)
        ws = self._local_setup(
            monkeypatch,
            adapter,
            receive_script=[WebSocketDisconnect(code=1000)],
            query_params={"user_id": "   ", "platform": "   "},
        )

        self._run_connection(adapter, ws)

        assert ws.user_id == "unknown"
        assert ws.platform == "unknown"

    def test_disconnect_abnormal_code_logs_warning(self, monkeypatch):
        adapter = _make_adapter(manager=FakeManager())
        ws = self._local_setup(
            monkeypatch,
            adapter,
            receive_script=[WebSocketDisconnect(code=1006, reason="abnormal")],
            query_params={},
        )

        self._run_connection(adapter, ws)
        assert ws.accepted is True

    def test_runtime_error_not_connected_breaks_loop(self, monkeypatch):
        manager = FakeManager()
        adapter = _make_adapter(manager=manager)
        ws = self._local_setup(
            monkeypatch,
            adapter,
            receive_script=[RuntimeError("WebSocket is not connected")],
            query_params={},
        )

        self._run_connection(adapter, ws)

        assert manager.removed == [ws]
        assert "cleanup_websocket" in adapter.handlers.calls

    def test_runtime_error_other_is_logged_and_cleaned_up(self, monkeypatch):
        manager = FakeManager()
        adapter = _make_adapter(manager=manager)
        ws = self._local_setup(
            monkeypatch,
            adapter,
            receive_script=[RuntimeError("kaboom")],
            query_params={},
        )

        self._run_connection(adapter, ws)

        assert manager.removed == [ws]
        assert "cleanup_websocket" in adapter.handlers.calls

    def test_generic_receive_error_with_disconnect_text(self, monkeypatch):
        manager = FakeManager()
        adapter = _make_adapter(manager=manager)
        ws = self._local_setup(
            monkeypatch,
            adapter,
            receive_script=[RuntimeError("client disconnect happened")],
            query_params={},
        )

        self._run_connection(adapter, ws)
        assert manager.removed == [ws]

    def test_generic_receive_exception_reaches_outer_handler(self, monkeypatch):
        manager = FakeManager()
        adapter = _make_adapter(manager=manager)
        ws = self._local_setup(
            monkeypatch,
            adapter,
            receive_script=[ValueError("weird payload")],
            query_params={},
        )

        self._run_connection(adapter, ws)

        assert manager.removed == [ws]
        assert "cleanup_websocket" in adapter.handlers.calls

    def test_token_debug_log_failure_is_swallowed(self, monkeypatch):
        adapter = _make_adapter(manager=FakeManager())
        self._remote_setup(monkeypatch, adapter)

        import core.utils.ws_handshake_debug as ws_debug

        def _boom(*args, **kwargs):
            raise RuntimeError("debug log boom")

        monkeypatch.setattr(ws_debug, "log", _boom)
        ws = FakeWebSocket(
            receive_script=[WebSocketDisconnect(code=1000)],
            query_params={"token": "secret"},
        )

        self._run_connection(adapter, ws)
        assert ws.accepted is True

    def test_normal_message_is_dispatched_to_background_task(self, monkeypatch):
        adapter = _make_adapter(manager=FakeManager())
        seen = []

        async def _fake_safe(websocket, message):
            seen.append(message)

        monkeypatch.setattr(adapter, "_safe_process_message", _fake_safe)
        ws = self._local_setup(
            monkeypatch,
            adapter,
            receive_script=[{"type": "ping"}, WebSocketDisconnect(code=1000)],
            query_params={},
        )

        self._run_connection(adapter, ws)
        assert seen == [{"type": "ping"}]


# ============================================================
# _safe_process_message / _process_message
# ============================================================


class TestSafeProcessMessage:
    def test_delegates_to_process_message(self, monkeypatch):
        adapter = _make_adapter()
        seen = []

        async def _fake_process(websocket, message):
            seen.append(message)

        monkeypatch.setattr(adapter, "_process_message", _fake_process)
        asyncio.run(adapter._safe_process_message(FakeWebSocket(), {"type": "ping"}))
        assert seen == [{"type": "ping"}]

    def test_cancelled_error_is_reraised(self, monkeypatch):
        adapter = _make_adapter()

        async def _cancel(websocket, message):
            raise asyncio.CancelledError()

        monkeypatch.setattr(adapter, "_process_message", _cancel)

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(adapter._safe_process_message(FakeWebSocket(), {}))

    def test_disconnect_error_is_debug_only(self, monkeypatch):
        adapter = _make_adapter()

        async def _boom(websocket, message):
            raise RuntimeError("client disconnect")

        monkeypatch.setattr(adapter, "_process_message", _boom)
        asyncio.run(adapter._safe_process_message(FakeWebSocket(), {}))

    def test_other_error_is_logged_without_raising(self, monkeypatch):
        adapter = _make_adapter()

        async def _boom(websocket, message):
            raise RuntimeError("boom")

        monkeypatch.setattr(adapter, "_process_message", _boom)
        asyncio.run(adapter._safe_process_message(FakeWebSocket(), {}))


class TestProcessMessage:
    def test_non_dict_message_is_ignored(self):
        handlers = FakeHandlers()
        adapter = _make_adapter(manager=None, handlers=handlers)

        asyncio.run(adapter._process_message(FakeWebSocket(), "not a dict"))
        assert handlers.calls == []

    def test_heartbeat_is_refreshed(self):
        ws = FakeWebSocket()
        conn = SimpleNamespace(last_activity=0.0, last_heartbeat=0.0)
        manager = FakeManager(connections={ws: conn})
        handlers = FakeHandlers()
        adapter = _make_adapter(manager=manager, handlers=handlers)

        asyncio.run(adapter._process_message(ws, {"type": "ping"}))

        assert conn.last_activity > 0
        assert conn.last_heartbeat > 0
        assert handlers.calls == ["handle_ping"]

    def test_heartbeat_skips_when_connection_unknown(self):
        manager = FakeManager(connections={})
        handlers = FakeHandlers()
        adapter = _make_adapter(manager=manager, handlers=handlers)

        asyncio.run(adapter._process_message(FakeWebSocket(), {"type": "pong"}))
        assert handlers.calls == ["handle_pong"]

    def test_heartbeat_failure_is_swallowed(self):
        manager = FakeManager(connections=_RaisingDict())
        handlers = FakeHandlers()
        adapter = _make_adapter(manager=manager, handlers=handlers)

        asyncio.run(adapter._process_message(FakeWebSocket(), {"type": "ping"}))
        assert handlers.calls == ["handle_ping"]

    @pytest.mark.parametrize(
        "msg_type,expected",
        [
            ("ping", "handle_ping"),
            ("pong", "handle_pong"),
            ("greeting", "handle_greeting_message"),
            ("update_settings", "handle_update_settings"),
            ("update_user_physiology", "handle_update_physiology"),
            ("mobile_switch_model", "handle_mobile_switch_model"),
            ("reconnect", "handle_reconnect"),
        ],
    )
    def test_routes_simple_message_types(self, msg_type, expected):
        handlers = FakeHandlers()
        adapter = _make_adapter(manager=None, handlers=handlers)

        asyncio.run(adapter._process_message(FakeWebSocket(), {"type": msg_type}))
        assert handlers.calls == [expected]

    @pytest.mark.parametrize("msg_type", ["text", "text_input"])
    def test_text_message_normalized_then_chatted(self, msg_type):
        handlers = FakeHandlers()
        adapter = _make_adapter(manager=None, handlers=handlers)

        asyncio.run(adapter._process_message(FakeWebSocket(), {"type": msg_type}))
        assert handlers.calls == ["handle_text_message", "handle_chat_message"]

    @pytest.mark.parametrize("msg_type", ["text", "text_input"])
    def test_text_message_skips_chat_when_normalization_empty(self, msg_type):
        handlers = FakeHandlers(text_result=None)
        adapter = _make_adapter(manager=None, handlers=handlers)

        asyncio.run(adapter._process_message(FakeWebSocket(), {"type": msg_type}))
        assert handlers.calls == ["handle_text_message"]

    @pytest.mark.parametrize("msg_type", ["message", "chat"])
    def test_routes_chat_message_types(self, msg_type):
        handlers = FakeHandlers()
        adapter = _make_adapter(manager=None, handlers=handlers)

        asyncio.run(adapter._process_message(FakeWebSocket(), {"type": msg_type}))
        assert handlers.calls == ["handle_chat_message"]

    @pytest.mark.parametrize(
        "msg_type",
        ["demo_voice_input", "demo_generate_image", "generate_image"],
    )
    def test_routes_demo_message_types(self, monkeypatch, msg_type):
        adapter = _make_adapter(manager=None)
        seen = []

        async def _fake_demo(websocket, message):
            seen.append(message)

        monkeypatch.setattr(adapter, "_handle_demo_message", _fake_demo)

        asyncio.run(adapter._process_message(FakeWebSocket(), {"type": msg_type}))
        assert seen == [{"type": msg_type}]

    def test_routes_device_command_result(self, monkeypatch):
        adapter = _make_adapter(manager=None)
        seen = []

        async def _fake_device(message):
            seen.append(message)

        monkeypatch.setattr(adapter, "_handle_device_command_result", _fake_device)

        asyncio.run(
            adapter._process_message(FakeWebSocket(), {"type": "device_command_result"})
        )
        assert seen == [{"type": "device_command_result"}]

    def test_unknown_type_is_forwarded_to_manager(self):
        ws = FakeWebSocket()
        manager = FakeManager()
        adapter = _make_adapter(manager=manager)

        message = {"type": "unknown_type"}
        asyncio.run(adapter._process_message(ws, message))
        assert manager.handled == [(ws, message)]

    def test_unknown_type_without_manager_is_noop(self):
        adapter = _make_adapter(manager=None)
        asyncio.run(adapter._process_message(FakeWebSocket(), {"type": "nope"}))

    def test_handler_close_race_error_is_debug_only(self):
        handlers = FakeHandlers(
            errors={
                "handle_ping": RuntimeError(
                    "Cannot call send once a close message has been sent"
                )
            }
        )
        adapter = _make_adapter(manager=None, handlers=handlers)

        asyncio.run(adapter._process_message(FakeWebSocket(), {"type": "ping"}))
        assert handlers.calls == ["handle_ping"]

    def test_handler_not_connected_error_is_debug_only(self):
        handlers = FakeHandlers(
            errors={"handle_ping": RuntimeError("WebSocket is not connected")}
        )
        adapter = _make_adapter(manager=None, handlers=handlers)

        asyncio.run(adapter._process_message(FakeWebSocket(), {"type": "ping"}))
        assert handlers.calls == ["handle_ping"]

    def test_handler_other_error_is_logged(self):
        handlers = FakeHandlers(errors={"handle_ping": RuntimeError("boom")})
        adapter = _make_adapter(manager=None, handlers=handlers)

        asyncio.run(adapter._process_message(FakeWebSocket(), {"type": "ping"}))
        assert handlers.calls == ["handle_ping"]


# ============================================================
# 设备指令结果
# ============================================================


class TestDeviceCommandResult:
    def test_success_delegates_to_bridge(self, monkeypatch):
        adapter = _make_adapter()
        resolved = []

        class _Bridge:
            async def resolve_result(self, message):
                resolved.append(message)

        import core.services.device_command as dc_mod

        monkeypatch.setattr(dc_mod, "get_device_command_bridge", lambda: _Bridge())

        message = {"type": "device_command_result", "request_id": "r1"}
        asyncio.run(adapter._handle_device_command_result(message))
        assert resolved == [message]

    def test_bridge_failure_is_logged(self, monkeypatch):
        adapter = _make_adapter()

        import core.services.device_command as dc_mod

        def _boom():
            raise RuntimeError("bridge unavailable")

        monkeypatch.setattr(dc_mod, "get_device_command_bridge", _boom)

        asyncio.run(adapter._handle_device_command_result({"request_id": "r1"}))


# ============================================================
# 演示生图
# ============================================================


class TestHandleDemoMessage:
    def _setup(self, monkeypatch, *, demo=None, life_error=None):
        demo = demo if demo is not None else FakeDemo()
        adapter = _make_adapter(demo=demo)
        _patch_life_sim(monkeypatch, error=life_error)
        return adapter, demo

    @staticmethod
    def _run(adapter, ws, message):
        async def _run():
            await adapter._handle_demo_message(ws, message)
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        asyncio.run(_run())

    def test_ack_and_pipeline_started(self, monkeypatch):
        adapter, demo = self._setup(monkeypatch)
        ws = FakeWebSocket()

        self._run(
            adapter,
            ws,
            {
                "type": "generate_image",
                "content": "一只猫",
                "message_id": "m1",
                "conversation_id": "cv1",
                "num_images": "2",
            },
        )

        assert ws.sent[0]["event"] == "ack"
        assert ws.sent[0]["data"]["accepted"] is True
        assert demo.pipelines[0]["user_text"] == "一只猫"
        assert demo.pipelines[0]["num_images"] == 2
        assert demo.pipelines[0]["conversation_id"] == "cv1"

    @pytest.mark.parametrize(
        "message,expected",
        [
            ({"num_images": "abc"}, 1),
            ({"numImages": 3}, 3),
            ({"num": 4}, 4),
            ({}, 1),
        ],
    )
    def test_num_images_parsing(self, monkeypatch, message, expected):
        adapter, demo = self._setup(monkeypatch)
        ws = FakeWebSocket()
        payload = {"type": "generate_image", "content": "cat", "message_id": "m1"}
        payload.update(message)

        self._run(adapter, ws, payload)
        assert demo.pipelines[0]["num_images"] == expected

    def test_empty_text_sends_pipeline_error(self, monkeypatch):
        adapter, demo = self._setup(monkeypatch)
        ws = FakeWebSocket()

        self._run(
            adapter,
            ws,
            {"type": "generate_image", "content": "   ", "message_id": "m1"},
        )

        assert ws.sent[0]["event"] == "ack"
        assert demo.events[0]["event"] == "pipeline_error"
        assert demo.pipelines == []

    def test_existing_running_task_blocks_new_pipeline(self, monkeypatch):
        adapter, demo = self._setup(monkeypatch)
        ws = FakeWebSocket()

        async def _run():
            running = asyncio.create_task(_never())
            adapter._image_generation_tasks["m1"] = running
            try:
                await adapter._handle_demo_message(
                    ws,
                    {"type": "generate_image", "content": "cat", "message_id": "m1"},
                )
            finally:
                await _drain(running)

        asyncio.run(_run())

        assert demo.events[0]["event"] == "pipeline_error"
        assert demo.events[0]["data"]["message"] == "当前生图任务仍在进行中"
        assert demo.pipelines == []

    def test_voice_input_emits_stt_started(self, monkeypatch):
        adapter, demo = self._setup(monkeypatch)

        async def _no_sleep(_seconds):
            return None

        _asyncio_shim(monkeypatch, sleep=_no_sleep)
        ws = FakeWebSocket()

        self._run(
            adapter,
            ws,
            {
                "type": "demo_voice_input",
                "content": "hi",
                "message_id": "m1",
                "conversation_id": "cv1",
                "request_id": "r1",
            },
        )

        assert demo.events[0]["event"] == "stt_started"
        assert demo.events[0]["data"] == {"status": "listening"}

    def test_conversation_id_falls_back_to_user_id(self, monkeypatch):
        adapter, demo = self._setup(monkeypatch)
        ws = FakeWebSocket()
        ws.user_id = "u-42"

        self._run(
            adapter,
            ws,
            {"type": "generate_image", "content": "cat", "message_id": "m1"},
        )
        assert demo.pipelines[0]["conversation_id"] == "u-42"

    def test_conversation_id_defaults_to_demo(self, monkeypatch):
        adapter, demo = self._setup(monkeypatch)
        ws = FakeWebSocket()

        self._run(
            adapter,
            ws,
            {"type": "generate_image", "content": "cat", "message_id": "m1"},
        )
        assert demo.pipelines[0]["conversation_id"] == "demo"

    def test_message_id_generated_when_absent(self, monkeypatch):
        adapter, demo = self._setup(monkeypatch)
        ws = FakeWebSocket()

        self._run(adapter, ws, {"type": "generate_image", "content": "cat"})

        generated_id = demo.pipelines[0]["message_id"]
        assert generated_id
        assert demo.pipelines[0]["request_id"] == generated_id

    def test_life_simulation_failure_is_swallowed(self, monkeypatch):
        adapter, demo = self._setup(
            monkeypatch, life_error=RuntimeError("life sim down")
        )
        ws = FakeWebSocket()

        self._run(
            adapter,
            ws,
            {"type": "generate_image", "content": "cat", "message_id": "m1"},
        )
        assert demo.pipelines[0]["user_text"] == "cat"


# ============================================================
# _generate_image_and_send
# ============================================================


class TestGenerateImageAndSend:
    @staticmethod
    def _prepare(monkeypatch, *, lock=None, manager=None, prepare=None):
        adapter = _make_adapter()
        _patch_settings(monkeypatch, model=_image_model_settings())
        _patch_resource_lock(monkeypatch, lock or FakeResourceLock())
        _patch_image_manager(monkeypatch, manager or FakeImageManager())
        seen_results = []

        async def _default_prepare(result):
            seen_results.append(result)
            return {"success": True, "prompt": result.get("prompt")}

        monkeypatch.setattr(
            adapter, "_prepare_image_payload", prepare or _default_prepare
        )
        return adapter, seen_results

    def test_empty_prompt_returns_early(self, monkeypatch):
        adapter, _ = self._prepare(monkeypatch)
        ws = FakeWebSocket()

        asyncio.run(adapter._generate_image_and_send(ws, "   ", "m1", "cv1"))
        assert ws.sent == []

    def test_unstringable_prompt_is_ignored(self, monkeypatch):
        adapter, _ = self._prepare(monkeypatch)
        ws = FakeWebSocket()

        class _BadStr:
            def __str__(self):
                raise RuntimeError("cannot stringify")

        asyncio.run(adapter._generate_image_and_send(ws, _BadStr(), "m1", "cv1"))
        assert ws.sent == []

    def test_pipe_prompt_is_split(self, monkeypatch):
        manager = FakeImageManager(result={"success": True, "image_path": "x.png"})
        adapter, _ = self._prepare(monkeypatch, manager=manager)
        ws = FakeWebSocket()

        asyncio.run(
            adapter._generate_image_and_send(ws, "cat|dog", "m1", "cv1")
        )

        assert ws.sent[0]["data"]["status"] == "started"
        assert ws.sent[0]["data"]["prompt"] == "cat"
        assert manager.calls[0]["prompt"] == "cat"

    def test_queued_status_when_gate_busy(self, monkeypatch):
        lock = FakeResourceLock(
            status={"enabled": True, "active": 1, "waiting": 1}
        )
        adapter, _ = self._prepare(monkeypatch, lock=lock)
        ws = FakeWebSocket()

        asyncio.run(adapter._generate_image_and_send(ws, "cat", "m1", "cv1"))

        assert ws.sent[0]["data"]["status"] == "queued"
        assert ws.sent[0]["data"]["position"] == 3
        assert ws.sent[1]["data"]["status"] == "started"

    def test_queued_send_failure_is_swallowed(self, monkeypatch):
        lock = FakeResourceLock(status={"enabled": True, "active": 1, "waiting": 0})
        adapter, _ = self._prepare(monkeypatch, lock=lock)
        ws = FakeWebSocket(send_errors=[RuntimeError("queued send failed")])

        asyncio.run(adapter._generate_image_and_send(ws, "cat", "m1", "cv1"))
        assert ws.sent[0]["data"]["status"] == "started"

    def test_started_send_failure_is_swallowed(self, monkeypatch):
        manager = FakeImageManager(result={"success": True})
        adapter, _ = self._prepare(monkeypatch, manager=manager)
        ws = FakeWebSocket(send_errors=[RuntimeError("started send failed")])

        asyncio.run(adapter._generate_image_and_send(ws, "cat", "m1", "cv1"))
        assert manager.calls[0]["prompt"] == "cat"

    def test_result_prompt_filled_and_sent(self, monkeypatch):
        manager = FakeImageManager(result={"success": True, "image_path": "x.png"})
        adapter, seen = self._prepare(monkeypatch, manager=manager)
        ws = FakeWebSocket()

        asyncio.run(adapter._generate_image_and_send(ws, "cat", "m1", "cv1"))

        assert seen[0]["prompt"] == "cat"
        assert ws.sent[-1]["type"] == "image_result"
        assert ws.sent[-1]["data"]["success"] is True

    def test_cuda_oom_triggers_resource_optimize(self, monkeypatch):
        manager = FakeImageManager(error=RuntimeError("CUDA out of memory"))
        adapter, _ = self._prepare(monkeypatch, manager=manager)
        ws = FakeWebSocket()

        import core.resource_manager as rm_mod
        import core.utils.concurrency.async_tasks as tasks_mod

        class _FakeRm:
            async def optimize_resources(self):
                return None

        async def _get_rm():
            return _FakeRm()

        monkeypatch.setattr(rm_mod, "get_global_resource_manager", _get_rm)

        spawned = []

        def _spawn(coro, *, name=""):
            spawned.append(name)
            coro.close()
            return None

        monkeypatch.setattr(tasks_mod, "spawn_bg_task", _spawn)

        asyncio.run(adapter._generate_image_and_send(ws, "cat", "m1", "cv1"))

        assert spawned == ["cuda_oom_optimize"]
        assert ws.sent[-1]["data"]["success"] is False
        assert ws.sent[-1]["data"]["error_code"] == ErrorCode.INTERNAL_ERROR.value

    def test_cuda_oom_optimize_failure_is_swallowed(self, monkeypatch):
        manager = FakeImageManager(error=RuntimeError("CUDA out of memory"))
        adapter, _ = self._prepare(monkeypatch, manager=manager)
        ws = FakeWebSocket()

        import core.resource_manager as rm_mod

        async def _boom():
            raise RuntimeError("rm unavailable")

        monkeypatch.setattr(rm_mod, "get_global_resource_manager", _boom)

        asyncio.run(adapter._generate_image_and_send(ws, "cat", "m1", "cv1"))
        assert ws.sent[-1]["data"]["success"] is False

    def test_finally_cleanup_error_is_swallowed(self, monkeypatch):
        adapter, _ = self._prepare(monkeypatch)
        ws = FakeWebSocket()

        def _boom_current_task():
            raise RuntimeError("current_task boom")

        _asyncio_shim(monkeypatch, current_task=_boom_current_task)

        asyncio.run(adapter._generate_image_and_send(ws, "cat", "m1", "cv1"))
        assert ws.sent[-1]["type"] == "image_result"

    def test_generic_error_maps_error_code(self, monkeypatch):
        manager = FakeImageManager(error=ValueError("bad params"))
        adapter, _ = self._prepare(monkeypatch, manager=manager)
        ws = FakeWebSocket()

        asyncio.run(adapter._generate_image_and_send(ws, "cat", "m1", "cv1"))

        assert ws.sent[-1]["data"]["error_code"] == ErrorCode.INVALID_PARAMETER.value
        assert ws.sent[-1]["data"]["details"]["error_type"] == "ValueError"

    def test_error_response_send_failure_is_swallowed(self, monkeypatch):
        manager = FakeImageManager(error=ValueError("bad params"))
        adapter, _ = self._prepare(monkeypatch, manager=manager)
        ws = FakeWebSocket(send_error=RuntimeError("send failed"))

        asyncio.run(adapter._generate_image_and_send(ws, "cat", "m1", "cv1"))
        assert ws.sent == []

    def test_finally_removes_own_task_from_registry(self, monkeypatch):
        adapter, _ = self._prepare(monkeypatch)
        ws = FakeWebSocket()

        async def _run():
            task = asyncio.create_task(
                adapter._generate_image_and_send(ws, "cat", "m1", "cv1")
            )
            adapter._image_generation_tasks["m1"] = task
            await task

        asyncio.run(_run())
        assert "m1" not in adapter._image_generation_tasks

    def test_prepare_payload_failure_is_reported(self, monkeypatch):
        async def _boom(result):
            raise RuntimeError("payload failed")

        adapter, _ = self._prepare(monkeypatch, prepare=_boom)
        ws = FakeWebSocket()

        asyncio.run(adapter._generate_image_and_send(ws, "cat", "m1", "cv1"))
        assert ws.sent[-1]["data"]["success"] is False


# ============================================================
# _prepare_image_payload
# ============================================================


class TestPrepareImagePayload:
    @staticmethod
    def _patch_image_url(monkeypatch):
        import core.image.image_utils as img_utils

        monkeypatch.setattr(
            img_utils, "get_image_url", lambda path: f"url::{path}"
        )

    def test_thumbnail_generated_for_existing_file(self, monkeypatch, tmp_path):
        from PIL import Image

        self._patch_image_url(monkeypatch)
        adapter = _make_adapter()

        image_path = tmp_path / "pic.png"
        Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(image_path)

        payload = asyncio.run(
            adapter._prepare_image_payload(
                {"success": True, "image_path": str(image_path), "prompt": "cat"}
            )
        )

        assert payload["image_path"] == str(image_path)
        assert payload["image_url"] == f"url::{image_path}"
        assert payload["thumbnail_base64"].startswith("data:image/jpeg;base64,")
        raw = payload["thumbnail_base64"].split(",", 1)[1]
        assert base64.b64decode(raw)

    def test_missing_file_skips_thumbnail(self, monkeypatch, tmp_path):
        self._patch_image_url(monkeypatch)
        adapter = _make_adapter()

        missing = tmp_path / "nope.png"
        payload = asyncio.run(
            adapter._prepare_image_payload(
                {"success": True, "image_path": str(missing)}
            )
        )

        assert "thumbnail_base64" not in payload
        assert payload["image_url"] == f"url::{missing}"

    def test_thumbnail_failure_is_swallowed(self, monkeypatch, tmp_path):
        self._patch_image_url(monkeypatch)
        adapter = _make_adapter()

        image_path = tmp_path / "pic.png"
        image_path.write_bytes(b"not-a-real-image")

        import PIL.Image as pil_image

        def _boom(*args, **kwargs):
            raise OSError("cannot open")

        monkeypatch.setattr(pil_image, "open", _boom)

        payload = asyncio.run(
            adapter._prepare_image_payload(
                {"success": True, "image_path": str(image_path)}
            )
        )

        assert "thumbnail_base64" not in payload

    def test_images_list_is_normalized(self, monkeypatch):
        self._patch_image_url(monkeypatch)
        adapter = _make_adapter()

        payload = asyncio.run(
            adapter._prepare_image_payload(
                {
                    "success": True,
                    "images": [
                        {"image_path": "a.png"},
                        "not-a-dict",
                        {"image_path": ""},
                        {"image_path": "b.png"},
                    ],
                }
            )
        )

        assert payload["images"] == [
            {"image_path": "a.png", "url": "url::a.png"},
            {"image_path": "b.png", "url": "url::b.png"},
        ]
        assert payload["image_url"] == "url::a.png"

    def test_images_list_without_valid_entries_is_dropped(self, monkeypatch):
        self._patch_image_url(monkeypatch)
        adapter = _make_adapter()

        payload = asyncio.run(
            adapter._prepare_image_payload({"success": False, "images": ["x", {}]})
        )

        assert "images" not in payload
        assert payload["success"] is False

    def test_images_do_not_override_existing_image_url(self, monkeypatch):
        self._patch_image_url(monkeypatch)
        adapter = _make_adapter()

        payload = asyncio.run(
            adapter._prepare_image_payload(
                {
                    "success": True,
                    "image_path": "main.png",
                    "images": [{"image_path": "extra.png"}],
                }
            )
        )

        assert payload["image_url"] == "url::main.png"
        assert payload["images"] == [
            {"image_path": "extra.png", "url": "url::extra.png"}
        ]


# ============================================================
# _handle_resource_update / broadcast_message
# ============================================================


def _make_fake_rm(*, models=None, gpu_info=(100, 8192), cpu=10.0, mem=20.0):
    monitor = SimpleNamespace(
        get_gpu_memory_usage=lambda: gpu_info,
        get_cpu_usage=lambda: cpu,
        get_cpu_model=lambda: "cpu-x",
        get_memory_usage=lambda: mem,
        get_gpu_model=lambda: "gpu-x",
    )
    return SimpleNamespace(models=models if models is not None else {}, monitor=monitor)


def _model_stub(*, loaded=True, device="GPU", priority="HIGH", vram=100):
    return SimpleNamespace(
        device=device,
        priority=SimpleNamespace(name=priority),
        is_loaded=loaded,
        vram_usage_mb=vram,
    )


class TestHandleResourceUpdate:
    @staticmethod
    def _patch_deps(
        monkeypatch,
        *,
        rm=None,
        settings_error=False,
        lock_error=False,
        scheduler=None,
        scheduler_error=False,
    ):
        import core.resource_manager as rm_mod
        import config.integrated_config as cfg

        rm = rm if rm is not None else _make_fake_rm()
        monkeypatch.setattr(rm_mod, "get_resource_manager", lambda: rm)

        if settings_error:
            def _boom_settings():
                raise RuntimeError("settings boom")

            monkeypatch.setattr(cfg, "get_settings", _boom_settings)
        else:
            _patch_settings(
                monkeypatch,
                model=SimpleNamespace(
                    llm=SimpleNamespace(provider="local", model="fake-llm"),
                    text_path="models/x",
                ),
            )

        if lock_error:
            import core.utils.concurrency.resource_lock as rl_mod

            def _boom_lock():
                raise RuntimeError("lock boom")

            monkeypatch.setattr(rl_mod, "get_resource_lock", _boom_lock)
        else:
            _patch_resource_lock(
                monkeypatch,
                FakeResourceLock(status={"enabled": True, "active": 0}),
            )

        import core.services.scheduler.cpp_scheduler_engine as sched_mod

        if scheduler_error:
            def _boom_sched(*args, **kwargs):
                raise RuntimeError("scheduler boom")

            monkeypatch.setattr(sched_mod, "get_scheduler_engine", _boom_sched)
        else:
            monkeypatch.setattr(
                sched_mod,
                "get_scheduler_engine",
                lambda *a, **k: scheduler,
            )
        return rm

    def test_returns_early_without_manager(self):
        adapter = _make_adapter(manager=None)
        asyncio.run(adapter._handle_resource_update())
        assert adapter._last_broadcast_hash is None

    def test_returns_early_without_active_connections(self, monkeypatch):
        manager = FakeManager(active_connections=0)
        adapter = _make_adapter(manager=manager)
        self._patch_deps(monkeypatch)

        asyncio.run(adapter._handle_resource_update())
        assert manager.broadcasts == []

    def test_returns_early_within_min_interval(self, monkeypatch):
        manager = FakeManager(active_connections=2)
        adapter = _make_adapter(manager=manager)
        adapter._last_broadcast_time = __import__("time").time()
        self._patch_deps(monkeypatch)

        asyncio.run(adapter._handle_resource_update())
        assert manager.broadcasts == []

    def test_broadcasts_when_data_changes(self, monkeypatch):
        manager = FakeManager(active_connections=2)
        adapter = _make_adapter(manager=manager)
        self._patch_deps(
            monkeypatch,
            rm=_make_fake_rm(models={"m1": _model_stub()}),
            scheduler=SimpleNamespace(get_status=lambda: {"q": 0}),
        )

        asyncio.run(adapter._handle_resource_update())

        assert len(manager.broadcasts) == 1
        message = manager.broadcasts[0]
        assert message["type"] == "system_status"
        assert message["models"]["m1"]["is_loaded"] is True
        assert message["models"]["llm"]["provider"] == "local"
        assert message["system"]["gpu_memory_used"] == 100
        assert message["system"]["gpu_memory_total"] == 8192
        assert message["system"]["scheduler"] == {"q": 0}
        assert adapter._last_broadcast_hash is not None
        assert adapter._last_logged_connection_count == 2
        assert adapter._last_logged_models_state == 1

    def test_skips_broadcast_when_hash_unchanged(self, monkeypatch):
        manager = FakeManager(active_connections=1)
        adapter = _make_adapter(manager=manager)
        adapter._min_broadcast_interval = 0
        self._patch_deps(monkeypatch, rm=_make_fake_rm(models={"m1": _model_stub()}))

        asyncio.run(adapter._handle_resource_update())
        asyncio.run(adapter._handle_resource_update())

        assert len(manager.broadcasts) == 1

    def test_gpu_info_none_uses_defaults(self, monkeypatch):
        manager = FakeManager(active_connections=1)
        adapter = _make_adapter(manager=manager)
        self._patch_deps(monkeypatch, rm=_make_fake_rm(gpu_info=None))

        asyncio.run(adapter._handle_resource_update())

        system = manager.broadcasts[0]["system"]
        assert system["gpu_memory_used"] == 0
        assert system["gpu_memory_total"] == 8192

    def test_settings_injection_failure_is_swallowed(self, monkeypatch):
        manager = FakeManager(active_connections=1)
        adapter = _make_adapter(manager=manager)
        self._patch_deps(monkeypatch, settings_error=True)

        asyncio.run(adapter._handle_resource_update())

        assert "llm" not in manager.broadcasts[0]["models"]

    def test_gpu_gate_failure_is_swallowed(self, monkeypatch):
        manager = FakeManager(active_connections=1)
        adapter = _make_adapter(manager=manager)
        self._patch_deps(monkeypatch, lock_error=True)

        asyncio.run(adapter._handle_resource_update())

        assert manager.broadcasts[0]["system"]["gpu_gate"] is None

    def test_scheduler_failure_is_swallowed(self, monkeypatch):
        manager = FakeManager(active_connections=1)
        adapter = _make_adapter(manager=manager)
        self._patch_deps(monkeypatch, scheduler_error=True)

        asyncio.run(adapter._handle_resource_update())

        assert manager.broadcasts[0]["system"]["scheduler"] is None

    def test_scheduler_none_is_tolerated(self, monkeypatch):
        manager = FakeManager(active_connections=1)
        adapter = _make_adapter(manager=manager)
        self._patch_deps(monkeypatch, scheduler=None)

        asyncio.run(adapter._handle_resource_update())

        assert manager.broadcasts[0]["system"]["scheduler"] is None

    def test_unexpected_error_is_logged(self, monkeypatch):
        manager = FakeManager(active_connections=1)
        adapter = _make_adapter(manager=manager)

        rm = _make_fake_rm()
        rm.monitor.get_cpu_usage = MagicMock(side_effect=RuntimeError("cpu boom"))
        self._patch_deps(monkeypatch, rm=rm)

        asyncio.run(adapter._handle_resource_update())
        assert manager.broadcasts == []


class TestBroadcastMessage:
    def test_initializes_when_needed(self, monkeypatch):
        adapter = FastAPIWebSocketAdapter()
        adapter._initialized = False
        manager = FakeManager()

        async def _fake_initialize():
            adapter.websocket_manager = manager
            adapter._initialized = True

        monkeypatch.setattr(adapter, "initialize", _fake_initialize)

        asyncio.run(adapter.broadcast_message({"type": "x"}))
        assert manager.broadcasts == [{"type": "x"}]

    def test_returns_without_manager(self):
        adapter = _make_adapter(manager=None)
        asyncio.run(adapter.broadcast_message({"type": "x"}))

    def test_broadcast_error_is_logged(self):
        manager = FakeManager(broadcast_error=RuntimeError("broadcast boom"))
        adapter = _make_adapter(manager=manager)

        asyncio.run(adapter.broadcast_message({"type": "x"}))
        assert manager.broadcasts == []


# ============================================================
# 模块级单例
# ============================================================


class TestModuleSingletons:
    def test_get_adapter_creates_and_caches_instance(self, monkeypatch):
        created = []

        class _FakeAdapter:
            def __init__(self):
                self.initialized = False
                created.append(self)

            async def initialize(self):
                self.initialized = True

        monkeypatch.setattr(adapter_module, "FastAPIWebSocketAdapter", _FakeAdapter)
        monkeypatch.setattr(adapter_module, "_instance", None)
        monkeypatch.setattr(adapter_module, "_instance_lock", asyncio.Lock())

        instance = asyncio.run(get_fastapi_websocket_adapter())

        assert isinstance(instance, _FakeAdapter)
        assert instance.initialized is True
        assert len(created) == 1

    def test_get_adapter_reuses_cached_instance(self, monkeypatch):
        sentinel = object()
        monkeypatch.setattr(adapter_module, "_instance", sentinel)

        assert asyncio.run(get_fastapi_websocket_adapter()) is sentinel

    def test_initialize_websocket_adapter_returns_instance(self, monkeypatch):
        sentinel = object()

        async def _fake_get():
            return sentinel

        monkeypatch.setattr(adapter_module, "get_fastapi_websocket_adapter", _fake_get)
        assert asyncio.run(initialize_websocket_adapter()) is sentinel

    def test_shutdown_adapter_without_instance_returns(self, monkeypatch):
        monkeypatch.setattr(adapter_module, "_instance", None)
        asyncio.run(shutdown_websocket_adapter())
        assert adapter_module._instance is None

    def test_shutdown_adapter_calls_shutdown_and_clears(self, monkeypatch):
        calls = []

        class _FakeAdapter:
            async def shutdown(self):
                calls.append("shutdown")

        monkeypatch.setattr(adapter_module, "_instance", _FakeAdapter())

        asyncio.run(shutdown_websocket_adapter())

        assert calls == ["shutdown"]
        assert adapter_module._instance is None

    def test_shutdown_adapter_clears_instance_on_error(self, monkeypatch):
        class _FakeAdapter:
            async def shutdown(self):
                raise RuntimeError("shutdown boom")

        monkeypatch.setattr(adapter_module, "_instance", _FakeAdapter())

        with pytest.raises(RuntimeError, match="shutdown boom"):
            asyncio.run(shutdown_websocket_adapter())

        assert adapter_module._instance is None
