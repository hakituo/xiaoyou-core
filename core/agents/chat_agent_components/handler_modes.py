"""ChatAgent 非流式 handler：模式 / 长度 / 角色状态 → 影响指令。

从 ``core/agents/chat_agent_components/handler.py`` 拆出，本模块负责：
- ``_resolve_sensitive_mode``：隐私模式、本地模型、敏感话题关键词三重判定
- ``_resolve_reply_limits``：按用户消息长度决定软性回复字数上限
- ``_build_affect_instruction``：角色生命状态 + 情绪 → 对话影响指令

⚠️ 模块级 patch 语义：测试会按名替换门面模块的 ``get_life_simulation_service``，
因此该名字必须在**调用期**从门面模块取名，不能顶层 from-import 固化。
"""
from __future__ import annotations

from typing import Any, Optional

from core.agents.chat_agent_components.stream_utils import StreamContextBuilder

# 循环引用仅为保留「按门面模块打补丁」的语义，调用期才取属性
from core.agents.chat_agent_components import handler as _facade
from core.utils.logger import get_logger

logger = get_logger("ChatAgent")


async def _resolve_sensitive_mode(agent: Any, user_id: str, message: str) -> bool:
    """判定当前请求是否处于敏感（隐私 / 本地模型 / 显式指令）模式。"""
    is_sensitive_mode = False
    try:
        from core.managers.preference_manager import get_preference_manager
        from config.integrated_config import get_settings

        prefs = get_preference_manager()
        if prefs.get_mode() == "privacy":
            is_sensitive_mode = True

        # Rule: Local model -> Sensitive mode automatically
        settings = get_settings()
        provider = settings.model.llm.provider
        # Check provider or if using local text path
        if provider == "local" or (provider == "custom" and not settings.model.llm.base_url):
             # Double check if it's actually a local GGUF or similar
             if settings.model.text_path and (settings.model.text_path.endswith(".gguf") or "local" in str(settings.model.text_path).lower()):
                 is_sensitive_mode = True
                 logger.info("Local model detected, auto-enabling SENSITIVE/NSFW mode.")
             elif provider == "local":
                 is_sensitive_mode = True
                 logger.info("Local provider detected, auto-enabling SENSITIVE/NSFW mode.")

    except Exception as e:
        logger.warning(f"Failed to check mode/settings: {e}")

    cid = str(user_id or "").strip() or "default"
    if cid and not is_sensitive_mode:
        try:
            if hasattr(agent, "get_memory_manager_async"):
                mm = await agent.get_memory_manager_async(cid)
            else:
                mm = agent._get_memory_manager(cid)
            if hasattr(mm, "get_memories_by_topic"):
                mode_memories = mm.get_memories_by_topic(
                    "sensitive_mode_control", limit=8
                )
                from core.agents.chat_agent_components.persona_system.prompt.mode_control import (
                    resolve_memory_mode_toggle,
                )

                if resolve_memory_mode_toggle(mode_memories) is True:
                    is_sensitive_mode = True
        except Exception:
            pass

    msg_lower = str(message or "").lower()
    if not is_sensitive_mode:
        if (
            "/sensitive" in msg_lower
            or "[sensitive]" in msg_lower
            or "开启sensitive" in msg_lower
            or "/private" in msg_lower
            or "[private]" in msg_lower
            or "/nsfw" in msg_lower
            or "[nsfw]" in msg_lower
            or "开启nsfw" in msg_lower
        ):
            is_sensitive_mode = True

    return is_sensitive_mode


def _resolve_reply_limits(mode: str, message: str) -> Optional[int]:
    """按用户消息长度返回软性回复字数上限（None 表示不限制）。"""
    wants_long = False
    if message:
        wants_long = StreamContextBuilder.detect_wants_long(message)

    soft_reply_char_limit = None
    if mode != "study" and (not wants_long):
        msg_len = len((message or "").strip())
        if msg_len <= 6:
            soft_reply_char_limit = 80
        elif msg_len <= 12:
            soft_reply_char_limit = 120
        elif msg_len <= 24:
            soft_reply_char_limit = 180
    return soft_reply_char_limit


def _build_affect_instruction(
    agent: Any,
    user_id: str,
    soft_reply_char_limit: Optional[int],
    max_tokens: Optional[int],
) -> str:
    """读取角色生命状态并生成对话影响指令（失败时返回空串）。"""
    life_level = 1
    mood_score = 80.0
    shyness_score = 0.0
    immune_damage = 0.0
    is_sick = False
    intimacy_level = 0.1
    try:
        life_service = _facade.get_life_simulation_service()
        try:
            life_service.update_interaction(xp_gain=10)
        except TypeError:
            life_service.update_interaction()

        life_state = getattr(life_service, "life_stats", {}) or {}
        mood_score = float(life_state.get("mood_score", mood_score) or mood_score)
        shyness_score = float(
            life_state.get("shyness_score", shyness_score) or shyness_score
        )
        immune_damage = float(
            life_state.get("immune_damage", immune_damage) or immune_damage
        )
        is_sick = bool(life_state.get("is_sick", False))
        life_level = int(life_state.get("level", life_level) or life_level)

        if getattr(agent, "dependency_manager", None):
            try:
                intimacy_level = float(
                    agent.dependency_manager.get_intimacy_level() or intimacy_level
                )
            except Exception:
                intimacy_level = intimacy_level

        try:
            agent.emotion_manager.ingest_life_stats(
                user_id,
                {
                    "mood_score": mood_score,
                    "shyness_score": shyness_score,
                    "immune_damage": immune_damage,
                    "is_sick": is_sick,
                    "level": life_level,
                },
                intimacy_level=intimacy_level,
            )
        except Exception:
            pass
    except Exception:
        pass

    affect_instruction = ""
    try:
        affect_instruction = agent.emotion_manager.build_dialogue_affect_instruction(
            life_level=life_level,
            mood_score=mood_score,
            shyness_score=shyness_score,
            immune_damage=immune_damage,
            is_sick=is_sick,
            intimacy_level=intimacy_level,
            soft_reply_char_limit=soft_reply_char_limit,
            max_tokens=max_tokens,
        )
    except Exception:
        affect_instruction = ""
    return affect_instruction
