"""WeightedMemoryManager 的缓存、向量、状态、统计与批量 API。"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from memory.core.history_ops import (
    get_event_history as get_event_history_impl,
    get_recent_history as get_recent_history_impl,
)
from memory.core.vector_ops import (
    generate_missing_embeddings as generate_missing_embeddings_impl,
    update_memory_distillation as update_memory_distillation_impl,
    update_weight_config as update_weight_config_impl,
)


class WeightedManagerSupportMixin:
    """面向外围能力的轻量委托方法。"""

    def _update_cache(self, memory_id: str, memory: Dict[str, Any]) -> None:
        from memory.core.cache_ops import update_cache

        update_cache(self, memory_id, memory)

    def _get_from_cache(self, memory_id: str) -> Optional[Dict[str, Any]]:
        from memory.core.cache_ops import get_from_cache

        return get_from_cache(self, memory_id)

    async def get_recent_history(
        self,
        session_id: str = None,
        limit: int = 100,
        allowed_categories: List[str] = None,
        before: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        return await get_recent_history_impl(
            self,
            session_id=session_id,
            limit=limit,
            allowed_categories=allowed_categories,
            before=before,
        )

    async def get_event_history(
        self,
        conversation_id: str = None,
        limit: int = 100,
        before: Optional[float] = None,
        query: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        return await get_event_history_impl(
            self,
            conversation_id=conversation_id,
            limit=limit,
            before=before,
            query=query,
            roles=roles,
        )

    def update_memory_distillation(
        self,
        memory_id: str,
        summary: str,
        keywords: List[str],
        distillation_metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return update_memory_distillation_impl(
            self,
            memory_id,
            summary,
            keywords,
            distillation_metadata,
        )

    def generate_missing_embeddings(self) -> int:
        return generate_missing_embeddings_impl(
            self,
            vector_search_enabled=self._vector_search_enabled,
            embedding_generator=self._embedding_generator,
            logger=self._logger,
        )

    def run_pending_embedding_backfill(self) -> int:
        if int(getattr(self, "_pending_embedding_backfill", 0) or 0) <= 0:
            return 0
        self._pending_embedding_backfill = 0
        try:
            return self.generate_missing_embeddings()
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("后台补算缺失 embedding 失败(忽略): %s", exc)
            return 0

    def update_weight_config(self, new_config: Dict[str, float]) -> None:
        update_weight_config_impl(self, new_config, logger=self._logger, time_module=time)

    def update_state(
        self, content: str, status: str = "completed", ttl_hours: int = 24
    ) -> str:
        return self.state_tracker.add_state(content, status, ttl_hours)

    def get_active_states(self) -> List[Dict[str, Any]]:
        return self.state_tracker.get_active_states()

    def get_state_context(self) -> str:
        return self.state_tracker.get_context_string()

    def get_cache_stats(self) -> Dict[str, Any]:
        stats: Dict[str, Any] = {}
        if hasattr(self, "_unified_cache"):
            stats.update(self._unified_cache.get_all_stats())
        if hasattr(self, "_topic_weight_cache"):
            cache = self._topic_weight_cache
            stats["topic_weights"] = {
                "size": len(cache.weights),
                "last_rebuild_time": cache._last_rebuild_time,
                "needs_rebuild": cache.needs_rebuild(),
            }
        return stats

    def get_lock_stats(self) -> Dict[str, Any]:
        return dict(self._perf_stats)

    def get_optimization_stats(self) -> Dict[str, Any]:
        stats = {
            "enabled": self._enable_optimizations,
            "rw_lock_enabled": self._use_rw_lock,
            "perf_stats": dict(self._perf_stats),
            "caches": self.get_cache_stats(),
        }
        if self.vector_indexer is not None:
            stats["cpp_indexer"] = True
        return stats

    def clear_optimization_caches(self) -> None:
        if hasattr(self, "_unified_cache"):
            self._unified_cache.clear_all()
        if hasattr(self, "_topic_weight_cache"):
            self._topic_weight_cache.invalidate()

    def batch_delete_memories(self, memory_ids: List[str]) -> List[bool]:
        from memory.core.batch_ops import batch_delete_memories

        return batch_delete_memories(self, memory_ids)

    def batch_update_weights(self, updates: List[Tuple[str, float]]) -> List[bool]:
        from memory.core.batch_ops import batch_update_weights

        return batch_update_weights(self, updates)

    def batch_search_memories(
        self,
        queries: List[str],
        limit: int = 10,
        min_similarity: float = 0.3,
        category: Optional[str] = None,
    ) -> List[List[Dict[str, Any]]]:
        from memory.core.batch_ops import batch_search_memories

        return batch_search_memories(self, queries, limit, min_similarity, category)
