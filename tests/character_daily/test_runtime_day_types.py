"""角色通用运行时与日类型日程测试。"""

from datetime import time

from core.character.runtime_roles import get_autonomous_role_ids
from core.services.character_daily.config import load_schedule_templates
from core.services.character_daily.daily_plan import DailyPlanGenerator


def _signature(plan):
    return tuple(
        (
            slot.activity.value,
            slot.planned_start.strftime("%H:%M"),
            slot.planned_end.strftime("%H:%M"),
        )
        for slot in plan.slots
    )


def _activities_between(plan, start: time, end: time) -> list[str]:
    return [
        slot.activity.value
        for slot in plan.slots
        if start <= slot.planned_start.time() < end
    ]


def _assert_cooking_before_meal(activities: list[str], meal: str) -> None:
    assert activities.count(meal) == 1
    assert activities.count("cooking") == 1
    assert activities.index("cooking") < activities.index(meal)


def test_autonomous_roles_are_character_runtime_capability():
    """当前自主生活角色由通用运行时统一声明。

    主动消息与日记生成都按这个集合取角色；Ye（ye）已于 2026-10-01 从此集合
    移除（不再发消息、不再写日记），Ling（ling）与Lin（lin）仍是已注册角色，
    能正常对话、保留日程配置，但不拥有自主运行时。
    这里刻意写死集合：新增或移除角色时必须显式改这一行，避免白名单悄悄漂移。
    """
    assert get_autonomous_role_ids() == frozenset({"aveline"})


def test_ling_workday_and_rest_day_use_distinct_skeletons():
    """休息日必须是一套独立生活骨架，而不是工作日仅调权重。"""
    generator = DailyPlanGenerator(load_schedule_templates())

    workday = generator.generate("ling", "2026-09-11")  # Friday
    rest_day = generator.generate("ling", "2026-09-12")  # Saturday

    assert workday is not None
    assert rest_day is not None
    assert _signature(workday) != _signature(rest_day)


def test_aveline_meals_are_unique_and_prepared_before_eating():
    generator = DailyPlanGenerator(load_schedule_templates())

    workday = generator.generate("aveline", "2026-09-11")  # Friday
    rest_day = generator.generate("aveline", "2026-09-12")  # Saturday

    assert workday is not None
    assert rest_day is not None

    _assert_cooking_before_meal(
        _activities_between(workday, time(7, 0), time(8, 30)),
        "breakfast",
    )
    _assert_cooking_before_meal(
        _activities_between(rest_day, time(8, 30), time(10, 30)),
        "breakfast",
    )
    _assert_cooking_before_meal(
        _activities_between(rest_day, time(12, 30), time(13, 30)),
        "lunch",
    )
    _assert_cooking_before_meal(
        _activities_between(rest_day, time(18, 30), time(19, 30)),
        "dinner",
    )
