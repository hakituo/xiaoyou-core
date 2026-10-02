"""验证每日总结只有一条调度链路。

跑法：
    venv_cpu/bin/python tests/scripts/journal/verify_daily_summary_dispatch.py

三条入口（nightly 正线 / 睡眠补写 / nightly 睡眠标记）都必须：
1. 从注册角色取名单，换注册配置就换写日记的对象；
2. 不再出现 aveline / ling 这类角色字面量。
"""
from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager
from datetime import timezone
from pathlib import Path
from typing import ClassVar
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PASSED: list[str] = []
FAILED: list[str] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASSED.append(name)
        print(f"[OK] {name}")
    else:
        FAILED.append(name)
        print(f"[FAIL] {name} {detail}")


@contextmanager
def _registered_roles(role_ids: set):
    """临时把注册角色换成给定集合。"""
    with mock.patch(
        "core.character.runtime_roles.get_autonomous_role_ids",
        return_value=frozenset(role_ids),
    ):
        yield


class _FakeSummary:
    summary = "角色日记正文"
    stats: ClassVar[dict] = {}


def _patch_journal(calls: list) -> mock._patch:
    class _FakeJournal:
        async def generate_daily_summary(
            self, _date, force=False, persona="aveline", distinct_from=None
        ):
            calls.append((persona, force))
            return _FakeSummary()

    return mock.patch(
        "core.services.journal.service.get_journal_service",
        return_value=_FakeJournal(),
    )


def _verify_nightly_line() -> None:
    """nightly 正线：force=True，角色随注册配置变化。"""
    import datetime

    from memory.nightly.global_tasks import NightlyGlobalTaskService

    calls: list = []
    results: dict = {}
    expected = ["aveline", "ling"]

    async def run() -> None:
        service = NightlyGlobalTaskService()
        with _registered_roles(set(expected)), _patch_journal(calls), mock.patch(
            "memory.nightly.global_tasks.is_valid_daily_summary_obj", return_value=True
        ), mock.patch.object(
            NightlyGlobalTaskService, "_ensure_diary_file", staticmethod(lambda _d: None)
        ), mock.patch.object(
            NightlyGlobalTaskService,
            "_mark_roles_nightly_done",
            staticmethod(lambda _d, _r: None),
        ), mock.patch.object(
            NightlyGlobalTaskService,
            "_review_digital_wellbeing",
            staticmethod(lambda *_a: None),
        ), mock.patch.object(
            NightlyGlobalTaskService,
            "_generate_next_day_plan",
            new=mock.AsyncMock(return_value=None),
        ):
            await service._run_journal_plan_and_wellbeing(
                datetime.date(2026, 9, 25), results
            )

    asyncio.run(run())
    _check("nightly 只为注册角色写日记", [c[0] for c in calls] == expected, f"calls={calls}")
    _check("nightly 走 force=True", all(c[1] for c in calls), f"calls={calls}")


def _verify_backfill_line() -> None:
    """睡眠补写：force=False，角色同样随注册配置变化。"""
    from datetime import datetime

    from core.services.journal import daily_summary_dispatch as dispatch

    calls: list = []
    expected = ["aveline", "ling"]

    async def run() -> None:
        with _registered_roles(set(expected)), _patch_journal(calls), mock.patch.object(
            dispatch, "get_diary_target_date_str", lambda _dt: "2026-09-25"
        ), mock.patch(
            "core.services.journal.summary_guard.is_valid_daily_summary_obj",
            return_value=True,
        ):
            await dispatch.backfill_after_sleep(
                datetime(2026, 9, 26, 0, 10, tzinfo=timezone.utc), is_sleeping=True
            )

    dispatch.reset_backfill_state()
    asyncio.run(run())
    _check("补写只为注册角色写日记", [c[0] for c in calls] == expected, f"calls={calls}")
    _check("补写走 force=False（不覆盖 nightly）", not any(c[1] for c in calls), f"calls={calls}")
    dispatch.reset_backfill_state()


def _verify_sleep_marks_line() -> None:
    """nightly 睡眠标记也只打给注册角色。"""
    from memory.nightly import sleep_hooks

    marked: list[str] = []

    class _FakeSleepManager:
        def mark_nightly_done(self, role_id: str, date_str: str) -> None:
            marked.append(role_id)

    with _registered_roles({"aveline", "ling"}), mock.patch(
        "core.services.life_simulation.sleep_manager.get_sleep_manager",
        return_value=_FakeSleepManager(),
    ):
        sleep_hooks.mark_roles_nightly_done("2026-09-25")

    _check("睡眠标记只打给注册角色", sorted(marked) == ["aveline", "ling"], f"marked={marked}")


def main() -> int:
    print("=== 验证每日总结只有一条调度链路 ===\n")
    _verify_nightly_line()
    _verify_backfill_line()
    _verify_sleep_marks_line()

    print(f"\n结果: {len(PASSED)} 通过, {len(FAILED)} 失败")
    if FAILED:
        print("失败项:", ", ".join(FAILED))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
