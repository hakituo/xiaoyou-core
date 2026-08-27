"""按角色隔离链路强制重生成指定日期的日记并报告相似度。

运行示例：
    venv_core\Scripts\python.exe tests\scripts\journal\regenerate_persona_diaries.py \
        2026-08-20 2026-08-21
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.services.journal.summary_guard import (  # noqa: E402
    daily_summary_similarity,
    is_valid_daily_summary_obj,
)


async def _run(dates: list[str]) -> int:
    from core.llm import get_llm_module
    from core.services.journal.service import get_journal_service
    from core.services.scheduler.task.task_scheduler import shutdown_scheduler
    from core.services.study.summary_generator import StudySummaryGenerator

    service = get_journal_service()
    results = []

    # 此脚本只验证角色日记，不额外调用共享的学习专项总结 LLM。
    try:
        with mock.patch.object(
            StudySummaryGenerator,
            "generate",
            new=mock.AsyncMock(return_value=None),
        ):
            for date_str in dates:
                aveline = await service.generate_daily_summary(
                    date_str,
                    force=True,
                    persona="aveline",
                )
                if not is_valid_daily_summary_obj(aveline):
                    print(f"[FAIL] {date_str} Aveline: {aveline.stats}")
                    return 1

                ling = await service.generate_daily_summary(
                    date_str,
                    force=True,
                    persona="ling",
                    distinct_from=aveline.summary,
                )
                if not is_valid_daily_summary_obj(ling):
                    print(f"[FAIL] {date_str} Ling: {ling.stats}")
                    return 1

                similarity = daily_summary_similarity(aveline.summary, ling.summary)
                row = {
                    "date": date_str,
                    "similarity": round(similarity, 4),
                    "aveline_chat_turns": aveline.stats.get("chat_turn_count", 0),
                    "ling_chat_turns": ling.stats.get("chat_turn_count", 0),
                    "ling_collision_retried": bool(
                        ling.stats.get("identity_collision_retried")
                    ),
                    "aveline": aveline.summary,
                    "ling": ling.summary,
                }
                results.append(row)
                print(json.dumps(row, ensure_ascii=False, indent=2))
    finally:
        await get_llm_module().shutdown()
        await shutdown_scheduler()

    print(f"[OK] 已重生成 {len(results)} 天、{len(results) * 2} 篇角色日记")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dates", nargs="+", help="YYYY-MM-DD，可传多个日期")
    args = parser.parse_args()
    return asyncio.run(_run(args.dates))


if __name__ == "__main__":
    raise SystemExit(main())
