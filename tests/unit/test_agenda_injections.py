"""议程注入优先级竞争的守卫测试（2026-10-01 新增）。

背景：`dynamic_context.build_stream_messages` 原本把 5 段议程上下文全部塞进
user 消息前缀，导致角色把与当前话题无关的事也塞进同一句回复（实测：用户只说
「买了个显示器」，回复里同时出现催饭和「176 个词今天压着呢」）。

改成「按优先级取第一条命中的」之后，有两条语义必须钉住：
1. 每轮最多注入 1 条议程；
2. **没被选中的那条不能被消费** —— P1 计划提醒走 peek（不是 get_and_clear），
   P2 学习任务走 peek（不落盘）。否则「176 个单词今天没人提」会真的发生。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.agents.chat_agent_components.streaming_pipeline import agenda_injections as ai
from core.services.active_care.shared.reminder_injection import (
    get_reminder_injection_store,
)


@pytest.fixture(autouse=True)
def isolated_marker_dir(tmp_path, monkeypatch):
    """把「每天一次」标记文件隔离到 tmp_path。

    标记走 get_user_data_dir()，不隔离就会写进真实 companion_data ——
    正是 2026-10-01 在 tests/journal_plan 那边踩过的坑。
    """
    import core.utils.data_paths as data_paths

    monkeypatch.setattr(data_paths, "get_user_data_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def fake_ladder(monkeypatch):
    """把优先级阶梯换成可控的假探针，并记录每次调用与提交。

    第三项 once_per_day 统一给 False —— 优先级行为与「每天一次」节流分开测。
    """

    def build(*, hits: dict[str, str]):
        calls: list[str] = []
        commits: list[str] = []

        def make(name: str):
            async def probe(ctx):
                calls.append(name)
                text = hits.get(name, "")
                if not text:
                    return "", None

                async def commit():
                    commits.append(name)

                return text, commit

            return probe

        ladder = tuple((name, make(name), False) for name in ai.AGENDA_PRIORITY)
        monkeypatch.setattr(ai, "_LADDER", ladder)
        return calls, commits

    return build


@pytest.mark.asyncio
async def test_picks_highest_priority_and_stops(fake_ladder):
    """多条命中时只取优先级最高的那条，且不再继续探测。"""
    calls, _commits = fake_ladder(hits={
        "tomorrow_tone": "【今日总基调】x",
        "today_plan": "【今日学习生活计划】x",
        "meal_care": "【饮食提醒】x",
    })
    name, text, _commit = await ai.pick_agenda_injection(agent=None, user_id="u1")

    assert name == "tomorrow_tone"
    assert text == "【今日总基调】x"
    # P1/P2 没命中要继续探测，命中后立即停 → 只应探测到 tomorrow_tone 为止
    assert calls == ["plan_reminder", "daily_study_task", "tomorrow_tone"]


@pytest.mark.asyncio
async def test_returns_empty_when_nothing_hits(fake_ladder):
    calls, _commits = fake_ladder(hits={})
    name, text, commit = await ai.pick_agenda_injection(agent=None, user_id="u1")

    assert (name, text, commit) == ("", "", None)
    # 全不命中时要探测完整个阶梯
    assert calls == list(ai.AGENDA_PRIORITY)


@pytest.mark.asyncio
async def test_commit_only_runs_for_the_winner(fake_ladder):
    """提交回调只有胜出那条会被调用 —— 落选者不能被消费。"""
    _calls, commits = fake_ladder(hits={
        "daily_study_task": "【每日总结】x",
        "tomorrow_tone": "【今日总基调】x",
    })
    name, _text, commit = await ai.pick_agenda_injection(agent=None, user_id="u1")

    assert name == "daily_study_task"
    assert commits == []  # 调用方还没提交
    await commit()
    assert commits == ["daily_study_task"]


@pytest.mark.asyncio
async def test_probe_exception_does_not_abort_ladder(fake_ladder, monkeypatch):
    """某条探测抛异常时应跳过它、继续往下探测，而不是整轮没有议程。"""
    _calls, _commits = fake_ladder(hits={"tomorrow_tone": "【今日总基调】x"})

    async def boom(ctx):
        raise RuntimeError("probe 炸了")

    ladder = list(ai._LADDER)
    ladder[0] = ("plan_reminder", boom, False)
    monkeypatch.setattr(ai, "_LADDER", tuple(ladder))

    name, _text, _commit = await ai.pick_agenda_injection(agent=None, user_id="u1")
    assert name == "tomorrow_tone"


@pytest.mark.asyncio
async def test_reminder_peek_does_not_consume():
    """P1 的 peek 不能消费提醒队列 —— 没被选中时要留到下一轮。"""
    store = get_reminder_injection_store()
    await store.clear()
    await store.set_pending_reminder(
        reminder_text="该开物理了", task_title="复习恒定电流", ttl_seconds=300
    )
    try:
        first = await store.peek()
        second = await store.peek()
        assert first and second, "peek 之后提醒不该消失"
        assert first["task_title"] == "复习恒定电流"

        # 只有显式 clear() 才消费
        await store.clear()
        assert await store.peek() is None
    finally:
        await store.clear()


@pytest.mark.asyncio
async def test_reminder_probe_returns_clear_as_commit():
    """P1 命中的提交回调必须是 store.clear（选中后才消费）。"""
    store = get_reminder_injection_store()
    await store.clear()
    await store.set_pending_reminder(
        reminder_text="该开物理了", task_title="复习恒定电流", ttl_seconds=300
    )
    try:
        text, commit = await ai._probe_plan_reminder({})
        assert "【计划提醒】" in text
        assert "复习恒定电流" in text
        assert commit is not None
        assert await store.peek() is not None, "探测阶段不该消费"
        await commit()
        assert await store.peek() is None, "提交后应已消费"
    finally:
        await store.clear()


# ────────────────────── once_per_day 节流 ──────────────────────


def _ladder_with(once: set[str]):
    """复制当前阶梯，把名字在 once 里的条目标成 once_per_day。"""
    return tuple((n, p, n in once) for n, p, _ in ai._LADDER)


@pytest.mark.asyncio
async def test_state_agenda_injected_only_once_per_day(fake_ladder):
    """状态型议程（once_per_day=True）当天只注入一次，第二次就沉寂。

    这是 2026-10-01 的真实故障：today_plan 有内容而 P1/P2/P3 全空，
    于是连续 7 轮每轮都胜出，角色每轮都在提「十八点半那个数学还挂着」。
    """
    _calls, commits = fake_ladder(hits={"today_plan": "【今日计划】x"})
    with patch.object(ai, "_LADDER", _ladder_with({"today_plan"})):
        first = await ai.pick_agenda_injection(agent=None, user_id="u1")
        assert first[0] == "today_plan"
        await first[2]()  # 提交 → 写「今天已注入」标记

        second = await ai.pick_agenda_injection(agent=None, user_id="u1")
        assert second == ("", "", None), "当天第二次不该再注入 today_plan"
    assert commits == ["today_plan"]


@pytest.mark.asyncio
async def test_once_per_day_is_per_user(fake_ladder, isolated_marker_dir):
    """节流按会话隔离：另一个会话不受影响。"""
    fake_ladder(hits={"today_plan": "x"})
    with patch.object(ai, "_LADDER", _ladder_with({"today_plan"})):
        name, _t, commit = await ai.pick_agenda_injection(agent=None, user_id="u1")
        assert name == "today_plan"
        await commit()

        other, _t2, _c2 = await ai.pick_agenda_injection(agent=None, user_id="u2")
        assert other == "today_plan"

    from core.utils.time_utils import now_str

    today = now_str("%Y-%m-%d")
    marker = ai._marker_path("u1", today)
    # 标记必须落在隔离目录里，绝不能写进真实 companion_data
    assert str(marker).startswith(str(isolated_marker_dir))
    assert ai._already_injected("u1", "today_plan", today) is True
    assert ai._already_injected("u2", "today_plan", today) is False
    assert ai._already_injected("u1", "tomorrow_tone", today) is False


@pytest.mark.asyncio
async def test_event_agenda_not_throttled(fake_ladder):
    """事件型（once_per_day=False，如计划提醒）不该被节流拦住。"""
    _calls, _commits = fake_ladder(hits={"plan_reminder": "【计划提醒】x"})
    with patch.object(ai, "_LADDER", _ladder_with({"tomorrow_tone", "today_plan"})):
        for _ in range(2):
            name, _t, commit = await ai.pick_agenda_injection(agent=None, user_id="u1")
            assert name == "plan_reminder"
            await commit()


# ────────────────────── once_per_day 节流 ──────────────────────


def _ladder_with(once: set[str]):
    """复制当前阶梯，把名字在 once 里的条目标成 once_per_day。"""
    return tuple((n, p, n in once) for n, p, _ in ai._LADDER)


@pytest.mark.asyncio
async def test_state_agenda_injected_only_once_per_day(fake_ladder):
    """状态型议程（once_per_day=True）当天只注入一次，第二次就沉寂。

    这是 2026-10-01 的真实故障：today_plan 有内容而 P1/P2/P3 全空，
    于是连续 7 轮每轮都胜出，角色每轮都在提「十八点半那个数学还挂着」。
    """
    _calls, commits = fake_ladder(hits={"today_plan": "【今日计划】x"})
    with patch.object(ai, "_LADDER", _ladder_with({"today_plan"})):
        first = await ai.pick_agenda_injection(agent=None, user_id="u1")
        assert first[0] == "today_plan"
        await first[2]()  # 提交 → 写「今天已注入」标记

        second = await ai.pick_agenda_injection(agent=None, user_id="u1")
        assert second == ("", "", None), "当天第二次不该再注入 today_plan"
    assert commits == ["today_plan"]


@pytest.mark.asyncio
async def test_once_per_day_is_per_user(fake_ladder, isolated_marker_dir):
    """节流按会话隔离：另一个会话不受影响。"""
    fake_ladder(hits={"today_plan": "x"})
    with patch.object(ai, "_LADDER", _ladder_with({"today_plan"})):
        name, _t, commit = await ai.pick_agenda_injection(agent=None, user_id="u1")
        assert name == "today_plan"
        await commit()

        other, _t2, _c2 = await ai.pick_agenda_injection(agent=None, user_id="u2")
        assert other == "today_plan"

    from core.utils.time_utils import now_str

    today = now_str("%Y-%m-%d")
    marker = ai._marker_path("u1", today)
    # 标记必须落在隔离目录里，绝不能写进真实 companion_data
    assert str(marker).startswith(str(isolated_marker_dir))
    assert ai._already_injected("u1", "today_plan", today) is True
    assert ai._already_injected("u2", "today_plan", today) is False
    assert ai._already_injected("u1", "tomorrow_tone", today) is False


@pytest.mark.asyncio
async def test_event_agenda_not_throttled(fake_ladder):
    """事件型（once_per_day=False，如计划提醒）不该被节流拦住。"""
    _calls, _commits = fake_ladder(hits={"plan_reminder": "【计划提醒】x"})
    with patch.object(ai, "_LADDER", _ladder_with({"tomorrow_tone", "today_plan"})):
        for _ in range(2):
            name, _t, commit = await ai.pick_agenda_injection(agent=None, user_id="u1")
            assert name == "plan_reminder"
            await commit()
