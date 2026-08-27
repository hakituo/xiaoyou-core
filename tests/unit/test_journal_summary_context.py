"""`SummaryContextLoader` 的时区兼容回归测试。"""

import asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from core.services.character_daily.activity_model import (
    ActivitySlot,
    ActivityType,
    DailyPlan,
    DailyState,
)
from core.services.journal.summary_context import SummaryContextLoader


class _DummyStateStore:
    def __init__(self, state: DailyState) -> None:
        self._state = state

    def load(self) -> DailyState:
        return self._state


def test_load_character_daily_activities_accepts_timezone_aware_datetime():
    """每日总结上下文加载器应兼容 aware/naive 时间混用。"""
    plan = DailyPlan(
        role_id="aveline",
        date="2026-06-29",
        slots=[
            ActivitySlot(
                activity=ActivityType.READING,
                planned_start=datetime(2026, 6, 29, 20, 0),
                planned_end=datetime(2026, 6, 29, 21, 0),
            ),
            ActivitySlot(
                activity=ActivityType.GAMING,
                planned_start=datetime(2026, 6, 29, 21, 0),
                planned_end=datetime(2026, 6, 29, 22, 0),
            ),
        ],
        today_peer_chat_count=2,
    )
    state = DailyState(date="2026-06-29")
    state.set_plan(plan)

    loader = SummaryContextLoader(storage=MagicMock())
    aware_dt = datetime(2026, 6, 29, 21, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    with patch(
        "core.services.character_daily.state.DailyStateStore",
        return_value=_DummyStateStore(state),
    ):
        result = asyncio.run(loader.load_character_daily_activities(aware_dt))

    assert result["aveline"]["peer_chat_count"] == 2
    assert result["aveline"]["activities"] == [
        {
            "activity": "reading",
            "verb": "看完书",
            "time": "20:00",
            "status": "completed",
        },
        {
            "activity": "gaming",
            "verb": "打完游戏",
            "time": "21:00",
            "status": "ongoing",
        },
    ]
