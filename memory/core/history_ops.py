from typing import Any, Dict, List, Optional

from core.services.chat_history_store import get_chat_history_store
from memory.core.lock_utils import get_read_lock


async def get_recent_history(
    manager: Any,
    *,
    session_id: Optional[str] = None,
    limit: int = 100,
    allowed_categories: Optional[List[str]] = None,
    before: Optional[float] = None,
) -> List[Dict[str, Any]]:
    with get_read_lock(manager):
        all_memory = manager.short_term_memory + list(manager.weighted_memories.values())
        unique_memory = {m["id"]: m for m in all_memory}
        sorted_memory = sorted(unique_memory.values(), key=lambda x: x.get("timestamp", 0))

        result = []
        for msg in sorted_memory:
            if not msg.get("content"):
                continue
            if allowed_categories is not None:
                msg_category = msg.get("category")
                effective_category = msg_category if msg_category else "chat"
                if (
                    effective_category != "global_fact"
                    and effective_category not in allowed_categories
                ):
                    continue

            entry = {
                "role": msg.get("role") or msg.get("source", "assistant"),
                "content": msg.get("content", ""),
                "timestamp": msg.get("timestamp", 0),
                "id": msg.get("id", ""),
                "is_important": msg.get("is_important", False),
                "category": msg.get("category"),
            }
            meta = msg.get("metadata")
            if isinstance(meta, dict) and meta:
                for k in (
                    "image_url",
                    "image_base64",
                    "image_path",
                    "audio_base64",
                    "audio_path",
                    "voice_id",
                    "message_type",
                    "image_prompt",
                ):
                    if k in meta:
                        entry[k] = meta.get(k)
            result.append(entry)

        deduped: List[Dict[str, Any]] = []
        last_seen_ts: Dict[tuple, float] = {}
        for entry in result:
            role = entry.get("role")
            content = entry.get("content")
            ts = float(entry.get("timestamp", 0) or 0)
            key = (role, content)
            prev_ts = last_seen_ts.get(key)
            if prev_ts is not None and abs(ts - prev_ts) <= 8.0:
                continue
            deduped.append(entry)
            last_seen_ts[key] = ts
        result = deduped

        if before is not None:
            result = [
                entry for entry in result if float(entry.get("timestamp", 0) or 0) < before
            ]
        if len(result) > limit:
            return result[-limit:]
        return result


async def get_event_history(
    manager: Any,
    *,
    conversation_id: Optional[str] = None,
    limit: int = 100,
    before: Optional[float] = None,
    query: Optional[str] = None,
    roles: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    target_conversation_id = str(
        conversation_id or getattr(manager, "user_id", "default") or "default"
    ).strip() or "default"
    store = get_chat_history_store()
    items = store.list_conversation_events(
        target_conversation_id,
        limit=limit,
        before=before,
        query=query,
        roles=roles,
    )
    result: List[Dict[str, Any]] = []
    for item in items:
        metadata = item.get("metadata") if isinstance(item, dict) else {}
        result.append(
            {
                "event_id": str(item.get("event_id") or ""),
                "conversation_id": str(item.get("conversation_id") or target_conversation_id),
                "role": str(item.get("role") or "system"),
                "content": str(item.get("content") or ""),
                "timestamp": float(item.get("timestamp") or 0.0),
                "event_type": str(item.get("event_type") or "message"),
                "source_layer": "event_history",
                "storage_scope": str(item.get("storage_scope") or ""),
                "metadata": metadata if isinstance(metadata, dict) else {},
            }
        )
    return result
