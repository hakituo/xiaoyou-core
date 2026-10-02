"""计划项增 / 改 / 删接口的写入语义与路由注册回归测试。

背景（2026-09-11）：
    安卓端计划项此前**整篇覆盖** plan.md（POST /study-daily/plan），而计划真源是
    companion_data 下的 plan.json。后端每次计划同步都会用真源重新生成 plan.md，
    把客户端改动整片抹掉，并丢掉标题、备注与无时间项。勾选链路已在上一轮改走
    plan/item/status，本轮把增 / 改 / 删也收敛到真源，并顺手按 life.py 的先例
    把 824 行的 study_daily.py 拆成 shared / content / notes / plan + 聚合入口。

本文件固化：
- 增 / 改 / 删都必须落到 JournalService（真源），不是写 plan.md；
- 定位不到计划项要报错且不写；
- 时长缺省时不覆盖真源里的原值；
- 拆分后 study-daily 的路由集合与拆分前完全一致（防止漏 include 或前缀叠加）。
"""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core.services.journal.models import PlanItem  # noqa: E402
from routers.v1.study_daily import router as study_daily_router  # noqa: E402
from routers.v1.study_daily_plan import (  # noqa: E402
    PlanItemAddRequest,
    PlanItemRefRequest,
    PlanItemUpdateRequest,
    add_plan_item,
    remove_plan_item,
    update_plan_item,
)

# 拆分前后必须一致的 study-daily 路由集合；typed plan GET 是本轮新增合同。
EXPECTED_ROUTES = {
    ("GET", "/study-daily/calendar"),
    ("GET", "/study-daily/date/{date}"),
    ("GET", "/study-daily/latest-progress"),
    ("GET", "/study-daily/notes"),
    ("GET", "/study-daily/notes/{filename}"),
    ("GET", "/study-daily/library"),
    ("GET", "/study-daily/library/note"),
    ("GET", "/study-daily/plan"),
    ("POST", "/study-daily/plan/item/status"),
    ("POST", "/study-daily/plan/item/add"),
    ("POST", "/study-daily/plan/item/update"),
    ("POST", "/study-daily/plan/item/remove"),
}


class _FakePlan(SimpleNamespace):
    """带 items 的假计划对象（PlanItem 用真模型，保证 id/status 字段真实）"""

    def __init__(self, items):
        super().__init__(date="2026-09-11", items=list(items))


class _FakeJournal:
    """记录 add / update / remove / mark 调用的假 JournalService"""

    def __init__(self, plan=None):
        self.plan = plan
        self.add_calls = []
        self.update_calls = []
        self.remove_calls = []

    async def get_plan(self, date=None):
        return self.plan

    async def add_plan_item(self, date, item_dict):
        self.add_calls.append((date, item_dict))
        return self.plan

    async def update_plan_item(self, date, item_id, updates):
        self.update_calls.append((date, item_id, updates))
        return SimpleNamespace(id=item_id)

    async def remove_plan_item(self, date, item_id):
        self.remove_calls.append((date, item_id))
        return SimpleNamespace(id=item_id)


async def _fake_read_text(_path):
    return "- [ ] 08:00 新计划\n"


def _patch_io():
    """屏蔽真实文件系统与学习根目录配置，保证用例可离线跑。"""
    return (
        patch("routers.v1.study_daily_plan._plan_file_path", return_value=Path("plan.md")),
        patch("routers.v1.study_daily_plan._read_text_async", _fake_read_text),
    )


class _RouteTestCase(unittest.IsolatedAsyncioTestCase):
    async def _call(self, journal, coro_factory):
        """必须在 patch 作用域内 await：协程一旦延迟到 with 之外才执行，patch 已撤销，
        端点会拿到真实 JournalService 并改写真实计划数据（本文件曾因此误伤
        companion_data 下的 plan.json）。"""
        plan_patch, read_patch = _patch_io()
        with (
            patch(
                "core.services.journal.service.get_journal_service",
                return_value=journal,
            ),
            # 安全网：即使 patch 作用域写错，也不允许构造真实 JournalService
            patch(
                "core.services.journal.service.JournalService",
                side_effect=AssertionError("测试不得构造真实 JournalService"),
            ),
            plan_patch,
            read_patch,
        ):
            return await coro_factory()


class TestPlanItemAddRoute(_RouteTestCase):
    async def test_add_plan_item_writes_truth_source(self):
        journal = _FakeJournal(_FakePlan([]))
        resp = await self._call(
            journal,
            lambda: add_plan_item(
                PlanItemAddRequest(
                    date="2026-09-11", time="08:00", title="新计划", duration_minutes=30
                )
            ),
        )

        self.assertEqual(resp["status"], "success")
        self.assertEqual(
            journal.add_calls,
            [
                (
                    "2026-09-11",
                    {
                        "time": "08:00",
                        "title": "新计划",
                        "estimated_duration_minutes": 30,
                    },
                )
            ],
        )
        self.assertEqual(resp["data"]["plan"], "- [ ] 08:00 新计划\n")

    async def test_add_without_duration_defers_to_backend_default(self):
        """未填时长时不传该字段，交给后端默认值，避免被客户端写死。"""
        journal = _FakeJournal(_FakePlan([]))
        resp = await self._call(
            journal,
            lambda: add_plan_item(
                PlanItemAddRequest(date="2026-09-11", time="", title="灵活任务")
            ),
        )

        self.assertEqual(resp["status"], "success")
        self.assertEqual(journal.add_calls, [("2026-09-11", {"time": "", "title": "灵活任务"})])

    async def test_add_rejects_blank_title_and_bad_date(self):
        journal = _FakeJournal()
        blank = await self._call(
            journal,
            lambda: add_plan_item(
                PlanItemAddRequest(date="2026-09-11", time="08:00", title="  ")
            ),
        )
        bad_date = await self._call(
            journal,
            lambda: add_plan_item(
                PlanItemAddRequest(date="2026/09/11", time="08:00", title="新计划")
            ),
        )

        self.assertEqual(blank["status"], "error")
        self.assertEqual(bad_date["status"], "error")
        self.assertEqual(journal.add_calls, [])


class TestPlanItemUpdateRoute(_RouteTestCase):
    async def test_update_locates_then_writes_new_values(self):
        item = PlanItem(id="p_core", time="19:00", title="核心学习块")
        journal = _FakeJournal(_FakePlan([item]))
        resp = await self._call(
            journal,
            lambda: update_plan_item(
                PlanItemUpdateRequest(
                    date="2026-09-11",
                    target_time="19:00",
                    target_title="核心学习块",
                    time="20:30",
                    title="核心学习块（改）",
                    duration_minutes=45,
                )
            ),
        )

        self.assertEqual(resp["status"], "success")
        self.assertEqual(
            journal.update_calls,
            [
                (
                    "2026-09-11",
                    "p_core",
                    {
                        "time": "20:30",
                        "title": "核心学习块（改）",
                        "estimated_duration_minutes": 45,
                    },
                )
            ],
        )
        self.assertEqual(resp["data"]["item_id"], "p_core")

    async def test_update_without_duration_keeps_existing_value(self):
        """时长留空表示不改，不能把真源里的原时长冲成默认 60。"""
        item = PlanItem(id="p_core", time="19:00", title="核心学习块")
        journal = _FakeJournal(_FakePlan([item]))
        await self._call(
            journal,
            lambda: update_plan_item(
                PlanItemUpdateRequest(
                    date="2026-09-11",
                    target_time="19:00",
                    target_title="核心学习块",
                    time="20:30",
                    title="核心学习块",
                )
            ),
        )

        self.assertEqual(len(journal.update_calls), 1)
        self.assertNotIn("estimated_duration_minutes", journal.update_calls[0][2])

    async def test_update_unknown_item_returns_error_without_writing(self):
        journal = _FakeJournal(_FakePlan([PlanItem(time="19:00", title="核心学习块")]))
        resp = await self._call(
            journal,
            lambda: update_plan_item(
                PlanItemUpdateRequest(
                    date="2026-09-11",
                    target_time="09:00",
                    target_title="不存在的项",
                    time="10:00",
                    title="不存在的项",
                )
            ),
        )

        self.assertEqual(resp["status"], "error")
        self.assertEqual(journal.update_calls, [])

    async def test_update_matches_drifted_client_title(self):
        """客户端名称带着行尾 ✅ 与时长漂移时仍要能定位。"""
        item = PlanItem(id="p_vocab", time="21:10", title="复习到期英语词汇（123 个）")
        journal = _FakeJournal(_FakePlan([item]))
        await self._call(
            journal,
            lambda: update_plan_item(
                PlanItemUpdateRequest(
                    date="2026-09-11",
                    target_time="21:10",
                    target_title="复习到期英语词汇（123 个）（60分钟） ✅",
                    time="21:10",
                    title="复习到期英语词汇（123 个）",
                )
            ),
        )

        self.assertEqual(journal.update_calls[0][1], "p_vocab")


class TestPlanItemRemoveRoute(_RouteTestCase):
    async def test_remove_locates_then_deletes(self):
        item = PlanItem(id="p_core", time="19:00", title="核心学习块")
        journal = _FakeJournal(_FakePlan([item]))
        resp = await self._call(
            journal,
            lambda: remove_plan_item(
                PlanItemRefRequest(date="2026-09-11", time="19:00", title="核心学习块")
            ),
        )

        self.assertEqual(resp["status"], "success")
        self.assertEqual(journal.remove_calls, [("2026-09-11", "p_core")])

    async def test_remove_unknown_item_returns_error_without_writing(self):
        journal = _FakeJournal(_FakePlan([PlanItem(time="19:00", title="核心学习块")]))
        resp = await self._call(
            journal,
            lambda: remove_plan_item(
                PlanItemRefRequest(date="2026-09-11", time="19:00", title="不存在的项")
            ),
        )

        self.assertEqual(resp["status"], "error")
        self.assertEqual(journal.remove_calls, [])

    async def test_remove_blank_title_returns_error(self):
        journal = _FakeJournal(_FakePlan([PlanItem(time="19:00", title="核心学习块")]))
        resp = await self._call(
            journal,
            lambda: remove_plan_item(
                PlanItemRefRequest(date="2026-09-11", time="19:00", title="   ")
            ),
        )

        self.assertEqual(resp["status"], "error")
        self.assertEqual(journal.remove_calls, [])


class TestStudyDailyRouteRegistry(unittest.TestCase):
    def test_study_daily_routes_unchanged_after_split(self):
        """拆分后聚合入口必须仍注册出完整 study-daily 路由集合。"""
        actual = {
            (method, route.path)
            for route in study_daily_router.routes
            for method in (getattr(route, "methods", None) or [])
        }

        self.assertEqual(actual, EXPECTED_ROUTES)
        # 前缀叠加（/study-daily/study-daily/*）会立刻在这里暴露
        self.assertFalse(
            [path for _, path in actual if path.startswith("/study-daily/study-daily")]
        )


if __name__ == "__main__":
    unittest.main()
