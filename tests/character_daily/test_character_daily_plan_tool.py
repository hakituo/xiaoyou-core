from __future__ import annotations

from datetime import datetime

import pytest

from core.services.character_daily.activity_model import ActivitySlot, ActivityType, DailyPlan, DailyState
from core.services.character_daily.config import ActivityTemplate, TimeBlock
from core.services.character_daily.daily_plan import DailyPlanGenerator
from core.tools.character_daily_plan_tool import GetCharacterDailyPlanTool


def _build_demo_plan(role_id: str, hour_offset: int = 0) -> DailyPlan:
    base_date = "2026-06-28"
    slots = [
        ActivitySlot(
            activity=ActivityType.WAKING_UP,
            planned_start=datetime(2026, 6, 28, 7 + hour_offset, 0),
            planned_end=datetime(2026, 6, 28, 7 + hour_offset, 20),
            flexible=False,
            chat_eligible=False,
        ),
        ActivitySlot(
            activity=ActivityType.CREATIVE_HOBBY if role_id == "aveline" else ActivityType.GAMING,
            planned_start=datetime(2026, 6, 28, 7 + hour_offset, 20),
            planned_end=datetime(2026, 6, 28, 8 + hour_offset, 0),
            flexible=True,
            chat_eligible=True,
        ),
    ]
    return DailyPlan(role_id=role_id, date=base_date, slots=slots)


@pytest.mark.asyncio
async def test_character_daily_plan_tool_reads_self_and_peer(monkeypatch):
    state = DailyState(date="2026-06-28")
    state.set_plan(_build_demo_plan("aveline"))
    state.set_plan(_build_demo_plan("ling", hour_offset=1))

    monkeypatch.setattr(
        "core.tools.character_daily_plan_tool._resolve_scope_from_active_persona",
        lambda: "aveline",
    )
    monkeypatch.setattr(
        GetCharacterDailyPlanTool,
        "_load_state",
        staticmethod(lambda: state),
    )

    tool = GetCharacterDailyPlanTool()
    result = await tool._run(target="both", detail_level="summary")

    assert "七濑澪" in result
    assert "Ling" in result
    assert "角色日常计划" in result
    assert "做手工/写写画画" in result or "玩游戏" in result


def test_rest_day_pool_expands_and_relaxes():
    generator = DailyPlanGenerator()
    block = TimeBlock(
        period="afternoon_activity",
        start="14:00",
        end="17:00",
        pool=[
            ActivityTemplate("studying", 45, 90, 3.0),
            ActivityTemplate("reading", 30, 60, 2.0),
        ],
    )

    weekday_pool = generator._build_effective_pool("aveline", block, is_rest_day=False)
    rest_day_pool = generator._build_effective_pool("aveline", block, is_rest_day=True)

    weekday_names = {item.activity for item in weekday_pool}
    rest_day_names = {item.activity for item in rest_day_pool}
    weekday_study_weight = next(item.weight for item in weekday_pool if item.activity == "studying")
    rest_day_study_weight = next(item.weight for item in rest_day_pool if item.activity == "studying")

    assert "creative_hobby" not in weekday_names
    assert {"creative_hobby", "exercising"}.issubset(rest_day_names)
    assert rest_day_study_weight < weekday_study_weight
