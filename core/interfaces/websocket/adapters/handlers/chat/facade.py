#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聊天处理器门面（ChatHandlers）

把原先 1000+ 行的 chat_handlers.py 按职责拆到同包各模块后，本类只做编排：
接收 WS 消息 -> 规范化 -> 合并 -> 回复策略 -> 流式输出。
所有具体逻辑分布在 `chat/` 子包内。
"""

import time

from fastapi import WebSocket

from core.interfaces.websocket.adapters.handlers.chat.active_care import (
    run_active_care_update,
)
from core.interfaces.websocket.adapters.handlers.chat.cid import (
    normalize_shared_conversation_id,
)
from core.interfaces.websocket.adapters.handlers.chat.connection import (
    is_websocket_disconnected,
)
from core.interfaces.websocket.adapters.handlers.chat.context import (
    apply_conversation_isolation,
    build_peer_role_context,
)
from core.interfaces.websocket.adapters.handlers.chat.merge import ChatMessageMerger
from core.interfaces.websocket.adapters.handlers.chat.messages import handle_text_message
from core.interfaces.websocket.adapters.handlers.chat.model_pref import (
    apply_model_preference,
)
from core.interfaces.websocket.adapters.handlers.chat.prefetch import (
    schedule_prefetch_embedding,
)
from core.interfaces.websocket.adapters.handlers.chat.reply_policy import (
    apply_reply_policy,
)
from core.interfaces.websocket.adapters.handlers.chat.streaming import (
    run_chat_stream_task,
    run_greeting_stream_task,
)
from core.utils.logger import get_logger

logger = get_logger(__name__)


class ChatHandlers:
    """聊天相关的消息处理器（门面 / 编排层）"""

    def __init__(self, adapter):
        self.adapter = adapter
        self._merger = ChatMessageMerger(adapter)

    # ==================================================================
    # 公共接口（供 adapter.py 调用，签名保持不变）
    # ==================================================================
    async def cleanup_websocket(self, websocket: WebSocket):
        await self._merger.cleanup_websocket(websocket)

    async def handle_text_message(self, websocket: WebSocket, message: dict) -> dict:
        return await handle_text_message(websocket, message)

    async def handle_chat_message(
        self, websocket: WebSocket, message: dict, streaming_handler
    ):
        if self._should_skip_merge_wait(websocket, message):
            await self._handle_chat_message_now(websocket, message, streaming_handler)
            return
        wait_seconds = self._get_merge_wait_seconds()
        await self._merger.enqueue(
            websocket,
            message,
            streaming_handler,
            self._handle_chat_message_now,
            wait_seconds=wait_seconds,
        )

    async def handle_greeting_message(
        self, websocket: WebSocket, message: dict, streaming_handler
    ):
        """处理问候消息（使用流式输出）。"""
        msg_id = message.get("message_id") or f"greeting_{int(time.time() * 1000)}"
        conversation_id = (
            message.get("conversation_id")
            or getattr(websocket, "user_id", None)
            or "default"
        )
        request_id = message.get("request_id") or msg_id
        user_id = getattr(websocket, "user_id", "unknown")

        logger.info(
            f"[{time.time() * 1000:.0f}ms] Backend generating greeting for {user_id}"
        )

        await websocket.send_json(
            {
                "type": "message",
                "subtype": "acknowledged",
                "message_id": msg_id,
                "timestamp": time.time(),
                "conversation_id": conversation_id,
                "request_id": request_id,
            }
        )

        await run_greeting_stream_task(
            self.adapter,
            websocket=websocket,
            msg_id=msg_id,
            conversation_id=conversation_id,
            request_id=request_id,
            user_name=getattr(websocket, "user_name", None),
        )

    # ==================================================================
    # 合并相关便捷方法（委托给 merger，保留测试 monkeypatch 兼容点）
    # ==================================================================
    def _get_merge_wait_seconds(self) -> float:
        return self._merger._get_merge_wait_seconds()

    def _should_skip_merge_wait(self, websocket: WebSocket, message: dict) -> bool:
        return self._merger._should_skip_merge_wait(websocket, message)

    # ==================================================================
    # 核心聊天处理（编排各子模块）
    # ==================================================================
    async def _handle_chat_message_now(
        self, websocket: WebSocket, message: dict, streaming_handler
    ):
        content = message.get("content") or ""
        if not isinstance(content, list):
            content = str(content).strip()

        msg_id = message.get("message_id") or str(int(time.time() * 1000))
        conversation_id = (
            message.get("conversation_id")
            or getattr(websocket, "user_id", None)
            or "default"
        )
        # 跨平台共享 cid 规范化
        conversation_id = normalize_shared_conversation_id(conversation_id, message)

        model = message.get("model") or ""
        incoming_model_str = str(model).lower()
        persona_filename = message.get("persona_filename") or ""
        api_key_env = message.get("api_key_env") or ""
        logger.info(
            f"[WS Handler] conversation_id={conversation_id}, "
            f"persona_filename={persona_filename!r}, model={model!r}, api_key_env={api_key_env!r}"
        )

        # 双角色私聊上下文（peer/sender identity）
        service_dynamic_context = build_peer_role_context(
            websocket, message, conversation_id
        )
        # 对话隔离（当前始终返回原值，兼容历史调用）
        conversation_id = apply_conversation_isolation(
            websocket, conversation_id, incoming_model_str
        )
        # 强制模型偏好
        model = apply_model_preference(
            websocket, model, incoming_model_str, persona_filename
        )

        request_id = message.get("request_id") or msg_id
        user_id = getattr(websocket, "user_id", "unknown")
        content_preview = (
            str(content)[:50] if not isinstance(content, list) else "[多模态消息]"
        )
        logger.info(
            f"[{time.time() * 1000:.0f}ms] Backend starting processing for "
            f"user_id={user_id}, conversation_id={conversation_id}, msg: {content_preview}"
        )

        await websocket.send_json(
            {
                "type": "message",
                "subtype": "acknowledged",
                "message_id": msg_id,
                "timestamp": time.time(),
                "conversation_id": conversation_id,
                "request_id": request_id,
            }
        )

        if not content:
            await websocket.send_json(
                {
                    "type": "message",
                    "subtype": "response",
                    "content": "请提供有效的输入内容。",
                    "message_id": msg_id,
                    "timestamp": time.time(),
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                }
            )
            return

        # Active Care：消息缓存 + 实时晚安/早安意图检测
        await run_active_care_update(content, conversation_id)
        # 后台预取查询嵌入向量（不阻塞）
        schedule_prefetch_embedding(content_preview, conversation_id)

        # 被动回复策略：延迟 / 静默累积 / 睡眠恢复
        content, service_dynamic_context, should_return = await apply_reply_policy(
            self.adapter,
            conversation_id=conversation_id,
            content=content,
            persona_filename=persona_filename,
            service_dynamic_context=service_dynamic_context,
            websocket=websocket,
            is_disconnected=lambda ws: is_websocket_disconnected(self.adapter, ws),
        )
        if should_return:
            return

        await run_chat_stream_task(
            self.adapter,
            websocket=websocket,
            streaming_handler=streaming_handler,
            content=content,
            msg_id=msg_id,
            conversation_id=conversation_id,
            request_id=request_id,
            model=model,
            persona_filename=persona_filename,
            service_dynamic_context=service_dynamic_context,
            api_key_env=api_key_env,
            user_name=getattr(websocket, "user_name", None),
        )
