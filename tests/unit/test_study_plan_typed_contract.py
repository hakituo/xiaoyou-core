"""Study Daily typed plan 与 plan_item_id 优先合同回归测试。"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core.services.journal.models import DailyPlan, PlanItem  # noqa: E402
from routers.v1.study_daily_plan import (  # noqa: E402
    PlanItemAddRequest,
    PlanItemRefRequest,
    PlanItemStatusRequest,
    PlanItemUpdateRequest,
    add_plan_item,
    get_typed_daily_plan,
    remove_plan_item,
    update_plan_item,
    update_plan_item_status,
)


class _FakeJournal:
    def __init__(self, plan=None):
        self.plan = plan
        self.add_calls = []
        self.update_calls = []
        self.remove_calls = []
        self.mark_calls = []

    async def get_plan(self, date=None):
        return self.plan

    async def add_plan_item(self, date, item_dict):
        self.add_calls.append((date, item_dict))
        if self.plan is None:
            self.plan = DailyPlan(date=date, items=[])
        self.plan.items.append(PlanItem(**item_dict))
        return self.plan

    async def update_plan_item(self, date, item_id, updates):
        self.update_calls.append((date, item_id, updates))
        return self.plan

    async def remove_plan_item(self, date, item_id):
        self.remove_calls.append((date, item_id))
        return self.plan

    async def mark_plan_item_status(self, date, item_id, status):
        self.mark_calls.append((date, item_id, status))
        return self.plan


async def _fake_read_text(_path):
    return "- [ ] 08:00 新计划\n"


class _RouteTestCase(unittest.IsolatedAsyncioTestCase):
    async def _call(self, journal, coro_factory):
        with (
            patch(
                "core.services.journal.service.get_journal_service",
                return_value=journal,
            ),
            patch(
                "routers.v1.study_daily_plan._plan_file_path",
                return_value=Path("plan.md"),
            ),
            patch("routers.v1.study_daily_plan._read_text_async", _fake_read_text),
        ):
            return await coro_factory()


class TestTypedDailyPlan(_RouteTestCase):
    async def test_get_typed_plan_returns_truth_source_fields(self):
        plan = DailyPlan(
            date="2026-09-13",
            items=[
                PlanItem(
                    id="plan_math",
                    time="09:00",
                    title="数学 · 指数对数",
                    subject="数学",
                    priority="high",
                    estimated_duration_minutes=90,
                    source_key="curriculum:math.exp_log",
                    source_type="algorithm",
                    score=8.5,
                )
            ],
            notes="typed",
            source="algorithm_generated",
            revision_count=2,
        )
        resp = await self._call(
            _FakeJournal(plan),
            lambda: get_typed_daily_plan(date="2026-09-13"),
        )

        self.assertEqual(resp["status"], "success")
        data = resp["data"]
        self.assertEqual(data["date"], "2026-09-13")
        self.assertEqual(data["items"][0]["id"], "plan_math")
        self.assertEqual(data["items"][0]["subject"], "数学")
        self.assertEqual(data["revision_count"], 2)

    async def test_missing_plan_returns_stable_empty_contract(self):
        resp = await self._call(
            _FakeJournal(None),
            lambda: get_typed_daily_plan(date="2026-09-13"),
        )
        self.assertEqual(resp["data"]["items"], [])
        self.assertEqual(resp["data"]["date"], "2026-09-13")


class TestIdFirstCrud(_RouteTestCase):
    def _journal(self):
        return _FakeJournal(
            DailyPlan(
                date="2026-09-13",
                items=[
                    PlanItem(id="plan_a", time="09:00", title="同名任务"),
                    PlanItem(id="plan_b", time="10:00", title="同名任务"),
                ],
            )
        )

    async def test_update_uses_id_even_when_legacy_locator_is_wrong(self):
        journal = self._journal()
        resp = await self._call(
            journal,
            lambda: update_plan_item(
                PlanItemUpdateRequest(
                    date="2026-09-13",
                    item_id="plan_b",
                    target_time="00:00",
                    target_title="完全错误",
                    time="11:00",
                    title="改名任务",
                    duration_minutes=45,
                )
            ),
        )
        self.assertEqual(resp["status"], "success")
        self.assertEqual(journal.update_calls[0][1], "plan_b")

    async def test_wrong_id_never_falls_back_to_title_time(self):
        journal = self._journal()
        resp = await self._call(
            journal,
            lambda: update_plan_item(
                PlanItemUpdateRequest(
                    date="2026-09-13",
                    item_id="does-not-exist",
                    target_time="09:00",
                    target_title="同名任务",
                    time="12:00",
                    title="不应写入",
                )
            ),
        )
        self.assertEqual(resp["status"], "error")
        self.assertEqual(journal.update_calls, [])

    async def test_status_and_remove_use_stable_id(self):
        journal = self._journal()
        status_resp = await self._call(
            journal,
            lambda: update_plan_item_status(
                PlanItemStatusRequest(
                    date="2026-09-13",
                    item_id="plan_a",
                    done=True,
                )
            ),
        )
        remove_resp = await self._call(
            journal,
            lambda: remove_plan_item(
                PlanItemRefRequest(date="2026-09-13", item_id="plan_b")
            ),
        )
        self.assertEqual(status_resp["status"], "success")
        self.assertEqual(remove_resp["status"], "success")
        self.assertEqual(journal.mark_calls, [("2026-09-13", "plan_a", "completed")])
        self.assertEqual(journal.remove_calls, [("2026-09-13", "plan_b")])

    async def test_legacy_locator_remains_compatible_without_id(self):
        journal = self._journal()
        resp = await self._call(
            journal,
            lambda: remove_plan_item(
                PlanItemRefRequest(
                    date="2026-09-13",
                    time="10:00",
                    title="同名任务",
                )
            ),
        )
        self.assertEqual(resp["status"], "success")
        self.assertEqual(journal.remove_calls, [("2026-09-13", "plan_b")])

    async def test_add_returns_new_stable_id(self):
        journal = _FakeJournal(DailyPlan(date="2026-09-13", items=[]))
        resp = await self._call(
            journal,
            lambda: add_plan_item(
                PlanItemAddRequest(
                    date="2026-09-13",
                    time="08:00",
                    title="新计划",
                    duration_minutes=30,
                )
            ),
        )
        self.assertEqual(resp["status"], "success")
        self.assertTrue(resp["data"]["item_id"].startswith("plan_"))


if __name__ == "__main__":
    unittest.main()
