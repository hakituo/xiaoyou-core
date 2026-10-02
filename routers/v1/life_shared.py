# -*- coding: utf-8 -*-
"""生命状态域 - 共享模型与辅助函数。

各 life 子端点共用的请求模型、角色 scope 解析、服务获取与窗口计算；
集中在此避免子模块之间互相 import 形成环。"""

import logging
import time
from typing import Any, Optional
from pydantic import BaseModel, Field
from core.services.character_daily.activity_model import (
    ActivityType,
    DO_NOT_DISTURB_ACTIVITIES,
    HARD_BUSY_ACTIVITIES,
    SOFT_REPLY_DELAY_ACTIVITIES,
)

logger = logging.getLogger(__name__)

class SleepWakeRequest(BaseModel):
    """睡眠立即唤醒请求。"""

    role_id: str = Field(default="", description="角色 scope，可选：aveline/ling")
    persona_filename: str = Field(default="", description="当前会话人设文件名")
    conversation_id: str = Field(default="", description="当前会话对话 ID")
    message: str = Field(default="", description="唤醒原因或附加说明")


class ActivityInterruptRequest(BaseModel):
    """忙碌状态下强制进入聊天窗口的请求。"""

    role_id: str = Field(default="", description="角色 scope，可选：aveline/ling")
    persona_filename: str = Field(default="", description="当前会话人设文件名")
    conversation_id: str = Field(default="", description="当前会话对话 ID")
    message: str = Field(default="", description="打断原因或附加说明")


class ActivitySkipRequest(BaseModel):
    """跳过当前活动的请求（标记跳过，不再提醒回去做事）。"""

    role_id: str = Field(default="", description="角色 scope，可选：aveline/ling")
    persona_filename: str = Field(default="", description="当前会话人设文件名")
    conversation_id: str = Field(default="", description="当前会话对话 ID")
    message: str = Field(default="", description="跳过原因")


class ActivityExtendRequest(BaseModel):
    """延长中断窗口的请求。"""

    role_id: str = Field(default="", description="角色 scope，可选：aveline/ling")
    persona_filename: str = Field(default="", description="当前会话人设文件名")
    conversation_id: str = Field(default="", description="当前会话对话 ID")
    extend_seconds: int = Field(default=300, description="延长秒数，默认 300s")
    message: str = Field(default="", description="延长原因")


def _get_life_simulation_service():
    from core.services.life_simulation.service import get_life_simulation_service

    return get_life_simulation_service()


def _resolve_role_scope(payload: SleepWakeRequest) -> str:
    """从请求 payload 解析目标角色 scope。

    yeye/rushuang 已接入独立 QQ 账号参与 active_care；xiaolu/mianmian 仅接
    character_daily + sleep_manager。都返回它们自己的 scope，让 /wake 能正确
    唤醒对应角色，不会误清 aveline 的睡眠状态或刷新 aveline 的活动。
    """
    explicit_role = str(payload.role_id or "").strip().lower()
    if explicit_role in {"aveline", "ling", "yeye", "xiaolu", "rushuang", "mianmian", "chiba"}:
        return explicit_role

    try:
        from core.services.active_care.core.service import get_active_care_service

        active_care = get_active_care_service()
        storage = getattr(active_care, "storage", None)
        if storage is not None:
            persona_filename = str(payload.persona_filename or "").strip()
            if persona_filename:
                scope = storage.resolve_scope_from_persona_filename(persona_filename)
                if scope:
                    return str(scope).strip().lower()
            conversation_id = str(payload.conversation_id or "").strip()
            if conversation_id:
                scope = storage.resolve_scope_from_conversation_id(conversation_id)
                if scope:
                    return str(scope).strip().lower()
    except Exception as exc:
        logger.debug("解析睡眠唤醒 scope 失败: %s", exc)

    persona_lower = str(payload.persona_filename or "").strip().lower()
    conversation_lower = str(payload.conversation_id or "").strip().lower()
    if "yeye" in persona_lower or "Coco" in persona_lower or "__persona__yeye" in conversation_lower:
        return "yeye"
    if "xiaolu" in persona_lower or "Fawn" in persona_lower or "__persona__xiaolu" in conversation_lower:
        return "xiaolu"
    if "rushuang" in persona_lower or "Frost" in persona_lower or "__persona__rushuang" in conversation_lower:
        return "rushuang"
    if "mianmian" in persona_lower or "Mian" in persona_lower or "__persona__mianmian" in conversation_lower:
        return "mianmian"
    if "chiba" in persona_lower or "Chiba" in persona_lower or "Chiba" in persona_lower or "__persona__chiba" in conversation_lower or "__persona__Chiba" in conversation_lower:
        return "chiba"
    if "ling" in persona_lower or "__scope__ling" in conversation_lower:
        return "ling"
    return "aveline"


def _get_character_daily_engine():
    from core.services.character_daily.engine import get_character_daily_engine

    return get_character_daily_engine()


def _build_reply_policy_summary(activity: ActivityType, engine: Any) -> dict[str, Any]:
    """返回状态面板可直接展示的基础回复策略，不复用 Peer Chat 门控语义。"""
    if activity in DO_NOT_DISTURB_ACTIVITIES:
        return {"mode": "silent", "reason": "sleep"}
    if activity in HARD_BUSY_ACTIVITIES:
        return {"mode": "silent", "reason": "hard_busy"}
    if activity in SOFT_REPLY_DELAY_ACTIVITIES:
        try:
            from core.services.character_daily.reply_policy_support import (
                resolve_soft_delay_profile,
            )

            profile = resolve_soft_delay_profile(
                activity,
                engine.get_reply_policy_config(),
            )
            return {
                "mode": "delayed",
                "reason": profile.profile_name,
                "min_seconds": round(float(profile.min_seconds)),
                "max_seconds": round(float(profile.max_seconds)),
            }
        except Exception as exc:
            logger.warning("读取活动回复延迟档位失败: %s", exc)
            return {"mode": "delayed", "reason": "activity"}
    return {"mode": "immediate", "reason": "free"}


def _resolve_manual_interrupt_window_seconds() -> float:
    try:
        engine = _get_character_daily_engine()
        if engine is not None:
            config = engine.get_reply_policy_config()
            return max(
                60.0,
                float(getattr(config, "manual_interrupt_window_seconds", 600.0)),
            )
    except Exception as exc:
        logger.warning("读取手动打断窗口配置失败: %s", exc)
    return 600.0


def _resolve_skip_window_seconds(role_id: str, engine: Any = None) -> float:
    """计算 /跳过 命令的窗口时长：用当前活动槽位的剩余时间。

    /跳过 应覆盖整个活动的剩余时间，而不是固定 300 秒。
    这样用户跳过活动后，整个活动期间都可以自由聊天。

    Args:
        role_id: 角色 ID
        engine: CharacterDailyEngine 实例，None 时尝试获取

    Returns:
        窗口秒数；无法确定时回退到 3600 秒（1 小时）
    """
    if engine is None:
        engine = _get_character_daily_engine()
    if engine is not None:
        try:
            remaining = engine.get_current_slot_remaining_seconds(role_id)
            if remaining > 0:
                # 多给 5 分钟缓冲，避免活动刚好结束时窗口就过期
                return remaining + 300.0
        except Exception as exc:
            logger.warning("获取活动剩余时间失败: %s", exc)
    # 无法确定剩余时间，回退到 1 小时
    return 3600.0


def _normalize_conversation_id_for_interrupt(conversation_id: str, role_id: str) -> str:
    """规范化中断窗口相关的 conversation_id。

    与 /打断 接口保持一致：当 conversation_id 不含 __persona__ 后缀时，
    根据 role_id 追加 `__persona__{role_id}_qq_master` 后缀。

    Args:
        conversation_id: 原始会话 ID
        role_id: 已解析的 role_id

    Returns:
        规范化后的 conversation_id
    """
    cid = str(conversation_id or "").strip()
    if not cid:
        return cid
    if "__persona__" in cid:
        return cid
    role = str(role_id or "").strip().lower() or "aveline"
    return f"{cid}__persona__{role}_qq_master"


def _strip_persona_suffix_from_conversation_id(conversation_id: str) -> str:
    """移除 conversation_id 中的 __persona__ 后缀，返回基础会话 ID。"""
    cid = str(conversation_id or "").strip()
    if "__persona__" in cid:
        return cid.split("__persona__", 1)[0].strip("_")
    return cid


async def _clear_active_care_sleep_session(scope: str) -> bool:
    """清理 Active Care 中当前角色残留的晚安睡眠态。"""
    try:
        from core.services.active_care.core.service import get_active_care_service
        from core.services.active_care.shared.state_keys import (
            StateKeys,
            build_goodnight_clear_updates,
        )
        from core.services.active_care.state.sleep_state import SleepStateManager

        resolved_scope = str(scope or "").strip().lower()
        if not resolved_scope:
            return False

        active_care = get_active_care_service()
        if active_care is None or active_care.storage is None:
            return False

        state_data = await active_care.storage.get_proactive_state(scope=resolved_scope)
        last_goodnight = float(state_data.get(StateKeys.LAST_GOODNIGHT_TS) or 0.0)
        last_goodmorning = float(state_data.get(StateKeys.LAST_GOODMORNING_TS) or 0.0)
        if not SleepStateManager.is_sleep_session_active_from_state(
            last_goodnight,
            last_goodmorning,
        ):
            return False

        updates = build_goodnight_clear_updates()
        updates[StateKeys.LAST_GOODMORNING_TS] = time.time()
        await active_care.storage.save_proactive_state(
            updates,
            immediate=True,
            scope=resolved_scope,
        )
        return True
    except Exception as exc:
        logger.warning("清理 Active Care 睡眠态失败: %s", exc)
        return False


def _refresh_character_daily_activity(role_id: str) -> Optional[ActivityType]:
    """唤醒后立即刷新 character_daily engine 的 plan.current_activity。

    sleep_manager 的状态被 notify_sleep_interruption 立即修改后，
    CharacterDailyEngine 的 plan.current_activity 仍停留在上次 tick 的缓存
    （tick 间隔可达 2 分钟），导致 reply_policy 仍按旧活动判定为 DND。
    这里同步触发重算，保证后续消息能正常回复。

    Returns:
        刷新后的当前活动；engine 不存在或刷新失败时返回 None。
    """
    try:
        from core.services.character_daily.engine import get_character_daily_engine

        engine = get_character_daily_engine()
        if engine is None:
            return None
        refreshed = engine.refresh_current_activity(str(role_id or "").strip().lower())
        logger.info(
            "wake API: 已刷新 character_daily activity (role_id=%s, activity=%s)",
            role_id,
            getattr(refreshed, "value", refreshed),
        )
        return refreshed
    except Exception as exc:
        logger.warning("wake API: 刷新 character_daily activity 失败: %s", exc)
        return None


