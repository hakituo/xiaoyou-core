"""重建背单词 FSRS 状态，修复 App 评分映射与分钟级重复。

默认只预览；传入 ``--apply`` 后才会先备份、再原子写回。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.tools.study.english.fsrs_scheduler import (  # noqa: E402
    FSRS_SCHEMA_VERSION,
    rebuild_fsrs_card_from_history,
)
from core.utils.atomic_io import safe_json_dump  # noqa: E402


DEFAULT_PROGRESS_PATH = PROJECT_ROOT / "output" / "user_data" / "vocab_progress.json"


def _apply_card(data: dict[str, Any], card: Any, now: float) -> None:
    """把重建后的 Card 写入进度字段。"""
    data["fsrs_state"] = int(card.state)
    data["fsrs_step"] = card.step
    data["fsrs_stability"] = card.stability
    data["fsrs_difficulty"] = card.difficulty
    data["fsrs_due"] = card.due.timestamp()
    data["fsrs_last_review"] = (
        card.last_review.timestamp() if card.last_review else None
    )
    data["fsrs_schema_version"] = FSRS_SCHEMA_VERSION
    data["next_review"] = data["fsrs_due"]
    data["interval"] = max(0.0, (data["fsrs_due"] - now) / 86400.0)


def rebuild_progress(
    progress: dict[str, Any], now: float
) -> tuple[dict[str, Any], dict[str, int]]:
    """在内存中重建所有带评分历史的单词。"""
    rebuilt = json.loads(json.dumps(progress, ensure_ascii=False))
    stats = {
        "total": len(rebuilt),
        "rebuilt": 0,
        "legacy_due_now": 0,
        "rebuilt_due_now": 0,
        "due_moved_later": 0,
        "due_moved_earlier": 0,
    }
    for data in rebuilt.values():
        if not isinstance(data, dict) or not data.get("history"):
            continue
        old_due = float(data.get("fsrs_due") or data.get("next_review") or 0)
        if old_due and old_due <= now:
            stats["legacy_due_now"] += 1
        card = rebuild_fsrs_card_from_history(data)
        _apply_card(data, card, now)
        new_due = float(data["fsrs_due"])
        if new_due <= now:
            stats["rebuilt_due_now"] += 1
        if old_due and new_due > old_due + 1:
            stats["due_moved_later"] += 1
        elif old_due and new_due < old_due - 1:
            stats["due_moved_earlier"] += 1
        stats["rebuilt"] += 1
    return rebuilt, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS_PATH)
    parser.add_argument("--apply", action="store_true", help="备份后写回重建结果")
    args = parser.parse_args()

    progress_path = args.progress.resolve()
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    if not isinstance(progress, dict):
        raise ValueError("进度文件顶层必须是 JSON 对象")

    now = time.time()
    rebuilt, stats = rebuild_progress(progress, now)
    mode = "执行" if args.apply else "预览"
    print(f"FSRS v{FSRS_SCHEMA_VERSION} 迁移{mode}: {progress_path}")
    for key, value in stats.items():
        print(f"{key}: {value}")

    if not args.apply:
        print("未写入；确认后使用 --apply。")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = progress_path.with_name(
        f"{progress_path.stem}.pre_fsrs_v{FSRS_SCHEMA_VERSION}_{stamp}.bak.json"
    )
    shutil.copy2(progress_path, backup_path)
    safe_json_dump(rebuilt, progress_path)
    print(f"已备份: {backup_path}")
    print("已原子写回重建后进度。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
