"""计划项勾选接口 ``POST /study-daily/plan/item/status`` 的写入语义回归测试。

背景（2026-09-11）：
    用户反馈"安卓端 study 模块里的计划，勾了他不持久化，换个页面回去又没勾上"。
    核查 ``D:\\AI\\Study\\Daily\\2026\\09\\11\\plan.md`` 与计划真源
    ``companion_data/user_data/daily/2026/09/11/plan.json`` 发现两者严重不一致：

        plan.md  : 3 条，全部 "- [x]"
        plan.json: 4 条，全部 "status: pending"

    根因是安卓端勾选只把整篇 plan.md 覆盖写回，从不写计划真源；而后端每一次
    计划同步（12 点 / 18 点检查点重排、睡眠结算、背完单词自动勾选）都会用
    真源重新生成 plan.md（日志可查 12:01:22、18:00:09 两次"计划已同步到
    Study Daily"），把用户刚勾上的状态整片抹掉。

    修复：新增本接口，勾选改走 ``JournalService.mark_plan_item_status`` 写回
    真源，由真源统一派生 plan.md。

本文件固化该接口的关键约束：
- 客户端标题可能带行尾状态标记 / 时长括号，必须归一化后仍能命中；
- 同名多条按时间消歧，无法唯一定位时宁可报错也不误标；
- 写状态必须带**显式日期**（``mark_plan_item_status(None)`` 会落到"明日"）；
- 命中失败返回错误而非静默成功。
"""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core.services.journal.models import DailyPlan, PlanItem  # noqa: E402
from routers.v1.study_daily_plan import (  # noqa: E402
    PlanItemStatusRequest,
    _match_plan_item,
    _normalize_plan_title,
    update_plan_item_status,
)


class _FakeJournal:
    """记录 mark_plan_item_status 调用的假 JournalService。"""

    def __init__(self, plan):
        self.plan = plan
        self.mark_calls = []

    async def get_plan(self, date=None):
        self.get_plan_date = date
        return self.plan

    async def mark_plan_item_status(self, date, item_id, status):
        self.mark_calls.append((date, item_id, status))
        return SimpleNamespace(id=item_id, status=status)


async def _fake_read_text(_path):
    return "- [x] 19:00 核心学习块\n"


def _plan(*items):
    return DailyPlan(date="2026-09-11", items=list(items))


def _patch_io():
    """屏蔽真实文件系统与学习根目录配置，保证用例可离线跑。"""
    return (
        patch("routers.v1.study_daily_plan._plan_file_path", return_value=Path("plan.md")),
        patch("routers.v1.study_daily_plan._read_text_async", _fake_read_text),
    )


class TestPlanItemStatusRoute(unittest.IsolatedAsyncioTestCase):
    async def _call(self, journal, *, date="2026-09-11", time="", title="核心学习块", done=True):
        plan_patch, read_patch = _patch_io()
        with (
            patch("core.services.journal.service.get_journal_service", return_value=journal),
            # 安全网：即使 patch 作用域写错，也不允许构造真实 JournalService 改真实数据
            patch(
                "core.services.journal.service.JournalService",
                side_effect=AssertionError("测试不得构造真实 JournalService"),
            ),
            plan_patch,
            read_patch,
        ):
            return await update_plan_item_status(
                PlanItemStatusRequest(date=date, time=time, title=title, done=done)
            )

    async def test_checked_item_writes_completed_into_truth_source(self):
        """勾选必须写回真源，且使用显式日期（不是 None / 明日）。"""
        journal = _FakeJournal(_plan(PlanItem(id="p_core", time="19:00", title="核心学习块")))
        resp = await self._call(journal, time="19:00", done=True)

        self.assertEqual(resp["status"], "success")
        self.assertEqual(journal.get_plan_date, "2026-09-11")
        self.assertEqual(
            journal.mark_calls, [("2026-09-11", "p_core", "completed")]
        )
        self.assertEqual(resp["data"]["status"], "completed")
        self.assertEqual(resp["data"]["plan"], "- [x] 19:00 核心学习块\n")

    async def test_unchecked_item_writes_pending(self):
        """取消勾选写回 pending，而不是 skipped/completed。"""
        journal = _FakeJournal(
            _plan(PlanItem(id="p_core", time="19:00", title="核心学习块", status="completed"))
        )
        resp = await self._call(journal, time="19:00", done=False)

        self.assertEqual(resp["status"], "success")
        self.assertEqual(journal.mark_calls, [("2026-09-11", "p_core", "pending")])

    async def test_title_normalization_matches_all_source_forms(self):
        """真源标题、后端生成的 plan.md 行、安卓回写的行都要能命中。"""
        target = PlanItem(id="p_vocab", time="21:10", title="复习到期英语词汇（123 个）")
        journal = _FakeJournal(_plan(target))

        forms = (
            "复习到期英语词汇（123 个）",
            "复习到期英语词汇（123 个） （60分钟）",
            "复习到期英语词汇（123 个）（60分钟） ✅",
            " 复习到期英语词汇（123 个） ",
        )
        for form in forms:
            journal.mark_calls.clear()
            resp = await self._call(journal, time="21:10", title=form, done=True)
            self.assertEqual(resp["status"], "success", msg=form)
            self.assertEqual(journal.mark_calls, [("2026-09-11", "p_vocab", "completed")], msg=form)

    async def test_client_title_shorter_than_truth_still_matches(self):
        """安卓把行尾括号当 duration 剥掉后，名称比真源短也要能命中。"""
        journal = _FakeJournal(
            _plan(PlanItem(id="p_math", time="09:00", title="复习数学（第1章）"))
        )
        resp = await self._call(journal, time="09:00", title="复习数学", done=True)

        self.assertEqual(resp["status"], "success")
        self.assertEqual(journal.mark_calls, [("2026-09-11", "p_math", "completed")])

    async def test_same_title_disambiguated_by_time(self):
        """同名多条时按时间命中，不误标另一条。"""
        journal = _FakeJournal(
            _plan(
                PlanItem(id="p_morning", time="08:00", title="复习到期英语词汇（52 个）"),
                PlanItem(id="p_night", time="21:10", title="复习到期英语词汇（52 个）"),
            )
        )
        resp = await self._call(journal, time="21:10", title="复习到期英语词汇（52 个）", done=True)

        self.assertEqual(resp["status"], "success")
        self.assertEqual(journal.mark_calls, [("2026-09-11", "p_night", "completed")])

    async def test_ambiguous_candidates_are_not_marked(self):
        """同名多条且无法按时间消歧时宁可报错，也不猜着标。"""
        journal = _FakeJournal(
            _plan(
                PlanItem(id="p1", time="08:00", title="复习到期英语词汇（52 个）"),
                PlanItem(id="p2", time="21:10", title="复习到期英语词汇（52 个）"),
            )
        )
        resp = await self._call(journal, time="", title="复习到期英语词汇（52 个）", done=True)

        self.assertEqual(resp["status"], "error")
        self.assertEqual(journal.mark_calls, [])

    async def test_unknown_item_returns_error_without_writing(self):
        """真源里找不到的计划项必须报错，不能静默成功。"""
        journal = _FakeJournal(_plan(PlanItem(id="p_core", time="19:00", title="核心学习块")))
        resp = await self._call(journal, time="19:00", title="不存在的计划项", done=True)

        self.assertEqual(resp["status"], "error")
        self.assertEqual(journal.mark_calls, [])

    async def test_blank_title_is_rejected(self):
        journal = _FakeJournal(_plan(PlanItem(id="p_core", time="19:00", title="核心学习块")))
        resp = await self._call(journal, time="19:00", title="   ", done=True)

        self.assertEqual(resp["status"], "error")
        self.assertEqual(journal.mark_calls, [])

    async def test_invalid_date_is_rejected_before_touching_journal(self):
        journal = _FakeJournal(_plan(PlanItem(id="p_core", time="19:00", title="核心学习块")))
        resp = await self._call(journal, date="2026/09/11", time="19:00", done=True)

        self.assertEqual(resp["status"], "error")
        self.assertEqual(journal.mark_calls, [])

    def test_match_item_by_title_only_when_unique(self):
        """无固定时间的"灵活"项只给名称也应能命中。"""
        plan = _plan(PlanItem(id="p_flex", time=None, title="巩固昨日重点：general"))
        matched = _match_plan_item(
            plan, "", _normalize_plan_title("巩固昨日重点：general")
        )
        self.assertIsNotNone(matched)
        self.assertEqual(matched.id, "p_flex")


class TestVocabPlanAutoMarkDate(unittest.IsolatedAsyncioTestCase):
    """背完单词自动勾选计划项必须写今日计划，不能落到"明日"。"""

    async def test_auto_mark_uses_plan_date_not_none(self):
        from routers.v1 import vocab as vocab_router

        plan = DailyPlan(
            date="2026-09-11",
            items=[
                PlanItem(
                    id="p_vocab",
                    time="21:10",
                    title="复习到期英语词汇（123 个）",
                    source_key="vocab:due_review",
                )
            ],
        )
        journal = _FakeJournal(plan)
        service = SimpleNamespace(get_today_review_status=lambda: {"completed": True})

        with patch(
            "core.services.journal.service.get_journal_service", return_value=journal
        ):
            got = await vocab_router._mark_vocab_plan_completed_if_done(service)  # noqa: SLF001

        self.assertTrue(got)
        self.assertEqual(journal.mark_calls, [("2026-09-11", "p_vocab", "completed")])


if __name__ == "__main__":
    unittest.main()
