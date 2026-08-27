from __future__ import annotations

import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from memory.core.text_segmenter import segment_keyphrase


def extract_preference_updates(content: str) -> List[Dict[str, Any]]:
    text = str(content or "").strip()
    if not text:
        return []

    patterns = [
        (
            r"(?:我|本人|自己)\s*(?:很|更|特别|最)?\s*(喜欢|爱)\s*([^，。,.!！？\n]{1,20})",
            True,
        ),
        (
            r"(?:我|本人|自己)\s*(?:很|更|特别|最)?\s*(不喜欢|不爱|讨厌)\s*([^，。,.!！？\n]{1,20})",
            False,
        ),
        (
            r"(?:我|本人|自己)\s*(?:现在|最近|已经|改成)\s*(喜欢|爱)\s*([^，。,.!！？\n]{1,20})",
            True,
        ),
        (
            r"(?:我|本人|自己)\s*(?:现在|最近|已经|不再|戒了|改成)\s*(不喜欢|不爱|讨厌)\s*([^，。,.!！？\n]{1,20})",
            False,
        ),
    ]

    updates: List[Dict[str, Any]] = []
    for pattern, polarity in patterns:
        for m in re.finditer(pattern, text):
            raw_key = (m.group(2) or "").strip()
            if not raw_key:
                continue
            key = re.sub(r"\s+", " ", raw_key)
            segmented = segment_keyphrase(key)
            if len(segmented) < 1:
                continue
            if len(key) > 20:
                key = key[:20]
            if len(segmented) > 20:
                segmented = segmented[:20]
            updates.append({"key": segmented.lower(), "polarity": polarity, "_raw_key": key.lower()})

    dedup: Dict[tuple, Dict[str, Any]] = {}
    for u in updates:
        dedup[(u["key"], bool(u["polarity"]))] = u
    return list(dedup.values())


def rebuild_preference_index_locked(
    preference_index: Dict[str, str],
    weighted_memories: Dict[str, Dict[str, Any]],
):
    preference_index.clear()
    for mid, mem in weighted_memories.items():
        if mem.get("memory_type") != "preference":
            continue
        if mem.get("status") != "active":
            continue
        meta = mem.get("metadata")
        if not isinstance(meta, dict):
            continue
        k = meta.get("preference_key")
        if isinstance(k, str) and k.strip():
            preference_index[k.strip().lower()] = mid


def upsert_preference_locked(
    *,
    key: str,
    polarity: bool,
    source_memory_id: str,
    timestamp: float,
    weighted_memories: Dict[str, Dict[str, Any]],
    category_index: Dict[str, List[str]],
    preference_index: Dict[str, str],
    calculate_initial_weight: Callable[[str, bool, List[str], List[str]], float],
    mark_keyword_index_dirty: Callable[[str], None],
    normalize_memory_record: Optional[Callable[[Dict[str, Any]], tuple[Dict[str, Any], bool]]] = None,
    vector_search_enabled: bool,
    generate_embedding: Optional[Callable[[str], Any]] = None,
    embedding_to_base64: Optional[Callable[[Any], str]] = None,
) -> Optional[str]:
    k = str(key or "").strip()
    if not k:
        return None

    k = k.lower()
    memory_id = str(uuid.uuid4())

    prev_id = preference_index.get(k)
    if prev_id and prev_id in weighted_memories:
        prev = weighted_memories[prev_id]
        prev["status"] = "superseded"
        prev_meta = prev.get("metadata")
        if not isinstance(prev_meta, dict):
            prev_meta = {}
            prev["metadata"] = prev_meta
        prev_meta["superseded_by"] = memory_id

    content = f"偏好：{'喜欢' if polarity else '不喜欢'} {k}"
    topics = ["preference", k]
    emotions = ["neutral"]
    weight = max(7.5, calculate_initial_weight(content, True, topics, emotions))

    pref_memory = {
        "id": memory_id,
        "content": content,
        "timestamp": timestamp,
        "last_access_time": time.time(),
        "weight": weight,
        "topics": topics,
        "emotions": emotions,
        "emotion": "neutral",
        "is_important": True,
        "source": "system",
        "role": "system",
        "category": "preference",
        "summary": content,
        "keywords": [k.lower()],
        "is_distilled": True,
        "memory_type": "preference",
        "status": "active",
        "metadata": {
            "preference_key": k,
            "polarity": bool(polarity),
            "source_memory_id": source_memory_id,
        },
        "scopes": ["local", "cloud"],
        "embedding": None,
    }

    if vector_search_enabled and generate_embedding and embedding_to_base64:
        try:
            embedding = generate_embedding(content)
            pref_memory["embedding"] = embedding_to_base64(embedding)
        except Exception:
            pass

    if normalize_memory_record:
        pref_memory, _ = normalize_memory_record(pref_memory)

    weighted_memories[memory_id] = pref_memory
    category_index.setdefault("preference", []).append(memory_id)
    preference_index[k] = memory_id
    mark_keyword_index_dirty(memory_id)
    return memory_id


def get_active_preferences(
    preference_index: Dict[str, str],
    weighted_memories: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for k, mid in preference_index.items():
        mem = weighted_memories.get(mid)
        if not mem:
            continue
        if mem.get("status") != "active":
            continue
        meta = mem.get("metadata")
        if isinstance(meta, dict):
            result[k] = {
                "polarity": bool(meta.get("polarity")),
                "timestamp": float(mem.get("timestamp", 0) or 0),
                "memory_id": mid,
            }
    return result
