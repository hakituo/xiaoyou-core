#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聊天上下文辅助

- 对话隔离（当前已禁用，始终返回原始 cid）
- 双角色私聊上下文：构建 QQ 双角色 peer/sender 上下文块
"""

from core.utils.logger import get_logger

logger = get_logger(__name__)


def apply_conversation_isolation(
    websocket, conversation_id: str, incoming_model_str: str
) -> str:
    """应用对话隔离（已禁用）- 始终返回原始 conversation_id。

    Note: 移除 local/_local 分裂逻辑，所有模型共享同一会话历史。
    """
    return conversation_id


def build_peer_role_context(websocket, message: dict, conversation_id: str) -> str:
    """构建双角色私聊动态上下文（QQ peer / sender identity）。"""
    service_dynamic_context = ""

    peer_role_context = message.get("peer_role_context")
    if isinstance(peer_role_context, dict) and peer_role_context:
        try:
            from core.agents.chat_agent_components.persona_system.prompt import (
                build_qq_peer_role_context,
            )

            def _get_peer_recent_events(cid: str) -> str:
                try:
                    from core.services.dual_role.social_events import (
                        get_social_event_engine,
                    )

                    engine = get_social_event_engine()
                    return engine.build_recent_events_context(cid, max_items=3)
                except Exception:
                    return ""

            recent_events = _get_peer_recent_events(conversation_id)
            if recent_events:
                peer_role_context["recent_events"] = recent_events

            service_dynamic_context = build_qq_peer_role_context(peer_role_context)
        except Exception as e:
            logger.warning(f"构建QQ双角色私聊上下文失败: {e}")

    sender_identity_context = message.get("sender_identity_context")
    if isinstance(sender_identity_context, dict) and sender_identity_context:
        sender_identity = str(
            sender_identity_context.get("sender_identity") or ""
        ).strip()
        if sender_identity:
            identity_block = f"【说话者身份】{sender_identity}"
            if service_dynamic_context:
                if "【双角色私聊模式】" in service_dynamic_context:
                    service_dynamic_context = service_dynamic_context.replace(
                        "【双角色私聊模式】",
                        f"{identity_block}\n\n【双角色私聊模式】",
                        1,
                    )
                else:
                    service_dynamic_context = (
                        f"{identity_block}\n\n{service_dynamic_context}"
                    )
            else:
                service_dynamic_context = identity_block

    return service_dynamic_context
