# -*- coding: utf-8 -*-
"""生命状态域 - 活动中断窗口。

POST /life/activity/interrupt
POST /life/activity/skip
POST /life/activity/extend"""

import logging
import time
import uuid
from fastapi import APIRouter
from core.api.contract import error_response
from core.api.error_response import ErrorCode
from core.services.character_daily.activity_model import (
    ActivityType,
    DO_NOT_DISTURB_ACTIVITIES,
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
from .life_shared import (
    SleepWakeRequest,
    ActivityInterruptRequest,
    ActivitySkipRequest,
    ActivityExtendRequest,
    _get_life_simulation_service,
    _resolve_role_scope,
    _get_character_daily_engine,
    _resolve_manual_interrupt_window_seconds,
    _resolve_skip_window_seconds,
    _normalize_conversation_id_for_interrupt,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/life", tags=["生命与情绪"])

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
        logger.debug(
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
        logger.debug(
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


