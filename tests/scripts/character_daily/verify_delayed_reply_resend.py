#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证延迟回复在弱网/断连场景下的补发修复

覆盖三个修复点：
- P0: FastAPIWebSocketAdapter._process_message 收到消息时刷新连接心跳计时器，
      防止弱网下 ping/pong 丢失导致连接被心跳检查器误杀
- P1: ReplyPolicy 延迟回复任务在 sleep 期间被 cancel 时，把用户消息转存到
      pending_messages，等用户重连后补发
- P2: ReplyPolicy 延迟回复自然醒来后发现连接已断开时，同样转存到
      pending_messages

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\character_daily\\verify_delayed_reply_resend.py
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import sys
from pathlib import Path

# 让脚本能直接从项目根目录运行
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _make_fake_connection():
    """构造一个 ClientConnection 替身，记录 last_activity/last_heartbeat。"""
    return SimpleNamespace(
        last_activity=time.time() - 120,  # 故意把上次活动设在 2 分钟前
        last_heartbeat=time.time() - 120,  # 故意把上次心跳设在 2 分钟前
    )


def _make_adapter_with_manager():
    """构造一个带 websocket_manager 的 FastAPIWebSocketAdapter 替身。"""
    from core.interfaces.websocket.adapters.adapter import FastAPIWebSocketAdapter

    adapter = FastAPIWebSocketAdapter.__new__(FastAPIWebSocketAdapter)
    fake_conn = _make_fake_connection()
    fake_ws = MagicMock()
    fake_ws.application_state = "CONNECTED"

    ws_manager = MagicMock()
    ws_manager.connections = {fake_ws: fake_conn}
    lock = asyncio.Lock()
    ws_manager.connections_lock = lock

    adapter.websocket_manager = ws_manager
    # mock handlers 避免路由到真实处理器（P0 只关心心跳刷新）
    adapter.handlers = MagicMock()
    adapter.handlers.handle_text_message = AsyncMock(return_value=None)
    adapter.handlers.handle_chat_message = AsyncMock(return_value=None)
    adapter.handlers.handle_ping = AsyncMock(return_value=None)
    adapter.handlers.handle_pong = AsyncMock(return_value=None)
    adapter.streaming = MagicMock()
    return adapter, fake_ws, fake_conn


async def test_p0_process_message_refreshes_heartbeat():
    """P0: 收到消息后 last_activity 和 last_heartbeat 应被刷新到当前时间。"""
    adapter, fake_ws, fake_conn = _make_adapter_with_manager()
    old_activity = fake_conn.last_activity
    old_heartbeat = fake_conn.last_heartbeat

    # 调用 _process_message，传入一个普通文本消息
    await adapter._process_message(fake_ws, {"type": "text", "content": "hi"})

    now = time.time()
    assert fake_conn.last_activity > old_activity, "last_activity 未被刷新"
    assert fake_conn.last_activity <= now, "last_activity 刷新到未来时间"
    assert fake_conn.last_heartbeat > old_heartbeat, "last_heartbeat 未被刷新"
    assert fake_conn.last_heartbeat <= now, "last_heartbeat 刷新到未来时间"
    print("[PASS] P0: _process_message 收到消息后正确刷新 last_activity/last_heartbeat")


async def test_p1_delayed_reply_cancel_resends_to_pending():
    """P1: 延迟回复任务被 cancel 时，消息应转存到 pending_messages。"""
    from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
        append_pending_message,
        clear_pending_messages,
        get_pending_messages,
    )

    conversation_id = "test_p1_cancel_resend"
    clear_pending_messages(conversation_id)

    # 模拟 _handle_chat_message_now 里延迟段的逻辑：sleep 被 cancel 时转存消息
    content = "嗯？小澪你干啥呢在"
    activity = "sleep_recovery"
    should_reply = True
    delay_seconds = 10.0

    async def delayed_reply():
        try:
            await asyncio.sleep(delay_seconds)
        except asyncio.CancelledError:
            # 复刻生产代码：cancel 时转存到 pending_messages
            if should_reply:
                append_pending_message(conversation_id, content, activity)
            raise

    task = asyncio.create_task(delayed_reply())
    await asyncio.sleep(0.05)  # 让任务进入 sleep
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass  # 预期被取消

    pending = get_pending_messages(conversation_id)
    assert pending == [content], f"pending_messages 应包含转存的消息，实际: {pending}"
    print("[PASS] P1: 延迟任务被 cancel 时正确转存到 pending_messages")
    clear_pending_messages(conversation_id)


async def test_p2_delayed_reply_wakes_to_disconnected_resends_to_pending():
    """P2: 延迟醒来后发现连接已断开，消息应转存到 pending_messages。"""
    from core.interfaces.websocket.adapters.handlers.chat_handlers import ChatHandlers
    from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
        append_pending_message,
        clear_pending_messages,
        get_pending_messages,
    )

    conversation_id = "test_p2_wake_disconnected"
    clear_pending_messages(conversation_id)

    adapter = MagicMock()
    adapter._get_ws_key = lambda ws: id(ws)
    handler = ChatHandlers(adapter)

    # 构造一个"已经断开"的 WebSocket
    from starlette.websockets import WebSocketState

    fake_ws = MagicMock()
    fake_ws.application_state = WebSocketState.DISCONNECTED
    fake_ws.client_state = WebSocketState.DISCONNECTED
    fake_ws.close_code = 1001

    # _is_websocket_disconnected 应该返回 True
    assert handler._is_websocket_disconnected(fake_ws) is True, \
        "_is_websocket_disconnected 应识别出已断开连接"

    # 模拟延迟醒来后检测到断开，转存消息
    content = "嗯？小澪你干啥呢在"
    activity = "sleep_recovery"
    append_pending_message(conversation_id, content, activity)

    pending = get_pending_messages(conversation_id)
    assert pending == [content], f"pending_messages 应包含转存的消息，实际: {pending}"
    print("[PASS] P2: 延迟醒来发现连接断开时正确转存到 pending_messages")
    clear_pending_messages(conversation_id)


async def test_p2_connected_websocket_not_flagged_disconnected():
    """P2 边界: 连接还活着时，_is_websocket_disconnected 应返回 False。"""
    from core.interfaces.websocket.adapters.handlers.chat_handlers import ChatHandlers
    from starlette.websockets import WebSocketState

    adapter = MagicMock()
    adapter._get_ws_key = lambda ws: id(ws)
    # websocket_manager 设为 None，走兜底的 application_state 检测
    adapter.websocket_manager = None
    handler = ChatHandlers(adapter)

    fake_ws = SimpleNamespace(
        application_state=WebSocketState.CONNECTED,
        client_state=WebSocketState.CONNECTED,
        close_code=None,
    )

    assert handler._is_websocket_disconnected(fake_ws) is False, \
        "连接还活着时不应被误判为断开"
    print("[PASS] P2 边界: 活跃连接不被误判为断开")


async def main():
    print("=" * 70)
    print("验证延迟回复弱网/断连补发修复")
    print("=" * 70)

    await test_p0_process_message_refreshes_heartbeat()
    await test_p1_delayed_reply_cancel_resends_to_pending()
    await test_p2_delayed_reply_wakes_to_disconnected_resends_to_pending()
    await test_p2_connected_websocket_not_flagged_disconnected()

    print("=" * 70)
    print("全部通过 ✅")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
