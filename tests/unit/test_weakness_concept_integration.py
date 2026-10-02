"""ConceptState 与 WeaknessTracker 的投影一致性测试。

覆盖：错误回答产生 weak state、weak concept 被安排复习、复习成功推进、
连续成功后不再出现在 weakness list，以及「三份状态不打架」。
"""
from __future__ import annotations

from core.services.study.student_state import get_student_state_manager
from core.services.study.teaching_orchestrator import TeachingOrchestrator
from core.services.study.weakness_tracker import get_weakness_tracker


def _orch() -> TeachingOrchestrator:
    return TeachingOrchestrator()


def _active_topics() -> set:
    report = get_weakness_tracker().get_weakness_report()
    return {
        item["topic"]
        for items in report.get("by_subject", {}).values()
        for item in items
    }


def test_wrong_answer_creates_weak_state_and_projection(study_sandbox):
    orch = _orch()
    orch.record_teaching("math", "导数")
    orch.record_answer("math", "导数", {"correctness": 0.1, "independent": True})

    state = orch.concepts.get_by_name("math", "导数")
    assert state.status.value == "weak"

    # 薄弱视图必须同步（而不是只有 ConceptState 知道）
    assert "导数" in _active_topics()


def test_weak_concept_is_scheduled_for_review(study_sandbox):
    orch = _orch()
    orch.record_answer("math", "导数", {"correctness": 0.1, "independent": True})

    tracker = get_weakness_tracker()
    item = next(i for i in tracker._get_items() if i.topic == "导数")

    assert item.next_review_date != ""
    assert item.source == "concept_projection"
    # 掌握度投影自 ConceptState（0-1 -> 0-10）
    assert item.confidence == round(orch.concepts.get_by_name("math", "导数").mastery * 10, 2)


def test_review_success_advances_state(study_sandbox):
    orch = _orch()
    orch.record_answer("math", "导数", {"correctness": 0.1, "independent": True})
    before = orch.concepts.get_by_name("math", "导数").mastery

    result = orch.record_answer(
        "math",
        "导数",
        {"correctness": 0.95, "independent": True},
        is_review=True,
    )

    assert result["status"] == "success"
    assert result["mastery"] > before
    assert orch.concepts.get_by_name("math", "导数").review_level >= 1


def test_consecutive_success_removes_from_weakness_list(study_sandbox):
    orch = _orch()
    orch.record_answer("math", "导数", {"correctness": 0.1, "independent": True})
    assert "导数" in _active_topics()

    for _ in range(4):
        orch.record_answer(
            "math", "导数", {"correctness": 0.95, "independent": True}, is_review=True
        )

    assert orch.concepts.get_by_name("math", "导数").status.value == "mastered"
    assert "导数" not in _active_topics()


def test_mastered_concept_is_not_in_due_reviews(study_sandbox):
    orch = _orch()
    for _ in range(4):
        orch.record_answer("physics", "简谐运动", {"correctness": 0.95, "independent": True})

    tracker = get_weakness_tracker()
    due_topics = {i.topic for i in tracker.get_due_reviews()}
    assert "简谐运动" not in due_topics


def test_three_sources_agree_after_mastery(study_sandbox):
    """ConceptState / WeaknessTracker / StudentState 对同一知识点结论一致。"""
    orch = _orch()
    for _ in range(4):
        orch.record_answer("physics", "简谐运动", {"correctness": 0.95, "independent": True})

    state = orch.concepts.get_by_name("physics", "简谐运动")
    assert state.status.value == "mastered"

    tracker = get_weakness_tracker()
    assert all(i.topic != "简谐运动" for i in tracker._get_items())

    student = get_student_state_manager().get_state()
    subject = student.subjects.get("physics")
    assert subject is not None
    # 科目 confidence 是知识点掌握度的汇总，不再是零散累加
    assert subject.confidence == round(state.mastery * 10, 2)


def test_subject_rollup_is_derived_from_concepts(study_sandbox):
    orch = _orch()
    orch.record_answer("math", "导数", {"correctness": 0.95, "independent": True})
    orch.record_answer("math", "积分", {"correctness": 0.95, "independent": True})

    concepts = orch.concepts.list_by_subject("math")
    expected = round(sum(c.mastery for c in concepts) / len(concepts) * 10, 2)

    student = get_student_state_manager().get_state()
    assert student.subjects["math"].confidence == expected
