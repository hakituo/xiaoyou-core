"""
统一缓存管理器

整合 memory 模块中所有缓存实例，提供统一接口：
- 统一统计信息
- 统一清理接口
- 缓存生命周期管理

缓存架构:
┌──────────────────────────────────────────────────────┐
│                  UnifiedCacheManager                  │
├──────────────┬──────────────┬────────────────────────┤
│  记忆缓存     │  嵌入缓存     │  主题缓存              │
│  L1 (20)     │  memory(2048)│  topic_weights(ttl=30s)│
│  L2 (50)     │  query(256)  │                        │
└──────────────┴──────────────┴────────────────────────┘

所有缓存命中路径:
1. 嵌入缓存: search_memories → get_embedding_validated → put_embedding
2. 查询缓存: search_memories → get_query_embedding → put_query_embedding
3. L1/L2缓存: access_memory → get_memory → put_memory
4. 主题缓存: get_top_topics → TopicWeightCache (独立管理)
"""

import threading
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple


class UnifiedCacheManager:
    """
    统一缓存管理器

    整合所有缓存实例，提供：
    1. 统一统计接口
    2. 统一清理接口
    3. 消除冗余缓存
    4. 缓存生命周期管理
    5. 嵌入缓存 b64 校验（防止记忆更新后缓存不一致）
    """

    DEFAULT_EMBEDDING_CACHE_SIZE = 2048
    DEFAULT_QUERY_CACHE_SIZE = 256
    DEFAULT_L1_SIZE = 20
    DEFAULT_L2_SIZE = 50
    DEFAULT_TOPIC_TTL = 30.0

    def __init__(
        self,
        embedding_cache_size: int = DEFAULT_EMBEDDING_CACHE_SIZE,
        query_cache_size: int = DEFAULT_QUERY_CACHE_SIZE,
        l1_size: int = DEFAULT_L1_SIZE,
        l2_size: int = DEFAULT_L2_SIZE,
        topic_ttl: float = DEFAULT_TOPIC_TTL,
    ):
        self._lock = threading.RLock()

        self._embedding_cache: OrderedDict[str, Tuple[str, Any]] = OrderedDict()
        self._embedding_cache_max = embedding_cache_size

        self._query_cache: OrderedDict[str, Any] = OrderedDict()
        self._query_cache_max = query_cache_size

        self._l1_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._l1_max = l1_size

        self._l2_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._l2_max = l2_size

        self._topic_ttl = topic_ttl

        self._stats = {
            "embedding_hits": 0,
            "embedding_misses": 0,
            "query_hits": 0,
            "query_misses": 0,
            "l1_hits": 0,
            "l1_misses": 0,
            "l2_hits": 0,
            "l2_misses": 0,
            "topic_rebuilds": 0,
        }

    # --- 嵌入缓存 ---

    def get_embedding(self, memory_id: str) -> Optional[Tuple[str, Any]]:
        """获取记忆嵌入缓存（不校验 b64）"""
        with self._lock:
            val = self._embedding_cache.get(memory_id)
            if val is not None:
                self._stats["embedding_hits"] += 1
                try:
                    self._embedding_cache.move_to_end(memory_id)
                except Exception:
                    pass
                return val
            self._stats["embedding_misses"] += 1
            return None

    def get_embedding_validated(
        self, memory_id: str, current_b64: str
    ) -> Optional[Any]:
        """
        获取记忆嵌入缓存，校验 b64 一致性。

        如果缓存的 b64 与当前 b64 不一致，说明记忆的嵌入已更新，
        缓存失效，返回 None。这防止了记忆更新后使用旧的嵌入向量。

        Args:
            memory_id: 记忆 ID
            current_b64: 当前记忆的 base64 编码嵌入

        Returns:
            嵌入向量（numpy 数组），缓存未命中或 b64 不一致返回 None
        """
        with self._lock:
            val = self._embedding_cache.get(memory_id)
            if val is not None:
                cached_b64, cached_emb = val
                if cached_b64 == current_b64 and cached_emb is not None:
                    self._stats["embedding_hits"] += 1
                    try:
                        self._embedding_cache.move_to_end(memory_id)
                    except Exception:
                        pass
                    return cached_emb
                else:
                    del self._embedding_cache[memory_id]
            self._stats["embedding_misses"] += 1
            return None

    def put_embedding(self, memory_id: str, b64: str, embedding: Any):
        """存入记忆嵌入缓存"""
        with self._lock:
            self._embedding_cache[memory_id] = (b64, embedding)
            try:
                self._embedding_cache.move_to_end(memory_id)
            except Exception:
                pass
            while len(self._embedding_cache) > self._embedding_cache_max:
                self._embedding_cache.popitem(last=False)

    def invalidate_embedding(self, memory_id: str):
        """使指定记忆的嵌入缓存失效"""
        with self._lock:
            self._embedding_cache.pop(memory_id, None)

    # --- 查询缓存 ---

    def get_query_embedding(self, query_hash: str) -> Optional[Any]:
        """获取查询嵌入缓存"""
        with self._lock:
            val = self._query_cache.get(query_hash)
            if val is not None:
                self._stats["query_hits"] += 1
                try:
                    self._query_cache.move_to_end(query_hash)
                except Exception:
                    pass
                return val
            self._stats["query_misses"] += 1
            return None

    def put_query_embedding(self, query_hash: str, embedding: Any):
        """存入查询嵌入缓存"""
        with self._lock:
            self._query_cache[query_hash] = embedding
            try:
                self._query_cache.move_to_end(query_hash)
            except Exception:
                pass
            while len(self._query_cache) > self._query_cache_max:
                self._query_cache.popitem(last=False)

    # --- 记忆 L1/L2 缓存 ---

    def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """获取记忆缓存 (L1 -> L2)，命中 L2 时提升到 L1"""
        with self._lock:
            val = self._l1_cache.get(memory_id)
            if val is not None:
                self._stats["l1_hits"] += 1
                try:
                    self._l1_cache.move_to_end(memory_id)
                except Exception:
                    pass
                return val

            val = self._l2_cache.get(memory_id)
            if val is not None:
                self._stats["l2_hits"] += 1
                self._l1_cache[memory_id] = val
                try:
                    self._l1_cache.move_to_end(memory_id)
                    self._l2_cache.move_to_end(memory_id)
                except Exception:
                    pass
                while len(self._l1_cache) > self._l1_max:
                    _, evicted = self._l1_cache.popitem(last=False)
                    if isinstance(evicted, dict):
                        mid = evicted.get("id", "")
                        if mid:
                            self._l2_cache[mid] = evicted
                            while len(self._l2_cache) > self._l2_max:
                                self._l2_cache.popitem(last=False)
                return val

            self._stats["l1_misses"] += 1
            return None

    def put_memory(self, memory_id: str, memory: Dict[str, Any]):
        """存入记忆缓存 (L1)，L1 满时淘汰到 L2"""
        with self._lock:
            self._l1_cache[memory_id] = memory
            try:
                self._l1_cache.move_to_end(memory_id)
            except Exception:
                pass
            while len(self._l1_cache) > self._l1_max:
                _, evicted = self._l1_cache.popitem(last=False)
                if isinstance(evicted, dict):
                    mid = evicted.get("id", memory_id)
                    self._l2_cache[mid] = evicted
                    while len(self._l2_cache) > self._l2_max:
                        self._l2_cache.popitem(last=False)

    def update_memory_access(self, memory_id: str, memory: Dict[str, Any]):
        """更新记忆访问：写入 L1 和 L2，递增访问计数"""
        with self._lock:
            self._l1_cache[memory_id] = memory
            self._l2_cache[memory_id] = memory
            try:
                self._l1_cache.move_to_end(memory_id)
                self._l2_cache.move_to_end(memory_id)
            except Exception:
                pass
            while len(self._l1_cache) > self._l1_max:
                _, evicted = self._l1_cache.popitem(last=False)
                if isinstance(evicted, dict):
                    mid = evicted.get("id", "")
                    if mid:
                        self._l2_cache[mid] = evicted
                        while len(self._l2_cache) > self._l2_max:
                            self._l2_cache.popitem(last=False)
            while len(self._l2_cache) > self._l2_max:
                self._l2_cache.popitem(last=False)

    def invalidate_memory(self, memory_id: str):
        """使记忆缓存失效（L1 + L2 + 嵌入缓存）"""
        with self._lock:
            self._l1_cache.pop(memory_id, None)
            self._l2_cache.pop(memory_id, None)
            self._embedding_cache.pop(memory_id, None)

    # --- 统一接口 ---

    def get_all_stats(self) -> Dict[str, Any]:
        """获取所有缓存统计"""
        with self._lock:
            emb_total = self._stats["embedding_hits"] + self._stats["embedding_misses"]
            q_total = self._stats["query_hits"] + self._stats["query_misses"]
            l1_total = self._stats["l1_hits"] + self._stats["l1_misses"]
            l2_total = self._stats["l2_hits"] + self._stats["l2_misses"]

            return {
                "embedding": {
                    "size": len(self._embedding_cache),
                    "max_size": self._embedding_cache_max,
                    "hits": self._stats["embedding_hits"],
                    "misses": self._stats["embedding_misses"],
                    "hit_rate": round(
                        self._stats["embedding_hits"] / emb_total, 4
                    ) if emb_total > 0 else 0.0,
                },
                "query": {
                    "size": len(self._query_cache),
                    "max_size": self._query_cache_max,
                    "hits": self._stats["query_hits"],
                    "misses": self._stats["query_misses"],
                    "hit_rate": round(
                        self._stats["query_hits"] / q_total, 4
                    ) if q_total > 0 else 0.0,
                },
                "l1": {
                    "size": len(self._l1_cache),
                    "max_size": self._l1_max,
                    "hits": self._stats["l1_hits"],
                    "misses": self._stats["l1_misses"],
                    "hit_rate": round(
                        self._stats["l1_hits"] / l1_total, 4
                    ) if l1_total > 0 else 0.0,
                },
                "l2": {
                    "size": len(self._l2_cache),
                    "max_size": self._l2_max,
                    "hits": self._stats["l2_hits"],
                    "misses": self._stats["l2_misses"],
                    "hit_rate": round(
                        self._stats["l2_hits"] / l2_total, 4
                    ) if l2_total > 0 else 0.0,
                },
                "topic_rebuilds": self._stats["topic_rebuilds"],
            }

    def clear_all(self) -> Dict[str, int]:
        """清空所有缓存"""
        with self._lock:
            cleared = {
                "embedding": len(self._embedding_cache),
                "query": len(self._query_cache),
                "l1": len(self._l1_cache),
                "l2": len(self._l2_cache),
            }
            self._embedding_cache.clear()
            self._query_cache.clear()
            self._l1_cache.clear()
            self._l2_cache.clear()
            return cleared

    def clear_embeddings(self) -> int:
        """清空嵌入缓存"""
        with self._lock:
            count = len(self._embedding_cache)
            self._embedding_cache.clear()
            return count

    def clear_queries(self) -> int:
        """清空查询缓存"""
        with self._lock:
            count = len(self._query_cache)
            self._query_cache.clear()
            return count

    def record_topic_rebuild(self):
        """记录主题缓存重建"""
        with self._lock:
            self._stats["topic_rebuilds"] += 1

    def reset_stats(self):
        """重置统计信息"""
        with self._lock:
            for key in self._stats:
                self._stats[key] = 0

    @property
    def embedding_cache(self) -> OrderedDict:
        return self._embedding_cache

    @property
    def query_cache(self) -> OrderedDict:
        return self._query_cache

    @property
    def embedding_cache_max_items(self) -> int:
        return self._embedding_cache_max

    @property
    def query_embedding_cache_max_items(self) -> int:
        return self._query_cache_max
