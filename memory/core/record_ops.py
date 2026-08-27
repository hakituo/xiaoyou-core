from collections import defaultdict
import time
from typing import Any, Dict, List, Tuple

from memory.core.lock_utils import get_write_lock


READABLE_CONTENT_PREVIEW = 2000
READABLE_TAG_LIMIT = 6
VALID_MEMORY_STATUSES = {
    "active",
    "superseded",
    "deleted",
    "pending_analysis",
}
STABLE_MEMORY_FIELDS = (
    "id",
    "memory_type",
    "source_ref",
    "source",
    "role",
    "scopes",
    "created_at",
)
AI_MUTABLE_MEMORY_FIELDS = (
    "category",
    "topics",
    "display_tags",
    "status",
    "summary",
    "readable_title",
    "readable_summary",
    "weight",
    "emotion",
    "emotions",
    "last_hit_time",
)
DERIVED_MEMORY_FIELDS = (
    "search_keywords",
    "keywords",
    "embedding",
    "last_access_time",
)
READABLE_MEMORY_TYPE_LABELS = {
    "dialogue": "对话",
    "event_summary": "摘要",
    "preference": "偏好",
    "profile": "画像",
    "state": "状态",
    "sensitive": "敏感",
    "task": "任务",
}
READABLE_CATEGORY_LABELS = {
    "uncategorized": "未分类",
    "daily": "日常",
    "learning": "学习",
    "work": "工作",
    "festival": "节日",
    "health": "健康",
    "profile": "画像",
    "preference": "偏好",
    "sensitive": "敏感",
    "state": "状态",
    "emotion": "情绪",
    "tech": "技术",
    "finance": "财务",
    "entertainment": "娱乐",
    "task": "任务",
}


def build_readable_preview(text: Any, *, fallback: str = "") -> str:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return fallback
    return normalized[:READABLE_CONTENT_PREVIEW]


def get_memory_field_policy() -> Dict[str, List[str]]:
    return {
        "stable_fields": list(STABLE_MEMORY_FIELDS),
        "ai_mutable_fields": list(AI_MUTABLE_MEMORY_FIELDS),
        "derived_fields": list(DERIVED_MEMORY_FIELDS),
    }


def status_rank(status: str) -> int:
    normalized = str(status or "").strip().lower()
    ranks = {
        "active": 4,
        "pending_analysis": 3,
        "superseded": 2,
        "deleted": 1,
    }
    return ranks.get(normalized, 0)


def merge_tags(base: List[str], incoming: List[str], limit: int = 8) -> List[str]:
    merged: List[str] = []
    for item in list(base or []) + list(incoming or []):
        text = str(item or "").strip()
        if not text:
            continue
        if text not in merged:
            merged.append(text)
        if len(merged) >= limit:
            break
    return merged


def infer_memory_type(manager: Any, record: Dict[str, Any]) -> str:
    category = str(record.get("category") or "uncategorized").strip().lower()
    topics = [
        str(item).strip().lower()
        for item in (record.get("topics") or [])
        if str(item).strip()
    ]
    metadata = record.get("metadata")
    source = str(record.get("source") or "").strip().lower()
    content = str(record.get("content") or "").strip()
    analysis_meta = metadata.get("analysis_meta") if isinstance(metadata, dict) else None
    rule_block = analysis_meta.get("rule") if isinstance(analysis_meta, dict) else None
    state_event = (
        str(rule_block.get("state_event") or "").strip() if isinstance(rule_block, dict) else ""
    )

    if category == "preference" or (
        isinstance(metadata, dict) and metadata.get("preference_key")
    ):
        return "preference"
    if category == "sensitive" or "sensitive" in topics:
        return "sensitive"
    if category == "profile" or source in {"system_profile", "profile"}:
        return "profile"
    if category == "state" or (state_event and state_event != "NONE"):
        return "state"
    if category == "task" or source in {"reminder", "todo", "task"}:
        return "task"
    if category == "diary" or source == "journal":
        return "event_summary"
    if bool(record.get("is_distilled")) or content.startswith("【历史摘要】"):
        return "event_summary"
    return "dialogue"


def build_source_ref(manager: Any, record: Dict[str, Any]) -> Dict[str, Any]:
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        event_ref = metadata.get("event_ref")
        if isinstance(event_ref, dict) and event_ref.get("event_id"):
            return {
                "kind": "event",
                "event_id": str(event_ref.get("event_id")),
                "session_id": str(event_ref.get("session_id") or ""),
                "source": str(record.get("source") or "chat"),
            }
        source_memory_id = metadata.get("source_memory_id")
        if source_memory_id:
            return {
                "kind": "memory",
                "memory_id": str(source_memory_id),
                "source": str(record.get("source") or "system"),
            }
    return {
        "kind": "memory",
        "memory_id": str(record.get("id") or ""),
        "source": str(record.get("source") or "chat"),
    }


def build_display_tags_for_record(
    manager: Any,
    *,
    memory_type: str,
    category: str,
    topics: List[str],
    status: str,
) -> List[str]:
    tags: List[str] = []
    type_label = READABLE_MEMORY_TYPE_LABELS.get(memory_type)
    if type_label:
        tags.append(type_label)
    category_label = READABLE_CATEGORY_LABELS.get(category, category)
    if category_label and category != "uncategorized":
        tags.append(category_label)
    if status == "pending_analysis":
        tags.append("待分析")
    for topic in topics:
        topic_text = str(topic).strip()
        if not topic_text:
            continue
        if topic_text.lower() in {"chat", "其他", "other"}:
            continue
        if topic_text not in tags:
            tags.append(topic_text)
        if len(tags) >= READABLE_TAG_LIMIT:
            break
    if not tags:
        tags.append("未分类")
    return tags[:READABLE_TAG_LIMIT]


def normalize_memory_record(manager: Any, memory: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    if not isinstance(memory, dict):
        return memory, False

    record = dict(memory)
    changed = False

    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        record["metadata"] = metadata
        changed = True

    content = str(record.get("content") or "")
    source = str(record.get("source") or "chat").strip() or "chat"
    if record.get("source") != source:
        record["source"] = source
        changed = True

    role = str(record.get("role") or source).strip() or source
    if record.get("role") != role:
        record["role"] = role
        changed = True

    category = str(record.get("category") or "").strip().lower()
    if category == "pending_analysis":
        category = "uncategorized"
        changed = True
    if not category:
        category = "uncategorized"
        changed = True
    if record.get("category") != category:
        record["category"] = category
        changed = True

    normalized_topics: List[str] = []
    for topic in record.get("topics") or []:
        topic_text = str(topic or "").strip()
        if not topic_text:
            continue
        if topic_text not in normalized_topics:
            normalized_topics.append(topic_text)
    if category not in {"uncategorized", "preference", "sensitive"} and category not in [
        str(item).strip().lower() for item in normalized_topics
    ]:
        normalized_topics.append(category)
        changed = True
    if record.get("topics") != normalized_topics:
        record["topics"] = normalized_topics
        changed = True

    status = str(record.get("status") or "").strip().lower()
    if bool(metadata.get("analysis_pending", False)):
        status = "pending_analysis"
    elif status not in VALID_MEMORY_STATUSES:
        status = "active"
    if record.get("status") != status:
        record["status"] = status
        changed = True

    memory_type = str(record.get("memory_type") or "").strip().lower()
    if not memory_type:
        memory_type = infer_memory_type(manager, record)
        changed = True
    if record.get("memory_type") != memory_type:
        record["memory_type"] = memory_type
        changed = True

    source_ref = record.get("source_ref")
    normalized_source_ref = build_source_ref(manager, record)
    if source_ref != normalized_source_ref:
        record["source_ref"] = normalized_source_ref
        changed = True

    readable_summary = build_readable_preview(
        record.get("summary") or content,
        fallback="",
    )
    if record.get("readable_summary") != readable_summary:
        record["readable_summary"] = readable_summary
        changed = True

    readable_prefix = READABLE_MEMORY_TYPE_LABELS.get(memory_type, "记忆")
    readable_title = build_readable_preview(
        record.get("readable_title") or readable_summary or content,
        fallback=f"{readable_prefix}记录",
    )
    if readable_title and not readable_title.startswith(readable_prefix):
        readable_title = f"{readable_prefix}｜{readable_title}"
    if record.get("readable_title") != readable_title:
        record["readable_title"] = readable_title
        changed = True

    display_tags = build_display_tags_for_record(
        manager,
        memory_type=memory_type,
        category=category,
        topics=normalized_topics,
        status=status,
    )
    if record.get("display_tags") != display_tags:
        record["display_tags"] = display_tags
        changed = True

    last_hit_time = record.get("last_hit_time")
    if last_hit_time in (None, ""):
        derived_last_hit = float(record.get("last_access_time") or record.get("timestamp") or 0.0)
        record["last_hit_time"] = derived_last_hit
        changed = True

    return record, changed


def build_memory_dedupe_key(manager: Any, record: Dict[str, Any]) -> Tuple[str, ...]:
    memory_type = str(record.get("memory_type") or "dialogue").strip().lower()
    status = str(record.get("status") or "active").strip().lower()
    metadata = record.get("metadata")
    source_ref = record.get("source_ref")
    if not isinstance(source_ref, dict):
        source_ref = build_source_ref(manager, record)
    if memory_type == "preference":
        preference_key = ""
        if isinstance(metadata, dict):
            preference_key = str(metadata.get("preference_key") or "").strip().lower()
        polarity = ""
        if isinstance(metadata, dict) and "polarity" in metadata:
            polarity = "1" if bool(metadata.get("polarity")) else "0"
        return (
            "preference",
            preference_key or str(record.get("content") or "").strip().lower(),
            polarity,
            status,
        )
    if source_ref.get("kind") == "event" and source_ref.get("event_id"):
        return (
            "event",
            memory_type,
            str(source_ref.get("event_id") or "").strip(),
            str(source_ref.get("source") or record.get("source") or "chat").strip().lower(),
        )
    if source_ref.get("kind") == "memory" and source_ref.get("memory_id"):
        return (
            "memory_ref",
            memory_type,
            str(source_ref.get("memory_id") or "").strip(),
            status,
        )
    content_key = " ".join(str(record.get("content") or "").strip().lower().split())
    return (
        "content",
        memory_type,
        str(record.get("source") or "chat").strip().lower(),
        content_key,
    )


def merge_metadata_records(manager: Any, base: Any, incoming: Any) -> Dict[str, Any]:
    base_meta = dict(base) if isinstance(base, dict) else {}
    incoming_meta = dict(incoming) if isinstance(incoming, dict) else {}
    merged = dict(base_meta)
    for key, value in incoming_meta.items():
        if key not in merged:
            merged[key] = value
            continue
        current_value = merged.get(key)
        if isinstance(current_value, dict) and isinstance(value, dict):
            merged[key] = merge_metadata_records(manager, current_value, value)
            continue
        if current_value in (None, "", [], {}):
            merged[key] = value
    return merged


def merge_duplicate_memory_records(
    manager: Any,
    base: Dict[str, Any],
    incoming: Dict[str, Any],
) -> Dict[str, Any]:
    preferred = dict(base)
    incoming_record = dict(incoming)

    base_status = str(preferred.get("status") or "active")
    incoming_status = str(incoming_record.get("status") or "active")
    if status_rank(incoming_status) > status_rank(base_status):
        preferred["status"] = incoming_status

    if str(preferred.get("category") or "uncategorized") == "uncategorized":
        incoming_category = str(incoming_record.get("category") or "uncategorized")
        if incoming_category != "uncategorized":
            preferred["category"] = incoming_category

    preferred["weight"] = max(
        float(preferred.get("weight") or 0.0),
        float(incoming_record.get("weight") or 0.0),
    )
    preferred["last_access_time"] = max(
        float(preferred.get("last_access_time") or 0.0),
        float(incoming_record.get("last_access_time") or 0.0),
    )
    preferred["last_hit_time"] = max(
        float(preferred.get("last_hit_time") or 0.0),
        float(incoming_record.get("last_hit_time") or 0.0),
    )
    preferred["is_important"] = bool(
        preferred.get("is_important", False) or incoming_record.get("is_important", False)
    )
    preferred["is_distilled"] = bool(
        preferred.get("is_distilled", False) or incoming_record.get("is_distilled", False)
    )
    preferred["topics"] = merge_tags(
        preferred.get("topics", []), incoming_record.get("topics", []), limit=8
    )
    preferred["display_tags"] = merge_tags(
        preferred.get("display_tags", []),
        incoming_record.get("display_tags", []),
        limit=READABLE_TAG_LIMIT,
    )
    preferred["emotions"] = merge_tags(
        preferred.get("emotions", []), incoming_record.get("emotions", []), limit=4
    )

    preferred_content = str(preferred.get("content") or "").strip()
    incoming_content = str(incoming_record.get("content") or "").strip()
    if (not preferred_content and incoming_content) or (
        incoming_content and len(incoming_content) > len(preferred_content)
    ):
        preferred["content"] = incoming_record.get("content")

    preferred_summary = str(preferred.get("summary") or "").strip()
    incoming_summary = str(incoming_record.get("summary") or "").strip()
    if (not preferred_summary and incoming_summary) or (
        incoming_summary and len(incoming_summary) > len(preferred_summary)
    ):
        preferred["summary"] = incoming_record.get("summary")

    preferred["metadata"] = merge_metadata_records(
        manager,
        preferred.get("metadata"),
        incoming_record.get("metadata"),
    )
    preferred["search_keywords"] = list(
        merge_tags(
            preferred.get("search_keywords", []),
            incoming_record.get("search_keywords", []),
            limit=16,
        )
    )
    preferred["keywords"] = list(
        merge_tags(
            preferred.get("keywords", []),
            incoming_record.get("keywords", []),
            limit=16,
        )
    )
    normalized, _ = normalize_memory_record(manager, preferred)
    return normalized


def rebuild_memory_indexes_locked(manager: Any) -> None:
    manager.category_index = defaultdict(list)
    manager.topic_weights = defaultdict(float)
    manager.topics = defaultdict(list)
    manager.emotion_memory_map = defaultdict(list)
    if hasattr(manager, "content_dedupe_index"):
        manager.content_dedupe_index = {}
    for memory_id, memory in manager.weighted_memories.items():
        category = str(memory.get("category") or "uncategorized")
        manager.category_index[category].append(memory_id)
        if hasattr(manager, "content_dedupe_index"):
            content_key = " ".join(
                str(memory.get("content") or "").strip().lower().split()
            )
            source_key = str(memory.get("source") or "").strip().lower()
            category_key = category.strip().lower() or "uncategorized"
            manager.content_dedupe_index[
                f"{content_key}\x00{source_key}\x00{category_key}"
            ] = memory_id
        for topic in memory.get("topics", []):
            topic_text = str(topic).strip()
            if not topic_text:
                continue
            if topic_text.lower() == "chat":
                topic_text = "chat"
            manager.topic_weights[topic_text] += float(memory.get("weight") or 1.0) * 0.1
        emotions = memory.get("emotions") or [memory.get("emotion")]
        seen_emotions = set()
        for emotion in emotions:
            emotion_text = str(emotion or "").strip().lower()
            if not emotion_text or emotion_text in seen_emotions:
                continue
            seen_emotions.add(emotion_text)
            manager.emotion_memory_map[emotion_text].append(
                {"memory_id": memory_id, "relevance_score": 0.8}
            )
    manager._update_topic_index()
    manager._rebuild_preference_index_locked()


def dedupe_weighted_memories_locked(manager: Any) -> Dict[str, Any]:
    merged_records: Dict[str, Dict[str, Any]] = {}
    dedupe_key_to_id: Dict[Tuple[str, ...], str] = {}
    alias_map: Dict[str, str] = {}
    duplicates_removed = 0

    ordered_records = sorted(
        manager.weighted_memories.items(),
        key=lambda item: (
            float((item[1] or {}).get("timestamp") or 0.0),
            float((item[1] or {}).get("weight") or 0.0),
        ),
    )
    for memory_id, memory in ordered_records:
        normalized, _ = normalize_memory_record(manager, memory)
        dedupe_key = build_memory_dedupe_key(manager, normalized)
        existing_id = dedupe_key_to_id.get(dedupe_key)
        if existing_id and existing_id in merged_records:
            merged_records[existing_id] = merge_duplicate_memory_records(
                manager,
                merged_records[existing_id],
                normalized,
            )
            alias_map[str(memory_id)] = existing_id
            duplicates_removed += 1
            continue
        normalized_id = str(normalized.get("id") or memory_id).strip() or str(memory_id)
        merged_records[normalized_id] = normalized
        dedupe_key_to_id[dedupe_key] = normalized_id
        alias_map[str(memory_id)] = normalized_id

    short_term_changed = False
    normalized_short: List[Dict[str, Any]] = []
    seen_short_ids = set()
    for memory in manager.short_term_memory:
        normalized_short_record, memory_changed = normalize_memory_record(manager, memory)
        resolved_id = alias_map.get(
            str(normalized_short_record.get("id") or "").strip(),
            str(normalized_short_record.get("id") or "").strip(),
        )
        if resolved_id and resolved_id != str(normalized_short_record.get("id") or "").strip():
            normalized_short_record["id"] = resolved_id
            memory_changed = True
        if resolved_id and resolved_id in seen_short_ids:
            short_term_changed = True
            continue
        if resolved_id:
            seen_short_ids.add(resolved_id)
        normalized_short.append(normalized_short_record)
        short_term_changed = short_term_changed or memory_changed
    manager.short_term_memory = normalized_short
    manager.weighted_memories = merged_records

    for memory in manager.weighted_memories.values():
        metadata = memory.get("metadata")
        if not isinstance(metadata, dict):
            continue
        source_memory_id = str(metadata.get("source_memory_id") or "").strip()
        if source_memory_id and source_memory_id in alias_map:
            resolved = alias_map[source_memory_id]
            if resolved != source_memory_id:
                metadata["source_memory_id"] = resolved

    rebuild_memory_indexes_locked(manager)
    if duplicates_removed > 0 or short_term_changed:
        manager._request_keyword_index_rebuild_locked()
    return {
        "duplicates_removed": duplicates_removed,
        "alias_count": len(alias_map),
        "total_memories": len(manager.weighted_memories),
        "short_term_changed": short_term_changed,
    }


def normalize_loaded_memories(manager: Any) -> bool:
    changed = False

    normalized_short: List[Dict[str, Any]] = []
    for memory in manager.short_term_memory:
        normalized, memory_changed = normalize_memory_record(manager, memory)
        normalized_short.append(normalized)
        changed = changed or memory_changed
    manager.short_term_memory = normalized_short

    normalized_weighted: Dict[str, Dict[str, Any]] = {}
    for memory_id, memory in manager.weighted_memories.items():
        normalized, memory_changed = normalize_memory_record(manager, memory)
        normalized_id = str(normalized.get("id") or memory_id).strip() or str(memory_id)
        if normalized_id != str(memory_id):
            changed = True
        changed = changed or memory_changed
        normalized_weighted[normalized_id] = normalized
    manager.weighted_memories = normalized_weighted

    rebuild_memory_indexes_locked(manager)
    return changed


def clean_memory_records(
    manager: Any,
    *,
    sync_save: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    with get_write_lock(manager):
        before_weighted = len(manager.weighted_memories)
        before_short = len(manager.short_term_memory)
        normalized_changed = normalize_loaded_memories(manager)
        dedupe_stats = dedupe_weighted_memories_locked(manager)
        result = {
            "normalized_changed": bool(normalized_changed),
            "weighted_before": before_weighted,
            "weighted_after": len(manager.weighted_memories),
            "short_term_before": before_short,
            "short_term_after": len(manager.short_term_memory),
            **dedupe_stats,
            "field_policy": get_memory_field_policy(),
        }
        manager.last_modified_time = time.time()
        should_save = bool(
            normalized_changed
            or dedupe_stats.get("duplicates_removed", 0) > 0
            or dedupe_stats.get("short_term_changed", False)
            or before_weighted != len(manager.weighted_memories)
            or before_short != len(manager.short_term_memory)
        )
    if dry_run:
        return result
    if should_save:
        if sync_save:
            manager.sync_save_memory()
        else:
            manager.save_memory()
    return result


def build_weighted_readable_views(manager: Any) -> Dict[str, Any]:
    records: List[Dict[str, Any]] = []
    # 快照迭代：防止并发写入 weighted_memories 时触发
    # "dictionary changed size during iteration"
    for memory in list(manager.weighted_memories.values()):
        normalized, _ = normalize_memory_record(manager, memory)
        records.append(normalized)

    records.sort(
        key=lambda item: (
            float(item.get("timestamp") or 0.0),
            float(item.get("weight") or 0.0),
        ),
        reverse=True,
    )

    by_type: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    topic_map: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    category_stats: Dict[str, int] = defaultdict(int)
    status_stats: Dict[str, int] = defaultdict(int)

    compact_records: List[Dict[str, Any]] = []
    for record in records:
        compact = {
            "id": str(record.get("id") or ""),
            "memory_type": str(record.get("memory_type") or "dialogue"),
            "category": str(record.get("category") or "uncategorized"),
            "status": str(record.get("status") or "active"),
            "weight": round(float(record.get("weight") or 0.0), 3),
            "timestamp": float(record.get("timestamp") or 0.0),
            "last_hit_time": float(record.get("last_hit_time") or 0.0),
            "readable_title": str(record.get("readable_title") or ""),
            "readable_summary": str(record.get("readable_summary") or ""),
            "display_tags": list(record.get("display_tags") or [])[:READABLE_TAG_LIMIT],
            "topics": list(record.get("topics") or [])[:READABLE_TAG_LIMIT],
            "source": str(record.get("source") or "chat"),
            "source_ref": record.get("source_ref") or {},
        }
        compact_records.append(compact)
        by_type[compact["memory_type"]].append(compact)
        category_stats[compact["category"]] += 1
        status_stats[compact["status"]] += 1
        for topic in compact["topics"]:
            topic_text = str(topic).strip()
            if not topic_text or topic_text.lower() in {"chat", "其他", "other"}:
                continue
            topic_map[topic_text].append(compact)

    by_type_payload = {
        "conversation_id": manager.user_id,
        "groups": {
            key: {
                "count": len(items),
                "items": items[:50],
            }
            for key, items in sorted(
                by_type.items(),
                key=lambda item: (-len(item[1]), item[0]),
            )
        },
    }

    top_topic_items = sorted(
        topic_map.items(),
        key=lambda item: (-len(item[1]), item[0]),
    )[:50]
    by_topic_payload = {
        "conversation_id": manager.user_id,
        "groups": [
            {
                "topic": topic,
                "count": len(items),
                "items": items[:20],
            }
            for topic, items in top_topic_items
        ],
    }

    timeline_payload = {
        "conversation_id": manager.user_id,
        "items": compact_records[:200],
    }

    summary_payload = {
        "conversation_id": manager.user_id,
        "total_memories": len(compact_records),
        "field_policy": get_memory_field_policy(),
        "memory_type_distribution": {
            key: len(items) for key, items in sorted(by_type.items(), key=lambda item: item[0])
        },
        "category_distribution": dict(sorted(category_stats.items(), key=lambda item: item[0])),
        "status_distribution": dict(sorted(status_stats.items(), key=lambda item: item[0])),
        "top_topics": [
            {"topic": topic, "count": len(items)}
            for topic, items in top_topic_items[:10]
        ],
    }
    return {
        "all": compact_records,
        "by_type": by_type_payload,
        "by_topic": by_topic_payload,
        "timeline": timeline_payload,
        "summary": summary_payload,
    }
