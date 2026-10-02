from __future__ import annotations

import pytest

from core.services.journal.curriculum_candidates import CurriculumCandidateProvider
from core.services.study.concept_resolver import CurriculumConceptIndex, PlannerModuleMeta
from core.services.study.concept_rules import ConceptStatus
from core.services.study.concept_state import get_concept_state_manager
from core.services.study.curriculum import CurriculumModule, CurriculumProgress

pytestmark = pytest.mark.usefixtures("study_sandbox")


def _progress(
    *,
    module_id: str = "physics.mechanics.newton",
    subject_id: str = "physics",
    name: str | None = None,
    coverage: str = "complete",
    status: str = ConceptStatus.UNKNOWN.value,
    mastery: float = 0.0,
    missing: tuple[str, ...] = (),
    last_taught_at: str = "",
    next_review_at: str = "",
) -> CurriculumProgress:
    display = name or (
        "牛顿运动定律"
        if module_id.endswith("newton")
        else module_id.rsplit(".", 1)[-1]
    )
    return CurriculumProgress(
        module=CurriculumModule(
            id=module_id,
            name=display,
            subject_id=subject_id,
            subject_name=subject_id,
            group="测试",
            required=True,
            importance=5,
            default_duration_minutes=75,
            prerequisites=missing,
            learning_objectives=("掌握核心概念",),
            note_paths=(),
        ),
        coverage_status=coverage,
        status=status,
        mastery=mastery,
        evidence_count=0,
        last_taught_at=last_taught_at,
        next_review_at=next_review_at,
        missing_prerequisite_ids=missing,
        missing_prerequisite_names=("前置知识",) if missing else (),
    )


def test_partial_curriculum_never_autonomously_schedules_new_content() -> None:
    assert CurriculumCandidateProvider().build([_progress(coverage="partial")]) == []


def test_complete_ready_module_becomes_curriculum_candidate() -> None:
    candidate = CurriculumCandidateProvider().build([_progress()])[0]
    assert candidate.key == "curriculum:physics.mechanics.newton"
    assert candidate.metadata["source_type"] == "curriculum"


def test_unknown_locked_module_does_not_jump_prerequisites() -> None:
    assert CurriculumCandidateProvider().build(
        [_progress(missing=("physics.mechanics.kinematics",))]
    ) == []


def test_learning_module_can_continue_when_prerequisite_history_is_sparse() -> None:
    candidates = CurriculumCandidateProvider().build(
        [
            _progress(
                status=ConceptStatus.LEARNING.value,
                mastery=0.35,
                missing=("physics.mechanics.kinematics",),
            )
        ]
    )
    assert len(candidates) == 1
    assert candidates[0].metadata["concept_status"] == "learning"


def test_mastered_concept_module_is_not_scheduled() -> None:
    assert CurriculumCandidateProvider().build(
        [_progress(status=ConceptStatus.MASTERED.value, mastery=0.9)]
    ) == []


def test_llm_preference_only_boosts_whitelisted_candidate() -> None:
    candidates = CurriculumCandidateProvider().build(
        [
            _progress(module_id="physics.mechanics.newton"),
            _progress(module_id="physics.mechanics.work_energy"),
        ],
        preferred_module_ids=(
            "physics.fake.hallucinated",
            "physics.mechanics.work_energy",
        ),
    )
    preferred = next(c for c in candidates if c.key.endswith("work_energy"))
    assert preferred.metadata["planner_preferred"] is True
    assert preferred.score_factors["llm_advice"] > 0


def test_162_equal_nodes_keep_subject_coverage() -> None:
    subjects = ("math", "physics", "chemistry", "biology", "english", "chinese")
    progress = [
        _progress(
            module_id=f"{subject}.module_{index:02d}",
            subject_id=subject,
        )
        for subject in subjects
        for index in range(27)
    ]
    candidates = CurriculumCandidateProvider().build(progress, limit=12)
    assert len(progress) == 162
    assert {c.metadata["subject_id"] for c in candidates} == set(subjects)


def test_external_skips_and_practice_can_return_when_mastered(monkeypatch) -> None:
    meta = {
        "english.vocabulary": PlannerModuleMeta(
            "english.vocabulary", "english", "核心词汇", "external", ()
        ),
        "english.reading": PlannerModuleMeta(
            "english.reading", "english", "阅读理解", "practice", ()
        ),
    }
    monkeypatch.setattr(CurriculumConceptIndex, "load", lambda self, **_: meta)
    progress = [
        _progress(
            module_id="english.vocabulary",
            subject_id="english",
            status=ConceptStatus.MASTERED.value,
            mastery=0.95,
        ),
        _progress(
            module_id="english.reading",
            subject_id="english",
            status=ConceptStatus.MASTERED.value,
            mastery=0.95,
        ),
    ]
    candidates = CurriculumCandidateProvider().build(progress)
    assert [c.key for c in candidates] == ["curriculum:english.reading"]
    assert candidates[0].metadata["planner_mode"] == "practice"


def test_partial_concept_evidence_does_not_master_whole_module(
    monkeypatch,
) -> None:
    meta = {
        "physics.oscillation.shm": PlannerModuleMeta(
            "physics.oscillation.shm",
            "physics",
            "简谐运动",
            "concept",
            ("胡克定律", "回复力"),
        )
    }
    monkeypatch.setattr(CurriculumConceptIndex, "load", lambda self, **_: meta)
    concepts = get_concept_state_manager()
    concepts.mark_mastered("physics", "胡克定律")

    candidates = CurriculumCandidateProvider().build(
        [
            _progress(
                module_id="physics.oscillation.shm",
                subject_id="physics",
                name="简谐运动",
            )
        ]
    )
    assert len(candidates) == 1
    assert candidates[0].metadata["concept_status"] == "learning"
    assert candidates[0].metadata["matched_concepts"] == ["胡克定律"]


def test_all_declared_evidence_mastered_can_master_module(monkeypatch) -> None:
    meta = {
        "physics.oscillation.shm": PlannerModuleMeta(
            "physics.oscillation.shm",
            "physics",
            "简谐运动",
            "concept",
            ("胡克定律", "回复力"),
        )
    }
    monkeypatch.setattr(CurriculumConceptIndex, "load", lambda self, **_: meta)
    concepts = get_concept_state_manager()
    concepts.mark_mastered("physics", "胡克定律")
    concepts.mark_mastered("physics", "回复力")

    candidates = CurriculumCandidateProvider().build(
        [
            _progress(
                module_id="physics.oscillation.shm",
                subject_id="physics",
                name="简谐运动",
            )
        ]
    )
    assert candidates == []
