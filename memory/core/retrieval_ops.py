from collections import defaultdict
import hashlib
import time
from typing import Any, Dict, List, Optional, Tuple
from memory.core.search import hybrid_search
from memory.core.keyword_index import expand_keywords
from memory.core.recall_probability import passes_recall_filter
from memory.core.scoring_utils import (
    compute_hybrid_score_with_result as _compute_hybrid_score,
    apply_recall_ranking as _apply_recall_ranking,
    DEFAULT_SCORING_CONFIG as _DEFAULT_SCORING_CONFIG,
)
from memory.core.lock_utils import get_read_lock, get_write_lock


def get_category_stats(manager: Any) -> Dict[str, Any]:
    stats = {
        "counts": defaultdict(int),
        "avg_weight": defaultdict(float),
        "total_memories": 0,
        "distribution": {},
    }

    with get_read_lock(manager):
        total_weight_by_cat = defaultdict(float)
        for memory in manager.weighted_memories.values():
            cat = memory.get("category", "uncategorized") or "uncategorized"
            stats["counts"][cat] += 1
            total_weight_by_cat[cat] += memory.get("weight", 0)
            stats["total_memories"] += 1

        for cat, count in stats["counts"].items():
            if count > 0:
                stats["avg_weight"][cat] = round(total_weight_by_cat[cat] / count, 2)
                stats["distribution"][cat] = round(
                    (count / stats["total_memories"]) * 100, 1
                )

    stats["counts"] = dict(stats["counts"])
    stats["avg_weight"] = dict(stats["avg_weight"])
    return stats


def search_by_keyword(
    manager: Any,
    query: str,
    limit: int = 10,
    category: Optional[str] = None,
    emotion: Optional[str] = None,
    exclude_sensitive: bool = False,
) -> List[Dict[str, Any]]:
    results = []
    query_lower = query.lower()

    # 先确保关键词索引就绪（内部自取写锁），再进入读锁，
    # 避免在持有读锁时请求写锁导致同线程读->写锁升级自死锁
    manager._ensure_keyword_index_ready()

    with get_read_lock(manager):
        if category:
            candidate_ids = set(manager.category_index.get(category, []))
        else:
            candidate_ids = None

        query_keywords = list(manager._extract_keywords(query))
        expanded_keywords = manager._expand_keywords(query_keywords, top_k=3)

        def _is_valid_memory(memory: Dict[str, Any]) -> bool:
            if memory.get("status") == "superseded":
                return False
            if (
                memory.get("memory_type") == "preference"
                and memory.get("status") != "active"
            ):
                return False
            if exclude_sensitive and memory.get("category") == "sensitive":
                return False
            return True

        # 统一关键词搜索逻辑：根据关键词权重映射进行评分
        base_set = set(query_keywords)
        keyword_weights: Dict[str, float] = {}
        if expanded_keywords:
            for kw in expanded_keywords:
                keyword_weights[kw] = 1.0 if kw in base_set else 0.5
        elif query_keywords:
            for kw in query_keywords:
                keyword_weights[kw] = 1.0

        if keyword_weights:
            memory_id_scores = defaultdict(float)
            for keyword, weight in keyword_weights.items():
                if keyword in manager._keyword_index:
                    for memory_id in manager._keyword_index[keyword]:
                        if candidate_ids is not None and memory_id not in candidate_ids:
                            continue
                        memory = manager.weighted_memories.get(memory_id)
                        if not memory or not _is_valid_memory(memory):
                            continue
                        memory_id_scores[memory_id] += weight

            sorted_memory_ids = sorted(
                memory_id_scores.items(), key=lambda x: x[1], reverse=True
            )
            for memory_id, _ in sorted_memory_ids:
                if memory_id in manager.weighted_memories:
                    mem = manager.weighted_memories[memory_id]
                    if category and mem.get("category") != category:
                        continue
                    results.append(mem)

        if not results:
            # 无关键词匹配时回退到全文搜索
            memories_snapshot = (
                [manager.weighted_memories[mid] for mid in candidate_ids if mid in manager.weighted_memories]
                if candidate_ids is not None
                else list(manager.weighted_memories.values())
            )
            for memory in memories_snapshot:
                if not _is_valid_memory(memory):
                    continue
                c = (memory.get("summary") or memory.get("content", "") or "").lower()
                if query_lower in c:
                    results.append(memory)

    if emotion:
        for res in results:
            current_weight = res.get("weight", 0)
            if emotion in res.get("emotions", []):
                res["_sort_weight"] = current_weight * 1.2
            else:
                res["_sort_weight"] = current_weight
        results.sort(key=lambda x: x.get("_sort_weight", 0), reverse=True)
        for res in results:
            res.pop("_sort_weight", None)
    else:
        results.sort(key=lambda x: x.get("weight", 0), reverse=True)

    return results[:limit]


def _deterministic_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def get_cached_query_embedding(manager: Any, query: str, embedding_generator: Any):
    if not query:
        return None

    if manager._query_embedding_cache_max_items <= 0:
        return embedding_generator.generate_embedding(query)

    key = _deterministic_hash(query)
    uc = getattr(manager, '_unified_cache', None)
    if uc is not None:
        cached = uc.get_query_embedding(key)
        if cached is not None:
            return cached

    emb = embedding_generator.generate_embedding(query)
    if uc is not None:
        uc.put_query_embedding(key, emb)
    else:
        with get_write_lock(manager):
            manager._query_embedding_cache[key] = emb
            try:
                manager._query_embedding_cache.move_to_end(key)
            except Exception:
                pass
            while (
                manager._query_embedding_cache_max_items > 0
                and len(manager._query_embedding_cache) > manager._query_embedding_cache_max_items
            ):
                manager._query_embedding_cache.popitem(last=False)
    return emb


def get_cached_memory_embedding(manager: Any, memory: Dict[str, Any], embedding_generator: Any):
    if not isinstance(memory, dict):
        return None
    b64 = memory.get("embedding")
    if not b64:
        return None
    mid = str(memory.get("id") or "").strip()
    if not mid:
        return None

    uc = getattr(manager, '_unified_cache', None)
    if uc is not None:
        cached_emb = uc.get_embedding_validated(mid, b64)
        if cached_emb is not None:
            return cached_emb
    elif manager._embedding_cache_max_items > 0:
        with get_read_lock(manager):
            cached = manager._embedding_cache.get(mid)
            if cached is not None and isinstance(cached, tuple) and len(cached) == 2:
                cached_b64, cached_emb = cached
                if cached_b64 == b64 and cached_emb is not None:
                    try:
                        manager._embedding_cache.move_to_end(mid)
                    except Exception:
                        pass
                    return cached_emb

    try:
        emb = embedding_generator.base64_to_embedding(b64)
    except Exception:
        return None
    if emb is None:
        return None
    try:
        if len(emb) <= 0:
            return None
    except Exception:
        return None

    if uc is not None:
        uc.put_embedding(mid, b64, emb)
    elif manager._embedding_cache_max_items > 0:
        with get_write_lock(manager):
            manager._embedding_cache[mid] = (b64, emb)
            try:
                manager._embedding_cache.move_to_end(mid)
            except Exception:
                pass
            while (
                manager._embedding_cache_max_items > 0
                and len(manager._embedding_cache) > manager._embedding_cache_max_items
            ):
                manager._embedding_cache.popitem(last=False)
    return emb


def search_memories(
    manager: Any,
    *,
    query: str,
    limit: int = 10,
    min_similarity: float = 0.3,
    category: Optional[str] = None,
    emotion: Optional[str] = None,
    exclude_sensitive: bool = False,
    vector_search_enabled: bool,
    embedding_generator: Any,
    logger: Any,
) -> List[Dict[str, Any]]:
    if not vector_search_enabled or not query:
        if not vector_search_enabled:
            logger.warning("向量搜索未启用，回退到关键词搜索")
        return search_by_keyword(manager, query, limit, category=category, emotion=emotion, exclude_sensitive=exclude_sensitive)

    cache_key = f"search:{_deterministic_hash(query)}:{limit}:{category}:{emotion}:{exclude_sensitive}"
    if manager.search_cache:
        cached_res = getattr(manager.search_cache, "get_sync", lambda *args, **kwargs: None)(
            cache_key
        )
        if cached_res:
            return cached_res

    try:
        query_embedding = get_cached_query_embedding(manager, query, embedding_generator)

        # 单次读锁内收集候选记忆引用，避免 N 次锁获取
        with get_read_lock(manager):
            if category:
                candidate_ids = manager.category_index.get(category, [])
            else:
                candidate_ids = list(manager.weighted_memories.keys())
            # 一次性收集有效记忆引用（dict.get 是 O(1)，读快照安全）
            candidate_memories = []
            for mid in candidate_ids:
                memory = manager.weighted_memories.get(mid)
                if not memory:
                    continue
                if "embedding" not in memory or not memory["embedding"]:
                    continue
                if exclude_sensitive and memory.get("category") == "sensitive":
                    continue
                candidate_memories.append(memory)

        # 锁外做 embedding 缓存查询和相似度计算
        valid_memories = []
        valid_embeddings = []
        for memory in candidate_memories:
            mem_embedding = get_cached_memory_embedding(
                manager, memory, embedding_generator
            )
            if mem_embedding is None:
                continue
            valid_memories.append(memory)
            valid_embeddings.append(mem_embedding)

        if not valid_memories:
            logger.info(f"向量搜索未找到结果，尝试关键词搜索: {query}")
            return search_by_keyword(manager, query, limit, category=category, emotion=emotion, exclude_sensitive=exclude_sensitive)

        candidates = []
        try:
            import numpy as np
            embeddings_matrix = np.vstack(valid_embeddings)
            similarities = embedding_generator.batch_cosine_similarity(
                query_embedding, embeddings_matrix
            )
            for idx, memory in enumerate(valid_memories):
                similarity = float(similarities[idx])
                if similarity >= min_similarity:
                    candidates.append(_compute_hybrid_score(memory, similarity, emotion))
        except Exception:
            for memory in valid_memories:
                try:
                    mem_embedding = get_cached_memory_embedding(
                        manager, memory, embedding_generator
                    )
                    if mem_embedding is None:
                        continue
                    similarity = embedding_generator.cosine_similarity(
                        query_embedding, mem_embedding
                    )
                    if similarity >= min_similarity:
                        candidates.append(_compute_hybrid_score(memory, similarity, emotion))
                except Exception:
                    continue

        if not candidates:
            logger.info(f"向量搜索未找到结果，尝试关键词搜索: {query}")
            return search_by_keyword(manager, query, limit, category=category, emotion=emotion, exclude_sensitive=exclude_sensitive)

        candidates.sort(key=lambda x: x.get("hybrid_score", 0), reverse=True)
        final_results = candidates[:limit]
        if manager.search_cache:
            getattr(manager.search_cache, "set_sync", lambda *args, **kwargs: None)(
                cache_key, final_results, ttl=60
            )
        return final_results
    except Exception as e:
        logger.error(f"向量搜索失败: {e}")
        return search_by_keyword(manager, query, limit, category=category, emotion=emotion, exclude_sensitive=exclude_sensitive)


_TOP_TOPICS_CACHE_TTL = 30.0
_TOP_TOPICS_CACHE_MAX_ENTRIES = 64


def _get_top_topics_cache(manager: Any) -> Dict[str, Tuple[float, List[Tuple[str, float]]]]:
    if not hasattr(manager, "_top_topics_cache"):
        manager._top_topics_cache: Dict[str, Tuple[float, List[Tuple[str, float]]]] = {}
    return manager._top_topics_cache


def _cleanup_top_topics_cache(cache: Dict[str, Tuple[float, List[Tuple[str, float]]]]) -> None:
    if len(cache) <= _TOP_TOPICS_CACHE_MAX_ENTRIES:
        return
    now = time.time()
    expired_keys = [
        k for k, (ts, _) in cache.items()
        if (now - ts) >= _TOP_TOPICS_CACHE_TTL
    ]
    for k in expired_keys:
        del cache[k]
    if len(cache) > _TOP_TOPICS_CACHE_MAX_ENTRIES * 2:
        sorted_items = sorted(cache.items(), key=lambda x: x[1][0])
        for k, _ in sorted_items[: len(sorted_items) - _TOP_TOPICS_CACHE_MAX_ENTRIES]:
            cache.pop(k, None)


def invalidate_top_topics_cache(manager: Any) -> None:
    """使主题缓存失效，接入 TopicWeightCache"""
    if hasattr(manager, '_topic_weight_cache') and manager._topic_weight_cache is not None:
        manager._topic_weight_cache.invalidate()
    cache = _get_top_topics_cache(manager)
    cache.pop(getattr(manager, "user_id", "default"), None)


def get_top_topics(manager: Any, limit: int = 5) -> List[Tuple[str, float]]:
    cache_key = manager.user_id
    now = time.time()
    cache = _get_top_topics_cache(manager)
    with get_read_lock(manager):
        cached = cache.get(cache_key)
        if cached is not None:
            cached_ts, cached_result = cached
            if (now - cached_ts) < _TOP_TOPICS_CACHE_TTL and len(cached_result) >= limit:
                return cached_result[:limit]

    # 读锁内仅读取数据，不修改共享状态
    with get_read_lock(manager):
        topic_total_weights: Dict[str, float] = {}
        for memory in manager.weighted_memories.values():
            w = float(memory.get("weight") or 0.0)
            ts = float(memory.get("timestamp") or 0.0)
            current_w = manager.weight_calculator.apply_time_decay(w, ts)
            for topic in memory.get("topics", []):
                topic_text = str(topic).strip()
                if topic_text:
                    topic_total_weights[topic_text] = round(
                        topic_total_weights.get(topic_text, 0.0) + current_w, 2
                    )
        sorted_topics = sorted(topic_total_weights.items(), key=lambda x: x[1], reverse=True)
        result = sorted_topics[:max(limit, 20)]

    # 写锁内更新共享状态
    with get_write_lock(manager):
        manager.topic_weights.update(topic_total_weights)
        cache[cache_key] = (now, result)
        _cleanup_top_topics_cache(cache)
    return result[:limit]


def search_by_similarity(
    manager: Any,
    *,
    query: str,
    limit: int = 10,
    min_similarity: float = 0.5,
    min_weight: Optional[float] = None,
    source: Optional[str] = None,
    topics: Optional[List[str]] = None,
    vector_search_enabled: bool,
    embedding_generator: Any,
    logger: Any,
) -> List[Dict[str, Any]]:
    if not vector_search_enabled:
        logger.warning("向量搜索功能未启用")
        return manager.get_weighted_memories(min_weight=min_weight, limit=limit, topics=topics)
    if not query:
        return []

    try:
        query_embedding = get_cached_query_embedding(manager, query, embedding_generator)
    except Exception as e:
        logger.error(f"生成查询向量嵌入失败: {e}")
        return []

    # 如果存在 C++ 索引器，使用极速引擎计算
    if hasattr(manager, "vector_indexer"):
        try:
            cpp_results = manager.vector_indexer.search(
                query_embedding=query_embedding,
                top_k=limit,
                min_similarity=min_similarity,
                current_time=time.time(),
                decay_rate=manager.weight_calculator.config.get("recency_decay_factor", 0.95),
                base_min_weight=manager.weight_calculator.config.get("base_weight", 1.0) * 0.1,
                absolute_min_weight=min_weight or 0.0,
                filter_source=source or "",
                filter_topics=topics or []
            )

            results = []
            for cpp_res in cpp_results:
                mem_obj = manager.weighted_memories.get(cpp_res.id)
                if mem_obj:
                    res_copy = mem_obj.copy()
                    res_copy["similarity_score"] = cpp_res.similarity
                    res_copy["weighted_score"] = cpp_res.final_score
                    results.append(res_copy)
            return results
        except Exception as e:
            logger.error(f"C++ VectorIndexer 检索失败，回退到 Python 原生检索: {e}", exc_info=True)

    results: List[Dict[str, Any]] = []
    with get_read_lock(manager):
        memories_snapshot = list(manager.weighted_memories.values())
    for memory in memories_snapshot:
        try:
            if min_weight is not None and float(memory.get("weight", 0) or 0) < float(min_weight):
                continue
            if source and memory.get("source") != source:
                continue
            if topics:
                memory_topics = memory.get("topics", [])
                if not any(t in memory_topics for t in topics):
                    continue
            mem_embedding = get_cached_memory_embedding(manager, memory, embedding_generator)
            if mem_embedding is None:
                continue
            similarity = float(
                embedding_generator.cosine_similarity(query_embedding, mem_embedding)
            )
            if similarity < float(min_similarity):
                continue
            w = float(memory.get("weight") or 0.0)
            ts = float(memory.get("timestamp") or 0.0)
            current_weight = manager.weight_calculator.apply_time_decay(w, ts)
            normalized_weight = min(float(current_weight) / 20.0, 1.0)
            weighted_score = (
                normalized_weight * _DEFAULT_SCORING_CONFIG.weight_score_weight
                + similarity * _DEFAULT_SCORING_CONFIG.similarity_weight
            )
            result = memory.copy()
            result["similarity_score"] = similarity
            result["current_weight"] = current_weight
            result["weighted_score"] = weighted_score
            results.append(result)
        except Exception:
            continue
    results.sort(key=lambda x: x.get("weighted_score", 0), reverse=True)
    return results[:limit]


def hybrid_search_memories(
    manager: Any,
    *,
    query: str,
    limit: int = 10,
    min_similarity: float = 0.5,
    min_weight: Optional[float] = None,
    keyword_weight: float = 0.3,
    use_probability: bool = True,
    emotion: Optional[str] = None,
    scope: Optional[str] = None,
    exclude_categories: Optional[List[str]] = None,
    associative_top_k: int = 3,
    conflict_filter: bool = True,
    rng: Optional[Any] = None,
    random_seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    manager._ensure_keyword_index_ready()

    def search_sim_fn(*args, **kwargs):
        return manager.search_by_similarity(*args, **kwargs)

    return hybrid_search(
        query=query,
        weighted_memories=manager.weighted_memories,
        keyword_index=manager._keyword_index,
        keyword_graph=manager._keyword_graph,
        extract_keywords=manager._extract_keywords,
        expand_keywords=expand_keywords,
        search_by_similarity_fn=search_sim_fn,
        passes_recall_filter=passes_recall_filter,
        apply_time_decay=manager.weight_calculator.apply_time_decay,
        detect_emotion_fn=manager._detect_emotion,
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
    manager: Any,
    *,
    query: str,
    limit: int = 10,
    min_similarity: float = 0.5,
    min_weight: Optional[float] = None,
    emotion: Optional[str] = None,
    scope: Optional[str] = None,
) -> List[Dict[str, Any]]:
    excluded_categories = ["preference", "sensitive", "state"]
    results = hybrid_search_memories(
        manager,
        query=query,
        limit=max(limit * 2, limit),
        min_similarity=min_similarity,
        min_weight=min_weight,
        keyword_weight=0.3,
        use_probability=True,
        emotion=emotion,
        scope=scope,
        exclude_categories=excluded_categories,
        associative_top_k=3,
        conflict_filter=True,
    )
    filtered: List[Dict[str, Any]] = []
    for memory in results:
        memory_type = str(memory.get("memory_type") or "dialogue").strip().lower()
        category = str(memory.get("category") or "uncategorized").strip().lower()
        if memory_type in {"preference", "state", "sensitive", "profile"}:
            continue
        if category in {"preference", "state", "sensitive"}:
            continue
        filtered.append(memory)
    return _apply_recall_ranking(filtered, limit=limit, source_layer="semantic_memory")


def get_preference_state_memories(
    manager: Any,
    *,
    query: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    normalized_query = str(query or "").strip().lower()
    preferences: List[Dict[str, Any]] = []
    states: List[Dict[str, Any]] = []
    state_context = manager.get_state_context()

    with get_read_lock(manager):
        for memory in sorted(
            manager.weighted_memories.values(),
            key=lambda item: (
                float(item.get("last_hit_time") or item.get("last_access_time") or 0.0),
                float(item.get("weight") or 0.0),
            ),
            reverse=True,
        ):
            memory_type = str(memory.get("memory_type") or "dialogue").strip().lower()
            category = str(memory.get("category") or "uncategorized").strip().lower()
            searchable_text = " ".join(
                [
                    str(memory.get("content") or ""),
                    str(memory.get("readable_title") or ""),
                    str(memory.get("readable_summary") or ""),
                    " ".join(str(t).strip() for t in (memory.get("topics") or []) if str(t).strip()),
                ]
            ).lower()
            if normalized_query and normalized_query not in searchable_text:
                continue
            if memory_type == "preference" or category == "preference":
                if str(memory.get("status") or "active") != "active":
                    continue
                preferences.append(memory)
                continue
            if memory_type == "state" or category == "state":
                states.append(memory)

    active_states = manager.get_active_states()
    if normalized_query:
        filtered_active_states = []
        for item in active_states:
            text = " ".join(
                [
                    str(item.get("content") or ""),
                    str(item.get("status") or ""),
                    str(item.get("type") or ""),
                ]
            ).lower()
            if normalized_query in text:
                filtered_active_states.append(item)
        active_states = filtered_active_states

    return {
        "preferences": _apply_recall_ranking(preferences, limit=limit, source_layer="preference_memory"),
        "state_memories": _apply_recall_ranking(states, limit=limit, source_layer="state_memory"),
        "active_states": active_states[:limit],
        "state_context": state_context,
    }


def build_recall_bundle(
    manager: Any,
    *,
    query: str,
    limit: int = 10,
    history_limit: int = 30,
) -> Dict[str, Any]:
    semantic_memories = search_semantic_memories(
        manager,
        query=query,
        limit=limit,
    )
    preference_state = get_preference_state_memories(
        manager,
        query=query,
        limit=limit,
    )
    return {
        "semantic_memories": semantic_memories,
        "preference_state": preference_state,
        "history_limit": history_limit,
    }
