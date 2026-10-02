"""通用角色运行时与 ActivityInstance 契约测试。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

from core.agents.chat_agent_components.persona_system.prompt.components import (
    character_daily_context,
)
from core.services.character_daily import activity_instance as activity_instance_module
from core.services.character_daily.activity_instance import (
    ActivityInstance,
    ActivityInstanceResolver,
    ActivityInstanceStore,
)
from core.services.character_daily.activity_model import (
    ActivitySlot,
    ActivityType,
    DailyPlan,
)
from core.services.character_daily.activity_return import core as activity_return_core


def _shopping_plan(role_id: str = "ling") -> tuple[DailyPlan, ActivitySlot]:
    slot = ActivitySlot(
        activity=ActivityType.SHOPPING,
        planned_start=datetime(2026, 9, 12, 15, 0),
        planned_end=datetime(2026, 9, 12, 17, 0),
    )
    plan = DailyPlan(
        role_id=role_id,
        date="2026-09-12",
        slots=[slot],
        current_activity=ActivityType.SHOPPING,
    )
    return plan, slot


def test_activity_instance_resolution_is_stable(monkeypatch):
    """同一角色、日期、槽位必须得到同一份具体生活事实。"""
    monkeypatch.setattr(activity_instance_module.time, "time", lambda: 123.0)
    profiles = {
        "ling": {
            "shopping": {
                "purpose": [{"value": "买日用品", "weight": 1}],
                "companion_mode": [{"value": "classmate", "weight": 1}],
                "location": [{"value": "学校附近商场", "weight": 1}],
                "transport": [{"value": "地铁", "weight": 1}],
            }
        }
    }
    resolver = ActivityInstanceResolver(profiles=profiles)
    plan, slot = _shopping_plan()

    first = resolver.resolve(plan.role_id, plan.date, slot)
    second = resolver.resolve(plan.role_id, plan.date, slot)

    assert first == second
    assert first.purpose == "买日用品"
    assert first.companion_mode == "classmate"
    assert first.location == "学校附近商场"
    assert first.transport == "地铁"


def test_activity_instance_store_keeps_first_resolved_fact(tmp_path):
    """Nightly 重跑不能覆盖同一槽位已经确定的事实。"""
    plan, slot = _shopping_plan()
    first = ActivityInstance(
        instance_id="first",
        role_id=plan.role_id,
        date=plan.date,
        slot_key=slot.slot_key(),
        activity=slot.activity.value,
        planned_start=slot.planned_start.isoformat(),
        planned_end=slot.planned_end.isoformat(),
        purpose="买日用品",
        companion_mode="classmate",
    )
    second = replace(first, instance_id="second", purpose="临时改买衣服")
    store = ActivityInstanceStore(state_dir=tmp_path)

    assert store.save_many((first,)) == 1
    assert store.save_many((second,)) == 0
    persisted = store.get(plan.role_id, plan.date, slot.slot_key())

    assert persisted is not None
    assert persisted.instance_id == "first"
    assert persisted.purpose == "买日用品"


def test_non_autonomous_role_does_not_generate_instances():
    """普通角色仍可有轻量日程，但不生成持续生活 ActivityInstance。"""
    plan, _ = _shopping_plan(role_id="xiaolu")
    resolver = ActivityInstanceResolver(profiles={})

    assert resolver.resolve_plan(plan) == ()


def test_main_chat_injects_persisted_activity_instance(monkeypatch):
    """主对话应读 Nightly 已落盘的具体事实，不在聊天路径临时编故事。"""
    plan, slot = _shopping_plan()
    instance = ActivityInstance(
        instance_id="ling-shopping",
        role_id="ling",
        date=plan.date,
        slot_key=slot.slot_key(),
        activity="shopping",
        planned_start=slot.planned_start.isoformat(),
        planned_end=slot.planned_end.isoformat(),
        purpose="买日用品",
        companion_mode="classmate",
        location="学校附近商场",
        transport="地铁",
    )
    fake_store = SimpleNamespace()
    calls: list[bool] = []

    def get_for_slot(_plan, _slot, *, resolve_if_missing=True):
        calls.append(resolve_if_missing)
        return instance

    fake_store.get_for_slot = get_for_slot
    fake_engine = SimpleNamespace(
        state=SimpleNamespace(get_plan=lambda role_id: plan if role_id == "ling" else None),
        get_current_activity=lambda role_id: ActivityType.SHOPPING,
    )

    from core.services.character_daily import engine as engine_module

    monkeypatch.setattr(character_daily_context, "resolve_persona_slug_scope", lambda _: "ling")
    monkeypatch.setattr(
        character_daily_context,
        "get_current_time",
        lambda: datetime(2026, 9, 12, 15, 30),
    )
    monkeypatch.setattr(engine_module, "get_character_daily_engine", lambda: fake_engine)
    monkeypatch.setattr(
        activity_instance_module,
        "ActivityInstanceStore",
        lambda: fake_store,
    )

    text = character_daily_context.build_character_daily_context("core_ling.json")

    assert calls == [False]
    assert "daily_activity=出门买东西" in text
    assert "买日用品" in text
    assert "和同学一起" in text
    assert "学校附近商场" in text
    assert "地铁" in text
    assert "completion=unknown" in text

    # 实例缺失时仍可知道活动，但不能把缺失解释成默认独处或尚未开始。
    fake_store.get_for_slot = lambda *_args, **kwargs: (
        calls.append(kwargs["resolve_if_missing"])
    )
    fallback = character_daily_context.build_character_daily_context("core_ling.json")
    assert calls == [False, False]
    assert "daily_activity=出门买东西" in fallback and "学校附近商场" not in fallback
    assert "unknown=location,companions,progress" in fallback


def test_activity_return_uses_generic_autonomous_role_gate(monkeypatch):
    """活动回归资格应来自通用角色运行时，而不是 SleepManager 私有白名单。"""
    monkeypatch.setattr(activity_return_core, "is_autonomous_role", lambda _: False)

    result = asyncio.run(
        activity_return_core.send_activity_return_message(
            conversation_id="conversation-1",
            role_id="xiaolu",
            activity="shopping",
            return_type="work",
        )
    )

    assert result["delivered"] is False
    assert result["reason"] == "role_not_autonomous"
