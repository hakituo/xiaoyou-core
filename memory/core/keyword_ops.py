from typing import Any, Dict, List, Optional

from memory.core.keyword_index import (
    rebuild_keyword_index,
    remove_memory_from_keyword_index,
    upsert_memory_keywords,
)
from memory.core.preferences import (
    get_active_preferences,
    rebuild_preference_index_locked,
)
from memory.core.lock_utils import get_read_lock, get_write_lock


def ensure_keyword_index_ready(manager: Any) -> None:
    with get_write_lock(manager):
        if (
            manager._keyword_force_rebuild
            or manager._index_updated
            or (
                not manager._keyword_index
                and isinstance(manager.weighted_memories, dict)
                and manager.weighted_memories
            )
        ):
            manager._refresh_keyword_index_locked()


def mark_keyword_index_dirty_locked(manager: Any, memory_id: str) -> None:
    mid = str(memory_id or "").strip()
    if not mid:
        return
    manager._keyword_dirty_ids.add(mid)
    manager._index_updated = True


def request_keyword_index_rebuild_locked(manager: Any) -> None:
    manager._keyword_force_rebuild = True
    manager._keyword_dirty_ids.clear()
    manager._index_updated = True


def rebuild_preference_index_for_manager(manager: Any) -> None:
    rebuild_preference_index_locked(manager.preference_index, manager.weighted_memories)


def rebuild_keyword_index_locked(manager: Any, *, logger: Any) -> None:
    (
        manager._keyword_index,
        manager._keyword_graph,
        manager._memory_keyword_sets,
        manager._memory_keyword_pairs,
    ) = rebuild_keyword_index(manager.weighted_memories, manager._extract_keywords)

    logger.debug(f"关键词索引已更新，包含 {len(manager._keyword_index)} 个关键词")
    manager._rebuild_preference_index_locked()


def remove_memory_from_keyword_index_locked(
    manager: Any,
    memory_id: str,
    memory: Optional[Dict[str, Any]] = None,
) -> None:
    remove_memory_from_keyword_index(
        memory_id,
        memory,
        manager._keyword_index,
        manager._keyword_graph,
        manager._memory_keyword_sets,
        manager._memory_keyword_pairs,
        manager._extract_keywords,
    )

    mid = str(memory_id or "").strip()
    if not mid:
        return
    for key, value in list(manager.preference_index.items()):
        if value == mid:
            manager.preference_index.pop(key, None)


def upsert_memory_keywords_locked(manager: Any, memory_id: str, memory: Dict[str, Any]) -> None:
    mid = str(memory_id or "").strip()
    if not mid:
        return

    upsert_memory_keywords(
        mid,
        memory,
        manager._keyword_index,
        manager._keyword_graph,
        manager._memory_keyword_sets,
        manager._memory_keyword_pairs,
        manager._extract_keywords,
    )

    if memory.get("memory_type") == "preference":
        if memory.get("status") == "active":
            meta = memory.get("metadata")
            if isinstance(meta, dict):
                key = meta.get("preference_key")
                if isinstance(key, str) and key.strip():
                    manager.preference_index[key.strip().lower()] = mid
        else:
            for key, value in list(manager.preference_index.items()):
                if value == mid:
                    manager.preference_index.pop(key, None)


def refresh_keyword_index_locked(manager: Any) -> None:
    if manager._keyword_force_rebuild or (
        not manager._keyword_index
        and isinstance(manager.weighted_memories, dict)
        and manager.weighted_memories
    ):
        manager._rebuild_keyword_index_locked()
        manager._keyword_force_rebuild = False
        manager._keyword_dirty_ids.clear()
        manager._index_updated = False
        return

    if not manager._index_updated:
        return

    if not manager._keyword_dirty_ids:
        manager._rebuild_keyword_index_locked()
        manager._keyword_force_rebuild = False
        manager._index_updated = False
        return

    dirty_ids = list(manager._keyword_dirty_ids)
    manager._keyword_dirty_ids.clear()

    for mid in dirty_ids:
        mem = manager.weighted_memories.get(mid)
        if mem is None:
            manager._remove_memory_from_keyword_index_locked(mid)
            continue
        manager._upsert_memory_keywords_locked(mid, mem)

    manager._index_updated = False


def update_keyword_index(manager: Any) -> None:
    with get_write_lock(manager):
        manager._refresh_keyword_index_locked()


def expand_keywords(manager: Any, keywords: List[str], top_k: int = 3) -> List[str]:
    if not keywords:
        return []
    base = [k.strip().lower() for k in keywords if isinstance(k, str) and k.strip()]
    expanded = set(base)
    with get_read_lock(manager):
        for keyword in base:
            rel = manager._keyword_graph.get(keyword)
            if not isinstance(rel, dict) or not rel:
                continue
            sorted_rel = sorted(rel.items(), key=lambda item: item[1], reverse=True)[:top_k]
            for related_keyword, _ in sorted_rel:
                if isinstance(related_keyword, str) and related_keyword.strip():
                    expanded.add(related_keyword.strip().lower())
    return list(expanded)


def get_active_preferences_view(manager: Any) -> Dict[str, Any]:
    with get_read_lock(manager):
        return get_active_preferences(manager.preference_index, manager.weighted_memories)


def normalize_category_dir(category: str | None) -> str:
    name = str(category or "").strip()
    if not name:
        return "unknown"
    invalid_chars = '<>:"/\\|?*'
    safe = "".join(char for char in name if char not in invalid_chars).strip().rstrip(".")
    if not safe:
        return "unknown"
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update({f"COM{i}" for i in range(1, 10)})
    reserved.update({f"LPT{i}" for i in range(1, 10)})
    if safe.upper() in reserved:
        return f"_{safe}"
    return safe
