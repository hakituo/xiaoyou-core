"""角色日常执行态与做饭联动测试。"""

from __future__ import annotations

from datetime import datetime

from core.services.character_daily.activity_model import (
    ActivityExecutionStatus,
    ActivitySlot,
    ActivityType,
    DailyPlan,
)
from core.services.character_daily.plan_execution import sync_plan_execution
from core.services.character_daily.plan_view import format_plan_for_tool


class _FakeLifeService:
    def __init__(self) -> None:
        self.inventory_events: list[tuple[str, int, float]] = []

    def add_food_to_inventory(self, food_id: str, quantity: int, expire_at_ts: float) -> None:
        self.inventory_events.append((food_id, quantity, expire_at_ts))


def test_sync_plan_execution_marks_completion_and_cooking_output(monkeypatch):
    """做饭槽位结束后应落为已完成，并产出可食用库存。"""
    fake_service = _FakeLifeService()
    monkeypatch.setattr(
        "core.services.life_simulation.service.get_life_simulation_service",
        lambda: fake_service,
    )

    plan = DailyPlan(
        role_id="aveline",
        date="2026-07-01",
        slots=[
            ActivitySlot(
                activity=ActivityType.COOKING,
                planned_start=datetime(2026, 7, 1, 7, 0),
                planned_end=datetime(2026, 7, 1, 7, 30),
                chat_eligible=False,
            ),
            ActivitySlot(
                activity=ActivityType.BREAKFAST,
                planned_start=datetime(2026, 7, 1, 7, 30),
                planned_end=datetime(2026, 7, 1, 8, 0),
                chat_eligible=False,
            ),
        ],
    )

    changed = sync_plan_execution(plan, datetime(2026, 7, 1, 7, 45))

    assert changed is True
    assert plan.slots[0].execution_status == ActivityExecutionStatus.COMPLETED
    assert plan.slots[0].produced_food_ids == ["sandwich", "soy_milk"]
    assert plan.slots[1].execution_status == ActivityExecutionStatus.IN_PROGRESS
    assert [item[0] for item in fake_service.inventory_events] == ["sandwich", "soy_milk"]


def test_sync_plan_execution_is_idempotent_for_completed_cooking(monkeypatch):
    """已完成的做饭槽位不应重复产出库存。"""
    fake_service = _FakeLifeService()
    monkeypatch.setattr(
        "core.services.life_simulation.service.get_life_simulation_service",
        lambda: fake_service,
    )

    cooking_slot = ActivitySlot(
        activity=ActivityType.COOKING,
        planned_start=datetime(2026, 7, 1, 12, 0),
        planned_end=datetime(2026, 7, 1, 12, 25),
        chat_eligible=False,
    )
    lunch_slot = ActivitySlot(
        activity=ActivityType.LUNCH,
        planned_start=datetime(2026, 7, 1, 12, 25),
        planned_end=datetime(2026, 7, 1, 12, 50),
        chat_eligible=False,
    )
    plan = DailyPlan(
        role_id="ling",
        date="2026-07-01",
        slots=[cooking_slot, lunch_slot],
    )

    assert sync_plan_execution(plan, datetime(2026, 7, 1, 12, 40)) is True
    first_events = list(fake_service.inventory_events)

    assert sync_plan_execution(plan, datetime(2026, 7, 1, 12, 45)) is False
    assert fake_service.inventory_events == first_events
    assert cooking_slot.produced_food_ids == ["sandwich"]


def test_format_plan_for_tool_shows_execution_status_and_output(monkeypatch):
    """计划展示文本应带出执行状态和做饭产物。"""
    fake_service = _FakeLifeService()
    monkeypatch.setattr(
        "core.services.life_simulation.service.get_life_simulation_service",
        lambda: fake_service,
    )

    plan = DailyPlan(
        role_id="aveline",
        date="2026-07-01",
        slots=[
            ActivitySlot(
                activity=ActivityType.COOKING,
                planned_start=datetime(2026, 7, 1, 17, 30),
                planned_end=datetime(2026, 7, 1, 18, 0),
                chat_eligible=False,
            ),
            ActivitySlot(
                activity=ActivityType.DINNER,
                planned_start=datetime(2026, 7, 1, 18, 0),
                planned_end=datetime(2026, 7, 1, 18, 30),
                chat_eligible=False,
            ),
        ],
    )
    sync_plan_execution(plan, datetime(2026, 7, 1, 18, 5))

    result = format_plan_for_tool(
        plan,
        role_id="aveline",
        detail_level="full",
        now=datetime(2026, 7, 1, 18, 5),
    )

    assert "已完成" in result
    assert "beef_noodle" in result
