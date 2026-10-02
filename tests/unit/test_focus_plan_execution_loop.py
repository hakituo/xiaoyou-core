# -*- coding: utf-8 -*-
"""FocusSession -> PlanItem 执行闭环与 typed daily goal 回归。"""

import asyncio
import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from core.services.journal.models import DailyPlan, PlanItem
from core.services.journal.plan_crud import PlanCRUDService
from core.services.study.focus_session_models import FocusSession
from core.services.study.focus_session_service import FocusSessionService
from routers.v1.study_daily_plan import _serialize_daily_plan


class _FakeStorage:
    def __init__(self, plan: DailyPlan):
        self.plan = plan
        self.save_count = 0

    async def get_plan(self, _dt, scope="user"):
        assert scope == "user"
        return self.plan

    async def save_plan(self, plan, _dt, scope="user"):
        assert scope == "user"
        self.plan = plan
        self.save_count += 1


class _FakeJournalService:
    def __init__(self, plan: DailyPlan):
        self.storage = _FakeStorage(plan)

    @staticmethod
    def _parse_date(date_str):
        return datetime.strptime(date_str, "%Y-%m-%d")


def test_focus_sessions_accumulate_minutes_and_finish_only_at_estimated_duration():
    item = PlanItem(
        id="plan_physics_shm",
        title="物理 · 简谐运动",
        estimated_duration_minutes=60,
    )
    plan = DailyPlan(date="2026-09-14", items=[item])
    service = _FakeJournalService(plan)
    crud = PlanCRUDService(service)

    asyncio.run(
        crud.apply_focus_session_result(
            "2026-09-14", item.id, "focus_a", 25.0
        )
    )
    assert item.actual_minutes == 25.0
    assert item.status == "in_progress"

    # 同一个 finish 网络重试不能重复累计。
    asyncio.run(
        crud.apply_focus_session_result(
            "2026-09-14", item.id, "focus_a", 25.0
        )
    )
    assert item.actual_minutes == 25.0
    assert item.focus_session_ids == ["focus_a"]

    asyncio.run(
        crud.apply_focus_session_result(
            "2026-09-14", item.id, "focus_b", 25.0
        )
    )
    assert item.actual_minutes == 50.0
    assert item.status == "in_progress"

    asyncio.run(
        crud.apply_focus_session_result(
            "2026-09-14", item.id, "focus_c", 10.0
        )
    )
    assert item.actual_minutes == 60.0
    assert item.status == "completed"
    assert item.focus_session_ids == ["focus_a", "focus_b", "focus_c"]


def test_focus_projection_keeps_terminal_status_but_still_records_real_minutes():
    item = PlanItem(
        id="plan_done",
        title="已手动完成的任务",
        estimated_duration_minutes=60,
        status="completed",
    )
    service = _FakeJournalService(DailyPlan(date="2026-09-14", items=[item]))
    crud = PlanCRUDService(service)

    asyncio.run(
        crud.apply_focus_session_result(
            "2026-09-14", item.id, "focus_after_done", 5.0
        )
    )

    assert item.actual_minutes == 5.0
    assert item.status == "completed"


def test_focus_finish_retry_returns_old_finished_session_without_double_daily_sync(monkeypatch):
    service = FocusSessionService()
    now = time.time()
    current = FocusSession(
        session_id="focus_old",
        user_id="default",
        subject="数学",
        planned_minutes=25,
        status="active",
        created_at=now - 600,
        started_at=now - 600,
        last_resume_at=now - 600,
    )
    service._active["default"] = current

    sync_calls = []
    monkeypatch.setattr(service, "_sync_to_daily", lambda sess: sync_calls.append(sess.session_id))
    monkeypatch.setattr(service, "_persist", lambda _sess: None)
    monkeypatch.setattr(service, "_load_latest_active", lambda _user_id: None)

    first = service.finish("default", session_id="focus_old")
    saved = first.to_dict()
    monkeypatch.setattr(
        service,
        "get_summary",
        lambda _user_id, session_id: saved if session_id == "focus_old" else None,
    )

    # 模拟客户端已开始下一轮 WORK 后，上一轮 finish 响应因网络丢失而重试。
    next_session = FocusSession(
        session_id="focus_new",
        user_id="default",
        subject="数学",
        planned_minutes=25,
        status="active",
        created_at=now,
        started_at=now,
        last_resume_at=now,
    )
    service._active["default"] = next_session

    retried = service.finish("default", session_id="focus_old")

    assert retried.session_id == "focus_old"
    assert retried.status == "finished"
    assert sync_calls == ["focus_old"]
    assert service._active["default"].session_id == "focus_new"
    assert service._active["default"].status == "active"


def test_typed_daily_plan_reads_goal_from_runtime_config_not_plan_storage():
    plan = DailyPlan(
        date="2026-09-14",
        items=[
            PlanItem(
                id="plan_math",
                title="数学",
                actual_minutes=25.0,
                focus_session_ids=["focus_a"],
            )
        ],
    )

    with patch(
        "core.services.journal.plan_policy.load_journal_plan_settings",
        return_value=SimpleNamespace(daily_goal_minutes=515),
    ):
        data = _serialize_daily_plan(plan, "2026-09-14")

    assert data["daily_goal_minutes"] == 515
    assert data["items"][0]["actual_minutes"] == 25.0
    assert data["items"][0]["focus_session_ids"] == ["focus_a"]
    assert "daily_goal_minutes" not in plan.model_fields_set
