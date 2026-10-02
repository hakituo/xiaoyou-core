"""每日总结的唯一调度入口。

收敛背景（2026-09-27）：
生成每日总结原本有两条互相独立的链路——nightly 全局任务
（``memory/nightly/global_tasks.py``）与生活模拟每分钟 tick 里的兜底
（``core/services/life_simulation/orchestrator.py``）。后者自己抄了一份
角色名单 ``("aveline", "ling")`` 和一套日期归属推理，注册角色摘掉 ling
之后，兜底反而成了她日记的唯一入口，每天凌晨补写一篇。

收敛之后：
- **给谁写**：一律 ``get_diary_persona_ids()``（注册角色真源），不再有任何角色字面量
- **是否补 / 何时补 / 用不用 force**：全部由本模块决定
- **调用方**：只负责「什么时候想起来检查一次」+ 提供本域事实（用户是否睡着）

依赖方向保持单向：``life_simulation`` → ``journal``，本模块不反向依赖调用方。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from core.utils.time_utils import get_diary_target_date_str

from core.utils.logger import get_logger

logger = get_logger(__name__)

# 补写窗口：只有凌晨才补。中午之后 get_diary_target_date() 指向今天，
# 今天还没过完，此时补写必然写出「我没找你」的空日记。
_BACKFILL_WINDOW_END_HOUR = 12

# 进程内补写状态：一个日期补成功后不再重复；失败不标记，留给下一次检查重试。
_last_backfilled_date: str | None = None
_backfill_task: asyncio.Task | None = None


def reset_backfill_state() -> None:
    """清空进程内补写状态（测试隔离用）。"""
    global _last_backfilled_date, _backfill_task
    _last_backfilled_date = None
    _backfill_task = None


def _is_valid_summary(summary: Any) -> bool:
    from core.services.journal.summary_guard import is_valid_daily_summary_obj

    return summary is not None and is_valid_daily_summary_obj(summary)


def _resolve_backfill_date(now_dt: datetime, *, is_sleeping: bool) -> str | None:
    """判断此刻是否该补写；返回要补的日期，不该补时返回 None。"""
    if not is_sleeping:
        return None
    if now_dt.hour >= _BACKFILL_WINDOW_END_HOUR:
        return None
    date_key = get_diary_target_date_str(now_dt)
    if not date_key:
        return None
    if _last_backfilled_date == date_key:
        return None
    return date_key


async def generate_registered_summaries(
    date_key: str,
    *,
    force: bool,
    reason: str,
) -> dict[str, Any]:
    """给全部注册角色生成每日总结，返回 ``{role_id: DailySummary | None}``。

    :param force: True 覆盖重生成（nightly 正线），False 只补缺口（睡眠兜底）
    :param reason: 仅用于日志区分调用来源，不参与任何判断
    """
    from core.services.journal.diary_personas import get_diary_persona_ids
    from core.services.journal.service import get_journal_service

    role_ids = get_diary_persona_ids()
    if not role_ids:
        logger.warning("没有注册角色，跳过每日总结: %s (reason=%s)", date_key, reason)
        return {}

    journal_service = get_journal_service()
    written: dict[str, str] = {}
    results: dict[str, Any] = {}
    for role_id in role_ids:
        logger.info(
            "Generating daily summary for %s (force=%s) persona=%s reason=%s",
            date_key,
            force,
            role_id,
            reason,
        )
        try:
            summary = await journal_service.generate_daily_summary(
                date_key,
                force=force,
                persona=role_id,
                # 与前面所有角色的正文比对，撞稿就按身份边界重写
                distinct_from="\n".join(written.values()) or None,
            )
        except Exception as exc:  # noqa: BLE001 - 单个角色失败不能拖垮其余角色
            logger.warning("生成 %s 的每日总结失败: %s", role_id, exc)
            results[role_id] = None
            continue
        results[role_id] = summary
        if _is_valid_summary(summary):
            written[role_id] = str(getattr(summary, "summary", "") or "").strip()
    return results


async def backfill_after_sleep(
    now_dt: datetime,
    *,
    is_sleeping: bool,
) -> dict[str, Any]:
    """睡眠会话中补写「已结束那天」的日记缺口（需要等待结果时用）。

    nightly 是正线（force=True 全量重写）；这里只补它没覆盖到的缺口，
    所以用 force=False——已有的总结会被原样跳过，不会覆盖 nightly 的成果。
    """
    global _last_backfilled_date

    date_key = _resolve_backfill_date(now_dt, is_sleeping=is_sleeping)
    if not date_key:
        return {}

    results = await generate_registered_summaries(
        date_key, force=False, reason="sleep_backfill"
    )
    if results and all(_is_valid_summary(item) for item in results.values()):
        _last_backfilled_date = date_key
        logger.info("睡眠补写完成: %s 角色=%s", date_key, sorted(results))
    else:
        # 不标记完成，下一次检查会再试（与历史兜底行为一致）
        logger.warning(
            "睡眠补写未全部成功，稍后重试: %s 角色=%s", date_key, sorted(results)
        )
    return results


def schedule_backfill_after_sleep(
    now_dt: datetime,
    *,
    is_sleeping: bool,
) -> asyncio.Task | None:
    """给「不想阻塞主循环」的调用方（如生活模拟每秒 tick）的 fire-and-forget 入口。

    返回创建的任务；不需要补写或上一批还没跑完时返回 None。
    """
    global _backfill_task

    if _backfill_task is not None and not _backfill_task.done():
        return None
    if _resolve_backfill_date(now_dt, is_sleeping=is_sleeping) is None:
        return None

    _backfill_task = asyncio.create_task(
        backfill_after_sleep(now_dt, is_sleeping=is_sleeping)
    )
    return _backfill_task
