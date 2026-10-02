"""按事件时间修正背单词历史评分语义，并重建 FSRS Card 状态。

背景
----
App 早就按 1=Again、2=Hard、3=Good、4=Easy 提交，但后端在
``LEGACY_RATING_CUTOFF`` 之前仍按旧 0-5 量表解释
（1/2→Again、3→Hard、4→Good、5→Easy）。2026-09-01 的 FSRS v2 重建把
**全部**历史统一按新语义回放，于是旧 ``quality=4``（实为 Good）被当成 Easy，
旧卡片被系统性高估（例如 numerous：stability 123 天、difficulty 1.0）。

本脚本不改写任何原始 history（保留 timestamp 与 quality 原值），只按事件
发生时间选择正确的评分 schema 重新 replay，得到新的 FSRS 状态。

用法
----
    # 默认 dry-run，只打印统计，不写任何文件
    python scripts/maintenance/migrate_vocab_fsrs_history.py

    # 确认后落盘（自动备份，幂等）
    python scripts/maintenance/migrate_vocab_fsrs_history.py --apply

    # 从最近一次备份回滚
    python scripts/maintenance/migrate_vocab_fsrs_history.py --rollback

备份文件名：``vocab_progress.pre_rating_migration_YYYYMMDD_HHMMSS.bak.json``
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.tools.study.english.fsrs_scheduler import (  # noqa: E402
    FSRS_SCHEMA_VERSION,
    LEGACY_RATING_CUTOFF,
    LEGACY_RATING_CUTOFF_ISO,
    RATING_MIGRATION_VERSION,
    rebuild_fsrs_card_from_history,
)
from core.utils.atomic_io import safe_json_dump  # noqa: E402

DEFAULT_PROGRESS_PATH = PROJECT_ROOT / "output" / "user_data" / "vocab_progress.json"
BACKUP_GLOB = "vocab_progress.pre_rating_migration_*.bak.json"
RATING_MIGRATION_FIELD = "rating_migration_version"


# ---------------------------------------------------------------------------
# 迁移逻辑
# ---------------------------------------------------------------------------


def _valid_events(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按时间排序、可参与 replay 的历史事件。"""
    events: List[Dict[str, Any]] = []
    for event in data.get("history", []) or []:
        if not isinstance(event, dict):
            continue
        try:
            timestamp = float(event.get("timestamp") or 0)
            int(event.get("quality"))
        except (TypeError, ValueError):
            continue
        if timestamp <= 0:
            continue
        events.append(event)
    events.sort(key=lambda e: float(e["timestamp"]))
    return events


def _apply_card(data: Dict[str, Any], card: Any, now: float) -> None:
    """把重建后的 Card 写入进度字段（保留 word/history/easiness 等原字段）。"""
    data["fsrs_state"] = int(card.state)
    data["fsrs_step"] = card.step
    data["fsrs_stability"] = card.stability
    data["fsrs_difficulty"] = card.difficulty
    data["fsrs_due"] = card.due.timestamp()
    data["fsrs_last_review"] = (
        card.last_review.timestamp() if card.last_review else None
    )
    data["fsrs_schema_version"] = FSRS_SCHEMA_VERSION
    data[RATING_MIGRATION_FIELD] = RATING_MIGRATION_VERSION
    data["next_review"] = data["fsrs_due"]
    data["interval"] = max(0.0, (data["fsrs_due"] - now) / 86400.0)
    # reps 只作兼容展示：与 apply_progress 的口径一致（历史评分条数）
    data["reps"] = len(
        [
            e
            for e in (data.get("history") or [])
            if isinstance(e, dict) and e.get("quality") is not None
        ]
    )


def _is_migrated(data: Dict[str, Any]) -> bool:
    return (
        data.get(RATING_MIGRATION_FIELD) == RATING_MIGRATION_VERSION
        and data.get("fsrs_schema_version") == FSRS_SCHEMA_VERSION
    )


def rebuild_progress(
    progress: Dict[str, Any], now: float, force: bool = False
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """在内存中重建所有带评分历史的单词，返回 (新进度, 统计)。"""
    rebuilt = json.loads(json.dumps(progress, ensure_ascii=False))

    stats: Dict[str, Any] = {
        "total_words": len(rebuilt),
        "total_events": 0,
        "legacy_events": 0,
        "current_events": 0,
        "quality_counts": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
        "legacy_quality_counts": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
        "rebuilt_cards": 0,
        "skipped_already_migrated": 0,
        "due_earlier": 0,
        "due_later": 0,
        "due_unchanged": 0,
    }
    old_stability: List[float] = []
    new_stability: List[float] = []
    old_difficulty: List[float] = []
    new_difficulty: List[float] = []

    for data in rebuilt.values():
        if not isinstance(data, dict):
            continue
        events = _valid_events(data)
        stats["total_events"] += len(events)
        for event in events:
            quality = int(event["quality"])
            if 1 <= quality <= 5:
                stats["quality_counts"][quality] += 1
            if float(event["timestamp"]) < LEGACY_RATING_CUTOFF:
                stats["legacy_events"] += 1
                if 1 <= quality <= 5:
                    stats["legacy_quality_counts"][quality] += 1
            else:
                stats["current_events"] += 1

        if not events:
            continue
        if _is_migrated(data) and not force:
            stats["skipped_already_migrated"] += 1
            continue

        old_due = float(data.get("fsrs_due") or data.get("next_review") or 0)
        if data.get("fsrs_stability") is not None:
            old_stability.append(float(data["fsrs_stability"]))
        if data.get("fsrs_difficulty") is not None:
            old_difficulty.append(float(data["fsrs_difficulty"]))

        card = rebuild_fsrs_card_from_history(data)
        _apply_card(data, card, now)
        stats["rebuilt_cards"] += 1

        new_stability.append(float(data["fsrs_stability"]))
        new_difficulty.append(float(data["fsrs_difficulty"]))
        new_due = float(data["fsrs_due"])
        if old_due and new_due < old_due - 1:
            stats["due_earlier"] += 1
        elif old_due and new_due > old_due + 1:
            stats["due_later"] += 1
        else:
            stats["due_unchanged"] += 1

    def _summary(old: List[float], new: List[float]) -> Dict[str, Any]:
        if not old or not new:
            return {}
        return {
            "old_mean": round(statistics.fmean(old), 3),
            "new_mean": round(statistics.fmean(new), 3),
            "old_median": round(statistics.median(old), 3),
            "new_median": round(statistics.median(new), 3),
            "old_max": round(max(old), 3),
            "new_max": round(max(new), 3),
            "increased": sum(1 for o, n in zip(old, new) if n > o + 1e-9),
            "decreased": sum(1 for o, n in zip(old, new) if n < o - 1e-9),
        }

    stats["stability"] = _summary(old_stability, new_stability)
    stats["difficulty"] = _summary(old_difficulty, new_difficulty)
    return rebuilt, stats


def print_stats(stats: Dict[str, Any], cutoff_iso: str) -> None:
    print(f"评分语义 cutoff: {cutoff_iso} (UTC ts={LEGACY_RATING_CUTOFF:.0f})")
    print(f"总词数              : {stats['total_words']}")
    print(f"总历史事件数        : {stats['total_events']}")
    print(
        f"legacy 事件数       : {stats['legacy_events']} "
        f"(current 事件数 {stats['current_events']})"
    )
    print(f"全部事件 quality 分布: {stats['quality_counts']}")
    print(f"legacy 事件 quality 分布: {stats['legacy_quality_counts']}")
    print(f"重建卡片数量        : {stats['rebuilt_cards']}")
    if stats["skipped_already_migrated"]:
        print(f"已迁移跳过          : {stats['skipped_already_migrated']}")
    print(f"stability 变化      : {stats['stability']}")
    print(f"difficulty 变化     : {stats['difficulty']}")
    print(
        f"due 被提前 / 推迟 / 不变: "
        f"{stats['due_earlier']} / {stats['due_later']} / {stats['due_unchanged']}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _latest_backup(progress_path: Path) -> Optional[Path]:
    backups = sorted(progress_path.parent.glob(BACKUP_GLOB))
    return backups[-1] if backups else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS_PATH)
    parser.add_argument("--apply", action="store_true", help="备份后写回重建结果")
    parser.add_argument(
        "--force", action="store_true", help="已迁移的卡片也强制重新 replay"
    )
    parser.add_argument(
        "--rollback", action="store_true", help="从最近一次迁移备份恢复"
    )
    args = parser.parse_args()

    progress_path = args.progress.resolve()

    if args.rollback:
        backup = _latest_backup(progress_path)
        if backup is None:
            print("未找到迁移备份，无法回滚。")
            return 1
        shutil.copy2(backup, progress_path)
        print(f"已从 {backup.name} 回滚 {progress_path.name}")
        return 0

    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    if not isinstance(progress, dict):
        raise ValueError("进度文件顶层必须是 JSON 对象")

    now = time.time()
    rebuilt, stats = rebuild_progress(progress, now, force=args.force)
    mode = "执行" if args.apply else "预览(dry-run)"
    print(f"FSRS 评分语义迁移 {mode}: {progress_path}")
    print_stats(stats, LEGACY_RATING_CUTOFF_ISO)

    if not args.apply:
        print("未写入任何文件；确认后使用 --apply。")
        return 0

    if stats["rebuilt_cards"] == 0:
        # 幂等：已经迁移过就什么都不做，也不再产生一份重复备份，
        # 否则第二次 apply 会用「已迁移」的内容覆盖第一次的回滚点。
        print("没有需要重建的卡片（已迁移或没有历史），未写入任何文件。")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = progress_path.with_name(
        f"{progress_path.stem}.pre_rating_migration_{stamp}.bak.json"
    )
    suffix = 1
    while backup_path.exists():
        suffix += 1
        backup_path = progress_path.with_name(
            f"{progress_path.stem}.pre_rating_migration_{stamp}_{suffix}.bak.json"
        )
    shutil.copy2(progress_path, backup_path)
    safe_json_dump(rebuilt, progress_path)
    print(f"已备份: {backup_path}")
    print("已原子写回修正后的进度。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
