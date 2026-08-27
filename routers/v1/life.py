# -*- coding: utf-8 -*-
"""生命状态（life）域。

提供 Aveline 的生命模拟状态（健康 / 饥饿 / 心情 / 能量）与情绪检测能力。
"""

import logging
import time
import uuid
from core.utils.time_utils import now_iso
from typing import Any, Optional

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, Field

from core.api.contract import error_response
from core.api.error_response import ErrorCode
from core.services.character_daily.activity_model import (
    ActivityType,
    CHAT_ELIGIBLE_ACTIVITIES,
    DO_NOT_DISTURB_ACTIVITIES,
    HARD_BUSY_ACTIVITIES,
    SOFT_REPLY_DELAY_ACTIVITIES,
)
from core.services.character_daily.interrupt_window import (
    activate_manual_interrupt_window,
    extend_manual_interrupt_window,
    get_manual_interrupt_window,
    mark_skip_current_activity,
)
from core.services.character_daily.activity_return import (
    schedule_activity_return,
    cancel_scheduled_return,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/life", tags=["生命与情绪"])


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
    if "xiaolu" in persona_lower or "小鹿" in persona_lower or "__persona__xiaolu" in conversation_lower:
        return "xiaolu"
    if "rushuang" in persona_lower or "Frost" in persona_lower or "__persona__rushuang" in conversation_lower:
        return "rushuang"
    if "mianmian" in persona_lower or "Mian" in persona_lower or "__persona__mianmian" in conversation_lower:
        return "mianmian"
    if "chiba" in persona_lower or "Chiba" in persona_lower or "千葉" in persona_lower or "__persona__chiba" in conversation_lower or "__persona__Chiba" in conversation_lower:
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
        from core.services.active_care.shared.constants import (
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


@router.get("/status", summary="获取角色生命状态")
async def get_life_status(
    scope: str = Query("aveline", description="角色 scope（aveline/ling/rushuang/yeye 等）"),
    persona: Optional[str] = Query(None, description="人格文件名（如 qq/Aveline_QQ_Master.json），传入后按角色隔离生命状态，优先级高于 scope"),
):
    try:
        # persona 文件名优先：用后端权威映射解析成角色 scope，避免前端 slug 与后端不一致
        if persona:
            try:
                from core.utils.data_paths import (
                    build_shared_persona_conversation_id,
                    resolve_memory_user_id,
                    resolve_data_scope_from_conversation_id,
                )
                cid = build_shared_persona_conversation_id(persona)
                scope = resolve_data_scope_from_conversation_id(resolve_memory_user_id(cid))
            except Exception as e:
                logger.warning(f"按 persona 解析生命状态 scope 失败，回退传入 scope: {e}")
        sim = _get_life_simulation_service()
        # 按 scope 取该角色的独立生命状态（energy/hunger/thirst/mood_score 等）
        state = sim.get_state_for_scope(scope)

        # 状态面板需要和回复策略看到同一份“当前活动”。这里主动刷新一次，
        # 避免 character_daily 的两分钟 tick 让 App 长时间展示旧活动。
        sleep_summary = sim.get_sleep_summary(scope)
        engine = _get_character_daily_engine()
        current_activity = ActivityType.SLEEPING
        if not bool(sleep_summary.get("is_sleeping")):
            current_activity = (
                engine.refresh_current_activity(scope)
                if engine is not None
                else ActivityType.IDLE
            )
        reply_policy = _build_reply_policy_summary(current_activity, engine)
        daily_plan = engine.state.get_plan(scope) if engine is not None else None

        # 获取当前情绪（per-scope 端口，当前为 mock，待后端情绪 per-scope 改造后接入）
        emo_data = sim.get_emotion_for_scope(scope)
        current_emotion = emo_data.get("primary_emotion", "calm")
        emotion_mix = emo_data.get("emotion_mix", {})

        return {
            "status": "success",
            "data": state,
            "life_status": state,  # 兼容旧字段
            "emotion": current_emotion,
            "emotion_mix": emotion_mix,
            "emotion_mock": emo_data.get("mock", False),
            "activity": current_activity.value,
            "activity_chat_eligible": current_activity in CHAT_ELIGIBLE_ACTIVITIES,
            "reply_policy": reply_policy,
            "sleep_summary": sleep_summary,
            "daily_plan": daily_plan.to_dict() if daily_plan is not None else None,
            "scope": scope,
            "timestamp": now_iso(),
        }
    except Exception as e:
        logger.error(f"获取生活模拟状态失败: {e}")
        resp = error_response(ErrorCode.INTERNAL_ERROR, message=str(e))
        resp["retryable"] = True
        resp["retry_after_seconds"] = 5
        return resp


@router.post("/sleep/wake", summary="立即唤醒当前角色")
async def wake_sleeping_role(payload: SleepWakeRequest):
    request_id = str(uuid.uuid4())
    try:
        sim = _get_life_simulation_service()
        role_id = _resolve_role_scope(payload)
        before_summary = sim.get_sleep_summary(role_id)
        phase = str(before_summary.get("phase") or "").strip().lower()
        is_sleeping = bool(before_summary.get("is_sleeping"))
        ac_cleared = False
        if not is_sleeping:
            ac_cleared = await _clear_active_care_sleep_session(role_id)
            if ac_cleared:
                _refresh_character_daily_activity(role_id)
                refreshed_summary = sim.get_sleep_summary(role_id)
                return {
                    "status": "success",
                    "action": "woken_up",
                    "role_id": role_id,
                    "previous_phase": phase,
                    "sleep_summary": refreshed_summary,
                    "message": f"{role_id} 的残留晚安态已清理",
                    "request_id": request_id,
                }
            # sleep_manager 判定未在睡，但 character_daily 的 plan.current_activity
            # 可能仍停留在 DND 活动（如午睡 napping）。用户发 /wake 的意图是"叫醒并回复"，
            # 需要同步刷新；若刷新后仍是 DND，自动激活中断窗口，避免 reply_policy 静默累积消息。
            refreshed_activity = _refresh_character_daily_activity(role_id)
            if refreshed_activity in DO_NOT_DISTURB_ACTIVITIES:
                conversation_id = str(payload.conversation_id or "").strip()
                if conversation_id:
                    window_seconds = _resolve_manual_interrupt_window_seconds()
                    activate_manual_interrupt_window(
                        conversation_id=conversation_id,
                        role_id=role_id,
                        activity=refreshed_activity.value,
                        window_seconds=window_seconds,
                        source="wake_auto_interrupt_dnd",
                    )
                    logger.info(
                        "wake API: character_daily 仍处于 DND 活动 %s，已自动激活中断窗口 (role=%s, conv=%s)",
                        refreshed_activity.value, role_id, conversation_id,
                    )
                return {
                    "status": "success",
                    "action": "woken_up",
                    "role_id": role_id,
                    "previous_phase": phase,
                    "activity": refreshed_activity.value,
                    "sleep_summary": before_summary,
                    "message": f"{role_id} 已从{refreshed_activity.value}被打断",
                    "request_id": request_id,
                }
            return {
                "status": "success",
                "action": "already_awake",
                "role_id": role_id,
                "sleep_summary": before_summary,
                "message": f"{role_id} 当前不在睡眠中",
                "request_id": request_id,
            }

        after_summary = sim.notify_sleep_interruption(
            role_id=role_id,
            message=str(payload.message or "").strip(),
            conversation_id=str(payload.conversation_id or "").strip(),
        )
        ac_cleared = await _clear_active_care_sleep_session(role_id)
        _refresh_character_daily_activity(role_id)
        return {
            "status": "success",
            "action": "woken_up",
            "role_id": role_id,
            "previous_phase": phase,
            "sleep_summary": after_summary,
            "active_care_cleared": ac_cleared,
            "request_id": request_id,
        }
    except Exception as e:
        logger.error(f"Sleep wake error: {e}", exc_info=True)
        return error_response(
            ErrorCode.INTERNAL_ERROR,
            message=str(e),
            request_id=request_id,
        )


@router.post("/activity/interrupt", summary="强制打断当前活动并进入聊天窗口")
async def interrupt_current_activity(payload: ActivityInterruptRequest):
    request_id = str(uuid.uuid4())
    try:
        role_id = _resolve_role_scope(
            SleepWakeRequest(
                role_id=payload.role_id,
                persona_filename=payload.persona_filename,
                conversation_id=payload.conversation_id,
                message=payload.message,
            )
        )
        conversation_id = str(payload.conversation_id or "").strip()
        # 规范化 conversation_id，确保与后续消息处理时使用的 ID 一致
        # 避免 interrupt_window 无法命中导致 persona_hint 不注入
        conversation_id = _normalize_conversation_id_for_interrupt(conversation_id, role_id)
        if not conversation_id:
            return error_response(
                ErrorCode.INVALID_PAYLOAD,
                message="conversation_id 不能为空",
                request_id=request_id,
            )

        sim = _get_life_simulation_service()
        sleep_summary = sim.get_sleep_summary(role_id)
        if bool(sleep_summary.get("is_sleeping")):
            return {
                "status": "success",
                "action": "sleeping_use_wake",
                "role_id": role_id,
                "sleep_summary": sleep_summary,
                "message": f"{role_id} 当前还在睡，先用 /唤醒",
                "request_id": request_id,
            }

        engine = _get_character_daily_engine()
        current_activity = (
            engine.refresh_current_activity(role_id)
            if engine is not None
            else ActivityType.IDLE
        )
        if current_activity in DO_NOT_DISTURB_ACTIVITIES:
            return {
                "status": "success",
                "action": "sleeping_use_wake",
                "role_id": role_id,
                "activity": current_activity.value,
                "sleep_summary": sleep_summary,
                "message": f"{role_id} 当前属于睡眠/起床过渡态，先用 /唤醒",
                "request_id": request_id,
            }
        if current_activity == ActivityType.IDLE:
            return {
                "status": "success",
                "action": "already_available",
                "role_id": role_id,
                "activity": current_activity.value,
                "message": f"{role_id} 现在本来就在空闲聊天态",
                "request_id": request_id,
            }

        window_seconds = _resolve_manual_interrupt_window_seconds()
        logger.info(
            "Activity interrupt debug: conversation_id=%s role_id=%s window_seconds=%s",
            conversation_id, role_id, window_seconds,
        )

        # 如果当前窗口已标记跳过活动（/skip 创建），/打断 不应覆盖 /skip 的长窗口
        # 否则用户先后用 /skip 和 /打断 时，/skip 的"整个活动期间自由聊天"效果会丢失
        existing_window = get_manual_interrupt_window(
            conversation_id=conversation_id,
            role_id=role_id,
        )
        if existing_window and bool(existing_window.get("skip_activity")):
            remaining_seconds = max(
                0.0,
                float(existing_window.get("expire_ts") or 0.0) - time.time(),
            )
            remaining_minutes = int(remaining_seconds // 60)
            if remaining_minutes >= 60:
                remaining_display = f"{remaining_minutes // 60} 小时 {remaining_minutes % 60} 分钟"
            else:
                remaining_display = f"{remaining_minutes} 分钟"
            logger.info(
                "Activity interrupt: 已有 skip 窗口，跳过覆盖 (conversation=%s, remaining=%.1fs)",
                conversation_id, remaining_seconds,
            )
            return {
                "status": "success",
                "action": "already_skipped",
                "role_id": role_id,
                "activity": current_activity.value,
                "conversation_id": conversation_id,
                "remaining_seconds": int(remaining_seconds),
                "remaining_display": remaining_display,
                "message": f"{role_id} 当前活动已跳过，约 {remaining_display} 内都能继续聊天，无需再打断",
                "request_id": request_id,
            }

        window_state = activate_manual_interrupt_window(
            conversation_id=conversation_id,
            role_id=role_id,
            activity=current_activity.value,
            window_seconds=window_seconds,
            source="qq_command_interrupt",
        )
        # 安排回归消息：窗口快结束时主动提醒用户要回去做事了
        try:
            await schedule_activity_return(
                conversation_id=conversation_id,
                role_id=role_id,
                activity=current_activity.value,
                return_type="work",
                window_seconds=window_seconds,
                source="qq_command_interrupt",
            )
        except Exception as e:
            logger.warning(
                "Activity interrupt: 安排回归消息失败 (conversation=%s): %s",
                conversation_id, e,
            )
        logger.info(
            "Activity interrupt debug: window_state=%s",
            window_state,
        )
        return {
            "status": "success",
            "action": "interrupted",
            "role_id": role_id,
            "activity": current_activity.value,
            "conversation_id": conversation_id,
            "window_seconds": int(window_seconds),
            "window_expire_ts": float(window_state.get("expire_ts") or 0.0),
            "message": f"已从 {current_activity.value} 打断，进入临时聊天窗口",
            "request_id": request_id,
        }
    except Exception as e:
        logger.error(f"Activity interrupt error: {e}", exc_info=True)
        return error_response(
            ErrorCode.INTERNAL_ERROR,
            message=str(e),
            request_id=request_id,
        )


@router.post("/activity/skip", summary="跳过当前活动，标记为已完成")
async def skip_current_activity(payload: ActivitySkipRequest):
    """跳过当前活动，使其不再被提醒回去做事。"""
    request_id = str(uuid.uuid4())
    try:
        conversation_id = str(payload.conversation_id or "").strip()
        if not conversation_id:
            return error_response(
                ErrorCode.INVALID_PAYLOAD,
                message="conversation_id 不能为空",
                request_id=request_id,
            )

        # 解析 role_id 并规范化 conversation_id
        # /打断 接口会通过 _resolve_role_scope 解析并扩展 conversation_id
        # 为含 __persona__ 后缀的 ID，这里需要同样处理，确保能命中同一个窗口
        role_id = _resolve_role_scope(
            SleepWakeRequest(
                role_id=payload.role_id,
                persona_filename=payload.persona_filename,
                conversation_id=conversation_id,
                message=payload.message,
            )
        )
        conversation_id = _normalize_conversation_id_for_interrupt(conversation_id, role_id)

        # 检查是否睡眠中，睡眠中需要先唤醒
        sim = _get_life_simulation_service()
        sleep_summary = sim.get_sleep_summary(role_id)
        if bool(sleep_summary.get("is_sleeping")):
            return {
                "status": "success",
                "action": "sleeping_use_wake",
                "role_id": role_id,
                "sleep_summary": sleep_summary,
                "message": f"{role_id} 当前还在睡，先用 /唤醒",
                "request_id": request_id,
            }

        # 获取当前活动，用于没有窗口时创建
        engine = _get_character_daily_engine()
        current_activity = (
            engine.refresh_current_activity(role_id)
            if engine is not None
            else ActivityType.IDLE
        )
        if current_activity in DO_NOT_DISTURB_ACTIVITIES:
            return {
                "status": "success",
                "action": "sleeping_use_wake",
                "role_id": role_id,
                "activity": current_activity.value,
                "sleep_summary": sleep_summary,
                "message": f"{role_id} 当前属于睡眠/起床过渡态，先用 /唤醒",
                "request_id": request_id,
            }
        if current_activity == ActivityType.IDLE:
            return {
                "status": "success",
                "action": "already_available",
                "role_id": role_id,
                "activity": current_activity.value,
                "message": f"{role_id} 现在本来就在空闲聊天态",
                "request_id": request_id,
            }

        # 计算跳过窗口时长：用当前活动槽位的剩余时间，而非固定 300 秒
        # 这样 /跳过 的效果是整个活动期间都可以自由聊天
        skip_window_seconds = _resolve_skip_window_seconds(role_id, engine)

        # 检查中断窗口是否存在，不存在则自动创建并标记跳过
        window = get_manual_interrupt_window(
            conversation_id=conversation_id,
            role_id=role_id,
        )
        if not window:
            window = activate_manual_interrupt_window(
                conversation_id=conversation_id,
                role_id=role_id,
                activity=current_activity.value,
                window_seconds=skip_window_seconds,
                source="qq_command_skip_auto_interrupt",
                skip_activity=True,
            )
            updated_window = window
        else:
            # 已有窗口，延长到活动结束时间并标记跳过
            now_ts = time.time()
            current_expire = float(window.get("expire_ts") or 0.0)
            needed_expire = now_ts + skip_window_seconds
            if needed_expire > current_expire:
                extend_seconds = needed_expire - current_expire
                extend_manual_interrupt_window(
                    conversation_id=conversation_id,
                    extend_seconds=extend_seconds,
                )
            # 标记跳过当前活动
            updated_window = mark_skip_current_activity(
                conversation_id=conversation_id,
            )
        if not updated_window:
            return error_response(
                ErrorCode.INTERNAL_ERROR,
                message="标记跳过活动失败",
                request_id=request_id,
            )

        # 跳过活动后不再需要回归消息
        try:
            await cancel_scheduled_return(conversation_id=conversation_id)
        except Exception as e:
            logger.warning(
                "Activity skip: 取消回归消息调度失败 (conversation=%s): %s",
                conversation_id, e,
            )

        activity = str(updated_window.get("activity") or "unknown").strip()
        remaining_seconds = max(
            0.0,
            float(updated_window.get("expire_ts") or 0.0) - time.time(),
        )

        action = "auto_skipped" if window and window.get("source") == "qq_command_skip_auto_interrupt" else "skipped"

        # 将剩余秒数转为友好的分钟/小时显示
        remaining_minutes = int(remaining_seconds // 60)
        if remaining_minutes >= 60:
            remaining_display = f"{remaining_minutes // 60} 小时 {remaining_minutes % 60} 分钟"
        else:
            remaining_display = f"{remaining_minutes} 分钟"

        logger.info(
            "Activity skip: role=%s activity=%s conversation=%s action=%s remaining=%.1fs",
            role_id, activity, conversation_id, action, remaining_seconds,
        )

        return {
            "status": "success",
            "action": action,
            "role_id": role_id,
            "activity": activity,
            "conversation_id": conversation_id,
            "remaining_seconds": int(remaining_seconds),
            "remaining_display": remaining_display,
            "message": f"已跳过 {activity}，约 {remaining_display} 内自由聊天，不再提醒回去做事",
            "request_id": request_id,
        }
    except Exception as e:
        logger.error(f"Activity skip error: {e}", exc_info=True)
        return error_response(
            ErrorCode.INTERNAL_ERROR,
            message=str(e),
            request_id=request_id,
        )


@router.post("/activity/extend", summary="延长中断窗口时间")
async def extend_interrupt_window(payload: ActivityExtendRequest):
    """延长中断窗口时间，让聊天继续。"""
    request_id = str(uuid.uuid4())
    try:
        conversation_id = str(payload.conversation_id or "").strip()
        if not conversation_id:
            return error_response(
                ErrorCode.INVALID_PAYLOAD,
                message="conversation_id 不能为空",
                request_id=request_id,
            )

        # 解析 role_id 并规范化 conversation_id，确保命中同一个中断窗口
        role_id = _resolve_role_scope(
            SleepWakeRequest(
                role_id=payload.role_id,
                persona_filename=payload.persona_filename,
                conversation_id=conversation_id,
                message=payload.message,
            )
        )
        conversation_id = _normalize_conversation_id_for_interrupt(conversation_id, role_id)
        extend_seconds = int(payload.extend_seconds or 300)

        # 延长中断窗口
        updated_window = extend_manual_interrupt_window(
            conversation_id=conversation_id,
            extend_seconds=float(extend_seconds),
        )
        if not updated_window:
            return {
                "status": "success",
                "action": "no_window_or_max_extended",
                "role_id": role_id,
                "message": "当前没有活跃的中断窗口，或已达到延长上限",
                "request_id": request_id,
            }

        activity = str(updated_window.get("activity") or "unknown").strip()
        extended_count = int(updated_window.get("extended_count") or 0)
        remaining_seconds = max(
            0.0,
            float(updated_window.get("expire_ts") or 0.0) - time.time(),
        )

        # 重新安排回归消息，按新的剩余时间计算
        try:
            await schedule_activity_return(
                conversation_id=conversation_id,
                role_id=role_id,
                activity=activity,
                return_type="work",
                window_seconds=remaining_seconds,
                source="qq_command_extend",
            )
        except Exception as e:
            logger.warning(
                "Activity extend: 重新安排回归消息失败 (conversation=%s): %s",
                conversation_id, e,
            )

        logger.info(
            "Activity extend: role=%s activity=%s conversation=%s extended=%ds count=%d remaining=%.1fs",
            role_id, activity, conversation_id, extend_seconds, extended_count, remaining_seconds,
        )

        return {
            "status": "success",
            "action": "extended",
            "role_id": role_id,
            "activity": activity,
            "conversation_id": conversation_id,
            "extend_seconds": extend_seconds,
            "extended_count": extended_count,
            "remaining_seconds": int(remaining_seconds),
            "message": f"已延长 {extend_seconds} 秒，剩余约 {int(remaining_seconds)} 秒",
            "request_id": request_id,
        }
    except Exception as e:
        logger.error(f"Activity extend error: {e}", exc_info=True)
        return error_response(
            ErrorCode.INTERNAL_ERROR,
            message=str(e),
            request_id=request_id,
        )


@router.post("/emotion/detect", summary="检测文本情绪")
async def detect_emotion(payload: Any = Body(...)):
    request_id = str(uuid.uuid4())
    try:
        if not isinstance(payload, dict):
            return error_response(
                ErrorCode.INVALID_PAYLOAD,
                message="请求体必须是JSON对象",
                request_id=request_id,
            )

        text = str(payload.get("text") or "").strip()
        if not text:
            return {
                "status": "success",
                "emotion": "neutral",
                "confidence": 0.0,
                "request_id": request_id,
            }

        from core.emotion.detector_v2 import get_emotion_detector_v2
        detector = get_emotion_detector_v2()
        state = detector.detect(text)

        return {
            "status": "success",
            "emotion": state.primary_emotion.value if state.primary_emotion else "neutral",
            "confidence": state.confidence,
            "request_id": request_id,
        }
    except Exception as e:
        logger.error(f"Emotion detect error: {e}", exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e), request_id=request_id)
