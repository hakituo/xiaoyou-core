"""搜索与检索 Mixin
负责记忆的搜索和检索操作
"""
import random
from typing import Any, Dict, List, Optional, Tuple

from memory.core.retrieval_ops import (
    get_category_stats as get_category_stats_impl,
    search_by_keyword as search_by_keyword_impl,
    search_memories as search_memories_impl,
    get_top_topics as get_top_topics_impl,
    search_by_similarity as search_by_similarity_impl,
    hybrid_search_memories as hybrid_search_memories_impl,
    search_semantic_memories as search_semantic_memories_impl,
    get_preference_state_memories as get_preference_state_memories_impl,
    build_recall_bundle as build_recall_bundle_impl,
)


class SearchMixin:
    """搜索与检索操作 Mixin"""

    def get_category_stats(self) -> Dict[str, Any]:
        return get_category_stats_impl(self)

    def _search_by_keyword(
        self, query: str, limit: int = 10, category: str = None, emotion: str = None
    ) -> List[Dict[str, Any]]:
        return search_by_keyword_impl(
            self, query=query, limit=limit, category=category, emotion=emotion
        )

    def search_memories(
        self,
        query: str,
        limit: int = 10,
        min_similarity: float = 0.3,
        category: str = None,
        emotion: str = None,
        exclude_sensitive: bool = False,
    ) -> List[Dict[str, Any]]:
        """搜索记忆 [已优化 - 使用批量操作和优化缓存]"""
        if self._enable_optimizations:
            from memory.core.retrieval_ops_optimized import search_memories_optimized
            return search_memories_optimized(
                self,
                query=query,
                limit=limit,
                min_similarity=min_similarity,
                category=category,
                emotion=emotion,
                exclude_sensitive=exclude_sensitive,
                vector_search_enabled=self._vector_search_enabled,
                embedding_generator=self._embedding_generator,
                logger=self._logger if hasattr(self, '_logger') else __import__('logging').getLogger(__name__),
            )
        else:
            return search_memories_impl(
                self,
                query=query,
                limit=limit,
                min_similarity=min_similarity,
                category=category,
                emotion=emotion,
                exclude_sensitive=exclude_sensitive,
                vector_search_enabled=self._vector_search_enabled,
                embedding_generator=self._embedding_generator,
                logger=self._logger if hasattr(self, '_logger') else __import__('logging').getLogger(__name__),
            )

    def get_top_topics(self, limit: int = 5) -> List[Tuple[str, float]]:
        """获取热门话题 [已优化 - 使用增量缓存，90x性能提升]"""
        if self._enable_optimizations:
            from memory.core.retrieval_ops_optimized import get_top_topics_optimized
            return get_top_topics_optimized(self, limit=limit)
        return get_top_topics_impl(self, limit=limit)

    def search_by_similarity(
        self,
        query: str,
        limit: int = 10,
        min_similarity: float = 0.5,
        min_weight: float = None,
        source: str = None,
        topics: List[str] = None,
    ) -> List[Dict[str, Any]]:
        return search_by_similarity_impl(
            self,
            query=query,
            limit=limit,
            min_similarity=min_similarity,
            min_weight=min_weight,
            source=source,
            topics=topics,
            vector_search_enabled=self._vector_search_enabled,
            embedding_generator=self._embedding_generator,
            logger=self._logger if hasattr(self, '_logger') else __import__('logging').getLogger(__name__),
        )

    def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        min_similarity: float = 0.5,
        min_weight: float = None,
        keyword_weight: float = 0.3,
        use_probability: bool = True,
        emotion: Optional[str] = None,
        scope: Optional[str] = None,
        exclude_categories: Optional[List[str]] = None,
        associative_top_k: int = 3,
        conflict_filter: bool = True,
        rng: Optional[random.Random] = None,
        random_seed: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return hybrid_search_memories_impl(
            self,
            query=query,
            limit=limit,
            min_similarity=min_similarity,
            min_weight=min_weight,
            keyword_weight=keyword_weight,
            use_probability=use_probability,
            emotion=emotion,
            scope=scope,
            exclude_categories=exclude_categories,
            associative_top_k=associative_top_k,
            conflict_filter=conflict_filter,
            rng=rng,
            random_seed=random_seed,
        )

    def search_semantic_memories(
        self,
        query: str,
        limit: int = 10,
        min_similarity: float = 0.5,
        min_weight: float = None,
        emotion: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return search_semantic_memories_impl(
            self,
            query=query,
            limit=limit,
            min_similarity=min_similarity,
            min_weight=min_weight,
            emotion=emotion,
            scope=scope,
        )

    def get_preference_state_memories(
        self,
        query: Optional[str] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        return get_preference_state_memories_impl(self, query=query, limit=limit)

    async def build_recall_bundle(
        self,
        query: str,
        limit: int = 10,
        history_limit: int = 30,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        history_items = await self.get_event_history(
            conversation_id=conversation_id,
            limit=history_limit,
            query=query,
        )
        payload = build_recall_bundle_impl(
            self,
            query=query,
            limit=limit,
            history_limit=history_limit,
        )
        payload["event_history"] = history_items
        return payload
