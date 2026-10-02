# -*- coding: utf-8 -*-
"""生命状态域 - 睡眠与唤醒。

POST /life/sleep/wake"""

import logging
import uuid
from fastapi import APIRouter
from core.api.contract import error_response
from core.api.error_response import ErrorCode
from core.services.character_daily.activity_model import (
    DO_NOT_DISTURB_ACTIVITIES,
)
from core.services.character_daily.interrupt_window import (
    activate_manual_interrupt_window,
)
from .life_shared import (
    SleepWakeRequest,
    _get_life_simulation_service,
    _resolve_role_scope,
    _resolve_manual_interrupt_window_seconds,
    _clear_active_care_sleep_session,
    _refresh_character_daily_activity,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/life", tags=["生命与情绪"])

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


