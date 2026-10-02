"""为指定日期生成学习生活计划

用法:
    python scripts/generate_plan_for_date.py              # 默认今天
    python scripts/generate_plan_for_date.py 2026-08-06   # 指定日期
"""
import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.utils.time_utils import get_current_time  # noqa: E402


async def main(date_str: str) -> int:
    from core.services.journal.service import get_journal_service

    service = get_journal_service()

    # 先检查是否已有计划
    existing = await service.get_plan(date_str)
    if existing:
        print(f"=== {date_str} 计划已存在（{len(existing.items)} 项），将强制重新生成 ===")
    else:
        print(f"=== 为 {date_str} 生成计划（不存在） ===")

    plan = await service.generate_plan_for_date(date_str, force=True)
    print(f"日期: {plan.date}")
    print(f"计划项数: {len(plan.items)}")
    if plan.notes:
        print(f"备注: {plan.notes}")
    for it in sorted(plan.items, key=lambda x: (x.time or "99:99", x.category)):
        time_str = it.time if it.time else "灵活"
        print(f"  [{time_str}] {it.title}（{it.category or '未分类'}）"
              f"{f' {it.estimated_duration_minutes}分钟' if it.estimated_duration_minutes else ''}")

    # 验证文件写入
    from datetime import datetime
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    filepath = service.storage.get_daily_dir(dt, scope="user") / "plan.json"
    if filepath.exists():
        print(f"\n计划文件已写入: {filepath}")
    else:
        print(f"\n[警告] 计划文件未写入: {filepath}（可能 LLM 返回空 items）")

    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        target = get_current_time().strftime("%Y-%m-%d")
    raise SystemExit(asyncio.run(main(target)))
