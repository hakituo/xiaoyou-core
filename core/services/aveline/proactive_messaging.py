#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主动消息模块。

负责主动消息的生成、分发与历史追加：
- generate_proactive_message：生成主动问候消息（流式）
- dispatch_proactive_message：通过 WebSocket / QQ 官方机器人分发主动消息
- _dispatch_to_qq_official：通过 QQOfficialAdapter 发送主动消息
- append_proactive_message：将主动消息追加到对话历史（WeightedMemory + ChatHistoryStore）

所有函数均为模块级函数，第一参数为 `service`（AvelineService 实例），
与 stream_orchestrator.py 风格保持一致。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, AsyncGenerator, Dict, Optional

from core.utils.time_utils import (
    get_current_time_str,
    get_time_period,
)
from core.utils.logger import get_logger

logger = get_logger("AVELINE_SERVICE")


async def generate_proactive_message(
    service: Any,
    conversation_id: Optional[str] = None,
    save_to_history: bool = False,
    user_name: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """生成主动问候消息 - 流式输出版本"""
    try:
        # 检查是否配置了云端模型
        is_cloud_model = False
        try:
            provider = (service.settings or {}).model.llm.provider if service.settings else None
            is_cloud_model = provider in [
                "deepseek",
                "siliconflow",
                "dashscope",
                "openai",
                "aveline",
            ]
        except Exception:
            pass

        # 如果是云端模型，生成更智能的问候语
        if is_cloud_model:
            time_period = get_time_period()
            system_prompt = f"现在是{time_period}。请根据当前时间生成一句简短、温暖、自然的问候语。不要太正式，要像朋友之间的问候。"

            cid = str(conversation_id).strip() if conversation_id else ""
            if not cid:
                cid = "system_greeting"

            # 使用stream_conversation来生成greeting
            async for chunk in service.stream_conversation(
                user_input="[SYSTEM_GREETING]",  # 特殊标记，表示这是系统问候
                conversation_id=cid,
                request_id=f"greeting_{cid}_{int(time.time())}",
                message_id=f"greeting_{int(time.time())}",
                save_history=save_to_history,
                max_tokens=60,
                temperature=0.9,  # 提高温度让问候更自然
                user_name=user_name,
                system_prompt=system_prompt,
            ):
                # 直接转发所有chunk
                yield chunk
        else:
            # 本地模型：使用简单的默认问候，避免加载模型
            time_period = get_time_period()
            greetings = [
                f"嗨，{time_period}好~",
                f"{time_period}好呀！",
                f"你好，现在是{get_current_time_str('%H:%M')}。",
                f"{time_period}好！有什么我能帮你的吗？",
            ]
            import random

            default_greeting = random.choice(greetings)

            yield {
                "type": "message",
                "subtype": "response_chunk",
                "content": default_greeting,
                "timestamp": time.time(),
            }
            yield {
                "type": "message",
                "subtype": "response_done",
                "timestamp": time.time(),
            }

    except Exception as e:
        logger.error(f"生成问候语失败: {e}", exc_info=True)
        friendly = service._friendly_stream_error_message(e)
        yield {
            "type": "error",
            "message": friendly,
            "timestamp": time.time(),
        }
        default_greeting = f"你好，现在是{get_current_time_str('%H:%M')}。"
        yield {
            "type": "message",
            "subtype": "response_chunk",
            "content": default_greeting,
            "timestamp": time.time(),
        }
        yield {
            "type": "message",
            "subtype": "response_done",
            "timestamp": time.time(),
        }


async def dispatch_proactive_message(
    service: Any,
    target_conversation_id: str,
    content: str,
    thought: str = "",
    message_type: str = "text",
    tts_text: str = "",
    client_type: str = "",
    requested_client_type: str = "",
    hardware_payload: Optional[Dict[str, Any]] = None,
    original_primary_conversation_id: str = "",
    extra_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    分发主动消息：通过 WebSocket 推送到前端，或通过 QQOfficialAdapter 发送到 QQ 官方机器人。
    返回 {"delivered": True/False} 表示是否成功送达。
    """
    delivered = False
    try:
        # 检查是否是 QQ 官方机器人
        cid_str = str(target_conversation_id)
        if client_type == "qq_official" or "qq_official" in cid_str:
            delivered = await service._dispatch_to_qq_official(
                target_conversation_id, content, client_type
            )
            if delivered:
                await service.append_proactive_message(
                    conversation_id=target_conversation_id,
                    content=content,
                    thought=thought,
                )
                logger.info(f"Active Care: 已通过QQ官方机器人发送消息到 {target_conversation_id}")
            return {"delivered": delivered}

        # 原有的 WebSocket 分发逻辑
        from core.interfaces.websocket.websocket_manager import get_websocket_manager

        ws_manager = get_websocket_manager()
        if ws_manager is None:
            logger.warning("dispatch_proactive_message: WebSocketManager 不可用")
            return {"delivered": False}

        payload = {
            "type": "proactive_message",
            "subtype": "active_care",
            "content": content,
            "conversation_id": target_conversation_id,
            "thought": thought,
            "message_type": message_type,
            "tts_text": tts_text or content,
            "client_type": client_type,
            "requested_client_type": requested_client_type,
            "hardware_payload": hardware_payload or {},
            "original_primary_conversation_id": original_primary_conversation_id,
            "is_proactive": True,
            "timestamp": time.time(),
            "message_id": str(uuid.uuid4()),
        }

        # 合并 extra_payload（如 target_qq_id）
        if extra_payload and isinstance(extra_payload, dict):
            payload.update(extra_payload)

        # 确定广播目标 user_id：优先用主人原始 cid（private_xxx），
        # 确保消息发到主人的所有 QQ 角色连接，再由 receiver 按 persona 路由；
        # original 为空时回退到 target（peer_chat 等场景需调用方传入 original）
        broadcast_user_id = str(
            original_primary_conversation_id or target_conversation_id or ""
        ).strip()

        delivered = await ws_manager.broadcast(
            payload, user_id=broadcast_user_id
        )

        # [DEBUG] 诊断 peer script 历史保存问题
        is_peer_script = bool(payload.get("is_peer_script", False))
        if is_peer_script:
            logger.info(
                "Active Care [DEBUG] peer_script delivered=%s, target_cid=%s, broadcast_uid=%s",
                delivered, target_conversation_id, broadcast_user_id,
            )

        if delivered:
            # 透传 extra_payload 里的 is_peer_script 和 peer_speaker（说话者）
            _ep = extra_payload if isinstance(extra_payload, dict) else {}
            _is_ps = bool(_ep.get("is_peer_script"))
            _speaker = str(_ep.get("peer_speaker") or "").strip()
            # 互聊消息存到独立的 peer conversation，不污染主人的聊天记录
            save_cid = target_conversation_id
            if _is_ps:
                # 从 extra_payload 提取 role_id，构建 peer_{role_id} conversation
                _role_id = str(_ep.get("role_id") or "").strip()
                if _role_id:
                    save_cid = f"peer_{_role_id}"
            await service.append_proactive_message(
                conversation_id=save_cid,
                content=content,
                thought=thought,
                is_peer_script=_is_ps,
                peer_speaker=_speaker,
            )
            user_online = ws_manager.is_user_online(broadcast_user_id)
            if user_online:
                logger.info(
                    f"主动消息已实时送达: conversation={target_conversation_id}"
                )
            else:
                logger.info(
                    f"主动消息已存入离线队列（用户不在线）: conversation={target_conversation_id}"
                )
        else:
            logger.warning(
                f"主动消息分发失败（无活跃连接且无法存储）: conversation={target_conversation_id}"
            )

    except Exception as e:
        logger.error(f"dispatch_proactive_message 异常: {e}", exc_info=True)

    return {"delivered": bool(delivered)}


async def _dispatch_to_qq_official(
    service: Any, target_conversation_id: str, content: str, client_type: str
) -> bool:
    """通过 QQOfficialAdapter 发送主动消息"""
    try:
        from clients.bots.qq_official.adapter import QQOfficialAdapter

        # 从 target_conversation_id 中提取用户ID和persona
        target_user_id = ""
        target_persona = ""
        if "__persona__" in target_conversation_id:
            parts = target_conversation_id.split("__persona__", 1)
            target_user_id = parts[0].replace("private_", "")
            target_persona = parts[1]
        elif target_conversation_id.startswith("private_"):
            target_user_id = target_conversation_id.replace("private_", "")

        # 获取所有活跃的官方机器人实例
        instances = QQOfficialAdapter.get_active_instances()
        if not instances:
            logger.warning("dispatch_to_qq_official: 无活跃的QQ官方机器人实例")
            return False

        # 根据persona_filename选择对应的机器人
        matched_adapter = None
        for inst_info in instances:
            inst_persona = str(inst_info.get("persona_filename") or "").strip()
            role_id = str(inst_info.get("role_id") or "").strip()

            # 如果target_persona包含在inst_persona中，或者role_id匹配
            if target_persona and (target_persona in inst_persona or role_id in target_persona):
                for key, adapter in QQOfficialAdapter._instances.items():
                    if adapter.cfg.role_id == role_id:
                        matched_adapter = adapter
                        break
                if matched_adapter:
                    break

        # 如果没有匹配到，使用第一个可用的实例
        if not matched_adapter:
            for inst_info in instances:
                role_id = str(inst_info.get("role_id") or "").strip()
                for key, adapter in QQOfficialAdapter._instances.items():
                    if adapter.cfg.role_id == role_id:
                        matched_adapter = adapter
                        break
                if matched_adapter:
                    break

        if matched_adapter:
            success = await matched_adapter.send_proactive_message(
                content, target_user_id
            )
            if success:
                logger.info(f"Active Care: 已通过QQ官方机器人 {matched_adapter.cfg.role_name} 发送消息")
                return True

        return False
    except Exception as e:
        logger.error(f"_dispatch_to_qq_official 异常: {e}", exc_info=True)
        return False


async def append_proactive_message(
    service: Any,
    conversation_id: str,
    content: str,
    thought: str = "",
    is_peer_script: bool = False,
    peer_speaker: str = "",
):
    """
    Append a proactive message (from Active Care) to conversation history.
    This ensures the message is visible in the chat interface history.
    """
    try:
        # [OPTIMIZATION] Unified Memory System
        # Directly add to WeightedMemoryManager with specific metadata for Active Care
        from memory.weighted_memory_manager import get_weighted_memory_manager
        memory_manager = get_weighted_memory_manager(conversation_id)
        if memory_manager:
            thought_text = str(thought or "").strip()
            # 双角色剧本消息单独分类，让主聊天能区分"角色间私聊"与"角色回复主人"
            if is_peer_script:
                memory_manager.add_memory(
                    content=content,
                    role="assistant",
                    source="peer_chat",
                    category="peer_chat",  # 角色间私聊，区别于普通主动关怀
                    scopes=["local", "cloud"],
                    metadata={
                        "conversation_id": conversation_id,
                        "is_proactive": True,
                        "is_peer_script": True,  # 明确标记：这是角色间的私聊剧本
                        "type": "peer_script",
                        "original_source": "peer_chat",
                        "peer_speaker": peer_speaker,  # 真正的说话者（content 不含前缀，靠此字段区分）
                        "thought": thought_text,
                    },
                )
            else:
                memory_manager.add_memory(
                    content=content,
                    role="assistant",
                    source="active_care",
                    category="chat",  # 普通主动关怀，get_history 会包含
                    scopes=["local", "cloud"],
                    metadata={
                        "conversation_id": conversation_id,
                        "is_proactive": True,
                        "type": "proactive",
                        "original_source": "active_care",
                        "thought": thought_text,
                    },
                )
            if thought_text:
                memory_manager.add_memory(
                    content=thought_text,
                    role="system",
                    is_important=False,
                    source="active_care",
                    category="thinking",
                    scopes=["local"],
                    metadata={
                        "conversation_id": conversation_id,
                        "hidden": True,
                        "is_proactive_thought": True,
                        "original_source": "active_care",
                    },
                )
            logger.info(
                f"Active Care message added to WeightedMemoryManager for {conversation_id}"
            )

        # 同步写入 ChatHistoryStore，确保重启后主动消息不丢失
        # 这样 backfill 机制能恢复主动消息，主 LLM 能看到完整上下文
        try:
            import uuid
            from core.services.chat_history_store import get_chat_history_store
            store = get_chat_history_store()

            # 【思考可见性】将 thought 以内心独白形式拼入 content，
            # 让主聊天模型在后续轮次能看到自己当时的动机，避免逻辑断裂
            chat_history_content = content
            thought_text = str(thought or "").strip()
            if thought_text:
                chat_history_content = f"（心想：{thought_text}）\n\n{content}"

            def _write_proactive_event():
                store.append_event(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=chat_history_content,
                    message_id=uuid.uuid4().hex,
                    event_type="proactive_message",
                    metadata={
                        "source": "active_care",
                        "is_proactive": True,
                        "type": "proactive",
                        "has_thought": bool(thought_text),
                    },
                )

            await asyncio.to_thread(_write_proactive_event)
        except Exception as e:
            logger.warning(f"写入 ChatHistoryStore 失败: {e}")

        logger.info(
            f"Successfully appended proactive message to conversation {conversation_id}"
        )
    except Exception as e:
        logger.error(f"Failed to append proactive message: {e}")
