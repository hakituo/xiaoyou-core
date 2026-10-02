"""验证主动消息与主聊天共享已有活动事实，且不跨角色或反向写入。"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.agents.chat_agent_components.persona_system.prompt.components import character_daily_context
from core.services.active_care.checker.checker_state_detector import CheckerStateDetector
from core.services.active_care.decision.content_planner import ContentPlanner
from core.services.active_care.prompt import prompt_builder, prompt_context_builders
from core.services.character_daily import activity_instance, engine
from core.services.character_daily.activity_model import ActivitySlot, ActivityType, DailyPlan


@pytest.fixture
def activity_scene(monkeypatch, tmp_path):
    now = datetime(2026, 9, 11, 16, 0)
    slot = ActivitySlot(ActivityType.SHOPPING, now.replace(hour=15), now.replace(hour=17))
    plan = DailyPlan(role_id="ye", date="2026-09-11", slots=[slot], current_activity=ActivityType.SHOPPING)
    store = activity_instance.ActivityInstanceStore(state_dir=tmp_path)
    instance = activity_instance.ActivityInstance(
        instance_id="fixture-ye", role_id="ye", date=plan.date, slot_key=slot.slot_key(),
        activity="shopping", planned_start=slot.planned_start.isoformat(),
        planned_end=slot.planned_end.isoformat(), purpose="买日用品",
        location="校园超市", companion_mode="alone", transport="步行",
    )
    store.save_many((instance,))
    read = Mock(wraps=store.get_for_slot)
    save = Mock(side_effect=AssertionError("对话不得写活动实例"))
    monkeypatch.setattr(store, "get_for_slot", read)
    monkeypatch.setattr(store, "save_many", save)
    monkeypatch.setattr(activity_instance, "ActivityInstanceStore", lambda: store)
    fake_engine = SimpleNamespace(
        _running=True,
        state=SimpleNamespace(get_plan=lambda role: plan if role == "ye" else None),
        get_current_activity=lambda role: plan.current_activity,
        get_activity_context_text=lambda role: f"{role}正在买东西",
        get_peer_chat_summary=lambda: "别的角色互聊",
    )
    monkeypatch.setattr(engine, "get_character_daily_engine", lambda: fake_engine)
    monkeypatch.setattr(character_daily_context, "get_current_time", lambda: now)
    monkeypatch.setattr("core.character.runtime_roles.get_autonomous_role_ids", lambda **_: frozenset({"ye", "ling"}))
    return plan, slot, read, save


def test_shared_persisted_facts_are_read_only(activity_scene):
    _, _, read, save = activity_scene
    chat = character_daily_context.build_character_daily_context("core_ye.json")
    active = prompt_context_builders.build_role_activity_context_text("core_ye.json")
    assert active == chat
    assert "校园超市" in active and "买日用品" in active and "步行" in active
    assert "completion=unknown" in active
    assert all(call.kwargs["resolve_if_missing"] is False for call in read.call_args_list)
    save.assert_not_called()


def test_missing_instance_keeps_only_base_activity(activity_scene):
    _, _, read, save = activity_scene
    read.return_value = None
    text = prompt_context_builders.build_role_activity_context_text("core_ye.json")
    assert "daily_activity=出门买东西" in text and "校园超市" not in text
    assert "unknown=location,companions,progress" in text
    save.assert_not_called()


def test_explicit_current_location_overrides_plan_in_both_paths(activity_scene):
    facts = {"location": "宿舍", "activity": "休息"}
    chat = character_daily_context.build_character_daily_context("core_ye.json", current_facts=facts)
    active = prompt_context_builders.build_role_activity_context_text("core_ye.json", current_facts=facts)
    assert chat == active
    assert "confirmed_location=宿舍" in chat and "校园超市" not in chat
    assert "scheduled_activity=出门买东西" in chat
    assert "confirmed_activity=休息" in chat
    assert "known_details=" not in chat
    activity_scene[3].assert_not_called()


def test_execution_override_does_not_inject_planned_location(activity_scene):
    plan, _, read, _ = activity_scene
    plan.current_activity = ActivityType.SLEEPING
    text = prompt_context_builders.build_role_activity_context_text("core_ye.json")
    assert "校园超市" not in text
    read.assert_not_called()


def test_unknown_or_non_autonomous_role_has_no_fallback(activity_scene):
    assert prompt_context_builders.build_role_activity_context_text("unknown.json") == ""
    assert prompt_context_builders.build_role_activity_context_text("core_rushuang.json") == ""


def test_decision_receives_only_selected_autonomous_role(activity_scene):
    detector = CheckerStateDetector(SimpleNamespace())
    context = detector._get_character_daily_context("core_ye.json")
    assert set(context) == {"ye"}
    assert "校园超市" in context["ye"]["activity_facts"]
    assert detector._get_character_daily_context("unknown.json") == {}


def test_decision_uses_generic_role_facts_and_respects_sleep():
    planner = ContentPlanner.__new__(ContentPlanner)
    metrics = dict(sleep_session_active=False, reduced_mode_active=False,
                   reduced_mode_reason="", sleep_duration_text="")
    context = {"character_daily": {"new_role": {
        "activity": "shopping", "activity_facts": "在校园超市买日用品",
    }}}
    text = "".join(planner._build_dynamic_constraints(context, metrics, 16, 100))
    assert "校园超市" in text and "没有新内容就 defer" in text
    context["character_daily"]["new_role"]["activity"] = "sleeping"
    text = "".join(planner._build_dynamic_constraints(context, metrics, 16, 100))
    assert "正在睡觉，应 defer" in text


def test_activity_facts_survive_task_filter_without_polluting_notifications():
    sections = [prompt_builder.PromptSection("role_activity_anchor", "校园超市")]
    for task in ("share_thought", "proactive_chat", "activity_return_proactive"):
        assert prompt_builder._filter_dynamic_sections(task, sections, "休息一下") == sections
    assert prompt_builder._filter_dynamic_sections("usage_limit_exceeded", sections) == []
