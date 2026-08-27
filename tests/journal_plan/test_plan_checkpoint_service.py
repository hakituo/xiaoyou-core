"""计划检查点自动重排测试。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from core.services.journal.models import DailyPlan, PlanItem
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


@pytest.mark.asyncio
async def test_evening_checkpoint_replans_when_progress_is_bad(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """傍晚 18 点且当天几乎没动时，应自动压缩成保底计划。"""
    service = JournalService()
    monkeypatch.setattr(
        service.storage,
        "get_daily_dir",
        lambda date, scope="user": _build_daily_dir(tmp_path, date, scope),
    )

    now = datetime(2099, 12, 31, 18, 5)
    plan = DailyPlan(
        date=now.strftime("%Y-%m-%d"),
        items=[
            PlanItem(time="08:00", title="数学套卷", category="study", subject="数学", estimated_duration_minutes=120),
            PlanItem(time="10:30", title="英语阅读", category="study", subject="英语", estimated_duration_minutes=60),
            PlanItem(time="19:30", title="化学整理", category="study", subject="化学", estimated_duration_minutes=90),
        ],
        notes="原计划偏满",
    )
    await service.storage.save_plan(plan, now, scope="user")

    async def _fake_cleanup(_plan: DailyPlan, **_: object) -> int:
        return 0

    async def _fake_sync_study(_plan: DailyPlan, _date: datetime) -> None:
        return None

    monkeypatch.setattr(service._plan_service, "_cleanup_plan_reminders", _fake_cleanup)
    monkeypatch.setattr(service._plan_service, "_sync_plan_to_study_daily", _fake_sync_study)

    updated = await service.maybe_reassess_today_plan(now=now)
    assert updated is not None
    assert updated.revision_count == 1
    assert updated.source == "algorithm_adjusted"
    assert f"{plan.date}:evening" in updated.checkpoint_reviews

    deferred_titles = {
        item.title
        for item in updated.items
        if item.settlement_reason == "checkpoint_capacity"
    }
    assert deferred_titles
    assert all(
        item.status == "pending" and item.time is None
        for item in updated.items
        if item.title in deferred_titles
    )
    assert all(item.status != "completed" for item in updated.items if item.title in {
        "数学套卷", "英语阅读", "化学整理"
    })

    pending_titles = {item.title for item in updated.items if item.status == "pending"}
    assert pending_titles
    assert pending_titles == {"数学套卷", "英语阅读", "化学整理"}
    assert "自动重排" in str(updated.notes or "")


@pytest.mark.asyncio
async def test_noon_checkpoint_only_marks_review_when_plan_is_healthy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """中午前半段执行正常时，只记录复盘已完成，不应强行改计划。"""
    service = JournalService()
    monkeypatch.setattr(
        service.storage,
        "get_daily_dir",
        lambda date, scope="user": _build_daily_dir(tmp_path, date, scope),
    )

    now = datetime(2099, 12, 30, 12, 5)
    plan = DailyPlan(
        date=now.strftime("%Y-%m-%d"),
        items=[
            PlanItem(
                time="08:00",
                title="英语晨读",
                category="study",
                subject="英语",
                estimated_duration_minutes=40,
                status="completed",
            ),
            PlanItem(
                time="14:00",
                title="物理专题练习",
                category="study",
                subject="物理",
                estimated_duration_minutes=70,
            ),
        ],
        notes="节奏正常",
    )
    await service.storage.save_plan(plan, now, scope="user")

    updated = await service.maybe_reassess_today_plan(now=now)
    assert updated is not None
    assert updated.revision_count == 0
    assert updated.notes == "节奏正常"
    assert f"{plan.date}:noon" in updated.checkpoint_reviews
    assert [item.title for item in updated.items] == ["英语晨读", "物理专题练习"]


@pytest.mark.asyncio
async def test_replan_keeps_in_progress_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """重排不能把进行中或超时待办误标为 completed。"""
    service = JournalService()
    monkeypatch.setattr(
        service.storage,
        "get_daily_dir",
        lambda date, scope="user": _build_daily_dir(tmp_path, date, scope),
    )
    now = datetime(2099, 12, 31, 18, 10)
    plan = DailyPlan(
        date=now.strftime("%Y-%m-%d"),
        items=[
            PlanItem(
                time="17:00",
                title="正在做的数学",
                estimated_duration_minutes=60,
                status="in_progress",
            ),
            PlanItem(
                time="08:00",
                title="错过的英语",
                estimated_duration_minutes=180,
                status="pending",
            ),
        ],
    )
    await service.storage.save_plan(plan, now, scope="user")

    async def _cleanup(_plan: DailyPlan, **_: object) -> int:
        return 0

    async def _sync(_plan: DailyPlan, _date: datetime) -> None:
        return None

    monkeypatch.setattr(service._plan_service, "_cleanup_plan_reminders", _cleanup)
    monkeypatch.setattr(service._plan_service, "_sync_plan_to_study_daily", _sync)

    updated = await service.maybe_reassess_today_plan(now=now)

    assert updated is not None
    active = next(item for item in updated.items if item.title == "正在做的数学")
    overdue = next(item for item in updated.items if item.title == "错过的英语")
    assert active.status == "in_progress"
    assert overdue.status == "pending"
    assert overdue.time is None
    assert overdue.settlement_reason == "checkpoint_capacity"
    assert all(item.status != "completed" for item in updated.items)
