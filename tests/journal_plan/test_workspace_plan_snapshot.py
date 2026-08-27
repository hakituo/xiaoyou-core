"""Workspace 自动任务只镜像 Journal 主计划。"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.services.journal.models import DailyPlan, PlanItem
from core.services.workspace.daily_task_service import WorkspaceDailyTaskService


@pytest.mark.asyncio
async def test_workspace_snapshot_uses_main_plan_without_hard_reminders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: dict[str, dict] = {}

    class _DailyManager:
        def get_record(self, date: str) -> dict:
            return records.setdefault(date, {})

        def _get_file_path(self, date: str) -> str:
            return str(tmp_path / "daily" / f"{date}.json")

    class _JournalService:
        async def get_plan(self, date: str) -> DailyPlan:
            return DailyPlan(
                date=date,
                items=[
                    PlanItem(
                        id="main-plan-item",
                        time="09:00",
                        title="主计划词汇复习",
                        subject="英语",
                        estimated_duration_minutes=30,
                        source_key="vocab:due_review",
                    )
                ],
            )

    async def _noop(*_: object, **__: object):
        return None

    async def _schedule_forbidden(*_: object, **__: object) -> str:
        raise AssertionError("Journal 自动计划镜像不应创建 Workspace 硬提醒")

    monkeypatch.setattr(
        "core.services.daily.manager.get_daily_manager",
        lambda: _DailyManager(),
    )
    monkeypatch.setattr(
        "core.services.journal.get_journal_service",
        lambda: _JournalService(),
    )
    service = WorkspaceDailyTaskService(
        base_dir=tmp_path / "workspace",
        get_study_overview=_noop,
        write_study_text=_noop,
        schedule_message=_schedule_forbidden,
        delete_message=_noop,
        append_workspace_memory=_noop,
    )

    result = await service.generate_daily_tasks_from_progress(
        date="2099-01-05",
        force=True,
    )

    assert result["source"] == "journal_plan_snapshot"
    assert result["hard_reminders_created"] == 0
    task = records["2099-01-05"]["daily_tasks"]["timed"][0]
    assert task["id"] == "main-plan-item"
    assert task["source"] == "journal_plan_snapshot"
