#!/usr/bin/env python3
"""验证 WinError 121 降噪与 Active Care 双 QQ 可靠投递修复。"""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from collections import defaultdict, deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from clients.bots.qq.utils.transport_helpers import _ws_connect
from core.interfaces.websocket.message_sending import (
    get_qq_target_role_id,
    qq_connection_accepts_message,
)
from core.interfaces.websocket.offline_queue import OfflineQueueMixin
from core.services.active_care.core.conversation_router import ConversationRouter
from core.utils.websocket_logging import RecoverableWebSocketDisconnectFilter


def _payload(role_id: str, content: str = "测试消息") -> dict:
    return {
        "type": "proactive_message",
        "client_type": "qq",
        "conversation_id": f"shared__persona__{role_id}_qq_master",
        "content": content,
    }


async def _verify_transport_id_preserved() -> None:
    class DummyContext:
        async def resolve_primary_conversation_id(self) -> str:
            return "shared__scope__ling"

    class DummyStorage:
        def resolve_scope_from_conversation_id(self, conversation_id: str) -> str:
            return "ling"

        def set_runtime_scope(self, scope: str) -> None:
            self.scope = scope

    executor = SimpleNamespace(
        context=DummyContext(),
        storage=DummyStorage(),
        qq_connection_resolver=SimpleNamespace(
            get_first_user_id=lambda: "private_123456789"
        ),
    )
    router = ConversationRouter(executor)
    target, transport_id, requested = await router.resolve_target_conversation(
        "qq", persona_filename="qq/Ling_QQ_Master.json"
    )
    assert target == "shared__persona__ling_qq_master"
    assert transport_id == "private_123456789"
    assert requested == "qq"


def _verify_role_routing() -> None:
    ling_ws = SimpleNamespace(client_id="qq_ling_private_123456789")
    aveline_ws = SimpleNamespace(client_id="qq_aveline_private_123456789")
    ling_message = _payload("ling")
    assert get_qq_target_role_id(ling_message) == "ling"
    assert qq_connection_accepts_message(ling_ws, ling_message)
    assert not qq_connection_accepts_message(aveline_ws, ling_message)


async def _verify_offline_replay_is_role_aware() -> None:
    class DummyQueue(OfflineQueueMixin):
        def __init__(self) -> None:
            self.offline_queue = defaultdict(lambda: deque(maxlen=50))
            self.offline_ttl = 24 * 3600
            self.sent: list[dict] = []

        async def send_with_retry(self, websocket, message: str) -> bool:
            self.sent.append(json.loads(message))
            return True

    user_id = "private_123456789"
    queue = DummyQueue()
    queue.store_offline_message(user_id, _payload("aveline", "A"))
    queue.store_offline_message(user_id, _payload("ling", "L"))
    ling_ws = SimpleNamespace(client_id="qq_ling_private_123456789")
    await queue._flush_offline_messages(user_id, ling_ws)

    assert [item["content"] for item in queue.sent] == ["L"]
    assert len(queue.offline_queue[user_id]) == 1
    assert queue.offline_queue[user_id][0][1]["content"] == "A"


async def _verify_failed_replay_is_retained() -> None:
    class FailingQueue(OfflineQueueMixin):
        def __init__(self) -> None:
            self.offline_queue = defaultdict(lambda: deque(maxlen=50))
            self.offline_ttl = 24 * 3600

        async def send_with_retry(self, websocket, message: str) -> bool:
            return False

    user_id = "private_123456789"
    queue = FailingQueue()
    queue.offline_queue[user_id].append((time.time(), _payload("ling", "保留")))
    ling_ws = SimpleNamespace(client_id="qq_ling_private_123456789")
    await queue._flush_offline_messages(user_id, ling_ws)
    assert len(queue.offline_queue[user_id]) == 1


async def _verify_ping_timeout() -> None:
    sentinel = object()
    with patch("clients.bots.qq.utils.transport_helpers.websockets.connect") as connect:
        connect.return_value = sentinel
        result = await _ws_connect("ws://127.0.0.1:8000/api/v1/ws")
    assert result is sentinel
    assert connect.call_args.kwargs["ping_interval"] == 20
    assert connect.call_args.kwargs["ping_timeout"] == 60


def _verify_winerror_log_normalization() -> None:
    error = OSError("信号灯超时时间已到")
    error.winerror = 121
    record = logging.LogRecord(
        name="websockets.server",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="data transfer failed",
        args=(),
        exc_info=(OSError, error, None),
    )
    assert RecoverableWebSocketDisconnectFilter().filter(record)
    assert record.levelno == logging.INFO
    assert record.exc_info is None
    assert "WinError 121" in record.getMessage()


def _verify_server_ping_timeout() -> None:
    main_text = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert "ws_ping_interval=30.0" in main_text
    assert "ws_ping_timeout=60.0" in main_text


async def main() -> int:
    await _verify_transport_id_preserved()
    _verify_role_routing()
    await _verify_offline_replay_is_role_aware()
    await _verify_failed_replay_is_retained()
    await _verify_ping_timeout()
    _verify_winerror_log_normalization()
    _verify_server_ping_timeout()
    print("PASS: WinError 121 与 Active Care 双 QQ 可靠投递验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
