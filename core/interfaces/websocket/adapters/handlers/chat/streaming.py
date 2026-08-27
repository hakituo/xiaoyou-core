#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流式回复任务

把聊天/问候的流式输出封装成独立任务，含超时与异常兜底。
"""

import asyncio
from typing import Any, Dict

from core.utils.logger import get_logger

logger = get_logger(__name__)

_CHAT_TASK_TIMEOUT = 180


async def run_chat_stream_task(
    adapter,
    *,
    websocket,
    streaming_handler,
    content: str,
    msg_id: str,
    conversation_id: str,
    request_id: str,
    model: str,
    persona_filename: str,
    service_dynamic_context: str,
    api_key_env: str,
    user_name,
):
    """执行一次流式聊天回复，注册到 adapter 的任务表并等待完成。"""
    content_preview = (
        str(content)[:50] if not isinstance(content, list) else "[多模态消息]"
    )

    async def _handle_chat_task():
        try:
            from core.core_engine.service_singletons import get_aveline_service

            svc = get_aveline_service()
            if svc is None:
                raise RuntimeError("AvelineService could not be initialized")

            try:
                await asyncio.wait_for(
                    streaming_handler.handle_stream(
                        websocket=websocket,
                        svc=svc,
                        content=content,
                        msg_id=msg_id,
                        conversation_id=conversation_id,
                        request_id=request_id,
                        model=model,
                        user_name=user_name,
                        persona_filename=persona_filename,
                        service_dynamic_context=service_dynamic_context,
                        api_key_env=api_key_env,
                        platform=str(getattr(websocket, "platform", "") or "").strip().lower()
                        or None,
                    ),
                    timeout=_CHAT_TASK_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.error(
                    f"Chat task timed out ({_CHAT_TASK_TIMEOUT}s) for "
                    f"cid={conversation_id}, msg={content_preview}"
                )
                await websocket.send_json(
                    {
                        "type": "message",
                        "subtype": "response",
                        "content": "响应超时，请重试",
                        "message_id": msg_id,
                        "timestamp": time.time(),
                        "conversation_id": conversation_id,
                        "request_id": request_id,
                    }
                )
        except asyncio.CancelledError:
            logger.info(f"Chat task cancelled for cid={conversation_id}")
        except Exception as e:
            logger.error(f"Chat task error: {e}")
            try:
                await websocket.send_json(
                    {
                        "type": "message",
                        "subtype": "response",
                        "content": f"处理消息时出错: {e}",
                        "message_id": msg_id,
                        "timestamp": time.time(),
                        "conversation_id": conversation_id,
                        "request_id": request_id,
                    }
                )
            except Exception:
                pass

    task = asyncio.create_task(_handle_chat_task())
    await adapter._register_chat_task(websocket, msg_id, task)


async def run_greeting_stream_task(
    adapter,
    *,
    websocket,
    msg_id: str,
    conversation_id: str,
    request_id: str,
    user_name,
):
    """执行一次流式问候，注册到 adapter 的任务表并等待完成。"""
    async def _handle_greeting_task():
        try:
            from core.core_engine.service_singletons import get_aveline_service

            svc = get_aveline_service()
            if svc is None:
                raise RuntimeError("AvelineService could not be initialized")

            # 使用 generate_proactive_message 生成流式问候
            async for chunk in svc.generate_proactive_message(
                conversation_id=conversation_id,
                save_to_history=True,
                user_name=user_name,
            ):
                if isinstance(chunk, dict):
                    chunk["message_id"] = msg_id
                    chunk["conversation_id"] = conversation_id
                    chunk["request_id"] = request_id
                    await websocket.send_json(chunk)

        except Exception as e:
            logger.error(f"Greeting task error: {e}")
            await websocket.send_json(
                {
                    "type": "message",
                    "subtype": "response",
                    "content": f"生成问候时出错: {e}",
                    "message_id": msg_id,
                    "timestamp": time.time(),
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                }
            )

    task = asyncio.create_task(_handle_greeting_task())
    await adapter._register_chat_task(websocket, msg_id, task)
