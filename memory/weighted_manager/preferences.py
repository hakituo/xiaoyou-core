"""WeightedMemoryManager 的偏好、敏感记忆与重要提示查询。"""

from __future__ import annotations

import heapq
import time
from typing import Any, Dict, List, Optional, Set

from memory.core.preferences import extract_preference_updates, upsert_preference_locked
from memory.core.utils import extract_keywords


class WeightedManagerPreferenceMixin:
    """偏好提取和重要记忆视图职责。"""

    def get_sensitive_memories(self, limit: int = 10) -> List[Dict[str, Any]]:
        lock_ctx = self._rw_lock.read_lock() if self._use_rw_lock else self.lock
        with lock_ctx:
            self._perf_stats["rw_lock_reads"] += 1
            candidates = [
                memory
                for memory in self.weighted_memories.values()
                if str(memory.get("category") or "").strip().lower() == "sensitive"
            ]
            return heapq.nlargest(limit, candidates, key=lambda item: item["timestamp"])

    def _extract_keywords(self, content: str) -> Set[str]:
        return extract_keywords(content)

    def _extract_preference_updates(self, content: str) -> List[Dict[str, Any]]:
        return extract_preference_updates(content)

    def _upsert_preference_locked(
        self,
        key: str,
        polarity: bool,
        source_memory_id: str,
        timestamp: float,
    ) -> Optional[str]:
        generator = self._embedding_generator
        memory_id = upsert_preference_locked(
            key=key,
            polarity=polarity,
            source_memory_id=source_memory_id,
            timestamp=timestamp,
            weighted_memories=self.weighted_memories,
            category_index=self.category_index,
            preference_index=self.preference_index,
            calculate_initial_weight=self.weight_calculator.calculate_initial_weight,
            mark_keyword_index_dirty=self._mark_keyword_index_dirty_locked,
            normalize_memory_record=self._normalize_memory_record,
            vector_search_enabled=self._vector_search_enabled,
            generate_embedding=getattr(generator, "generate_embedding", None),
            embedding_to_base64=getattr(generator, "embedding_to_base64", None),
        )
        if memory_id:
            self.last_modified_time = time.time()
        return memory_id

    def get_important_prompts(self) -> List[Dict[str, Any]]:
        lock_ctx = self._rw_lock.read_lock() if self._use_rw_lock else self.lock
        with lock_ctx:
            self._perf_stats["rw_lock_reads"] += 1
            prompts = list(self.important_prompts)
            if prompts:
                return prompts
            derived: List[Dict[str, Any]] = []
            for memory in sorted(
                self.weighted_memories.values(),
                key=lambda item: float(item.get("timestamp") or 0.0),
                reverse=True,
            ):
                topics = [
                    str(topic).strip()
                    for topic in (memory.get("topics") or [])
                    if str(topic).strip()
                ]
                if "user_instruction" in topics or bool(memory.get("is_important", False)):
                    derived.append(memory)
                if len(derived) >= 20:
                    break
            return derived
