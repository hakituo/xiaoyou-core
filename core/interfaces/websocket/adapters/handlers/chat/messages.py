#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
消息规范化

把原始 WS 消息规范成内部 dict（文本消息 / 问候消息的协议层处理）。
"""

import time

from fastapi import WebSocket


async def handle_text_message(websocket: WebSocket, message: dict) -> dict:
    """处理文本消息，返回标准化后的消息。"""
    content = message.get("text") or message.get("content") or ""

    # 如果是列表（多模态），保持原样，否则转为字符串
    if isinstance(content, list):
        pass
    else:
        content = str(content).strip()

    return {
        "type": "message",
        "content": content,
        "message_id": message.get("message_id") or str(int(time.time() * 1000)),
        "conversation_id": message.get("conversation_id"),
        "request_id": message.get("request_id"),
        "model": message.get("model"),
        "persona_filename": message.get("persona_filename"),
        "peer_role_context": message.get("peer_role_context"),
        "sender_identity_context": message.get("sender_identity_context"),
        "skip_merge_wait": bool(message.get("skip_merge_wait")),
    }
