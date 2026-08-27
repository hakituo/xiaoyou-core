"""
角色日常活动解析辅助。

负责把 DailyPlan 的时间槽位映射成“当前应该表现出的活动”。
"""

from datetime import datetime, timedelta

from core.services.character_daily.activity_model import (
    ActivityType,
    DailyPlan,
    normalize_datetime_for_reference,
)

# waking_up 只保留刚起床后的短窗口，避免被误当成长时间状态。
_WAKE_UP_GRACE = timedelta(minutes=10)


def resolve_planned_activity(plan: DailyPlan, now: datetime) -> ActivityType:
    """解析当前时刻应使用的计划活动。

    规则：
    1. 命中当前 slot 时，直接使用 slot.activity。
    2. 早晨刚从 sleeping 结束后的短空档，保留为 waking_up。
    3. 其他空档统一回落到 idle，避免长时间卡在上一项活动。
    """
    slot = plan.find_current_slot(now)
    if slot:
        return slot.activity

    previous_slot = _find_previous_slot(plan, now)
    if _should_keep_waking_up(previous_slot, now):
        return ActivityType.WAKING_UP

    return ActivityType.IDLE


def _find_previous_slot(plan: DailyPlan, now: datetime):
    previous = None
    for slot in plan.slots:
        normalized_now = normalize_datetime_for_reference(slot.planned_end, now)
        if slot.planned_end <= normalized_now:
            previous = slot
            continue
        break
    return previous


def _should_keep_waking_up(previous_slot, now: datetime) -> bool:
    if previous_slot is None:
        return False
    if previous_slot.activity != ActivityType.SLEEPING:
        return False
    normalized_now = normalize_datetime_for_reference(previous_slot.planned_end, now)
    return normalized_now - previous_slot.planned_end <= _WAKE_UP_GRACE
