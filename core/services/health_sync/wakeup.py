# -*- coding: utf-8 -*-
"""基于 Samsung Health 真实起床时间退出低打扰模式。

背景
----
Active Care 里 ``quiet_mode_active = last_goodnight_ts > 0 and not sleep_session_active``。
原有的自动退出逻辑（``checker_state_detector._check_wakeup_from_daily_record``）
依赖用户**手填的计划起床时间** ``daily_record.sleep_cycle.wakeup``，
和手表测出来的真实起床时间没有关系。

本模块补上这条链路：手机端同步上来的 ``sleep_end_time`` 一旦更新，
且晚于 ``last_goodnight_ts``（说明是这次晚安之后真的醒了），
就清掉 goodnight 状态，让 AI 立刻恢复正常打扰级别。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

from core.utils.logger import get_logger
from core.utils.time_utils import from_timestamp

logger = get_logger("HealthWakeup")

MAIN_SLEEP_MIN_MINUTES = 180
OVERNIGHT_SLEEP_MIN_MINUTES = 90


def _parse_iso_ts(value: Any) -> Optional[float]:
    """把 ISO-8601 字符串解析成 Unix 时间戳，失败返回 None。"""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    # Python 3.10 的 fromisoformat 不认结尾的 Z
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        # 无时区信息时按本地时间处理（手机端上报的通常是本地时刻）
        return dt.timestamp()
    return dt.timestamp()


def classify_sleep_session(wake_event: Dict[str, Any]) -> str:
    """把 Samsung 睡眠区间区分为主睡眠或午睡/小憩。

    时间戳本身完全采用 Samsung Health；这里只决定该区间是否有资格更新
    Daily Record 的“当天起床”。短时白天睡眠不会覆盖主睡眠。
    """
    start_ts = _parse_iso_ts(wake_event.get("sleep_start"))
    end_ts = _parse_iso_ts(wake_event.get("sleep_end"))
    reported_minutes = wake_event.get("sleep_minutes")
    try:
        duration_minutes = float(reported_minutes)
    except (TypeError, ValueError):
        duration_minutes = 0.0
    if start_ts is not None and end_ts is not None and end_ts > start_ts:
        duration_minutes = (end_ts - start_ts) / 60.0

    if duration_minutes >= MAIN_SLEEP_MIN_MINUTES:
        return "main_sleep"
    if (
        duration_minutes >= OVERNIGHT_SLEEP_MIN_MINUTES
        and start_ts is not None
        and end_ts is not None
        and from_timestamp(start_ts).date() != from_timestamp(end_ts).date()
    ):
        return "main_sleep"
    return "nap"


def sync_wakeup_to_daily_record(wake_event: Dict[str, Any]) -> Dict[str, Any]:
    """将健康设备的真实起床时间写入对应自然日记录。"""
    sleep_kind = classify_sleep_session(wake_event)
    if sleep_kind != "main_sleep":
        return {
            "applied": False,
            "reason": "午睡/小憩不更新当天正式起床时间",
            "sleep_kind": sleep_kind,
        }
    sleep_end_ts = _parse_iso_ts(wake_event.get("sleep_end"))
    if sleep_end_ts is None:
        return {"applied": False, "reason": "sleep_end 无法解析"}

    wakeup_dt = from_timestamp(sleep_end_ts)
    sleep_start_ts = _parse_iso_ts(wake_event.get("sleep_start"))
    try:
        from core.services.daily.manager import get_daily_manager

        manager = get_daily_manager()
        record_date = wakeup_dt.strftime("%Y-%m-%d")
        sleep_result = None
        if sleep_start_ts is not None:
            sleep_result = manager.record_sleep(
                from_timestamp(sleep_start_ts).strftime("%H:%M"),
                target_date=record_date,
                source="samsung_health",
            )
        wakeup_result = manager.record_wakeup(
            wakeup_dt.strftime("%H:%M"),
            source="samsung_health",
            target_date=record_date,
        )
        return {
            "applied": True,
            "wakeup": wakeup_dt.strftime("%H:%M"),
            "date": record_date,
            "sleep_result": sleep_result,
            "wakeup_result": wakeup_result,
            "sleep_kind": sleep_kind,
        }
    except Exception as e:
        logger.error("同步健康起床时间到日记录失败: %s", e)
        return {"applied": False, "reason": str(e)}


async def exit_quiet_mode_on_wakeup(wake_event: Dict[str, Any]) -> Dict[str, Any]:
    """检测到起床事件时退出低打扰模式。

    Args:
        wake_event: store 生成的 ``wake_up`` 事件，需含 ``sleep_end``

    Returns:
        处理结果字典，``applied`` 表示是否真的清了状态
    """
    sleep_end_ts = _parse_iso_ts(wake_event.get("sleep_end"))
    if sleep_end_ts is None:
        return {"applied": False, "reason": "sleep_end 无法解析"}

    sleep_kind = classify_sleep_session(wake_event)

    # 日记录是 AI 回答主作息问题的数据源，不能依赖 Active Care 是否启动；
    # 午睡只作为独立健康事件保留，不能覆盖当天正式起床时间。
    daily_record_result = await asyncio.to_thread(
        sync_wakeup_to_daily_record, wake_event
    )

    try:
        from core.services.active_care.core.service import get_active_care_service
        from core.services.active_care.shared.constants import (
            StateKeys,
            build_goodnight_clear_updates,
        )
    except ImportError as e:
        logger.warning("Active Care 模块不可用，跳过退出低打扰: %s", e)
        return {
            "applied": False,
            "reason": "active_care 不可用",
            "daily_record": daily_record_result,
        }

    try:
        service = get_active_care_service()
        if service is None:
            return {
                "applied": False,
                "reason": "active_care 服务未启动",
                "daily_record": daily_record_result,
            }

        state = await service.storage.get_proactive_state()
        last_goodnight_ts = float(state.get(StateKeys.LAST_GOODNIGHT_TS) or 0.0)

        updates: Dict[str, Any] = {
            StateKeys.LAST_SLEEP_SESSION_END_TS: sleep_end_ts,
            StateKeys.LAST_SLEEP_SESSION_SOURCE: "samsung_health",
            StateKeys.LAST_SLEEP_SESSION_KIND: sleep_kind,
        }
        if sleep_kind == "main_sleep":
            updates[StateKeys.LAST_GOODMORNING_TS] = sleep_end_ts
        updates[StateKeys.LAST_SLEEP_SESSION_END_TS] = sleep_end_ts

        sleep_start_ts = _parse_iso_ts(wake_event.get("sleep_start"))
        if sleep_start_ts:
            updates[StateKeys.LAST_SLEEP_SESSION_START_TS] = sleep_start_ts
            updates[StateKeys.LAST_SLEEP_SESSION_DURATION_SECONDS] = max(
                0.0, sleep_end_ts - sleep_start_ts
            )

        cleared_quiet_mode = last_goodnight_ts > 0 and sleep_end_ts > last_goodnight_ts
        stale_for_quiet_mode = last_goodnight_ts > 0 and sleep_end_ts <= last_goodnight_ts
        if cleared_quiet_mode:
            updates.update(build_goodnight_clear_updates())
            updates[StateKeys.LAST_LOW_DISTURBANCE_EXIT_TS] = sleep_end_ts
            updates[StateKeys.LAST_LOW_DISTURBANCE_EXIT_SOURCE] = "samsung_health"

        await service.storage.save_user_sleep_state(updates, immediate=True)
        logger.info(
            "Samsung Health 睡眠已同步(kind=%s, sleep_end=%s, cleared_quiet=%s)",
            sleep_kind,
            wake_event.get("sleep_end"),
            cleared_quiet_mode,
        )
        return {
            "applied": cleared_quiet_mode,
            "state_synced": True,
            "sleep_kind": sleep_kind,
            "wake_up_at": wake_event.get("sleep_end"),
            "reason": (
                "已退出低打扰模式"
                if cleared_quiet_mode
                else "历史睡眠数据未退出当前低打扰"
                if stale_for_quiet_mode
                else "已同步睡眠事实，当前没有低打扰需要退出"
            ),
            "daily_record": daily_record_result,
        }
    except Exception as e:
        logger.error("退出低打扰失败: %s", e)
        return {
            "applied": False,
            "reason": str(e),
            "daily_record": daily_record_result,
        }
