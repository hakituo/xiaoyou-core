from collections import defaultdict
from typing import Any, Dict, Optional

from memory.core.retrieval_ops import invalidate_top_topics_cache
from memory.core.lock_utils import get_write_lock


def _invalidate(manager: Any) -> None:
    invalidate_top_topics_cache(manager)


def update_memory_weight(
    manager: Any, memory_id: str, weight_delta: float, *, logger: Any, time_module: Any
) -> bool:
    with get_write_lock(manager):
        if memory_id not in manager.weighted_memories:
            logger.warning(f"记忆ID不存在: {memory_id}")
            return False
        memory = manager.weighted_memories[memory_id]
        new_weight = max(0.1, memory["weight"] + weight_delta)
        memory["weight"] = round(new_weight, 2)
        memory["last_access_time"] = time_module.time()
        manager.last_modified_time = time_module.time()
        _invalidate(manager)
        logger.info(f"已更新记忆权重，ID: {memory_id}, 新权重: {new_weight}")
        return True


def set_memory_important(
    manager: Any, memory_id: str, important: bool, *, logger: Any, time_module: Any
) -> bool:
    """标记/取消标记记忆为重要。

    重要记忆会进入 important_prompts 层，并在权重计算时获得加成。
    """
    need_save = False
    with get_write_lock(manager):
        if memory_id not in manager.weighted_memories:
            logger.warning(f"标记重要失败: 记忆ID不存在: {memory_id}")
            return False
        memory = manager.weighted_memories[memory_id]
        old_val = bool(memory.get("is_important", False))
        if old_val == important:
            return True  # 无变化
        memory["is_important"] = important
        memory["last_access_time"] = time_module.time()
        manager.last_modified_time = time_module.time()
        _invalidate(manager)
        logger.info(f"已{'标记' if important else '取消'}记忆重要: {memory_id}")
        need_save = True
    if need_save:
        manager.save_memory()
    return True


def delete_memory(
    manager: Any, memory_id: str, *, logger: Any, time_module: Any
) -> bool:
    need_save = False
    with get_write_lock(manager):
        if memory_id not in manager.weighted_memories:
            logger.warning(f"删除失败: 记忆ID不存在: {memory_id}")
            return False
        memory = manager.weighted_memories[memory_id]
        category = memory.get("category", "uncategorized")
        if hasattr(manager, "content_dedupe_index"):
            raw = str(memory.get("content", ""))
            norm_content = " ".join(raw.strip().lower().split())
            src_key = str(memory.get("source", "")).strip().lower()
            cat_key = str(category).strip().lower() or "uncategorized"
            dedupe_key = f"{norm_content}\x00{src_key}\x00{cat_key}"
            if manager.content_dedupe_index.get(dedupe_key) == memory_id:
                del manager.content_dedupe_index[dedupe_key]
        del manager.weighted_memories[memory_id]
        if category in manager.category_index:
            if memory_id in manager.category_index[category]:
                manager.category_index[category].remove(memory_id)
        uc = getattr(manager, '_unified_cache', None)
        if uc is not None:
            uc.invalidate_memory(memory_id)
        else:
            if memory_id in manager._cache["l1"]:
                del manager._cache["l1"][memory_id]
            if memory_id in manager._cache["l2"]:
                del manager._cache["l2"][memory_id]
        if memory_id in manager._cache["access_count"]:
            del manager._cache["access_count"][memory_id]
        manager.last_modified_time = time_module.time()
        manager._request_keyword_index_rebuild_locked()
        _invalidate(manager)
        if category == "preference":
            manager._rebuild_preference_index_locked()
        logger.info(f"已删除加权记忆: {memory_id}")
        need_save = True
    if need_save:
        manager.save_memory()
    return need_save


def access_memory(
    manager: Any,
    memory_id: str,
    importance: int = 1,
    *,
    logger: Any,
    time_module: Any,
) -> Optional[Dict[str, Any]]:
    with get_write_lock(manager):
        cached_memory = manager._get_from_cache(memory_id)
        if cached_memory:
            cached_memory["weight"] = manager.weight_calculator.update_weight_by_access(
                cached_memory["weight"], importance
            )
            cached_memory["last_access_time"] = time_module.time()
            if memory_id in manager.weighted_memories:
                wm = manager.weighted_memories[memory_id]
                wm["weight"] = cached_memory["weight"]
                wm["last_access_time"] = cached_memory[
                    "last_access_time"
                ]
            manager.last_modified_time = time_module.time()
            manager._update_cache(memory_id, cached_memory)
            logger.debug(
                f"已从缓存访问记忆，ID: {memory_id}, 新权重: {cached_memory['weight']}"
            )
            return cached_memory

        if memory_id not in manager.weighted_memories:
            logger.warning(f"记忆ID不存在: {memory_id}")
            return None
        memory = manager.weighted_memories[memory_id]
        memory["weight"] = manager.weight_calculator.update_weight_by_access(
            memory["weight"], importance
        )
        memory["last_access_time"] = time_module.time()
        manager.last_modified_time = time_module.time()
        manager._update_cache(memory_id, memory)
        logger.debug(f"已访问记忆，ID: {memory_id}, 新权重: {memory['weight']}")
        return memory.copy()


def clear_all_memories(manager: Any, *, logger: Any) -> None:
    with get_write_lock(manager):
        manager.short_term_memory = []
        manager.weighted_memories = {}
        if hasattr(manager, "content_dedupe_index"):
            manager.content_dedupe_index = {}
        manager.topics = defaultdict(list)
        manager.user_preferences = {}
        manager.preference_index = {}
        manager.important_prompts = []
        manager.topic_weights = defaultdict(float)
        manager.emotion_memory_map = defaultdict(list)
        uc = getattr(manager, '_unified_cache', None)
        if uc is not None:
            uc.clear_all()
        manager._cache["l1"].clear()
        manager._cache["l2"].clear()
        manager._cache["access_count"] = {}
        manager._keyword_index = defaultdict(list)
        manager._keyword_graph = defaultdict(dict)
        manager._index_updated = False
        _invalidate(manager)
        logger.info(f"User {manager.user_id} memory fully cleared.")
    manager.save_memory()


def delete_message(manager: Any, message_id: str, *, logger: Any) -> bool:
    need_save = False
    with get_write_lock(manager):
        deleted = False
        removed_weighted_ids = set()
        original_len = len(manager.short_term_memory)
        manager.short_term_memory = [
            m
            for m in manager.short_term_memory
            if m.get("id") != message_id and m.get("message_id") != message_id
        ]
        if len(manager.short_term_memory) < original_len:
            deleted = True
        if message_id in manager.weighted_memories:
            mem = manager.weighted_memories.get(message_id)
            if isinstance(mem, dict):
                manager._remove_memory_from_keyword_index_locked(message_id, mem)
                cat = mem.get("category")
                if isinstance(cat, str) and cat in manager.category_index:
                    try:
                        while message_id in manager.category_index[cat]:
                            manager.category_index[cat].remove(message_id)
                    except ValueError:
                        pass
            del manager.weighted_memories[message_id]
            removed_weighted_ids.add(message_id)
            deleted = True
        else:
            keys_to_remove = []
            for k, v in manager.weighted_memories.items():
                if v.get("message_id") == message_id:
                    keys_to_remove.append(k)
            for k in keys_to_remove:
                mem = manager.weighted_memories.get(k)
                if isinstance(mem, dict):
                    manager._remove_memory_from_keyword_index_locked(k, mem)
                    cat = mem.get("category")
                    if isinstance(cat, str) and cat in manager.category_index:
                        try:
                            while k in manager.category_index[cat]:
                                manager.category_index[cat].remove(k)
                        except ValueError:
                            pass
                del manager.weighted_memories[k]
                removed_weighted_ids.add(k)
                deleted = True
        original_len = len(manager.important_prompts)
        manager.important_prompts = [
            m
            for m in manager.important_prompts
            if m.get("id") != message_id and m.get("message_id") != message_id
        ]
        if len(manager.important_prompts) < original_len:
            deleted = True
        if deleted:
            if removed_weighted_ids:
                for emotion, entries in list(manager.emotion_memory_map.items()):
                    manager.emotion_memory_map[emotion] = [
                        entry
                        for entry in entries
                        if str((entry or {}).get("memory_id") or "")
                        not in removed_weighted_ids
                    ]
            logger.info(f"已删除记忆: {message_id}")
            need_save = True
    if need_save:
        manager.save_memory()
        return True
    return False
