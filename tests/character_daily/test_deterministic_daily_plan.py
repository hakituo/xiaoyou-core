"""角色每日计划接入共享确定性引擎的回归测试。"""

from datetime import datetime, timedelta

import pytest

from core.services.character_daily.activity_model import (
    ActivitySlot,
    ActivityType,
    DailyPlan,
    DailyState,
)
from core.services.character_daily.config import (
    ActivityTemplate,
    CharacterDailyConfig,
    LLMPlanConfig,
    RoleScheduleTemplate,
    TimeBlock,
)
from core.services.character_daily.daily_plan import DailyPlanGenerator


def _template(role_id: str = "demo") -> RoleScheduleTemplate:
    return RoleScheduleTemplate(
        role_id=role_id,
        wake_time="07:00",
        sleep_time="23:00",
        time_blocks=[
            TimeBlock(
                period="morning",
                start="07:00",
                end="10:00",
                fixed=[ActivityTemplate("waking_up", 20, 20)],
                pool=[
                    ActivityTemplate("reading", 50, 60, 2.0),
                    ActivityTemplate("gaming", 50, 60, 2.0),
                ],
            )
        ],
    )


def _signature(plan: DailyPlan):
    return [
        (
            slot.activity,
            slot.planned_start,
            slot.planned_end,
            slot.flexible,
        )
        for slot in plan.slots
    ]


def test_same_role_and_date_is_stable() -> None:
    generator = DailyPlanGenerator({"demo": _template()})
    first = generator.generate("demo", "2099-01-05")
    second = generator.generate("demo", "2099-01-05")
    assert first is not None and second is not None
    assert _signature(first) == _signature(second)


def test_yesterday_high_frequency_activity_gets_repeat_penalty() -> None:
    generator = DailyPlanGenerator({"demo": _template()})
    baseline = generator.generate("demo", "2099-01-06")
    assert baseline is not None
    previous = DailyPlan(
        role_id="demo",
        date="2099-01-05",
        slots=[
            ActivitySlot(
                activity=ActivityType.READING,
                planned_start=datetime(2099, 1, 5, 8, 0) + timedelta(hours=index),
                planned_end=datetime(2099, 1, 5, 9, 0) + timedelta(hours=index),
            )
            for index in range(4)
        ],
    )
    punished = generator.generate("demo", "2099-01-06", previous_plan=previous)
    assert punished is not None
    baseline_reading = sum(
        slot.activity == ActivityType.READING for slot in baseline.slots
    )
    punished_reading = sum(
        slot.activity == ActivityType.READING for slot in punished.slots
    )
    assert punished_reading < baseline_reading


def test_sleeping_slot_keeps_next_day_wake_time() -> None:
    plan = DailyPlanGenerator({"demo": _template()}).generate(
        "demo", "2099-01-05"
    )
    assert plan is not None
    sleeping = [slot for slot in plan.slots if slot.activity == ActivityType.SLEEPING]
    assert len(sleeping) == 1
    assert sleeping[0].planned_start == datetime(2099, 1, 5, 23, 0)
    assert sleeping[0].planned_end == datetime(2099, 1, 6, 7, 0)
    assert sleeping[0].flexible is False
    assert sleeping[0].chat_eligible is False


def test_rest_day_extras_are_template_driven_for_any_role() -> None:
    template = RoleScheduleTemplate(
        role_id="future_role",
        wake_time="07:00",
        sleep_time="23:00",
        time_blocks=[
            TimeBlock(
                period="morning",
                start="07:00",
                end="10:00",
                pool=[ActivityTemplate("studying", 60, 60, 1.0)],
            )
        ],
        rest_day_extras={
            "morning": [ActivityTemplate("gaming", 60, 60, 5.0)]
        },
    )
    generator = DailyPlanGenerator({"future_role": template})

    weekday = generator.generate("future_role", "2026-08-28")
    weekend = generator.generate("future_role", "2026-08-29")

    assert weekday is not None and weekend is not None
    assert all(slot.activity != ActivityType.GAMING for slot in weekday.slots)
    assert any(slot.activity == ActivityType.GAMING for slot in weekend.slots)


def test_engine_ignores_legacy_llm_plan_enabled(monkeypatch) -> None:
    import core.services.character_daily.engine as engine_module

    monkeypatch.setattr(engine_module, "load_schedule_templates", lambda: {})
    monkeypatch.setattr(engine_module, "get_sleep_manager", lambda: object())
    config = CharacterDailyConfig(llm_plan=LLMPlanConfig(enabled=True))

    engine = engine_module.CharacterDailyEngine(config=config)

    assert isinstance(engine._generator, DailyPlanGenerator)
    assert "LLMPlanGenerator" not in vars(engine_module)


@pytest.mark.asyncio
async def test_engine_generates_for_every_loaded_template(monkeypatch) -> None:
    """运行时角色集合必须来自模板键，不能受兼容常量限制。"""
    import core.services.character_daily.engine as engine_module

    templates = {
        "demo": _template("demo"),
        "future_role": _template("future_role"),
    }
    monkeypatch.setattr(
        engine_module,
        "load_schedule_templates",
        lambda: templates,
    )
    monkeypatch.setattr(engine_module, "get_sleep_manager", lambda: object())
    engine = engine_module.CharacterDailyEngine(config=CharacterDailyConfig())
    engine._state = DailyState(date="2099-01-05")

    saved: list[set[str]] = []

    class _Store:
        def save(self, state: DailyState, immediate: bool = False) -> None:
            assert immediate is True
            saved.append(set(state.plans))

    engine._store = _Store()
    generated = await engine._ensure_daily_plans("2099-01-05")

    assert engine.managed_role_ids == ("demo", "future_role")
    assert generated == ("demo", "future_role")
    assert set(engine.state.plans) == set(templates)
    assert saved == [set(templates)]
