import asyncio
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from clients.bots.qq.session.connection import SessionConnectionManager
from clients.bots.qq.session.session import XiaoyouSession


class _FakeAdapter:
    def __init__(self):
        self._conn_issue_notified = {}
        self.sessions = {}
        self.send_to_napcat = AsyncMock(return_value=None)
        self.cfg = SimpleNamespace(role_id="", master_qq_id="")


class TestQQSessionHeartbeat(unittest.IsolatedAsyncioTestCase):
    async def test_handle_server_heartbeat_replies_ping_payload(self):
        session = XiaoyouSession("default_user", _FakeAdapter())
        fake_ws = AsyncMock()
        session.ws = fake_ws

        handled = await session._handle_server_heartbeat({"type": "ping"})
        self.assertTrue(handled)
        fake_ws.send.assert_awaited_once()
        raw = fake_ws.send.await_args.args[0]
        payload = json.loads(raw)
        self.assertEqual(payload.get("type"), "pong")
        self.assertEqual(payload.get("text"), "__heartbeat__")
        self.assertEqual(payload.get("platform"), "qq")

    async def test_handle_server_heartbeat_ignores_non_ping(self):
        session = XiaoyouSession("default_user", _FakeAdapter())
        fake_ws = AsyncMock()
        session.ws = fake_ws

        handled = await session._handle_server_heartbeat({"type": "message"})
        self.assertFalse(handled)
        fake_ws.send.assert_not_awaited()


class _FakeTransportSocket:
    def get_extra_info(self, name):
        return None


class _FakeCoreWs:
    def __init__(self):
        self.transport = _FakeTransportSocket()
        self.closed = False

    async def send(self, _payload):
        return None

    async def close(self):
        self.closed = True


class _FakeWsContext:
    def __init__(self, ws):
        self._ws = ws

    async def __aenter__(self):
        return self._ws

    async def __aexit__(self, exc_type, exc, tb):
        self._ws.closed = True
        return False


class _ReconnectTestSession:
    def __init__(self, master_qq_id: str = "123456"):
        self.session_id = "private_123456"
        self.running = True
        self.queue = asyncio.Queue()
        self.adapter = _FakeAdapter()
        self._cfg = SimpleNamespace(
            xiaoyou_ws_url="ws://127.0.0.1:8000/api/v1/ws",
            xiaoyou_access_token="",
            master_qq_id=master_qq_id,
        )
        self._start_time = time.time()
        self._connection_state = "disconnected"
        self._connection_failure_since = 0.0
        self._last_connected_at = 0.0
        self._client_id = "qq_test_private_123456"
        self.ws = None
        self.receive_call_count = 0

    async def _receive_from_xiaoyou(self):
        self.receive_call_count += 1
        if self.receive_call_count == 1:
            return
        await asyncio.sleep(0.05)
        self.running = False

    async def _notify_connection_issue(self, ws_url: str, err: Exception):
        return None


class TestQQSessionReconnect(unittest.IsolatedAsyncioTestCase):
    async def test_reconnects_when_receive_loop_exits_without_new_message(self):
        session = _ReconnectTestSession()
        manager = SessionConnectionManager(session)
        connect_count = 0

        async def fake_ws_connect(*args, **kwargs):
            nonlocal connect_count
            connect_count += 1
            return _FakeWsContext(_FakeCoreWs())

        with patch("clients.bots.qq.session.connection._ws_connect", new=fake_ws_connect):
            await manager.run_loop()

        self.assertGreaterEqual(connect_count, 2)
        self.assertGreaterEqual(session.receive_call_count, 2)

    async def test_stale_session_does_not_delete_new_session_entry(self):
        adapter = _FakeAdapter()
        old_session = _ReconnectTestSession()
        old_session.adapter = adapter
        new_session = _ReconnectTestSession()
        new_session.adapter = adapter
        adapter.sessions = {old_session.session_id: new_session}
        manager = SessionConnectionManager(old_session)

        old_session.running = False
        await manager.run_loop()

        self.assertIs(adapter.sessions.get(old_session.session_id), new_session)

    async def test_master_session_keeps_retrying_without_stopping(self):
        session = _ReconnectTestSession(master_qq_id="123456")
        manager = SessionConnectionManager(session)
        connect_attempts = 0
        sleep_calls = 0

        async def fake_ws_connect(*args, **kwargs):
            nonlocal connect_attempts
            connect_attempts += 1
            raise ConnectionRefusedError("Connection refused")

        async def fake_sleep(_delay):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 7:
                session.running = False

        with (
            patch("clients.bots.qq.session.connection._ws_connect", new=fake_ws_connect),
            patch("clients.bots.qq.session.connection.asyncio.sleep", new=fake_sleep),
        ):
            await manager.run_loop()

        self.assertEqual(sleep_calls, 7)
        self.assertEqual(connect_attempts, 7)

    async def test_notify_connection_issue_has_restart_grace_period(self):
        session = _ReconnectTestSession(master_qq_id="123456")
        manager = SessionConnectionManager(session)
        session._connection_failure_since = time.time()

        await manager.notify_connection_issue(
            ws_url=session._cfg.xiaoyou_ws_url,
            err=ConnectionRefusedError("Connection refused"),
        )

        session.adapter.send_to_napcat.assert_not_awaited()
