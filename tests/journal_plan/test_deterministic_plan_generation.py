"""用户主计划确定性生成测试。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from core.services.journal.models import DailyPlan, PlanItem
from core.services.journal.plan_candidate_builder import (
    JournalPlanCandidateBuilder,
    JournalPlanningFacts,
)
from core.services.journal.plan_policy import JournalPlanSettings
from core.services.journal.service import JournalService


def _build_daily_dir(base: Path, date: datetime, scope: str = "user") -> Path:
    return (
        base
        / scope
        / "daily"
        / date.strftime("%Y")
        / date.strftime("%m")
        / date.strftime("%d")
    )


def _facts_with_all_sources() -> JournalPlanningFacts:
    previous = DailyPlan(
        date="2099-01-04",
        items=[
            PlanItem(
                title="昨日未完成数学",
                subject="数学",
                status="pending",
                source_key="manual:math",
                source_type="manual",
            )
        ],
    )
    return JournalPlanningFacts(
        review_overview={"due_today_count": 8, "due_words": 6},
        due_weaknesses=[
            {
                "id": "weak-physics",
                "subject": "物理",
                "topic": "电磁感应",
                "confidence": 2.0,
            }
        ],
        yesterday_summary={
            "vocab": {"to_review": 99},
            "subjects": [{"subject": "化学", "minutes": 45}],
            "overview": {"total_sessions": 2, "top_subjects": ["化学"]},
            "next_day_blueprint": {
                "timed_blocks": [
                    {"name": "核心学习块", "time": "14:00", "duration_minutes": 60}
                ],
                "untimed_blocks": [
                    {"name": "记录今日学习总结", "duration_minutes": 20}
                ],
                "priority_subjects": ["化学"],
            },
        },
        previous_plan=previous,
    )


def test_real_facts_create_due_weakness_and_carryover_candidates() -> None:
    settings = JournalPlanSettings()
    builder = JournalPlanCandidateBuilder(storage=None, settings=settings)
    bundle = builder.build(datetime(2099, 1, 5), _facts_with_all_sources())
    keys = {candidate.key for candidate in bundle.candidates}
    assert "vocab:due_review" in keys
    assert "weakness:weak-physics" in keys
    assert "carryover:manual:math" in keys
    assert "yesterday_subject:化学" in keys
    vocab = next(item for item in bundle.candidates if item.key == "vocab:due_review")
    assert vocab.title == "复习到期英语词汇（8 个）"
    assert bundle.has_learning_facts is True


def test_yesterday_vocab_is_used_only_as_lower_priority_fallback() -> None:
    settings = JournalPlanSettings()
    builder = JournalPlanCandidateBuilder(storage=None, settings=settings)
    facts = JournalPlanningFacts(
        review_overview={},
        yesterday_summary={"vocab": {"to_review": 7}},
    )

    bundle = builder.build(datetime(2099, 1, 5), facts)

    vocab = next(item for item in bundle.candidates if item.key == "vocab:due_review")
    assert vocab.title == "复核昨日词汇复习线索（7 个）"
    assert vocab.source == "template"
    assert vocab.base_score == 3.0


@pytest.mark.asyncio
async def test_generation_does_not_call_scheduler_or_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = JournalService()
    monkeypatch.setattr(
        service.storage,
        "get_daily_dir",
        lambda date, scope="user": _build_daily_dir(tmp_path, date, scope),
    )

    async def _load_facts(_target: datetime) -> JournalPlanningFacts:
        return _facts_with_all_sources()

    async def _sync(_plan: DailyPlan, _date: datetime) -> None:
        return None

    def _scheduler_forbidden():
        raise AssertionError("确定性计划生成不应访问 scheduler/LLM")

    monkeypatch.setattr(service._plan_service._candidate_builder, "load_facts", _load_facts)
    monkeypatch.setattr(service._plan_service, "_sync_plan_to_study_daily", _sync)
    monkeypatch.setattr(
        "core.services.scheduler.get_global_scheduler",
        _scheduler_forbidden,
    )

    plan = await service.generate_plan_for_date("2099-01-05", force=True)

    assert plan.source == "algorithm_generated"
    assert plan.items
    assert all(item.source_type in {"algorithm", "carryover"} for item in plan.items)


@pytest.mark.asyncio
async def test_force_generation_preserves_manual_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = JournalService()
    target = datetime(2099, 1, 5)
    monkeypatch.setattr(
        service.storage,
        "get_daily_dir",
        lambda date, scope="user": _build_daily_dir(tmp_path, date, scope),
    )
    manual = PlanItem(
        id="plan_manual",
        time="09:00",
        title="用户手动数学任务",
        estimated_duration_minutes=45,
        source_type="manual",
        reminder_id="reminder-start",
    )
    await service.storage.save_plan(
        DailyPlan(date=target.strftime("%Y-%m-%d"), items=[manual], source="manual"),
        target,
        scope="user",
    )

    async def _load_facts(_target: datetime) -> JournalPlanningFacts:
        return JournalPlanningFacts()

    async def _cleanup(_plan: DailyPlan, **_: object) -> int:
        return 0

    async def _sync(_plan: DailyPlan, _date: datetime) -> None:
        return None

    monkeypatch.setattr(service._plan_service._candidate_builder, "load_facts", _load_facts)
    monkeypatch.setattr(service._plan_service, "_cleanup_plan_reminders", _cleanup)
    monkeypatch.setattr(service._plan_service, "_sync_plan_to_study_daily", _sync)

    regenerated = await service.generate_plan_for_date("2099-01-05", force=True)

    preserved = next(item for item in regenerated.items if item.id == "plan_manual")
    assert preserved.title == "用户手动数学任务"
    assert preserved.source_type == "manual"
    assert preserved.reminder_id == "reminder-start"


@pytest.mark.asyncio
async def test_crud_marks_user_created_item_as_manual(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = JournalService()
    monkeypatch.setattr(
        service.storage,
        "get_daily_dir",
        lambda date, scope="user": _build_daily_dir(tmp_path, date, scope),
    )

    async def _sync(_plan: DailyPlan, _date: datetime) -> None:
        return None

    monkeypatch.setattr(service._plan_service, "_sync_plan_to_study_daily", _sync)
    plan = await service.add_plan_item(
        "2099-01-05",
        {"title": "用户手动新增", "estimated_duration_minutes": 30},
    )

    assert plan is not None
    assert plan.source == "manual"
    assert plan.items[0].source_type == "manual"


def test_sleep_settlement_rolls_next_day_with_limit() -> None:
    settings = JournalPlanSettings(max_carryover_count=2, max_carryover_items=2)
    builder = JournalPlanCandidateBuilder(storage=None, settings=settings)
    previous = DailyPlan(
        date="2099-01-04",
        items=[
            PlanItem(
                id="eligible",
                title="睡前未完成物理",
                status="skipped",
                source_key="physics",
                source_type="algorithm",
                settlement_reason="sleep",
                carryover_count=1,
            ),
            PlanItem(
                id="limited",
                title="已达到滚动上限",
                status="skipped",
                source_key="limit",
                settlement_reason="sleep",
                carryover_count=2,
            ),
            PlanItem(
                id="user_skipped",
                title="用户主动跳过",
                status="skipped",
                source_key="user-skip",
                settlement_reason=None,
            ),
        ],
    )
    bundle = builder.build(
        datetime(2099, 1, 5),
        JournalPlanningFacts(previous_plan=previous),
    )
    carryovers = [
        candidate for candidate in bundle.candidates if candidate.source == "carryover"
    ]
    assert [candidate.title for candidate in carryovers] == ["睡前未完成物理"]
    assert carryovers[0].metadata["carryover_count"] == 2
    assert carryovers[0].metadata["settlement_reason"] == "sleep"


def test_empty_facts_only_create_small_fallback() -> None:
    builder = JournalPlanCandidateBuilder(
        storage=None,
        settings=JournalPlanSettings(),
    )
    bundle = builder.build(datetime(2099, 1, 5), JournalPlanningFacts())
    assert bundle.has_learning_facts is False
    assert [candidate.key for candidate in bundle.candidates] == [
        "fallback:core_study",
        "fallback:wrapup",
    ]


def test_weekday_weekend_and_holiday_use_different_capacity() -> None:
    settings = JournalPlanSettings()
    weekday = next(
        datetime(2099, 1, day)
        for day in range(2, 9)
        if datetime(2099, 1, day).weekday() < 5
    )
    weekend = next(
        datetime(2099, 1, day)
        for day in range(2, 9)
        if datetime(2099, 1, day).weekday() >= 5
    )
    holiday = datetime(2099, 5, 1)
    policies = [
        settings.policy_for(value.date())
        for value in (weekday, weekend, holiday)
    ]
    assert [policy.max_items for policy in policies] == [6, 5, 4]
    assert [policy.capacity_minutes for policy in policies] == [240, 180, 150]
