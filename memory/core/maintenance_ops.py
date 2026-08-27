from typing import Any

from memory.core.lock_utils import get_write_lock
from memory.core.record_ops import rebuild_memory_indexes_locked


def reclassify_all_memories(manager: Any, *, logger: Any) -> None:
    if getattr(manager, "skip_auto_reclassify", False):
        logger.debug("跳过自动重分类 (skip_auto_reclassify=True)")
        return
    logger.info("开始重新分类和清理所有记忆...")
    count = 0

    with get_write_lock(manager):
        weighted_modified = False
        keys_to_remove = set()
        for memory_id, memory in manager.weighted_memories.items():
            content = memory.get("content", "")
            if not content:
                keys_to_remove.add(memory_id)
                weighted_modified = True
                continue
            current_category = memory.get("category")
            classified_category = manager._classify_category(content)
            if not current_category or (
                current_category == "uncategorized"
                and classified_category != "uncategorized"
            ):
                memory["category"] = classified_category
                if classified_category and classified_category not in memory.get("topics", []):
                    memory.setdefault("topics", []).append(classified_category)
                count += 1
                weighted_modified = True
            new_topics = manager._detect_topics(content)
            current_topics = memory.get("topics", [])
            if (
                not current_topics
                or (len(new_topics) > 0 and "其他" in current_topics)
                or (len(new_topics) > len(current_topics))
            ):
                memory["topics"] = new_topics
                count += 1
                weighted_modified = True
            if "emotion" not in memory:
                memory["emotion"] = manager._detect_emotion(content)
                weighted_modified = True
            weight = memory.get("weight", 0)
            if not memory.get("is_important", False) and weight <= 4.5:
                keys_to_remove.add(memory_id)
                count += 1
                weighted_modified = True
                continue
            if hasattr(manager, "_normalize_memory_record"):
                normalized, normalized_changed = manager._normalize_memory_record(memory)
                manager.weighted_memories[memory_id] = normalized
                if normalized_changed:
                    count += 1
                    weighted_modified = True

        for k in keys_to_remove:
            manager._remove_memory_from_keyword_index_locked(k, manager.weighted_memories.get(k))
            manager.weighted_memories.pop(k, None)
        if keys_to_remove:
            logger.info(f"权重记忆清理完成，移除了 {len(keys_to_remove)} 条低权重记忆")

        merged_messages = list(manager.short_term_memory)
        if manager.weighted_memories:
            merged_messages.extend(manager.weighted_memories.values())
        for msg in merged_messages:
            msg_id = msg.get("id")
            if not msg_id:
                continue
            content = msg.get("content", "")
            if not content:
                continue
            msg_category = msg.get("category")
            if not msg_category:
                msg_category = manager._classify_category(content)
                msg["category"] = msg_category
                if msg_category and msg_category not in msg.get("topics", []):
                    msg.setdefault("topics", []).append(msg_category)
                count += 1
            msg_topics = msg.get("topics", [])
            is_sensitive = msg_category == "sensitive" or (
                isinstance(msg_topics, list) and "sensitive" in msg_topics
            )
            if is_sensitive:
                continue
            msg_weight = msg.get("weight")
            if msg_weight is None:
                msg_weight = manager.weight_calculator.calculate_initial_weight(
                    content,
                    msg.get("is_important", False),
                    msg.get("topics", []),
                    msg.get("emotions", []),
                )
                msg["weight"] = msg_weight
                count += 1
            should_store_weighted = (
                msg.get("is_important", False)
                or (msg_category and msg_category != "uncategorized")
                or msg_weight > 4.5
            )
            if hasattr(manager, "_normalize_memory_record"):
                normalized_msg, normalized_changed = manager._normalize_memory_record(msg)
                if normalized_changed:
                    msg.clear()
                    msg.update(normalized_msg)
                    count += 1
            if should_store_weighted and msg_id not in manager.weighted_memories:
                manager.weighted_memories[msg_id] = msg
                count += 1
                weighted_modified = True

        # 重分类可能新增、删除或修改记录，所有派生索引必须从最终集合重建。
        # 只刷新 category/topic 会让 emotion_memory_map 继续引用已删除 ID。
        rebuild_memory_indexes_locked(manager)

        if weighted_modified:
            manager._request_keyword_index_rebuild_locked()

    if count > 0:
        logger.info(f"记忆重新分类和清理完成，更新了 {count} 条")
        manager.save_memory()
    else:
        logger.info("记忆重新分类完成，无需更新")
