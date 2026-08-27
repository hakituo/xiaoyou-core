"""关键词索引 Mixin
负责关键词索引的全部操作
"""
from typing import Any, Dict, List, Optional

from memory.core.keyword_ops import (
    ensure_keyword_index_ready as ensure_keyword_index_ready_impl,
    mark_keyword_index_dirty_locked as mark_keyword_index_dirty_locked_impl,
    request_keyword_index_rebuild_locked as request_keyword_index_rebuild_locked_impl,
    rebuild_preference_index_for_manager as rebuild_preference_index_for_manager_impl,
    rebuild_keyword_index_locked as rebuild_keyword_index_locked_impl,
    remove_memory_from_keyword_index_locked as remove_memory_from_keyword_index_locked_impl,
    upsert_memory_keywords_locked as upsert_memory_keywords_locked_impl,
    refresh_keyword_index_locked as refresh_keyword_index_locked_impl,
    update_keyword_index as update_keyword_index_impl,
    expand_keywords as expand_keywords_impl,
    get_active_preferences_view as get_active_preferences_view_impl,
    normalize_category_dir as normalize_category_dir_impl,
)


class KeywordIndexMixin:
    """关键词索引操作 Mixin"""

    def _ensure_keyword_index_ready(self):
        ensure_keyword_index_ready_impl(self)

    def _mark_keyword_index_dirty_locked(self, memory_id: str):
        mark_keyword_index_dirty_locked_impl(self, memory_id)

    def _request_keyword_index_rebuild_locked(self):
        request_keyword_index_rebuild_locked_impl(self)

    def _rebuild_preference_index_locked(self):
        rebuild_preference_index_for_manager_impl(self)

    def _rebuild_keyword_index_locked(self):
        rebuild_keyword_index_locked_impl(self, logger=self._logger if hasattr(self, '_logger') else __import__('logging').getLogger(__name__))

    def _remove_memory_from_keyword_index_locked(
        self, memory_id: str, memory: Optional[Dict[str, Any]] = None
    ):
        remove_memory_from_keyword_index_locked_impl(self, memory_id, memory)

    def _upsert_memory_keywords_locked(self, memory_id: str, memory: Dict[str, Any]):
        upsert_memory_keywords_locked_impl(self, memory_id, memory)

    def _refresh_keyword_index_locked(self):
        refresh_keyword_index_locked_impl(self)

    def _update_keyword_index(self):
        update_keyword_index_impl(self)

    def _expand_keywords(self, keywords: List[str], top_k: int = 3) -> List[str]:
        return expand_keywords_impl(self, keywords, top_k=top_k)

    def get_active_preferences(self) -> Dict[str, Any]:
        return get_active_preferences_view_impl(self)

    def _normalize_category_dir(self, category: Optional[str]) -> str:
        return normalize_category_dir_impl(category)
