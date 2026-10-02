"""按角色、自然日和会话 ID 清理聊天记录及其派生记忆。

默认仅预演；传入 ``--apply`` 才会原子写入。脚本不会创建备份，也不会
清理该角色当天与目标会话无关的日常、学习或主动关怀状态。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPANION_DATA = PROJECT_ROOT / "companion_data"


def _parse_date(value: str) -> date:
    return date.fromisoformat(str(value or "").strip())


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp_chat_day_purge_{os.getpid()}")
    temp_path.write_text(text, encoding="utf-8")
    os.replace(temp_path, path)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


def _read_jsonl(path: Path) -> list[tuple[str, dict[str, Any] | None]]:
    rows: list[tuple[str, dict[str, Any] | None]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            payload = None
        rows.append((line, payload if isinstance(payload, dict) else None))
    return rows


def _collect_nested_event_ids(value: Any) -> set[str]:
    event_ids: set[str] = set()
    if isinstance(value, dict):
        event_id = str(value.get("event_id") or "").strip()
        if event_id:
            event_ids.add(event_id)
        for nested in value.values():
            event_ids.update(_collect_nested_event_ids(nested))
    elif isinstance(value, list):
        for nested in value:
            event_ids.update(_collect_nested_event_ids(nested))
    return event_ids


def _memory_matches(
    record: dict[str, Any],
    *,
    event_ids: set[str],
    date_prefix: str,
    conversation_ids: set[str],
) -> bool:
    metadata = record.get("metadata")
    event_ref = metadata.get("event_ref") if isinstance(metadata, dict) else None
    if not isinstance(event_ref, dict):
        return False
    event_id = str(event_ref.get("event_id") or "").strip()
    if event_id and event_id in event_ids:
        return True
    relative_path = str(event_ref.get("relative_path") or "").replace("\\", "/")
    conversation_id = str(event_ref.get("conversation_id") or "").strip()
    return relative_path.startswith(date_prefix) and conversation_id in conversation_ids


def _build_indexes(
    records: list[dict[str, Any]],
) -> tuple[dict[str, float], dict[str, list[dict[str, Any]]]]:
    topic_weights: dict[str, float] = defaultdict(float)
    emotion_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        memory_id = str(record.get("id") or "").strip()
        if not memory_id:
            continue
        weight = float(record.get("weight") or 1.0)
        for topic in record.get("topics") or []:
            topic_text = str(topic or "").strip()
            if topic_text:
                topic_weights[topic_text] += weight * 0.1
        seen_emotions: set[str] = set()
        for emotion in record.get("emotions") or [record.get("emotion")]:
            emotion_text = str(emotion or "").strip().lower()
            if not emotion_text or emotion_text in seen_emotions:
                continue
            seen_emotions.add(emotion_text)
            emotion_map[emotion_text].append(
                {"memory_id": memory_id, "relevance_score": 0.8}
            )
    return dict(topic_weights), dict(emotion_map)


def purge_chat_day(
    *,
    role_root: Path,
    target_date: date,
    conversation_ids: set[str],
    apply: bool,
) -> dict[str, Any]:
    resolved_role_root = role_root.resolve()
    resolved_companion = COMPANION_DATA.resolve()
    if resolved_companion not in resolved_role_root.parents:
        raise RuntimeError(f"角色目录越界: {resolved_role_root}")
    if not conversation_ids:
        raise ValueError("至少需要一个 conversation_id")

    year = f"{target_date.year:04d}"
    month = f"{target_date.month:02d}"
    day = f"{target_date.day:02d}"
    date_prefix = f"{year}/{month}/{day}/"
    history_day = resolved_role_root / "chat_history" / year / month / day
    daily_events = resolved_role_root / "daily" / year / month / day / "events"
    weighted_root = resolved_role_root / "memories" / "weighted"

    history_updates: dict[Path, list[str]] = {}
    event_ids: set[str] = set()
    history_events_removed = 0
    history_files_matched = 0
    if history_day.exists():
        for path in sorted(history_day.rglob("*.jsonl")):
            kept: list[str] = []
            changed = False
            for line, payload in _read_jsonl(path):
                if payload is not None and str(payload.get("conversation_id") or "") in conversation_ids:
                    changed = True
                    history_events_removed += 1
                    event_ids.update(_collect_nested_event_ids(payload))
                else:
                    kept.append(line)
            if changed:
                history_files_matched += 1
                history_updates[path] = kept

    daily_updates: dict[Path, list[str]] = {}
    daily_events_removed = 0
    if daily_events.exists():
        for path in sorted(daily_events.glob("*.jsonl")):
            kept = []
            changed = False
            for line, payload in _read_jsonl(path):
                payload_event_ids = _collect_nested_event_ids(payload)
                matches = bool(
                    payload is not None
                    and (
                        str(payload.get("conversation_id") or "") in conversation_ids
                        or bool(payload_event_ids & event_ids)
                    )
                )
                if matches:
                    changed = True
                    daily_events_removed += 1
                else:
                    kept.append(line)
            if changed:
                daily_updates[path] = kept

    weighted_payloads: dict[Path, dict[str, Any]] = {}
    memory_records_removed = 0
    if weighted_root.exists():
        for path in sorted(weighted_root.rglob("*_weighted.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            records = payload.get("weighted_memories")
            if not isinstance(records, list):
                continue
            kept_records = [
                record
                for record in records
                if not (
                    isinstance(record, dict)
                    and _memory_matches(
                        record,
                        event_ids=event_ids,
                        date_prefix=date_prefix,
                        conversation_ids=conversation_ids,
                    )
                )
            ]
            removed = len(records) - len(kept_records)
            if removed:
                memory_records_removed += removed
                payload["weighted_memories"] = kept_records
                payload["last_updated"] = time.time()
            weighted_payloads[path] = payload

        records_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for path, payload in weighted_payloads.items():
            for record in payload.get("weighted_memories") or []:
                if isinstance(record, dict):
                    records_by_name[path.name].append(record)
        for path, payload in weighted_payloads.items():
            if "topic_weights" not in payload and "emotion_memory_map" not in payload:
                continue
            topic_weights, emotion_map = _build_indexes(records_by_name[path.name])
            if payload.get("topic_weights") != topic_weights or payload.get("emotion_memory_map") != emotion_map:
                payload["topic_weights"] = topic_weights
                payload["emotion_memory_map"] = emotion_map
                payload["last_updated"] = time.time()

    result = {
        "mode": "apply" if apply else "dry-run",
        "role_root": str(resolved_role_root),
        "date": target_date.isoformat(),
        "conversation_ids": sorted(conversation_ids),
        "history_files_matched": history_files_matched,
        "history_events_removed": history_events_removed,
        "daily_events_removed": daily_events_removed,
        "memory_records_removed": memory_records_removed,
    }
    if not apply:
        return result

    for path, payload in weighted_payloads.items():
        original = json.loads(path.read_text(encoding="utf-8"))
        if payload != original:
            _atomic_write_json(path, payload)
    for updates in (daily_updates, history_updates):
        for path, kept_lines in updates.items():
            if kept_lines:
                _atomic_write_text(path, "\n".join(kept_lines) + "\n")
            elif path.exists():
                path.unlink()

    if history_day.exists():
        remaining_history = list(history_day.rglob("*.jsonl"))
        if not remaining_history:
            resolved_history_day = history_day.resolve()
            chat_root = (resolved_role_root / "chat_history").resolve()
            if chat_root not in resolved_history_day.parents:
                raise RuntimeError(f"拒绝删除越界目录: {resolved_history_day}")
            shutil.rmtree(resolved_history_day)
        else:
            from core.services.chat_history_store import ChatHistoryStore

            ChatHistoryStore(resolved_role_root / "chat_history")._write_day_index(
                history_day,
                resolved_role_root / "chat_history",
            )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True, help="角色 scope，例如 ling")
    parser.add_argument("--date", required=True, help="自然日，格式 YYYY-MM-DD")
    parser.add_argument(
        "--conversation-id",
        action="append",
        required=True,
        dest="conversation_ids",
        help="要清理的会话 ID，可重复传入",
    )
    parser.add_argument("--apply", action="store_true", help="正式写入；默认仅预演")
    args = parser.parse_args()

    role_root = COMPANION_DATA / f"{str(args.scope).strip()}_data"
    result = purge_chat_day(
        role_root=role_root,
        target_date=_parse_date(args.date),
        conversation_ids={str(item).strip() for item in args.conversation_ids},
        apply=bool(args.apply),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
