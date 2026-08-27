"""晚安计划结算的跨日与展示语义回归测试。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from core.services.active_care.core.sleep_session_manager import SleepSessionManager
from core.services.journal.models import DailyPlan, PlanItem
from core.services.journal.service import JournalService
from core.utils.time_utils import from_timestamp


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
async def test_sleep_signal_cannot_settle_plan_generated_after_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧晚安信号不能清空夜间任务随后生成的新计划。"""
    service = JournalService()
    monkeypatch.setattr(
        service.storage,
        "get_daily_dir",
        lambda date, scope="user": _build_daily_dir(tmp_path, date, scope),
    )
    sleep_ts = from_timestamp(4102442400).timestamp()  # 2099-12-31 22:00
    plan_date = from_timestamp(sleep_ts)
    plan = DailyPlan(
        date=plan_date.strftime("%Y-%m-%d"),
        generated_at=sleep_ts + 300,
        items=[PlanItem(time="08:00", title="英语复习")],
    )
    await service.storage.save_plan(plan, plan_date, scope="user")

    result = await service._plan_checkpoint_service.settle_today_plan_on_sleep(
        sleep_ts=sleep_ts
    )

    loaded = await service.storage.get_plan(plan_date, scope="user")
    assert result["reason"] == "plan_generated_after_sleep_signal"
    assert loaded is not None
    assert [item.status for item in loaded.items] == ["pending"]


@pytest.mark.asyncio
async def test_sleep_settlement_marks_items_as_rollable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """睡眠自动结算必须留下 sleep 来源，供第二天候选生成器识别。"""
    service = JournalService()
    monkeypatch.setattr(
        service.storage,
        "get_daily_dir",
        lambda date, scope="user": _build_daily_dir(tmp_path, date, scope),
    )
    signal_ts = from_timestamp(4102442400).timestamp()
    plan_date = from_timestamp(signal_ts)
    plan = DailyPlan(
        date=plan_date.strftime("%Y-%m-%d"),
        generated_at=signal_ts - 60,
        items=[PlanItem(time="20:00", title="未完成学习块", status="pending")],
    )
    await service.storage.save_plan(plan, plan_date, scope="user")

    async def _cleanup(_plan: DailyPlan, **_: object) -> int:
        return 0

    async def _sync(_plan: DailyPlan, _date: datetime) -> None:
        return None

    monkeypatch.setattr(service._plan_service, "_cleanup_plan_reminders", _cleanup)
    monkeypatch.setattr(service._plan_service, "_sync_plan_to_study_daily", _sync)

    result = await service._plan_checkpoint_service.settle_today_plan_on_sleep(
        sleep_ts=signal_ts
    )
    loaded = await service.storage.get_plan(plan_date, scope="user")

    assert result["settled"] is True
    assert loaded is not None
    assert loaded.source == "algorithm_adjusted"
    assert loaded.items[0].status == "skipped"
    assert loaded.items[0].settlement_reason == "sleep"


@pytest.mark.asyncio
async def test_same_goodnight_signal_is_not_processed_twice() -> None:
    """轮询反复读到同一条晚安时，不应再次保存状态或结算计划。"""

    class _Storage:
        def __init__(self) -> None:
            self.saved: list[dict[str, Any]] = []

        async def save_user_sleep_state(
            self, updates: dict[str, Any], immediate: bool = False
        ) -> dict[str, Any]:
            self.saved.append(dict(updates))
            return dict(updates)

    storage = _Storage()
    manager = SleepSessionManager(
        intent_detector=None,
        sleep_policy=None,
        storage=storage,
        get_config_value=lambda attr, default: (
            True
            if attr == "active_care_enable_auto_goodnight_reduced_mode"
            else default
        ),
    )
    signal_ts = 4102442400.0
    state = {
        "last_goodnight_ts": signal_ts,
        "reduced_mode_active": True,
        "reduced_mode_reason": "goodnight",
    }

    result = await manager._try_enter_goodnight_on_intent(
        signal_ts + 600,
        state,
        inferred_goodnight=True,
        inferred_goodmorning=False,
        inferred_ts=signal_ts,
    )

    assert result is state
    assert storage.saved == []


def test_skipped_plan_markdown_is_not_checked() -> None:
    """跳过项必须与已完成项使用不同 checkbox 语义。"""
    service = JournalService()
    plan = DailyPlan(
        date="2099-12-31",
        items=[
            PlanItem(time="08:00", title="已完成", status="completed"),
            PlanItem(time="09:00", title="已跳过", status="skipped"),
        ],
    )

    markdown = service._plan_service._format_plan_as_markdown(plan)

    assert "- [x] 08:00 已完成" in markdown
    assert "- [ ] 09:00 已跳过" in markdown
    assert "- [x] 09:00 已跳过" not in markdown
