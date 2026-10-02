"""按角色隔离链路强制重生成指定日期的日记并报告相似度。

角色列表来自注册角色（character_runtime.yaml），不再硬编码 aveline / ling。
空白处会自动补跑：只补缺失日期（--only-missing）。

运行示例：
    venv_core\Scripts\python.exe tests\scripts\journal\regenerate_persona_diaries.py 2026-08-20 2026-08-21
    venv_core\Scripts\python.exe tests\scripts\journal\regenerate_persona_diaries.py --only-missing --since 2026-09-01
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
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


def _missing_dates(role_ids: tuple[str, ...], since: str) -> list[str]:
    """返回自 since 起、任一注册角色缺日记的日期。"""
    from core.utils.data.data_paths import get_role_data_dir

    start = datetime.date.fromisoformat(since)
    today = datetime.date.today()
    missing: list[str] = []
    day = start
    while day <= today:
        for role_id in role_ids:
            summary_file = (
                get_role_data_dir(role_id)
                / "daily"
                / f"{day.year:04d}"
                / f"{day.month:02d}"
                / f"{day.day:02d}"
                / "diary_summary.json"
            )
            if not summary_file.exists():
                missing.append(day.isoformat())
                break
        day += datetime.timedelta(days=1)
    return missing


async def _run(dates: list[str]) -> int:
    from core.llm import get_llm_module
    from core.services.journal.diary_personas import get_diary_persona_ids
    from core.services.journal.service import get_journal_service
    from core.services.scheduler.task.task_scheduler import shutdown_scheduler
    from core.services.study.summary_generator import StudySummaryGenerator

    service = get_journal_service()
    role_ids = get_diary_persona_ids()
    if not role_ids:
        print("[FAIL] 没有注册角色，无法生成日记")
        return 1
    print(f"[INFO] 注册角色: {', '.join(role_ids)}")
    results = []

    # 此脚本只验证角色日记，不额外调用共享的学习专项总结 LLM。
    try:
        with mock.patch.object(
            StudySummaryGenerator,
            "generate",
            new=mock.AsyncMock(return_value=None),
        ):
            for date_str in dates:
                written: dict[str, str] = {}
                row: dict[str, object] = {"date": date_str}
                for role_id in role_ids:
                    summary = await service.generate_daily_summary(
                        date_str,
                        force=True,
                        persona=role_id,
                        distinct_from="\n".join(written.values()) or None,
                    )
                    if not is_valid_daily_summary_obj(summary):
                        print(f"[FAIL] {date_str} {role_id}: {summary.stats}")
                        return 1
                    written[role_id] = summary.summary
                    row[f"{role_id}_chat_turns"] = summary.stats.get("chat_turn_count", 0)
                    row[f"{role_id}_collision_retried"] = bool(
                        summary.stats.get("identity_collision_retried")
                    )
                    row[role_id] = summary.summary
                texts = list(written.values())
                if len(texts) > 1:
                    row["similarity"] = round(daily_summary_similarity(texts[0], texts[1]), 4)
                results.append(row)
                print(json.dumps(row, ensure_ascii=False, indent=2))
    finally:
        await get_llm_module().shutdown()
        await shutdown_scheduler()

    print(f"[OK] 已重生成 {len(results)} 天、{len(results) * len(role_ids)} 篇角色日记")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dates", nargs="*", help="YYYY-MM-DD，可传多个日期")
    parser.add_argument("--only-missing", action="store_true", help="只补缺失日期")
    parser.add_argument("--since", default="2026-09-01", help="--only-missing 的起始日期")
    args = parser.parse_args()

    from core.services.journal.diary_personas import get_diary_persona_ids

    role_ids = get_diary_persona_ids()
    dates = list(args.dates)
    if args.only_missing:
        dates = sorted(set(dates) | set(_missing_dates(role_ids, args.since)))
    if not dates:
        print("[OK] 没有需要补生成的日期")
        return 0
    return asyncio.run(_run(dates))


if __name__ == "__main__":
    raise SystemExit(main())
