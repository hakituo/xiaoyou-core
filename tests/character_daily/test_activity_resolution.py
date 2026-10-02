"""角色日常空档期活动解析测试。"""

from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock

from core.services.character_daily.activity_model import (
    ActivitySlot,
    ActivityType,
    DailyState,
    DailyPlan,
)
from core.services.character_daily.activity_resolution import resolve_planned_activity
from core.services.character_daily.activity_state_sync import sync_current_activities


def test_gap_after_non_sleep_slot_falls_back_to_idle():
    """非睡眠活动后的空档不应继续卡在上一项活动。"""
    plan = DailyPlan(
        role_id="aveline",
        date="2026-06-29",
        slots=[
            ActivitySlot(
                activity=ActivityType.DINNER,
                planned_start=datetime(2026, 6, 29, 17, 40),
                planned_end=datetime(2026, 6, 29, 18, 15),
                chat_eligible=False,
            ),
            ActivitySlot(
                activity=ActivityType.PHONE_SCROLLING,
                planned_start=datetime(2026, 6, 29, 19, 0),
                planned_end=datetime(2026, 6, 29, 19, 40),
            ),
        ],
    )

    activity = resolve_planned_activity(plan, datetime(2026, 6, 29, 18, 30))

    assert activity == ActivityType.IDLE


def test_gap_after_sleep_slot_keeps_waking_up_temporarily():
    """刚睡醒后的短空档仍保留 waking_up。"""
    plan = DailyPlan(
        role_id="ling",
        date="2026-06-29",
        slots=[
            ActivitySlot(
                activity=ActivityType.SLEEPING,
                planned_start=datetime(2026, 6, 28, 23, 30),
                planned_end=datetime(2026, 6, 29, 8, 0),
                chat_eligible=False,
            ),
            ActivitySlot(
                activity=ActivityType.BREAKFAST,
                planned_start=datetime(2026, 6, 29, 8, 30),
                planned_end=datetime(2026, 6, 29, 9, 0),
                chat_eligible=False,
            ),
        ],
    )

    activity = resolve_planned_activity(plan, datetime(2026, 6, 29, 8, 5))

    assert activity == ActivityType.WAKING_UP


def test_gap_long_after_sleep_slot_falls_back_to_idle():
    """起床缓冲过长后仍无 slot，应回落到 idle。"""
    plan = DailyPlan(
        role_id="ling",
        date="2026-06-29",
        slots=[
            ActivitySlot(
                activity=ActivityType.SLEEPING,
                planned_start=datetime(2026, 6, 28, 23, 30),
                planned_end=datetime(2026, 6, 29, 8, 0),
                chat_eligible=False,
            ),
        ],
    )

    activity = resolve_planned_activity(plan, datetime(2026, 6, 29, 8, 12))

    assert activity == ActivityType.IDLE


def test_gap_after_sleep_slot_accepts_timezone_aware_now():
    """带时区的当前时间也应能参与计划槽位比较。"""
    plan = DailyPlan(
        role_id="ling",
        date="2026-06-29",
        slots=[
            ActivitySlot(
                activity=ActivityType.SLEEPING,
                planned_start=datetime(2026, 6, 28, 23, 30),
                planned_end=datetime(2026, 6, 29, 8, 0),
                chat_eligible=False,
            ),
            ActivitySlot(
                activity=ActivityType.BREAKFAST,
                planned_start=datetime(2026, 6, 29, 8, 30),
                planned_end=datetime(2026, 6, 29, 9, 0),
                chat_eligible=False,
            ),
        ],
    )

    aware_now = datetime(2026, 6, 29, 8, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
    activity = resolve_planned_activity(plan, aware_now)

    assert activity == ActivityType.WAKING_UP


def test_sync_current_activities_saves_when_activity_changes():
    """活动切换后应自动落盘，及时清掉旧的 waking_up。"""
    plan = DailyPlan(
        role_id="ling",
        date="2026-06-29",
        current_activity=ActivityType.WAKING_UP,
    )
    state = DailyState(date="2026-06-29")
    state.set_plan(plan)
    store = MagicMock()

    def updater(target_plan: DailyPlan, now: datetime):
        target_plan.current_activity = ActivityType.IDLE

    changed = sync_current_activities(
        state=state,
        role_ids=("ling",),
        updater=updater,
        store=store,
        now=datetime(2026, 6, 29, 8, 12),
    )

    assert changed is True
    store.save.assert_called_once_with(state)


def test_sync_current_activities_skips_save_when_activity_unchanged():
    """活动未变化时不应反复写盘。"""
    plan = DailyPlan(
        role_id="aveline",
        date="2026-06-29",
        current_activity=ActivityType.READING,
    )
    state = DailyState(date="2026-06-29")
    state.set_plan(plan)
    store = MagicMock()

    def updater(target_plan: DailyPlan, now: datetime):
        target_plan.current_activity = ActivityType.READING

    changed = sync_current_activities(
        state=state,
        role_ids=("aveline",),
        updater=updater,
        store=store,
        now=datetime(2026, 6, 29, 20, 0),
    )

    assert changed is False
    store.save.assert_not_called()
