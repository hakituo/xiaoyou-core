"""一次性回填：把"当天实际背了单词、却被记为 skipped"的历史计划项改为 completed

背景（2026-09-03）
----------------
用户反馈"我都背完了，他为什么会 skip"。核查 `companion_data/user_data/daily/*/plan.json`
后发现，只要当天有复习记录，计划里的"复习到期英语词汇"项**无一例外**全是
`skipped`：

    日期          复习次数   词数   词汇计划项
    2026-08-28      130     104   2 条 → skipped/sleep
    2026-08-29        0       0   2 条 → pending（确实没背，不回填）
    2026-08-30      195     124   2 条 → skipped/sleep
    2026-08-31      248     166   3 条 → skipped/sleep
    2026-09-01      106      63   3 条 → skipped/sleep
    2026-09-02      134      75   3 条 → skipped/sleep

根因：安卓端背完单词后没有任何机制把计划项标记为 completed，夜里睡眠结算
便把未完成项统一打成 `skipped`（settlement_reason=sleep），而这类项又被允许
结转到次日，与新的计划叠加，造成同名项多条并存、数字天天漂移。

修复（`routers/v1/vocab.py::_mark_vocab_plan_completed_if_done`）已保证**从今天起**
完成状态会正确回写。本脚本负责**清理历史遗留**：把那些"背过了却记为跳过"的
计划项按事实改回 completed，让历史记录与实际情况一致。

判据
----
某日 `vocab_progress.json` 中存在复习记录（复习次数 > 0）→ 该日所有
"复习到期英语词汇"计划项视为已完成。同一天出现多条是 bug 产物（本该只有一条），
因此一并标记。当天没有任何复习记录的日期（如 08-29）保持原状不动。

安全
----
默认 dry-run 只打印计划；显式 `--apply` 才写盘，写盘前先备份为 `.bak`。
`--since` 可限定起始日期。
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VOCAB_PATH = ROOT / "output" / "user_data" / "vocab_progress.json"
PLAN_DIR = ROOT / "companion_data" / "user_data" / "daily"

VOCAB_TITLE = "复习到期英语词汇"
VOCAB_KEY = "vocab:due_review"


def load_reviews_per_day() -> Tuple[collections.Counter, Dict[str, set]]:
    """从 vocab_progress.json 统计每天复习了多少次、多少个不同的词。"""
    if not VOCAB_PATH.exists():
        raise FileNotFoundError(f"找不到词汇进度文件: {VOCAB_PATH}")
    data = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))

    counts: collections.Counter = collections.Counter()
    words: Dict[str, set] = collections.defaultdict(set)
    for word, val in (data or {}).items():
        for h in (val or {}).get("history") or []:
            ts = h.get("timestamp")
            if not ts:
                continue
            day = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            counts[day] += 1
            words[day].add(word)
    return counts, words


def is_vocab_item(item: Dict[str, Any]) -> bool:
    if str(item.get("source_key") or "") == VOCAB_KEY:
        return True
    return VOCAB_TITLE in str(item.get("title") or "")


def plan_files() -> List[Tuple[str, Path]]:
    out = []
    for f in sorted(PLAN_DIR.rglob("plan.json")):
        try:
            date = "-".join(f.parent.parts[-3:])
        except Exception:  # noqa: BLE001
            continue
        out.append((date, f))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="实际写盘（默认只预览）")
    parser.add_argument("--since", default="", help="只处理该日期及之后，如 2026-08-30")
    parser.add_argument("--no-backup", action="store_true", help="写盘时不生成 .bak 备份")
    args = parser.parse_args()

    counts, words = load_reviews_per_day()
    files = plan_files()
    if args.since:
        files = [(d, f) for d, f in files if d >= args.since]

    print("=" * 78)
    print("历史词汇计划项回填（背过了却记为 skipped → completed）")
    print(f"模式: {'写盘' if args.apply else '预览（加 --apply 才会真的改）'}")
    print("=" * 78)

    changed_files = 0
    changed_items = 0
    skipped_no_review = 0
    already_done = 0

    for date, path in files:
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  [跳过] {date} 读取失败: {e}")
            continue

        items = plan.get("items") or []
        vocab_items = [it for it in items if is_vocab_item(it)]
        if not vocab_items:
            continue

        reviewed = counts.get(date, 0)
        n_words = len(words.get(date, ()))

        if reviewed <= 0:
            skipped_no_review += len(vocab_items)
            print(
                f"\n{date}  复习 {reviewed} 次 → 保持原样"
                f"（{len(vocab_items)} 项，状态 {[i.get('status') for i in vocab_items]}）"
            )
            continue

        targets = [
            it for it in vocab_items if str(it.get("status") or "") != "completed"
        ]
        if not targets:
            already_done += len(vocab_items)
            print(f"\n{date}  复习 {reviewed} 次 / {n_words} 词 → 已是 completed，无需改动")
            continue

        print(f"\n{date}  复习 {reviewed} 次 / {n_words} 词 → 回填 {len(targets)} 项")
        for it in targets:
            old = it.get("status")
            reason = it.get("settlement_reason")
            print(
                f"    {it.get('time') or '--'}  {str(it.get('title'))[:26]}"
                f"  {old}"
                + (f"/{reason}" if reason else "")
                + "  →  completed"
            )
            it["status"] = "completed"
            # 不再是"睡眠结算跳过"，清掉结算原因，避免被结转逻辑误判
            if "settlement_reason" in it:
                it["settlement_reason"] = None
            changed_items += 1

        if args.apply:
            if not args.no_backup:
                backup = path.with_suffix(path.suffix + ".bak")
                if not backup.exists():
                    shutil.copy2(path, backup)
            path.write_text(
                json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            changed_files += 1

    print("\n" + "=" * 78)
    print(f"计划改动: {changed_items} 个计划项 / {changed_files} 个文件")
    print(f"无复习记录保持原样: {skipped_no_review} 项")
    print(f"原本就已完成: {already_done} 项")
    if not args.apply:
        print("\n这是预览。确认无误后加 --apply 执行写盘。")
    else:
        print("\n写盘完成。备份文件后缀为 .bak（同名已存在时不覆盖）。")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
