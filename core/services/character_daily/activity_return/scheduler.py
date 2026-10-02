"""回归消息的异步调度。"""

from __future__ import annotations
from core.utils.logger import get_logger

import asyncio

from typing import Any, Literal

logger = get_logger(__name__)

# 默认提前多久发回归消息
DEFAULT_LEAD_SECONDS = 60.0

_scheduled_tasks: dict[str, asyncio.Task[Any]] = {}
_scheduler_lock = asyncio.Lock()


async def _wait_and_trigger(
    conversation_id: str,
    role_id: str,
    activity: str,
    return_type: Literal["work", "sleep"],
    source: str,
    delay_seconds: float,
) -> None:
    """等待指定时间后触发回归消息。"""
    try:
        await asyncio.sleep(max(0.0, delay_seconds))
        # 再检查一次窗口是否仍然有效（未被延长/跳过/清除）
        from core.services.character_daily.interrupt_window import (
            get_manual_interrupt_window,
            has_interrupt_window_ending_notified,
        )

        window = get_manual_interrupt_window(conversation_id=conversation_id, role_id=role_id)
        if not window:
            logger.debug("调度任务：窗口 %s 已不存在，取消回归消息", conversation_id)
            return
        if bool(window.get("skip_activity")):
            logger.debug("调度任务：窗口 %s 已跳过活动，取消回归消息", conversation_id)
            return
        if has_interrupt_window_ending_notified(conversation_id):
            logger.debug("调度任务：窗口 %s 已发送过结束通知，跳过", conversation_id)
            return

        from core.services.character_daily.activity_return.core import (
            send_activity_return_message,
        )

        await send_activity_return_message(
            conversation_id=conversation_id,
            role_id=role_id,
            activity=activity,
            return_type=return_type,
            source=source,
        )
    except asyncio.CancelledError:
        logger.debug("回归消息调度任务取消 (conversation=%s)", conversation_id)
    except Exception as e:
        logger.error("回归消息调度任务异常 (conversation=%s): %s", conversation_id, e, exc_info=True)


async def schedule_activity_return(
    *,
    conversation_id: str,
    role_id: str,
    activity: str,
    return_type: Literal["work", "sleep"],
    window_seconds: float,
    source: str = "",
    lead_seconds: float = DEFAULT_LEAD_SECONDS,
) -> dict[str, Any]:
    """安排一段时间后发送回归消息。

    用于 /打断 场景：窗口激活时就安排好，在 window_seconds - lead_seconds 时触发，
    避免依赖 engine._tick 的 120s 轮询而错过 60s 窗口。

    Args:
        conversation_id: 会话 ID
        role_id: 角色 ID
        activity: 被中断的活动
        return_type: work / sleep
        window_seconds: 窗口总时长
        source: 触发来源
        lead_seconds: 提前多久发消息

    Returns:
        {"scheduled": bool, "delay_seconds": float, "task": asyncio.Task}
    """
    conversation_id = str(conversation_id or "").strip()
    role_id = str(role_id or "").strip().lower()
    result = {
        "scheduled": False,
        "delay_seconds": 0.0,
        "task": None,
    }
    if not conversation_id or not role_id:
        return result

    delay_seconds = max(0.0, float(window_seconds or 0.0) - lead_seconds)
    result["delay_seconds"] = delay_seconds

    # 取消同一会话的旧调度任务
    await _cancel_scheduled_return(conversation_id)

    try:
        task = asyncio.create_task(
            _wait_and_trigger(
                conversation_id=conversation_id,
                role_id=role_id,
                activity=activity,
                return_type=return_type,
                source=source,
                delay_seconds=delay_seconds,
            ),
            name=f"activity_return_{conversation_id}",
        )
        async with _scheduler_lock:
            _scheduled_tasks[conversation_id] = task
        result["scheduled"] = True
        result["task"] = task
        logger.info(
            "已安排 %s 回归消息（conversation=%s, delay=%.0fs, lead=%.0fs, source=%s）",
            return_type, conversation_id, delay_seconds, lead_seconds, source,
        )
    except Exception as e:
        logger.error("安排回归消息失败 (conversation=%s): %s", conversation_id, e, exc_info=True)

    return result


async def _cancel_scheduled_return(conversation_id: str) -> None:
    """取消指定会话的调度任务。"""
    cid = str(conversation_id or "").strip()
    if not cid:
        return
    async with _scheduler_lock:
        old_task = _scheduled_tasks.pop(cid, None)
    if old_task and not old_task.done():
        old_task.cancel()
        try:
            await old_task
        except asyncio.CancelledError:
            pass


async def cancel_scheduled_return(conversation_id: str) -> None:
    """外部调用：取消指定会话的调度任务。"""
    await _cancel_scheduled_return(conversation_id)
