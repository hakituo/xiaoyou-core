"""启动时检查并补生成缺失的月度总结。

设计原则：
- 只检查"上一个月"，避免无限回溯
- 只补跑当前 active scope，避免启动时切换 persona 造成副作用
  （其他 scope 可由用户手动调用 verify_monthly_summary.py 补跑）
- 数据量 < MIN_DAILY_SUMMARIES_FOR_BACKFILL 时跳过，避免低质量总结
- 异步执行，不阻塞应用启动
- 失败不抛异常，只记日志

调用入口：lifespan 启动时通过 asyncio.create_task 触发
"""
from __future__ import annotations

from datetime import timedelta

from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

logger = get_logger("MonthlySummaryBackfill")

# 触发补跑的最小每日总结数量（避免数据太少时生成低质量总结）
MIN_DAILY_SUMMARIES_FOR_BACKFILL = 3


async def backfill_last_month_if_missing() -> None:
    """启动时检查上月月度总结，缺失且有足够数据时补生成。

    只检查当前 active scope，其他 scope 留给用户手动补跑。
    """
    try:
        from core.services.journal.service import get_journal_service

        svc = get_journal_service()

        # 上一个月的最后一天
        now = get_current_time()
        first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day_of_last_month = first_of_this_month - timedelta(days=1)
        month_str = last_day_of_last_month.strftime("%Y-%m")
        date_str = last_day_of_last_month.strftime("%Y-%m-%d")

        # 检查是否已存在（按当前 active scope）
        existing = await svc.get_monthly_summary(date_str)
        if existing:
            logger.info(
                "%s 月度总结已存在（scope=active），启动时跳过补跑",
                month_str,
            )
            return

        # 收集上月每日总结数量，评估是否有足够数据
        summary_svc = getattr(svc, "_summary_service", None)
        if summary_svc is None:
            logger.warning("无法获取 JournalSummaryService，跳过月度总结补跑")
            return
        daily_summaries = await summary_svc._collect_daily_summaries(last_day_of_last_month)
        if len(daily_summaries) < MIN_DAILY_SUMMARIES_FOR_BACKFILL:
            logger.info(
                "%s 每日总结数量不足 (%d/%d)，跳过补跑",
                month_str,
                len(daily_summaries),
                MIN_DAILY_SUMMARIES_FOR_BACKFILL,
            )
            return

        logger.info(
            "%s 月度总结缺失，启动时补生成（%d 天每日总结数据）",
            month_str,
            len(daily_summaries),
        )
        await svc.generate_monthly_summary(date_str)
        logger.info("%s 月度总结补跑完成", month_str)
    except Exception as exc:
        # 启动时补跑失败不影响应用启动
        logger.error(f"月度总结补跑流程异常: {exc}", exc_info=True)
