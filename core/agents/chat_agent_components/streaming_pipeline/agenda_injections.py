"""议程类注入的优先级竞争（从 dynamic_context.build_stream_messages 拆出）。

【为什么拆】
原来这里是 5 段 `if` 顺序 append：谁都不让谁，于是同一轮回复里可能同时出现
「催吃饭」「催背单词」「盯计划进度」。实测 2026-10-01 那轮，用户只说
「我买了个华为的显示器1669」，Aveline 的回复里同时塞了催饭和「176 个词今天压着呢」。
拆出来后：语气类（【情感影响指令】）保持常驻，议程类每轮**最多注入 1 条**。

【不丢东西】
P1（计划提醒）与 P2（每日学习任务）原本都是「取走即消费」——
P1 走 `get_and_clear()`，P2 先落盘再返回（落盘后当天再也取不到）。
改成 peek + 选中后 commit：没被选中的下一轮还能取到，只是不再和别的事挤在一句里。

【排序依据】
按「错过了会不会出事」排：P1 带时间点且 300s 过期，P2 一天只出一次，
P3 是昨日日记生成的「明天我要做 X」清单（催早饭的真凶之一），
P4 是今日计划清单，P5 是三餐软提示（只兜底，不与计划抢位）。

【每天最多一次（2026-10-01 补）】
只靠「按优先级取第一条」还不够：P1/P2 天然是取走即消费，但 P3/P4/P5 是只读的
状态型条目 —— 只要它有内容就会**每一轮都胜出**。实测当天 P1/P2/P3 全空，
P4 连续 7 轮胜出，角色每轮都在提「十八点半那个数学还挂着」。
所以状态型条目加了 once_per_day：当天第一次提过就沉寂，之后轮到别的条目或什么都不注入。
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, List, Optional, Tuple

from core.utils.logger import get_logger

logger = get_logger("ChatAgent")

Commit = Optional[Callable[[], Awaitable[None]]]
Probe = Callable[[dict], Awaitable[Tuple[str, Commit]]]


async def _probe_plan_reminder(ctx: dict) -> Tuple[str, Commit]:
    """P1：Active Care 计划提醒。peek 不消费，选中后才 clear。"""
    try:
        from core.services.active_care.shared.reminder_injection import (
            get_reminder_injection_store,
        )

        store = get_reminder_injection_store()
        pending = await store.peek()
        if not pending:
            return "", None
        parts = ["【计划提醒】"]
        merged_count = int(pending.get("merged_count") or 0)
        if merged_count > 1:
            parts.append(f"共有 {merged_count} 条提醒待自然带入本轮回复")
        if pending.get("task_title"):
            parts.append(f"任务：{pending['task_title']}")
        parts.append(f"提醒：{pending['reminder_text']}")
        if pending.get("recent_chat_summary"):
            parts.append(f"最近对话背景：{pending['recent_chat_summary']}")
        parts.append(
            "请在回复中自然地提醒用户这个计划，不要直接说'系统提醒你'，而是融入对话中。"
        )
        return "\n".join(parts), store.clear
    except Exception as e:
        logger.warning(f"Failed to peek Active Care reminder: {e}")
        return "", None


async def _probe_daily_study_task(ctx: dict) -> Tuple[str, Commit]:
    """P2：每日学习任务更新。peek 不落盘，选中后才 commit。"""
    prep = ctx.get("prep")
    if prep is not None and not (prep.is_cloud and not prep.is_sensitive_mode):
        return "", None
    agent = ctx.get("agent")
    user_id = str(ctx.get("user_id") or "")
    if agent is None:
        return "", None
    try:
        text = await agent._peek_daily_routine(user_id)
    except Exception as e:
        logger.warning(f"Failed to peek daily routine: {e}")
        return "", None
    if not text:
        return "", None
    ctx.get("events", []).append({
        "type": "thought_chain",
        "data": {
            "stage": "context_enrichment",
            "status": "success",
            "description": "Checking daily schedule...",
        },
        "done": False,
    })
    return f"【每日总结】\n{text}", lambda: agent._commit_daily_routine(user_id)


async def _probe_tomorrow_tone(ctx: dict) -> Tuple[str, Commit]:
    """P3：今日总基调（昨日日记生成）。只读，无消费。"""
    try:
        from core.services.journal.service import get_journal_service

        tone = await get_journal_service().get_tomorrow_tone()
        if not tone:
            return "", None
        return (
            f"【今日总基调（来自昨日日记总结）】\n{tone}\n"
            "这部分只用于语气、话题方向和互动节奏，不是日期或节日的事实来源。"
            "其中若出现‘今天/明天’或具体节日，不得直接复述，必须以权威日历事实锚点为准。"
        ), None
    except Exception as e:
        logger.warning(f"Failed to inject tomorrow_tone: {e}")
        return "", None


async def _probe_today_plan(ctx: dict) -> Tuple[str, Commit]:
    """P4：今日计划清单。只读，无消费（靠 pick_agenda_injection 的「每天一次」节流）。

    **文案在 2026-10-01 被改写过**：原版写着「你需要主动追踪主人的执行进度」与
    「如果主人长时间偏离计划（如该学习时在玩），可以自然地提醒一下进度」——
    这两句被模型直接执行成了「十八点半那个数学还挂着，现在八点二十了」这种催促。
    现在改成「背景资料 + 明确禁止催」，只保留勾选工具的使用说明。
    """
    try:
        from core.services.journal.service import get_journal_service

        svc = get_journal_service()
        today_plan = await svc.get_plan()
        if not (today_plan and today_plan.items):
            return "", None
        plan_text = svc.format_plan_for_injection(today_plan)
        if not plan_text:
            return "", None
        return (
            f"【今日计划（背景资料）】\n{plan_text}\n"
            "- 这只是他今天的安排，让你知道他在忙什么，**不是需要你监督的任务清单**。\n"
            "- 他主动说做完了某项时，可以调用 mark_plan_item_status 把对应项勾掉"
            "（传 item_id 和 status，date 留空默认今日）。\n"
            "- **不要主动追问进度，不要指出哪一项超时或还没做，不要催他去按计划做事。**\n"
            "  他聊什么就聊什么；他自己提起计划再谈。"
        ), None
    except Exception as e:
        logger.warning(f"Failed to inject today_plan: {e}")
        return "", None


async def _probe_meal_care(ctx: dict) -> Tuple[str, Commit]:
    """P5：三餐无记录时的软提示（只兜底，不与计划抢位）。

    原先这句是 user_bio 常驻块里的「- 用户三餐: 无记录（需要关注）」——
    「需要关注」被模型读成指令，实测 2026-09-28 早上 30 分钟内催了 6 次早饭。
    现在常驻块只留事实，提示降级成优先级最低的候选。
    """
    try:
        from core.services.daily.manager import get_daily_manager

        record = await asyncio.to_thread(get_daily_manager().get_record)
        if (record or {}).get("meals"):
            return "", None
    except Exception as e:
        logger.warning(f"Failed to peek meal care: {e}")
        return "", None
    return (
        "【饮食提醒】\n"
        "他今天还没有任何用餐记录。可以顺口问一句吃了没，问过就翻篇，不要连着追问。"
    ), None


# 顺序即优先级，从高到低。第三项 once_per_day 决定这条议程是否「每天最多注入一次」。
#
# 为什么需要 once_per_day：P1/P2 天然是「取走即消费」（清队列 / 落盘），但
# P3/P4/P5 是只读的「状态型」条目 —— 只要它有内容，就会**每一轮都胜出**。
# 2026-10-01 实测：当天 P1/P2/P3 全空，P4 连续 7 轮全部胜出，角色于是每轮都在
# 提「十八点半那个数学还挂着」。状态型条目改成每天一次后，当天第一次提过就沉寂，
# 后面轮到别的条目或什么都不注入。
#
# 事件型（False）：来了就该放出去，靠各自的消费语义防重复（P1 clear、P2 落盘）。
_LADDER: Tuple[Tuple[str, Probe, bool], ...] = (
    ("plan_reminder", _probe_plan_reminder, False),
    ("daily_study_task", _probe_daily_study_task, False),
    ("tomorrow_tone", _probe_tomorrow_tone, True),
    ("today_plan", _probe_today_plan, True),
    ("meal_care", _probe_meal_care, True),
)

AGENDA_PRIORITY: Tuple[str, ...] = tuple(name for name, _, _ in _LADDER)


def _marker_path(user_id: str, date_str: str):
    """「某条议程今天已注入过」的标记文件路径（按会话隔离，落在当日目录下）。"""
    from core.utils.data_paths import get_user_data_dir

    return (
        get_user_data_dir() / "daily"
        / date_str[0:4] / date_str[5:7] / date_str[8:10]
        / "agenda_injected.json"
    )


def _already_injected(user_id: str, name: str, date_str: str) -> bool:
    """同步读标记（调用方负责 to_thread）。读不到一律当「没注入过」。"""
    import json

    try:
        path = _marker_path(user_id, date_str)
        if not path.exists():
            return False
        payload = json.loads(path.read_text(encoding="utf-8")) or {}
        return name in {str(n) for n in (payload.get(str(user_id)) or [])}
    except Exception:
        return False


def _mark_injected(user_id: str, name: str, date_str: str) -> None:
    """同步写标记（调用方负责 to_thread）。失败只记日志，不影响本轮注入。"""
    import json

    try:
        path = _marker_path(user_id, date_str)
        payload = {}
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8")) or {}
        names = [str(n) for n in (payload.get(str(user_id)) or [])]
        if name not in names:
            names.append(name)
        payload[str(user_id)] = names
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.debug("标记议程已注入失败（不影响本轮）：%s", e)


async def pick_agenda_injection(
    *,
    agent: Any,
    user_id: str,
    prep: Any = None,
    events: Optional[List[dict]] = None,
) -> Tuple[str, str, Commit]:
    """按优先级逐个探测，返回第一条命中的 (名称, 文本, 提交回调)。

    命中的那条由调用方决定何时提交（消费）；**没命中的一律不消费**，留到下一轮。
    标记为 once_per_day 的条目，当天已经放过就跳过（不再参与竞争）。
    返回 ``("", "", None)`` 表示本轮没有任何议程要注入。
    """
    from core.utils.time_utils import now_str

    today = now_str("%Y-%m-%d")
    ctx = {
        "agent": agent,
        "user_id": user_id,
        "prep": prep,
        "events": events if events is not None else [],
    }
    for name, probe, once_per_day in _LADDER:
        if once_per_day:
            try:
                if await asyncio.to_thread(_already_injected, str(user_id), name, today):
                    continue
            except Exception as e:  # noqa: BLE001
                logger.debug("读议程标记失败，按未注入处理：%s", e)
        try:
            text, commit = await probe(ctx)
        except Exception as e:
            logger.warning("Agenda probe %s failed: %s", name, e)
            continue
        if text:
            return name, text, _compose_commit(commit, str(user_id), name, today, once_per_day)
    return "", "", None


def _compose_commit(
    commit: Commit, user_id: str, name: str, today: str, once_per_day: bool
) -> Commit:
    """把「条目自己的提交」与「写 once_per_day 标记」合成一个提交回调。"""
    if not once_per_day:
        return commit

    async def _commit() -> None:
        if commit is not None:
            await commit()
        await asyncio.to_thread(_mark_injected, user_id, name, today)

    return _commit

