"""把计划里「复习到期英语词汇（N 个）」的 N 刷新为当天实时待复习数

背景（2026-09-10）
----------------
用户反馈：Aveline 说「复习到期英语词汇（61 个）」，但背单词 app 显示 84 个待复习。

根因是计划项标题里的数字在生成那一刻就被冻结，而当天队列由 FSRS + daily
日志实时重算。结转逻辑（``carryover`` 的 base_score=14）又高于实时到期候选
（base_score=12），于是旧快照每天都在去重中胜出，数字永远停在生成那天。

``core/services/journal/plan_candidate_builder.py`` 已修复（词汇项不再结转、
结转键剥离累积前缀），从下一次生成计划起数字会自动与 app 一致。本脚本用于
把**已经生成好的历史计划**就地刷新，避免用户当天仍看到过时数字。

用法
----
    python scripts/maintenance/refresh_vocab_plan_due_count.py            # 预览今天
    python scripts/maintenance/refresh_vocab_plan_due_count.py --apply     # 写盘今天
    python scripts/maintenance/refresh_vocab_plan_due_count.py --date 2026-09-10 --apply

安全
----
默认 dry-run 只打印；显式 ``--apply`` 才写盘，写盘前备份为 ``.bak``。
当天实时待复习数为 0 时一律跳过，不删项、不改标题。
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PLAN_DIR = ROOT / "companion_data" / "user_data" / "daily"
VOCAB_TITLE = "复习到期英语词汇"
_COUNT_PATTERN = re.compile(r"（\d+ 个）")


def _plan_path(target_date: str) -> Path:
    year, month, day = target_date.split("-")
    return PLAN_DIR / year / month / day / "plan.json"


def _live_due_count() -> int:
    """读取背单词 app 口径的今日待复习数（due_today_count）。"""
    from core.tools.study.english.vocabulary_manager import get_vocabulary_manager

    overview = get_vocabulary_manager().get_review_overview() or {}
    return int(overview.get("due_today_count") or 0)


def _is_vocab_review_item(item: dict) -> bool:
    return VOCAB_TITLE in str(item.get("title") or "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        default=datetime.date.today().strftime("%Y-%m-%d"),
        help="目标日期 YYYY-MM-DD，默认今天",
    )
    parser.add_argument("--apply", action="store_true", help="实际写盘（默认只预览）")
    parser.add_argument("--no-backup", action="store_true", help="写盘时不生成 .bak 备份")
    args = parser.parse_args()

    path = _plan_path(args.date)
    print("=" * 78)
    print("刷新计划里的词汇项数字（计划标题 ← app 实时口径 due_today_count）")
    print(f"模式: {'写盘' if args.apply else '预览（加 --apply 才会真的改）'}")
    print(f"日期: {args.date}")
    print("=" * 78)

    if not path.exists():
        print(f"  [跳过] 找不到计划文件: {path}")
        return 1

    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"  [跳过] 读取失败: {exc}")
        return 1

    due = _live_due_count()
    print(f"  app 实时待复习: {due} 个")
    if due <= 0:
        print("  [跳过] 实时待复习为 0，保持计划原样（不删项、不改标题）")
        return 0

    items = plan.get("items") or []
    changed = 0
    for item in items:
        if not _is_vocab_review_item(item):
            continue
        old_title = str(item.get("title") or "")
        new_title = _COUNT_PATTERN.sub(f"（{due} 个）", old_title)
        if new_title == old_title:
            print(f"  [不变] {old_title}")
            continue
        print(f"  [更新] {old_title}  →  {new_title}")
        item["title"] = new_title
        changed += 1

    if changed == 0:
        print("\n无需改动。")
        return 0

    if not args.apply:
        print(f"\n预览结束，共 {changed} 项待更新；加 --apply 写盘。")
        return 0

    if not args.no_backup:
        backup = path.with_suffix(".json.bak")
        shutil.copy2(path, backup)
        print(f"\n已备份: {backup}")

    plan["updated_at"] = datetime.datetime.now().timestamp()
    path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写入: {path}（{changed} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
