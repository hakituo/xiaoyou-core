"""清理并压缩 companion_data 下的 short_term 文件。

只保留真实 user/assistant 对话，最多 60 条且落盘不超过 64 KiB。
完整聊天记录由 ChatHistoryStore 保存；本脚本不创建备份。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMPANION_DATA = PROJECT_ROOT / "companion_data"
MAX_RECORDS = 60
MAX_BYTES = 64 * 1024
NON_DIALOGUE_CATEGORIES = frozenset(
    {"thinking", "profile", "context_injection", "persona_prompt", "sensitive", "diary"}
)
DISK_FIELDS = (
    "id",
    "content",
    "timestamp",
    "created_at",
    "source",
    "role",
    "category",
    "memory_type",
    "is_important",
    "weight",
    "topics",
    "emotions",
    "emotion",
    "scopes",
)
METADATA_FIELDS = (
    "event_ref",
    "message_id",
    "platform",
    "is_proactive",
    "is_peer_script",
    "peer_speaker",
    "original_source",
    "type",
)


def find_short_term_files() -> list[Path]:
    """递归扫描所有角色和 dual_role 的短期记忆文件。"""
    if not COMPANION_DATA.exists():
        return []
    return sorted(
        path
        for path in COMPANION_DATA.rglob("*_short.json")
        if path.is_file()
        and path.parent.name == "short_term"
        and "backups" not in path.relative_to(COMPANION_DATA).parts
    )


def is_telegram_file(path: Path) -> bool:
    user_id = path.name.removesuffix("_short.json").lower()
    return user_id.startswith("tg_") or "telegram" in user_id


def infer_memory_type(record: dict[str, Any]) -> str:
    explicit = str(record.get("memory_type") or "").strip().lower()
    if explicit:
        return explicit
    content = str(record.get("content") or "").strip()
    if bool(record.get("is_distilled")) or content.startswith("【历史摘要】"):
        return "event_summary"
    return "dialogue"


def is_short_term_dialogue(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    content = str(record.get("content") or "").strip()
    source = str(record.get("source") or "").strip().lower()
    role = str(record.get("role") or source).strip().lower()
    category = str(record.get("category") or "").strip().lower()
    return bool(
        content
        and category not in NON_DIALOGUE_CATEGORIES
        and infer_memory_type(record) == "dialogue"
        and role in {"user", "assistant"}
        and source not in {"system", "system_summary", "workspace"}
    )


def compact_record(record: dict[str, Any]) -> dict[str, Any]:
    compact = {field: record[field] for field in DISK_FIELDS if field in record}
    compact["memory_type"] = infer_memory_type(record)
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        compact_metadata = {
            field: metadata[field]
            for field in METADATA_FIELDS
            if field in metadata
        }
        if compact_metadata:
            compact["metadata"] = compact_metadata
    return compact


def encoded_size(records: list[dict[str, Any]]) -> int:
    return len(json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8"))


def build_clean_records(records: list[Any]) -> tuple[list[dict[str, Any]], int]:
    dialogue = [compact_record(record) for record in records if is_short_term_dialogue(record)]
    removed_non_dialogue = len(records) - len(dialogue)
    dialogue.sort(key=lambda item: float(item.get("timestamp") or 0.0))
    dialogue = dialogue[-MAX_RECORDS:]
    while len(dialogue) > 1 and encoded_size(dialogue) > MAX_BYTES:
        dialogue.pop(0)
    return dialogue, removed_non_dialogue


def atomic_write(path: Path, records: list[dict[str, Any]]) -> None:
    temp_path = path.with_suffix(".json.tmp_cleanup")
    temp_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def clean_file(
    path: Path,
    *,
    dry_run: bool,
    delete_telegram: bool,
    quiet: bool,
) -> dict[str, Any]:
    before_bytes = path.stat().st_size
    if delete_telegram and is_telegram_file(path):
        if not dry_run:
            path.unlink()
        print(f"  [删除 Telegram] {path.relative_to(PROJECT_ROOT)}")
        return {"deleted": 1, "changed": 1, "before": before_bytes, "after": 0, "removed": 0}

    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  [跳过] {path.relative_to(PROJECT_ROOT)}: {exc}")
        return {"deleted": 0, "changed": 0, "before": before_bytes, "after": before_bytes, "removed": 0}
    if not isinstance(records, list):
        print(f"  [跳过] {path.relative_to(PROJECT_ROOT)}: 顶层不是数组")
        return {"deleted": 0, "changed": 0, "before": before_bytes, "after": before_bytes, "removed": 0}

    cleaned, removed_non_dialogue = build_clean_records(records)
    after_bytes = encoded_size(cleaned)
    changed = cleaned != records
    if changed and not dry_run:
        if cleaned:
            atomic_write(path, cleaned)
        else:
            path.unlink()
            after_bytes = 0

    if changed or not quiet:
        action = "删除空文件" if not cleaned else "清理"
        print(
            f"  [{action}] {path.relative_to(PROJECT_ROOT)}: "
            f"{len(records)} -> {len(cleaned)} 条, "
            f"非对话 {removed_non_dialogue} 条, "
            f"{before_bytes / 1024:.1f} -> {after_bytes / 1024:.1f} KiB"
        )
    return {
        "deleted": int(changed and not cleaned),
        "changed": int(changed),
        "before": before_bytes,
        "after": after_bytes,
        "removed": len(records) - len(cleaned),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只报告，不修改文件")
    parser.add_argument("--delete-telegram", action="store_true", help="直接删除 Telegram 短期记忆文件")
    parser.add_argument("--quiet", action="store_true", help="只显示发生变化的文件")
    args = parser.parse_args()

    files = find_short_term_files()
    print(f"扫描到 {len(files)} 个 short_term 文件")
    totals = {"deleted": 0, "changed": 0, "before": 0, "after": 0, "removed": 0}
    for path in files:
        result = clean_file(
            path,
            dry_run=args.dry_run,
            delete_telegram=args.delete_telegram,
            quiet=args.quiet,
        )
        for key in totals:
            totals[key] += int(result[key])

    mode = "DRY-RUN" if args.dry_run else "APPLY"
    print(
        f"[{mode}] 修改 {totals['changed']} 个，删除 {totals['deleted']} 个，"
        f"移除 {totals['removed']} 条，"
        f"{totals['before'] / 1024:.1f} -> {totals['after'] / 1024:.1f} KiB"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
