import json
import time
import logging
from pathlib import Path
from typing import Any, Dict, List

from core.utils.conversation_labels import get_conversation_label_info
from core.services.chat_history_store import get_chat_history_store


logger = logging.getLogger(__name__)


READABLE_HISTORY_FILES = (
    "short_term.json",
    "weighted_all.json",
    "weighted_by_type.json",
    "weighted_by_topic.json",
    "weighted_timeline.json",
    "weighted_summary.json",
)

# short_term 是可恢复的近期上下文窗口，不是完整记忆对象镜像。
# 派生的可读字段会在加载时由 normalize_memory_record 重建。
SHORT_TERM_DISK_FIELDS = (
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
SHORT_TERM_METADATA_FIELDS = (
    "event_ref",
    "message_id",
    "platform",
    "is_proactive",
    "is_peer_script",
    "peer_speaker",
    "original_source",
    "type",
)
SHORT_TERM_DISK_MAX_BYTES = 64 * 1024


def get_readable_history_dir(manager: Any) -> Path:
    info = get_conversation_label_info(manager.user_id)
    return manager.readable_history_root / str(info.get("safe_persona") or "default") / str(
        info.get("safe_lane") or "main"
    )


def write_readable_history_index(manager: Any) -> None:
    try:
        base = manager.readable_history_root
        base.mkdir(parents=True, exist_ok=True)
        entries = []
        for persona_dir in sorted([p for p in base.iterdir() if p.is_dir()], key=lambda p: p.name):
            for lane_dir in sorted([p for p in persona_dir.iterdir() if p.is_dir()], key=lambda p: p.name):
                files = sorted([p.name for p in lane_dir.glob("*.json")])
                entries.append(
                    {
                        "persona": persona_dir.name,
                        "lane": lane_dir.name,
                        "relative_path": lane_dir.relative_to(manager.memory_dir).as_posix(),
                        "files": files,
                    }
                )
        index_path = base / "index.json"
        manager._safe_json_dump({"entries": entries}, str(index_path))
    except Exception as e:
        logger.warning(f"写入可读历史索引失败: {e}")


def build_short_term_disk_records(
    manager: Any,
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    compact_records: List[Dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        normalized, _ = manager._normalize_memory_record(dict(msg))
        record = {
            field: normalized[field]
            for field in SHORT_TERM_DISK_FIELDS
            if field in normalized
        }
        metadata = normalized.get("metadata")
        if isinstance(metadata, dict):
            compact_meta = {
                field: metadata[field]
                for field in SHORT_TERM_METADATA_FIELDS
                if field in metadata
            }
            if compact_meta:
                record["metadata"] = compact_meta
        compact_records.append(record)

    # 条数上限无法约束超长消息和元数据造成的文件膨胀；落盘窗口同时限制为 64 KiB。
    # 完整内容已经由 ChatHistoryStore 保存，因此这里只从最旧记录开始缩短窗口。
    while len(compact_records) > 1:
        payload_size = len(
            json.dumps(compact_records, ensure_ascii=False, indent=2).encode("utf-8")
        )
        if payload_size <= SHORT_TERM_DISK_MAX_BYTES:
            break
        compact_records.pop(0)
    return compact_records


def hydrate_short_term_records(
    manager: Any,
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    hydrated: List[Dict[str, Any]] = []
    history_store = get_chat_history_store()
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        record = dict(msg)
        content = str(record.get("content") or "")
        metadata = record.get("metadata")
        event_ref = metadata.get("event_ref") if isinstance(metadata, dict) else None
        if (not content) and isinstance(event_ref, dict):
            loaded_content = history_store.get_event_content(event_ref)
            if loaded_content is not None:
                record["content"] = loaded_content
        record, _ = manager._normalize_memory_record(record)
        hydrated.append(record)
    return hydrated


def compact_weighted_memory_record(manager: Any, memory: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(memory, dict):
        return memory
    record, _ = manager._normalize_memory_record(memory)
    record.pop("embedding", None)
    record.pop("embedding_base64", None)
    for derived_field in (
        "source_ref",
        "readable_summary",
        "readable_title",
        "display_tags",
        "keywords",
        "last_hit_time",
    ):
        record.pop(derived_field, None)
    content_text = str(record.get("content") or "").strip()
    if content_text.startswith("【历史摘要】"):
        record["content"] = ""
        metadata = record.get("metadata")
        if isinstance(metadata, dict):
            compact_meta = dict(metadata)
            compact_meta["readable_hidden"] = True
            record["metadata"] = compact_meta
    metadata = record.get("metadata")
    event_ref = metadata.get("event_ref") if isinstance(metadata, dict) else None
    if isinstance(metadata, dict):
        compact_meta = dict(metadata)
        for runtime_field in (
            "reply_content",
            "thought",
            "reasoning_content",
            "model_hint",
            "trace_id",
            "thought_source",
            "defer_analysis",
        ):
            compact_meta.pop(runtime_field, None)
        record["metadata"] = compact_meta
    if isinstance(event_ref, dict) and event_ref.get("event_id"):
        record["content"] = ""
    return record


def hydrate_weighted_memory_record(manager: Any, memory: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(memory, dict):
        return memory
    record = dict(memory)
    content = str(record.get("content") or "")
    metadata = record.get("metadata")
    event_ref = metadata.get("event_ref") if isinstance(metadata, dict) else None
    if (not content) and isinstance(event_ref, dict):
        loaded_content = get_chat_history_store().get_event_content(event_ref)
        if loaded_content is not None:
            record["content"] = loaded_content
    normalized, _ = manager._normalize_memory_record(record)
    return normalized


def write_readable_history_mirror(manager: Any) -> None:
    try:
        readable_dir = get_readable_history_dir(manager)
        readable_dir.mkdir(parents=True, exist_ok=True)

        short_records = build_short_term_disk_records(manager, manager.short_term_memory)
        manager._safe_json_dump(short_records, str(readable_dir / "short_term.json"))

        weighted_records = [
            compact_weighted_memory_record(manager, memory)
            for memory in list(manager.weighted_memories.values())
        ]
        readable_views = manager._build_weighted_readable_views()
        weighted_payload = {
            "conversation_id": manager.user_id,
            "readable_title": get_conversation_label_info(manager.user_id).get("readable_title"),
            "weighted_memories": weighted_records,
            "last_updated": time.time(),
        }
        manager._safe_json_dump(weighted_payload, str(readable_dir / "weighted_all.json"))
        manager._safe_json_dump(readable_views["by_type"], str(readable_dir / "weighted_by_type.json"))
        manager._safe_json_dump(readable_views["by_topic"], str(readable_dir / "weighted_by_topic.json"))
        manager._safe_json_dump(readable_views["timeline"], str(readable_dir / "weighted_timeline.json"))
        manager._safe_json_dump(readable_views["summary"], str(readable_dir / "weighted_summary.json"))
        write_readable_history_index(manager)
    except Exception as e:
        logger.warning(f"写入可读历史镜像失败: {e}")


def remove_readable_history_files(manager: Any) -> None:
    try:
        readable_dir = get_readable_history_dir(manager)
        for child in READABLE_HISTORY_FILES:
            path = readable_dir / child
            if path.exists():
                path.unlink()
    except Exception:
        pass
