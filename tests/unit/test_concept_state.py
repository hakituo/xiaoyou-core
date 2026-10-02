"""ConceptState 知识点级状态测试。

覆盖：新建、答对提升、答错降低或保持、提示成功不等于独立成功、
多次独立成功进入 mastered、mastered 后再次失败可退化、状态文件损坏恢复。
"""
from __future__ import annotations

import json

from core.services.study.concept_state import (
    ConceptState,
    ConceptStateManager,
    ConceptStatus,
)


def _mgr(sandbox) -> ConceptStateManager:
    return ConceptStateManager(sandbox / ".state" / "concepts.json")


def test_new_concept_creation(study_sandbox):
    mgr = _mgr(study_sandbox)
    state = mgr.get_or_create("math", "导数")

    assert state.status == ConceptStatus.UNKNOWN
    assert state.mastery == 0.0
    assert state.evidence_count == 0
    assert state.independent_success_streak == 0
    # id 必须与薄弱视图同一套哈希，跨模块才能按 id 互查
    assert state.concept_id == ConceptState.make_id("math", "导数")
    # 科目归一化
    assert mgr.get_or_create("MATH", "导数").concept_id == state.concept_id


def test_correct_answer_raises_mastery(study_sandbox):
    mgr = _mgr(study_sandbox)
    mgr.mark_taught("math", "导数")
    state = mgr.apply_evaluation("math", "导数", correctness=0.95, independent=True)

    assert state.mastery > 0.0
    assert state.successful_retrievals == 1
    assert state.independent_success_streak == 1
    assert state.failed_retrievals == 0
    assert state.status == ConceptStatus.LEARNING
    assert state.next_review_at != ""


def test_wrong_answer_lowers_or_holds_mastery(study_sandbox):
    mgr = _mgr(study_sandbox)
    mgr.mark_taught("math", "导数")
    mgr.apply_evaluation("math", "导数", correctness=0.95, independent=True)
    before = mgr.get_by_name("math", "导数").mastery

    state = mgr.apply_evaluation("math", "导数", correctness=0.1, independent=True)

    assert state.mastery <= before
    assert state.failed_retrievals == 1
    assert state.independent_success_streak == 0
    assert state.status == ConceptStatus.WEAK


def test_wrong_answer_on_fresh_concept_never_goes_negative(study_sandbox):
    mgr = _mgr(study_sandbox)
    state = mgr.apply_evaluation("math", "极限", correctness=0.0, independent=True)
    assert state.mastery == 0.0
    assert state.status == ConceptStatus.WEAK


def test_hint_assisted_success_is_not_independent(study_sandbox):
    mgr = _mgr(study_sandbox)
    mgr.mark_taught("physics", "胡克定律")

    state = mgr.apply_evaluation(
        "physics", "胡克定律", correctness=0.95, independent=False, used_hint=True
    )

    assert state.hint_assisted_successes == 1
    assert state.independent_success_streak == 0
    assert state.successful_retrievals == 1
    # 提示成功不推进复习等级
    assert state.review_level == 0
    assert state.status != ConceptStatus.MASTERED


def test_hint_flag_forces_non_independent(study_sandbox):
    """used_hint=True 时即使声称 independent 也不得计入独立连击。"""
    mgr = _mgr(study_sandbox)
    state = mgr.apply_evaluation(
        "physics", "胡克定律", correctness=0.95, independent=True, used_hint=True
    )
    assert state.independent_success_streak == 0
    assert state.hint_assisted_successes == 1


def test_multiple_independent_successes_reach_mastered(study_sandbox):
    mgr = _mgr(study_sandbox)
    mgr.mark_taught("math", "三角函数")
    for _ in range(4):
        state = mgr.apply_evaluation(
            "math", "三角函数", correctness=0.95, independent=True
        )

    assert state.status == ConceptStatus.MASTERED
    assert state.independent_success_streak >= 3
    assert state.mastery >= 0.8
    assert state.last_success_at != ""


def test_mastered_can_degrade_on_failure(study_sandbox):
    mgr = _mgr(study_sandbox)
    mgr.mark_taught("math", "三角函数")
    for _ in range(4):
        mgr.apply_evaluation("math", "三角函数", correctness=0.95, independent=True)
    assert mgr.get_by_name("math", "三角函数").status == ConceptStatus.MASTERED

    state = mgr.apply_evaluation("math", "三角函数", correctness=0.0, independent=True)

    assert state.status != ConceptStatus.MASTERED
    assert state.independent_failure_streak == 1
    assert state.independent_success_streak == 0


def test_mastered_keeps_long_interval_review(study_sandbox):
    """已掌握不等于停止复习：仍要有长间隔的维持性复习日期。"""
    mgr = _mgr(study_sandbox)
    mgr.mark_taught("math", "数列")
    for _ in range(4):
        state = mgr.apply_evaluation("math", "数列", correctness=0.95, independent=True)

    assert state.status == ConceptStatus.MASTERED
    assert state.next_review_at != ""


def test_corrupt_state_file_is_backed_up_and_recovered(study_sandbox):
    """状态文件损坏时必须备份后安全重建，不能静默丢数据。"""
    path = study_sandbox / ".state" / "concepts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not valid json", encoding="utf-8")

    mgr = _mgr(study_sandbox)
    assert mgr.load() == {}

    backups = list(path.parent.glob("concepts.json.corrupt-*"))
    assert len(backups) == 1
    assert "not valid json" in backups[0].read_text(encoding="utf-8")

    # 重建后仍可正常写入
    state = mgr.get_or_create("math", "向量")
    assert state.status == ConceptStatus.UNKNOWN
    assert json.loads(path.read_text(encoding="utf-8"))["concepts"]


def test_persistence_roundtrip(study_sandbox):
    """写入后必须落盘，新实例能读到（模拟下一次对话）。"""
    path = study_sandbox / ".state" / "concepts.json"
    mgr = _mgr(study_sandbox)
    mgr.mark_taught("physics", "简谐运动")
    mgr.apply_evaluation("physics", "简谐运动", correctness=0.9, independent=True)

    fresh = ConceptStateManager(path)
    state = fresh.get_by_name("physics", "简谐运动")
    assert state is not None
    assert state.mastery > 0.0
    assert state.evidence_count == 2


def test_mark_mastered_is_explicit_override(study_sandbox):
    mgr = _mgr(study_sandbox)
    state = mgr.mark_mastered("math", "集合")
    assert state.status == ConceptStatus.MASTERED
    assert state.independent_success_streak >= 3



def test_name_drift_merges_into_same_concept(study_sandbox):
    """模型把同一知识点写成不同变体时不能拆成两条记录。

    实际观测：study_record_teaching 传「F = -kx」，
    下一轮 study_record_answer 传「F = -kx（回复力方向）」。
    严格 ID 会生成两个知识点，学习证据被劈开。
    """
    mgr = _mgr(study_sandbox)
    first = mgr.get_or_create("physics", "F = -kx")
    second = mgr.get_or_create("physics", "F = -kx（回复力方向）")

    assert second.concept_id == first.concept_id
    # 展示名保留首次写入的写法，不被后续变体覆盖
    assert second.name == "F = -kx"


def test_name_drift_keeps_distinct_concepts_apart(study_sandbox):
    """宽松匹配只能合并变体，不能把不同知识点误并。"""
    mgr = _mgr(study_sandbox)
    a = mgr.get_or_create("physics", "动量")
    b = mgr.get_or_create("physics", "动量守恒")

    assert a.concept_id != b.concept_id


def test_loose_name_ignores_parentheses_and_spaces(study_sandbox):
    from core.services.study.concept_state import ConceptState

    assert ConceptState.loose_name("F = -kx（回复力方向）") == ConceptState.loose_name("F=-kx")
