"""WeightedMemoryManager 的记忆写入与变更操作。"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from memory.core.maintenance_ops import reclassify_all_memories as reclassify_all_memories_impl
from memory.core.mutation_ops import (
    access_memory as access_memory_impl,
    clear_all_memories as clear_all_memories_impl,
    delete_memory as delete_memory_impl,
    delete_message as delete_message_impl,
    set_memory_important as set_memory_important_impl,
    update_memory_weight as update_memory_weight_impl,
)
from memory.core.storage import MemoryContext, _add_memory_core
from memory.core.vector_ops import decode_embedding_to_list


class WeightedManagerWriteMixin:
    """单条记忆写入、修改与删除职责。"""

    def add_memory(
        self,
        content: str = "",
        topics: List[str] = None,
        emotions: List[str] = None,
        is_important: bool = False,
        source: str = "chat",
        category: str = None,
        metadata: Dict[str, Any] = None,
        scopes: Optional[List[str]] = None,
        is_sensitive_mode: bool = False,
        *,
        input: Optional[Any] = None,
        **legacy_kwargs: Any,
    ) -> str:
        """添加带权重的记忆，兼容散装参数与 ``MemoryInput``。"""
        from memory.core.storage import MemoryInput

        if input is not None and isinstance(input, MemoryInput):
            inp = input
        else:
            inp = MemoryInput(
                content=content,
                topics=topics,
                emotions=emotions,
                is_important=is_important,
                source=source,
                category=category,
                metadata=metadata,
                scopes=scopes,
                user_id=self.user_id,
                is_sensitive_mode=is_sensitive_mode,
            )

        lock_context = self._rw_lock.write_lock() if self._use_rw_lock else self.lock
        need_save = False
        with lock_context:
            self._perf_stats["rw_lock_writes"] += 1
            generator = self._embedding_generator
            generate_embedding = getattr(generator, "generate_embedding", None)
            embedding_to_base64 = getattr(generator, "embedding_to_base64", None)
            base64_to_embedding = getattr(generator, "base64_to_embedding", None)
            ctx = MemoryContext(
                weighted_memories=self.weighted_memories,
                short_term_memory=self.short_term_memory,
                category_index=self.category_index,
                important_prompts=self.important_prompts,
                sensitive_memories=self.sensitive_memories,
                topic_weights=self.topic_weights,
                emotion_memory_map=self.emotion_memory_map,
                weight_calculator=self.weight_calculator,
                detect_topics_fn=self._detect_topics,
                detect_emotion_fn=self._detect_emotion,
                classify_category_fn=self._classify_category,
                extract_user_preferences_fn=self._extract_user_preferences,
                extract_preference_updates_fn=self._extract_preference_updates,
                upsert_preference_locked_fn=self._upsert_preference_locked,
                normalize_memory_record_fn=self._normalize_memory_record,
                mark_keyword_index_dirty_fn=self._mark_keyword_index_dirty_locked,
                schedule_save_fn=lambda: None,
                schedule_trim_fn=self._schedule_trim,
                update_topic_index_fn=self._update_topic_index,
                update_topic_index_incremental_fn=self._update_topic_index_incremental,
                vector_search_enabled=self._vector_search_enabled,
                generate_embedding_fn=generate_embedding,
                embedding_to_base64_fn=embedding_to_base64,
                content_dedupe_index=self.content_dedupe_index,
            )
            mem_input = MemoryInput(
                content=inp.content,
                topics=inp.topics,
                emotions=inp.emotions,
                is_important=inp.is_important,
                source=inp.source,
                category=inp.category,
                metadata=inp.metadata,
                scopes=inp.scopes,
                user_id=inp.user_id,
                is_sensitive_mode=inp.is_sensitive_mode,
            )
            memory_id, need_save = _add_memory_core(ctx, mem_input, legacy_kwargs)
            if memory_id and self._enable_optimizations:
                memory = self.weighted_memories.get(memory_id)
                if memory:
                    for topic in memory.get("topics", []):
                        self._topic_weight_cache.update_topic(
                            topic,
                            weight_delta=memory.get("weight", 0.0),
                            timestamp=memory.get("timestamp", time.time()),
                        )
            if memory_id and self.vector_indexer is not None:
                memory = self.weighted_memories.get(memory_id)
                if memory:
                    try:
                        embedding_list = decode_embedding_to_list(
                            memory.get("embedding"), base64_to_embedding
                        )
                        self.vector_indexer.addRecord(
                            str(memory_id),
                            embedding_list,
                            float(memory.get("weight") or 0.0),
                            float(memory.get("timestamp") or 0.0),
                            str(memory.get("source") or ""),
                            [str(topic) for topic in (memory.get("topics") or [])],
                        )
                    except Exception as exc:  # noqa: BLE001
                        self._logger.warning(
                            "Failed to sync memory %s to C++ VectorIndexer: %s",
                            memory_id,
                            exc,
                        )
        if need_save:
            self._schedule_save()
        return memory_id

    def update_memory_weight(self, memory_id: str, weight_delta: float) -> bool:
        return update_memory_weight_impl(
            self, memory_id, weight_delta, logger=self._logger, time_module=time
        )

    def set_memory_important(self, memory_id: str, important: bool) -> bool:
        return set_memory_important_impl(
            self, memory_id, important, logger=self._logger, time_module=time
        )

    def delete_memory(self, memory_id: str) -> bool:
        if self._enable_optimizations:
            lock_ctx = self._rw_lock.write_lock() if self._use_rw_lock else self.lock
            with lock_ctx:
                self._perf_stats["rw_lock_writes"] += 1
                memory = self.weighted_memories.get(memory_id)
                if memory:
                    for topic in memory.get("topics", []):
                        self._topic_weight_cache.remove_topic(
                            topic, weight_delta=memory.get("weight", 0.0)
                        )
        result = delete_memory_impl(self, memory_id, logger=self._logger, time_module=time)
        if result and self.vector_indexer is not None:
            try:
                self.vector_indexer.removeRecord(str(memory_id))
            except Exception as exc:  # noqa: BLE001
                self._logger.warning(
                    "Failed to remove memory %s from C++ VectorIndexer: %s", memory_id, exc
                )
        return result

    def access_memory(
        self, memory_id: str, importance: int = 1
    ) -> Optional[Dict[str, Any]]:
        return access_memory_impl(
            self, memory_id, importance=importance, logger=self._logger, time_module=time
        )

    def delete_message(self, message_id: str) -> bool:
        return delete_message_impl(self, message_id, logger=self._logger)

    def reclassify_all_memories(self) -> None:
        reclassify_all_memories_impl(self, logger=self._logger)

    def clear_all_memories(self) -> None:
        clear_all_memories_impl(self, logger=self._logger)
        if self.vector_indexer is not None:
            try:
                self.vector_indexer.clear()
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("Failed to clear C++ VectorIndexer: %s", exc)
