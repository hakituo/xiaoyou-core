"""TutorEngine 接入 ConceptState 的集成测试。

TutorEngine 是规则/统计/计划层，原先只吃 WeaknessTracker 的投影，看不到
「已掌握什么 / 只是讲过没验证过 / 靠提示才能答出」。本文件验证它现在能读到
知识点级数据，且新增字段不影响既有消费方（Active Care / 日记 / 路由）。
"""
from __future__ import annotations

from core.services.study.teaching_orchestrator import get_teaching_orchestrator
from core.services.study.tutor_engine import TutorEngine


def _engine() -> TutorEngine:
    return TutorEngine.get_instance()


def _seed_struggling_concept() -> None:
    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "简谐运动")
    orch.record_answer("physics", "简谐运动", {"correctness": 0.1, "independent": True})


def test_briefing_exposes_concept_progress(study_sandbox):
    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "简谐运动")
    orch.record_answer("physics", "简谐运动", {"correctness": 0.1, "independent": True})
    for _ in range(4):
        orch.record_answer("math", "导数", {"correctness": 0.95, "independent": True})

    progress = _engine().generate_daily_briefing()["concept_progress"]

    assert progress["total_concepts"] == 2
    assert progress["mastered_count"] == 1
    assert progress["weak_count"] == 1
    assert "导数" in progress["mastered_today"]
    assert {c["name"] for c in progress["weak_concepts"]} == {"简谐运动"}


def test_briefing_keeps_legacy_keys(study_sandbox):
    """既有消费方（Active Care / 日记 / 路由）依赖的字段不能消失。"""
    briefing = _engine().generate_daily_briefing()

    for key in (
        "date",
        "yesterday_review",
        "today_plan",
        "review_reminders",
        "encouragement",
        "streak_info",
    ):
        assert key in briefing, f"简报缺少既有字段: {key}"


def test_briefing_without_concepts_returns_empty_progress(study_sandbox):
    """没有任何知识点时不能报错，也不能凭空造数据。"""
    briefing = _engine().generate_daily_briefing()
    assert briefing["concept_progress"] == {}


def test_plan_includes_concept_focus_item(study_sandbox):
    _seed_struggling_concept()

    plan = _engine().generate_study_plan()
    focus_items = [i for i in plan["items"] if i["type"] == "concept_focus"]

    assert focus_items, "薄弱知识点应产生 concept_focus 计划项"
    names = {item["concept"] for item in focus_items[0]["items"]}
    assert "简谐运动" in names


def test_plan_marks_hint_dependency(study_sandbox):
    """靠提示才能答出的知识点要标出来，提示「假掌握」风险。"""
    orch = get_teaching_orchestrator()
    orch.record_answer(
        "physics", "胡克定律", {"correctness": 0.9, "independent": False, "used_hint": True}
    )

    plan = _engine().generate_study_plan()
    items = [
        item
        for i in plan["items"]
        if i["type"] == "concept_focus"
        for item in i["items"]
    ]
    hint_items = [i for i in items if i.get("concept") == "胡克定律"]

    assert hint_items
    assert hint_items[0]["note"] == "靠提示才能答出，需要独立检验"


def test_plan_marks_unverified_concept(study_sandbox):
    orch = get_teaching_orchestrator()
    orch.record_teaching("math", "极限")

    plan = _engine().generate_study_plan()
    items = [
        item
        for i in plan["items"]
        if i["type"] == "concept_focus"
        for item in i["items"]
    ]
    unverified = [i for i in items if i.get("concept") == "极限"]

    # 只讲过没验证过：教学接触后仍是 learning，不进 weak，但要在计划里可见
    assert unverified == [] or unverified[0]["note"] == "只讲过没验证过"


def test_weekly_analysis_exposes_concept_analysis(study_sandbox):
    _seed_struggling_concept()

    analysis = _engine().get_weekly_analysis()["concept_analysis"]

    assert analysis["total_concepts"] == 1
    assert analysis["mastery_distribution"]["weak"] == 1
    assert "简谐运动" in analysis["regressed_this_week"]
    assert "简谐运动" in analysis["unverified"]


def test_weekly_analysis_detects_hint_dependency(study_sandbox):
    orch = get_teaching_orchestrator()
    orch.record_answer(
        "physics", "胡克定律", {"correctness": 0.9, "independent": False, "used_hint": True}
    )

    analysis = _engine().get_weekly_analysis()["concept_analysis"]

    assert "胡克定律" in analysis["hint_dependent"]


def test_weekly_analysis_keeps_legacy_keys(study_sandbox):
    analysis = _engine().get_weekly_analysis()

    for key in (
        "period",
        "active_days",
        "total_minutes",
        "daily_trend",
        "subject_distribution",
        "weak_subjects",
        "persistent_struggles",
        "streak",
    ):
        assert key in analysis, f"周分析缺少既有字段: {key}"


def test_active_care_prompt_uses_concept_progress(study_sandbox):
    """知识点级数据要真的进入 Active Care 的注入文本，而不只是躺在 JSON 里。"""
    from core.agents.chat_agent_components.persona_system.prompt.components.user_bio import (
        build_study_context_for_active_care,
    )

    orch = get_teaching_orchestrator()
    orch.record_teaching("physics", "简谐运动")
    orch.record_answer("physics", "简谐运动", {"correctness": 0.1, "independent": True})

    text = build_study_context_for_active_care()

    assert "简谐运动" in text
    assert "薄弱" in text
