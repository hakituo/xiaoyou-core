from __future__ import annotations

import pytest

from core.services.study.concept_resolver import CurriculumConceptIndex, PlannerModuleMeta
from core.services.study.concept_rules import ConceptStatus
from core.services.study.curriculum import CurriculumModule, CurriculumProgress
from core.services.study.planning_advisor import StudyPlanningAdvisor


def _progress(
    module_id: str,
    *,
    subject_id: str = "physics",
    coverage: str = "complete",
    status: str = ConceptStatus.UNKNOWN.value,
    missing: tuple[str, ...] = (),
    duration: int = 60,
) -> CurriculumProgress:
    return CurriculumProgress(
        module=CurriculumModule(
            id=module_id,
            name=module_id.rsplit(".", 1)[-1],
            subject_id=subject_id,
            subject_name=subject_id,
            required=True,
            importance=5,
            default_duration_minutes=duration,
        ),
        coverage_status=coverage,
        status=status,
        mastery=0.0,
        evidence_count=0,
        last_taught_at="",
        next_review_at="",
        missing_prerequisite_ids=missing,
        missing_prerequisite_names=missing,
    )


def test_parse_filters_hallucinated_module_ids() -> None:
    eligible = [_progress("physics.mechanics.newton")]
    advice = StudyPlanningAdvisor.parse(
        {
            "priority_module_ids": [
                "physics.fake.not_in_blueprint",
                "physics.mechanics.newton",
            ],
            "subject_minutes": {"physics": 180},
            "rationale": "test",
        },
        eligible=eligible,
        daily_goal_minutes=420,
    )
    assert advice.priority_module_ids == ("physics.mechanics.newton",)
    assert advice.subject_minutes_map == {"physics": 180}
    assert advice.source == "llm"


def test_parse_caps_total_subject_minutes_to_daily_goal() -> None:
    eligible = [
        _progress("physics.mechanics.newton", subject_id="physics"),
        _progress("math.functions", subject_id="math"),
    ]
    advice = StudyPlanningAdvisor.parse(
        {
            "priority_module_ids": [],
            "subject_minutes": {
                "physics": 300,
                "math": 300,
                "chemistry": 999,
            },
        },
        eligible=eligible,
        daily_goal_minutes=420,
    )
    assert advice.subject_minutes_map == {"physics": 300, "math": 120}
    assert sum(advice.subject_minutes_map.values()) == 420


def test_subject_minutes_promote_whitelisted_modules() -> None:
    eligible = [
        _progress("physics.a", subject_id="physics"),
        _progress("math.a", subject_id="math", duration=60),
        _progress("math.b", subject_id="math", duration=60),
        _progress("chemistry.a", subject_id="chemistry"),
    ]
    advice = StudyPlanningAdvisor.parse(
        {"priority_module_ids": [], "subject_minutes": {"math": 120}},
        eligible=eligible,
        daily_goal_minutes=420,
    )
    assert advice.priority_module_ids[:2] == ("math.a", "math.b")
    assert set(advice.priority_module_ids) <= {item.module.id for item in eligible}


def test_balanced_sample_covers_all_subjects_before_second_round() -> None:
    subjects = ("math", "physics", "chemistry", "biology", "english", "chinese")
    eligible = [
        _progress(f"{subject}.m{index:02d}", subject_id=subject)
        for subject in subjects
        for index in range(25)
    ]
    sampled = StudyPlanningAdvisor._balanced_sample(eligible, limit=40)
    assert len(sampled) == 40
    assert {item.module.subject_id for item in sampled[:6]} == set(subjects)
    assert {item.module.subject_id for item in sampled} == set(subjects)


@pytest.mark.asyncio
async def test_advisor_filters_exploratory_weaknesses_before_plan(monkeypatch) -> None:
    meta = {
        "physics.oscillation.shm": PlannerModuleMeta(
            "physics.oscillation.shm",
            "physics",
            "简谐运动",
            "concept",
            ("胡克定律",),
        ),
        "english.vocabulary": PlannerModuleMeta(
            "english.vocabulary", "english", "核心词汇", "external", ()
        ),
    }
    monkeypatch.setattr(CurriculumConceptIndex, "load", lambda self, **_: meta)

    def _matches(self, subject, topic, **_):
        if subject == "physics" and topic in {"简谐运动", "胡克定律"}:
            return (meta["physics.oscillation.shm"],)
        if subject == "english" and topic == "核心词汇":
            return (meta["english.vocabulary"],)
        return ()

    monkeypatch.setattr(CurriculumConceptIndex, "match_modules", _matches)
    due = [
        {"subject": "physics", "topic": "简谐运动"},
        {"subject": "math", "topic": "傅里叶变换"},
        {"subject": "computer_science", "topic": "图灵完备"},
        {"subject": "philosophy", "topic": "存在主义"},
        {"subject": "psychology", "topic": "认知失调"},
        {"subject": "english", "topic": "核心词汇"},
    ]
    advice = await StudyPlanningAdvisor().advise(
        target_date="2026-09-14",
        daily_goal_minutes=420,
        curriculum_progress=(),
        review_overview={},
        due_weaknesses=due,
        yesterday_summary={},
    )
    assert advice.source == "deterministic"
    assert due == [{"subject": "physics", "topic": "简谐运动"}]


@pytest.mark.asyncio
async def test_advisor_skips_llm_when_no_autonomous_curriculum(monkeypatch) -> None:
    advisor = StudyPlanningAdvisor()

    async def _must_not_call(_messages):
        raise AssertionError("partial curriculum must not call LLM")

    monkeypatch.setattr(advisor, "_call_llm", _must_not_call)
    advice = await advisor.advise(
        target_date="2026-09-14",
        daily_goal_minutes=420,
        curriculum_progress=[_progress("physics.mechanics.newton", coverage="partial")],
        review_overview={},
        due_weaknesses=(),
        yesterday_summary={},
    )
    assert advice.priority_module_ids == ()
    assert advice.source == "deterministic"


def test_invalid_payload_falls_back_to_empty_advice() -> None:
    eligible = [_progress("physics.mechanics.newton")]
    advice = StudyPlanningAdvisor.parse(
        "not json",
        eligible=eligible,
        daily_goal_minutes=420,
    )
    assert advice.priority_module_ids == ()
    assert advice.subject_minutes == ()
    assert advice.source == "deterministic"
