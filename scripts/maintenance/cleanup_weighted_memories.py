"""迁移并清理 Aveline、Ling的 weighted memory。

默认只预演；传入 ``--apply`` 才会原子写入。脚本不会创建备份。
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPANION_DATA = PROJECT_ROOT / "companion_data"
AVELINE_ROOT = COMPANION_DATA / "aveline_data" / "memories" / "weighted"
LING_ROOT = COMPANION_DATA / "ling_data" / "memories" / "weighted"
DUAL_ROLE_ROOT = COMPANION_DATA / "dual_role" / "memories" / "weighted"
AVELINE_HISTORY = COMPANION_DATA / "aveline_data" / "chat_history"
LING_HISTORY = COMPANION_DATA / "ling_data" / "chat_history"
DUAL_TARGET_IDS = {
    "peer_3406280693__scope__dual_role",
    "peer_3795532329__scope__dual_role",
}

NON_PERSISTENT_CATEGORIES = {"thinking", "context_injection", "persona_prompt"}
DERIVED_FIELDS = {
    "source_ref",
    "readable_summary",
    "readable_title",
    "display_tags",
    "keywords",
    "last_hit_time",
    "embedding",
    "embedding_base64",
}
RUNTIME_METADATA_FIELDS = {
    "reply_content",
    "thought",
    "reasoning_content",
    "model_hint",
    "trace_id",
    "thought_source",
    "defer_analysis",
}


def load_payload(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"weighted 文件顶层不是对象: {path}")
    return data


def discover_user_ids(root: Path) -> list[str]:
    results = set()
    if not root.exists():
        return []
    for path in root.rglob("*_weighted.json"):
        if not path.is_file():
            continue
        results.add(path.name.removesuffix("_weighted.json"))
    return sorted(results)


def manager_files(root: Path, user_id: str) -> list[Path]:
    expected_name = f"{user_id}_weighted.json"
    return sorted(
        path
        for path in root.rglob(expected_name)
        if path.is_file() and path.name == expected_name
    )


def load_manager_records(root: Path, user_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in manager_files(root, user_id):
        payload = load_payload(path)
        for record in payload.get("weighted_memories") or []:
            if isinstance(record, dict):
                records.append(dict(record))
    return records


def collect_event_ids(value: Any, target: set[str]) -> None:
    if isinstance(value, dict):
        event_id = value.get("event_id")
        if event_id:
            target.add(str(event_id))
        for nested in value.values():
            collect_event_ids(nested, target)
    elif isinstance(value, list):
        for nested in value:
            collect_event_ids(nested, target)


def load_history_event_ids(root: Path) -> set[str]:
    """只读取实际 JSONL 事件，不把 index.json 中的空壳引用算作可恢复。"""
    event_ids: set[str] = set()
    for path in root.rglob("*.jsonl"):
        if not path.is_file():
            continue
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                collect_event_ids(json.loads(line), event_ids)
            except json.JSONDecodeError as exc:
                raise ValueError(f"聊天历史 JSONL 损坏: {path}:{line_number}") from exc
    return event_ids


def target_for_aveline(user_id: str) -> tuple[Path, str] | None:
    if user_id.startswith("tg_"):
        return None
    if user_id.startswith("peer_") and user_id.endswith("__scope__dual_role"):
        return DUAL_ROLE_ROOT, user_id
    if user_id in {
        "shared__scope__aveline",
        "private_123456789__scope__aveline",
        "private_123456789",
        "aveline",
    }:
        return AVELINE_ROOT, user_id
    if user_id.endswith("__persona__aveline_qq_master"):
        prefix = user_id.split("__persona__", 1)[0]
        return AVELINE_ROOT, f"{prefix}__scope__aveline"
    return None


def target_for_ling(user_id: str) -> tuple[Path, str] | None:
    if user_id.startswith("tg_"):
        return None
    if user_id in {
        "shared__scope__ling",
        "private_123456789__scope__ling",
        "ling",
    }:
        return LING_ROOT, user_id
    if "__persona__" in user_id:
        prefix = user_id.split("__persona__", 1)[0]
        if prefix == "shared" or prefix.startswith("private_"):
            return LING_ROOT, f"{prefix}__scope__ling"
    return None


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def memory_key(record: dict[str, Any]) -> tuple[str, ...]:
    metadata = record.get("metadata")
    event_ref = metadata.get("event_ref") if isinstance(metadata, dict) else None
    memory_type = str(record.get("memory_type") or "dialogue").strip().lower()
    source = str(record.get("source") or "chat").strip().lower()
    if isinstance(event_ref, dict) and event_ref.get("event_id"):
        return "event", memory_type, str(event_ref["event_id"]), source
    if isinstance(metadata, dict) and metadata.get("message_id"):
        # 相同短句可能在不同时间真实出现；只有同一 message_id 才视为同一对话记录。
        return "message", memory_type, str(metadata["message_id"]), source
    if memory_type == "preference" and isinstance(metadata, dict):
        preference_key = str(metadata.get("preference_key") or "").strip().lower()
        polarity = "1" if bool(metadata.get("polarity")) else "0"
        if preference_key:
            return "preference", preference_key, polarity
    content = normalize_text(record.get("content") or record.get("summary"))
    if content:
        return "content", memory_type, source, content
    return "id", str(record.get("id") or "")


def merge_unique_strings(base: Any, incoming: Any, *, limit: int) -> list[str]:
    merged: list[str] = []
    for item in list(base or []) + list(incoming or []):
        text = str(item or "").strip()
        if text and text not in merged:
            merged.append(text)
        if len(merged) >= limit:
            break
    return merged


def merge_metadata(base: Any, incoming: Any) -> dict[str, Any]:
    merged = dict(base) if isinstance(base, dict) else {}
    for key, value in (incoming.items() if isinstance(incoming, dict) else []):
        if key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = value
        elif isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_metadata(merged[key], value)
    return merged


def merge_records(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    merged["weight"] = max(
        float(base.get("weight") or 0.0),
        float(incoming.get("weight") or 0.0),
    )
    merged["last_access_time"] = max(
        float(base.get("last_access_time") or 0.0),
        float(incoming.get("last_access_time") or 0.0),
    )
    merged["is_important"] = bool(
        base.get("is_important", False) or incoming.get("is_important", False)
    )
    merged["is_distilled"] = bool(
        base.get("is_distilled", False) or incoming.get("is_distilled", False)
    )
    merged["topics"] = merge_unique_strings(base.get("topics"), incoming.get("topics"), limit=8)
    merged["emotions"] = merge_unique_strings(
        base.get("emotions"), incoming.get("emotions"), limit=4
    )
    for field in ("content", "summary"):
        current = str(merged.get(field) or "")
        candidate = str(incoming.get(field) or "")
        if candidate and len(candidate) > len(current):
            merged[field] = incoming.get(field)
    merged["metadata"] = merge_metadata(base.get("metadata"), incoming.get("metadata"))
    return merged


def normalize_record(record: dict[str, Any]) -> dict[str, Any] | None:
    normalized = dict(record)
    category = str(normalized.get("category") or "uncategorized").strip().lower()
    if category in NON_PERSISTENT_CATEGORIES:
        return None
    normalized["category"] = category

    if category == "diary":
        normalized["memory_type"] = "event_summary"
        normalized["is_distilled"] = True
    elif category == "sensitive":
        normalized["memory_type"] = "sensitive"
        normalized["scopes"] = ["local"]
    elif category == "profile":
        normalized["memory_type"] = "profile"
    elif category == "preference":
        normalized["memory_type"] = "preference"
    elif not str(normalized.get("memory_type") or "").strip():
        normalized["memory_type"] = "dialogue"

    topics = []
    for topic in normalized.get("topics") or []:
        text = str(topic or "").strip()
        if not text:
            continue
        if text.lower() == "chat":
            text = "chat"
        if text not in topics:
            topics.append(text)
    normalized["topics"] = topics[:8]

    for field in DERIVED_FIELDS:
        normalized.pop(field, None)
    metadata = normalized.get("metadata")
    if isinstance(metadata, dict):
        compact_metadata = dict(metadata)
        for field in RUNTIME_METADATA_FIELDS:
            compact_metadata.pop(field, None)
        normalized["metadata"] = compact_metadata
    return normalized


def compact_event_content(
    records: list[dict[str, Any]], known_event_ids: set[str]
) -> tuple[list[dict[str, Any]], int]:
    compacted: list[dict[str, Any]] = []
    removed_orphans = 0
    for record in records:
        metadata = record.get("metadata")
        event_ref = metadata.get("event_ref") if isinstance(metadata, dict) else None
        event_id = (
            str(event_ref.get("event_id") or "")
            if isinstance(event_ref, dict)
            else ""
        )
        if not event_id:
            compacted.append(record)
            continue
        if event_id in known_event_ids:
            record["content"] = ""
            compacted.append(record)
            continue
        if str(record.get("content") or "").strip():
            # 引用失效但正文仍在时保留正文，避免清理动作造成信息丢失。
            compacted.append(record)
            continue
        removed_orphans += 1
    return compacted, removed_orphans


def normalize_and_dedupe(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    normalized_records: dict[tuple[str, ...], dict[str, Any]] = {}
    removed_non_persistent = 0
    duplicates = 0
    for record in sorted(
        records,
        key=lambda item: (
            float(item.get("timestamp") or 0.0),
            float(item.get("weight") or 0.0),
        ),
    ):
        normalized = normalize_record(record)
        if normalized is None:
            removed_non_persistent += 1
            continue
        key = memory_key(normalized)
        existing = normalized_records.get(key)
        if existing is not None:
            normalized_records[key] = merge_records(existing, normalized)
            duplicates += 1
            continue
        normalized_records[key] = normalized
    return list(normalized_records.values()), {
        "removed_non_persistent": removed_non_persistent,
        "duplicates_removed": duplicates,
    }


def build_derived_indexes(records: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, list[dict[str, Any]]]]:
    topic_weights: dict[str, float] = defaultdict(float)
    emotion_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        memory_id = str(record.get("id") or "").strip()
        if not memory_id:
            continue
        weight = float(record.get("weight") or 1.0)
        for topic in record.get("topics") or []:
            topic_text = str(topic or "").strip()
            if not topic_text:
                continue
            if topic_text.lower() == "chat":
                topic_text = "chat"
            topic_weights[topic_text] += weight * 0.1
        seen_emotions = set()
        for emotion in (record.get("emotions") or [record.get("emotion")]):
            emotion_text = str(emotion or "").strip().lower()
            if not emotion_text or emotion_text in seen_emotions:
                continue
            seen_emotions.add(emotion_text)
            emotion_map[emotion_text].append(
                {"memory_id": memory_id, "relevance_score": 0.8}
            )
    return dict(topic_weights), dict(emotion_map)


def safe_category_dir(category: str) -> str:
    invalid_chars = '<>:"/\\|?*'
    safe = "".join(char for char in str(category or "") if char not in invalid_chars)
    safe = safe.strip().rstrip(".") or "unknown"
    if safe.upper() in {"CON", "PRN", "AUX", "NUL"}:
        return f"_{safe}"
    return safe


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp_weighted_cleanup_{os.getpid()}")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, path)


def remove_manager_files(root: Path, user_id: str) -> int:
    removed = 0
    resolved_root = root.resolve()
    for path in manager_files(root, user_id):
        resolved = path.resolve()
        if resolved_root not in resolved.parents:
            raise RuntimeError(f"拒绝删除越界文件: {resolved}")
        path.unlink()
        removed += 1
    return removed


def clear_weighted_files(root: Path) -> int:
    removed = 0
    resolved_root = root.resolve()
    for path in sorted(root.rglob("*_weighted.json")):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved_root not in resolved.parents:
            raise RuntimeError(f"拒绝删除越界文件: {resolved}")
        path.unlink()
        removed += 1
    return removed


def write_manager(root: Path, user_id: str, records: list[dict[str, Any]]) -> int:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get("category") or "uncategorized")].append(record)
    topic_weights, emotion_map = build_derived_indexes(records)
    now = time.time()
    uncategorized = grouped.pop("uncategorized", [])
    atomic_write(
        root / f"{user_id}_weighted.json",
        {
            "weighted_memories": uncategorized,
            "topic_weights": topic_weights,
            "emotion_memory_map": emotion_map,
            "last_updated": now,
        },
    )
    files_written = 1
    for category, category_records in sorted(grouped.items()):
        atomic_write(
            root / safe_category_dir(category) / f"{user_id}_weighted.json",
            {
                "weighted_memories": category_records,
                "category": category,
                "last_updated": now,
            },
        )
        files_written += 1
    return files_written


def build_plan() -> tuple[dict[tuple[Path, str], list[dict[str, Any]]], dict[str, Any]]:
    targets: dict[tuple[Path, str], list[dict[str, Any]]] = defaultdict(list)
    stats: dict[str, Any] = {
        "source_records": 0,
        "discarded_unmapped_records": 0,
        "source_files": 0,
        "targets": {},
    }
    dual_target_ids = set(DUAL_TARGET_IDS)

    for root, resolver in (
        (AVELINE_ROOT, target_for_aveline),
        (LING_ROOT, target_for_ling),
    ):
        for user_id in discover_user_ids(root):
            records = load_manager_records(root, user_id)
            stats["source_records"] += len(records)
            stats["source_files"] += len(manager_files(root, user_id))
            target = resolver(user_id)
            if target is None:
                stats["discarded_unmapped_records"] += len(records)
                continue
            targets[target].extend(records)
            if target[0] == DUAL_ROLE_ROOT:
                dual_target_ids.add(target[1])

    for user_id in sorted(dual_target_ids):
        records = load_manager_records(DUAL_ROLE_ROOT, user_id)
        if records:
            targets[(DUAL_ROLE_ROOT, user_id)].extend(records)

    history_ids = {
        AVELINE_ROOT: load_history_event_ids(AVELINE_HISTORY),
        LING_ROOT: load_history_event_ids(LING_HISTORY),
    }

    for target, records in list(targets.items()):
        cleaned, clean_stats = normalize_and_dedupe(records)
        removed_orphans = 0
        if target[0] in history_ids:
            cleaned, removed_orphans = compact_event_content(
                cleaned, history_ids[target[0]]
            )
        targets[target] = cleaned
        stats["targets"][f"{target[0].parent.parent.name}:{target[1]}"] = {
            "before": len(records),
            "after": len(cleaned),
            "removed_orphan_event_refs": removed_orphans,
            **clean_stats,
        }
    return targets, stats


def apply_plan(targets: dict[tuple[Path, str], list[dict[str, Any]]]) -> dict[str, int]:
    result = {
        "source_files_removed": clear_weighted_files(AVELINE_ROOT)
        + clear_weighted_files(LING_ROOT),
        "dual_files_removed": 0,
        "files_written": 0,
    }
    dual_ids = sorted(user_id for root, user_id in targets if root == DUAL_ROLE_ROOT)
    for user_id in dual_ids:
        result["dual_files_removed"] += remove_manager_files(DUAL_ROLE_ROOT, user_id)
    for (root, user_id), records in sorted(
        targets.items(), key=lambda item: (str(item[0][0]), item[0][1])
    ):
        result["files_written"] += write_manager(root, user_id, records)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="正式写入；默认仅预演")
    args = parser.parse_args()

    targets, stats = build_plan()
    output: dict[str, Any] = {
        "mode": "apply" if args.apply else "dry-run",
        **stats,
    }
    if args.apply:
        output["write_result"] = apply_plan(targets)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
