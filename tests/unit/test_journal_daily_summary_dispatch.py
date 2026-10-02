"""每日总结统一调度入口的行为契约。

要守的三件事：
1. 生成对象永远是注册角色（角色不能写死在任何调用方）
2. 补写窗口（凌晨 + 用户睡着）与去重只在这里判断
3. 单个角色失败不拖垮其余角色，且失败可重试
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.services.journal import daily_summary_dispatch as dispatch


def _at(hour: int, minute: int = 0) -> datetime:
    """构造测试时刻：日期归属只看 hour，时区不参与调度判断。"""
    return datetime(2026, 9, 26, hour, minute, tzinfo=timezone.utc)


class _FakeSummary:
    def __init__(self, text: str) -> None:
        self.summary = text
        self.stats: dict = {}


@pytest.fixture(autouse=True)
def _isolated_backfill_state():
    dispatch.reset_backfill_state()
    yield
    dispatch.reset_backfill_state()


@pytest.fixture
def registered_roles(monkeypatch):
    """固定注册角色为 aveline + ye（与当前 character_runtime.yaml 一致）。"""
    monkeypatch.setattr(
        "core.services.journal.diary_personas.get_diary_persona_ids",
        lambda: ("aveline", "ye"),
    )
    monkeypatch.setattr(
        "core.services.journal.summary_guard.is_valid_daily_summary_obj",
        lambda _summary: True,
    )
    return ("aveline", "ye")


def _patch_journal(monkeypatch, calls: list[tuple[str, bool, object]], *, fail_for=()):
    class _FakeJournal:
        async def generate_daily_summary(
            self, _date, force=False, persona="aveline", distinct_from=None
        ):
            calls.append((persona, force, distinct_from))
            if persona in fail_for:
                raise RuntimeError("生成失败")
            return _FakeSummary(f"{persona} 的日记正文")

    monkeypatch.setattr(
        "core.services.journal.service.get_journal_service",
        lambda: _FakeJournal(),
    )


async def test_generates_for_registered_roles_only(monkeypatch, registered_roles):
    calls: list[tuple[str, bool, object]] = []
    _patch_journal(monkeypatch, calls)

    results = await dispatch.generate_registered_summaries(
        "2026-09-25", force=True, reason="nightly"
    )

    assert tuple(results) == registered_roles
    assert [call[0] for call in calls] == list(registered_roles)
    assert all(call[1] is True for call in calls)  # nightly 走 force=True


async def test_unregistered_role_never_receives_diary(monkeypatch, registered_roles):
    """回归：ling 已从注册角色摘掉，不能再给她写日记。"""
    calls: list[tuple[str, bool, object]] = []
    _patch_journal(monkeypatch, calls)

    await dispatch.generate_registered_summaries(
        "2026-09-25", force=False, reason="sleep_backfill"
    )

    assert "ling" not in [call[0] for call in calls]


async def test_distinct_from_carries_previous_text(monkeypatch, registered_roles):
    calls: list[tuple[str, bool, object]] = []
    _patch_journal(monkeypatch, calls)

    await dispatch.generate_registered_summaries(
        "2026-09-25", force=True, reason="nightly"
    )

    assert calls[0][2] is None
    assert "aveline 的日记正文" in str(calls[1][2] or "")


async def test_single_role_failure_does_not_block_others(monkeypatch, registered_roles):
    calls: list[tuple[str, bool, object]] = []
    _patch_journal(monkeypatch, calls, fail_for=("aveline",))

    results = await dispatch.generate_registered_summaries(
        "2026-09-25", force=True, reason="nightly"
    )

    assert results["aveline"] is None
    assert results["ye"] is not None
    assert len(calls) == 2  # 前一个失败后仍然继续


async def test_no_registered_role_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "core.services.journal.diary_personas.get_diary_persona_ids",
        lambda: (),
    )
    calls: list[tuple[str, bool, object]] = []
    _patch_journal(monkeypatch, calls)

    assert await dispatch.generate_registered_summaries(
        "2026-09-25", force=True, reason="nightly"
    ) == {}
    assert calls == []


async def test_backfill_skipped_when_user_not_sleeping(monkeypatch, registered_roles):
    calls: list[tuple[str, bool, object]] = []
    _patch_journal(monkeypatch, calls)
    monkeypatch.setattr(dispatch, "get_diary_target_date_str", lambda _dt: "2026-09-25")

    assert (
        await dispatch.backfill_after_sleep(
            _at(0, 10), is_sleeping=False
        )
        == {}
    )
    assert calls == []


async def test_backfill_skipped_after_noon(monkeypatch, registered_roles):
    """中午之后日期归属指向"今天"，此时补写会写出空日记，必须挡掉。"""
    calls: list[tuple[str, bool, object]] = []
    _patch_journal(monkeypatch, calls)
    monkeypatch.setattr(dispatch, "get_diary_target_date_str", lambda _dt: "2026-09-26")

    assert (
        await dispatch.backfill_after_sleep(
            _at(13, 0), is_sleeping=True
        )
        == {}
    )
    assert calls == []


async def test_backfill_runs_once_per_date(monkeypatch, registered_roles):
    calls: list[tuple[str, bool, object]] = []
    _patch_journal(monkeypatch, calls)
    monkeypatch.setattr(dispatch, "get_diary_target_date_str", lambda _dt: "2026-09-25")

    first = await dispatch.backfill_after_sleep(
        _at(0, 10), is_sleeping=True
    )
    second = await dispatch.backfill_after_sleep(
        _at(0, 20), is_sleeping=True
    )

    assert len(first) == 2
    assert second == {}
    assert len(calls) == 2
    assert all(call[1] is False for call in calls)  # 补写只补缺口，不覆盖


async def test_backfill_retries_after_failure(monkeypatch, registered_roles):
    calls: list[tuple[str, bool, object]] = []
    _patch_journal(monkeypatch, calls, fail_for=("ye",))
    monkeypatch.setattr(dispatch, "get_diary_target_date_str", lambda _dt: "2026-09-25")

    await dispatch.backfill_after_sleep(_at(0, 10), is_sleeping=True)
    assert len(calls) == 2

    class _OkJournal:
        async def generate_daily_summary(
            self, _d, force=False, persona="aveline", distinct_from=None
        ):
            return _FakeSummary(f"{persona} 的日记正文")

    monkeypatch.setattr(
        "core.services.journal.service.get_journal_service",
        lambda: _OkJournal(),
    )
    retry = await dispatch.backfill_after_sleep(
        _at(0, 20), is_sleeping=True
    )
    assert len(retry) == 2


async def test_schedule_backfill_is_fire_and_forget(monkeypatch, registered_roles):
    calls: list[tuple[str, bool, object]] = []
    _patch_journal(monkeypatch, calls)
    monkeypatch.setattr(dispatch, "get_diary_target_date_str", lambda _dt: "2026-09-25")

    task = dispatch.schedule_backfill_after_sleep(
        _at(0, 10), is_sleeping=True
    )
    assert task is not None
    await task
    assert len(calls) == 2

    assert (
        dispatch.schedule_backfill_after_sleep(
            _at(0, 30), is_sleeping=True
        )
        is None
    )
