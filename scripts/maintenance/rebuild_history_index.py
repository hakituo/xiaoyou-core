"""重建 / 体检 chat_history 的 SQLite 派生索引

背景（2026-09-17）
----------------
History 的搜索与最近记录读取原先一律 `rglob` 全量 JSONL 并逐行 `json.loads`，
成本随累计历史线性增长。`core/services/chat_history_index.py` 引入 per-scope
SQLite 派生索引后，常规查询走索引、文件扫描退化为 fallback。

索引是**纯派生数据**：删掉不影响 JSONL 真源，下次查询会自动 `ensure_sync` 补齐。
本脚本用于两类场景：

1. 索引与真源不一致（进程被强杀、手工改了 JSONL、索引结构升级）时一次性重建；
2. 上线后体检各 scope 的索引规模与陈旧状态。

用法
----
    python scripts/maintenance/rebuild_history_index.py --health
    python scripts/maintenance/rebuild_history_index.py --scope aveline
    python scripts/maintenance/rebuild_history_index.py --all
    python scripts/maintenance/rebuild_history_index.py --scope user --sync

安全
----
`--health` / `--sync` 只读（`--sync` 仅补增量，不动已有行）；`--scope` / `--all`
会先清空该库的事件与文件表再全量导入，但**不碰任何 JSONL**。重复执行结果一致
（event_id 主键 + INSERT OR IGNORE）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="重建 chat_history SQLite 派生索引")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--scope", help="只处理指定角色 scope（如 aveline / ling / user）")
    group.add_argument("--all", action="store_true", help="处理所有已注册角色的 chat_history")
    group.add_argument("--health", action="store_true", help="只体检，不写入")
    parser.add_argument(
        "--sync",
        action="store_true",
        help="与 --scope 组合：只做增量 ensure_sync，不整体重建",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    from core.services.chat_history_index import (
        get_history_index,
        rebuild_history_index,
    )
    from core.utils.data_paths import get_all_chat_history_dirs, get_role_chat_history_dir

    if args.scope:
        roots = [get_role_chat_history_dir(args.scope)]
    else:
        roots = get_all_chat_history_dirs()

    if args.health:
        report = {}
        for root in roots:
            index = get_history_index(root)
            info = index.health()
            info["root"] = str(root)
            report[str(root)] = info
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.sync:
        report = {}
        for root in roots:
            try:
                report[str(root)] = get_history_index(root).ensure_sync(force=True)
            except Exception as exc:
                report[str(root)] = {"error": str(exc)}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if not args.scope and not args.all:
        print("请指定 --scope <scope> / --all / --health / --sync，见脚本 docstring。")
        return 2

    scope = args.scope if args.scope else None
    report = rebuild_history_index(scope)
    print(json.dumps(report, ensure_ascii=False, indent=2))

    failed = [key for key, value in report.items() if "error" in value]
    if failed:
        print(f"存在失败的 root: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
