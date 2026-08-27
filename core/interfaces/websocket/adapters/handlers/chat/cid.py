#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨平台 conversation_id 规范化

所有平台（QQ/Telegram/websocket/Android）使用同一 persona 时，
用 shared__persona__{slug} 作为 conversation_id，让聊天历史和记忆跨平台互通。
客户端若已直接传入 shared__persona__ 格式的 cid 则保留不动。
"""

from core.utils.logger import get_logger

logger = get_logger(__name__)


def normalize_shared_conversation_id(
    conversation_id: str, message: dict
) -> str:
    """把 conversation_id 规范化为跨平台共享 cid（失败则沿用原值）。"""
    try:
        cid_str = str(conversation_id or "").strip()
        if cid_str.startswith("shared__persona__"):
            return conversation_id

        # 优先用消息里携带的 persona_filename；没有则取后端 active persona
        effective_persona = str(message.get("persona_filename") or "").strip()
        if not effective_persona:
            try:
                from core.agents.chat_agent_components.persona_system import (
                    get_persona_manager,
                )

                effective_persona = str(
                    get_persona_manager().get_current_filename() or ""
                ).strip()
            except Exception as e:
                logger.debug(f"获取 active persona 失败: {e}")

        if effective_persona:
            from core.utils.data_paths import build_shared_persona_conversation_id

            new_cid = build_shared_persona_conversation_id(effective_persona)
            if new_cid and new_cid != cid_str:
                logger.info(
                    f"[WS Handler] 跨平台共享规范化 cid: {cid_str} -> {new_cid} "
                    f"(persona={effective_persona})"
                )
                return new_cid
    except Exception as e:
        logger.debug(f"conversation_id 共享规范化失败（继续用原值）: {e}")
    return conversation_id
