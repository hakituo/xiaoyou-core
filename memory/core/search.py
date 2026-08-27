from __future__ import annotations
import time
import random
import logging
from typing import List, Dict, Any, Optional, Set, Callable

from memory.core.scoring_utils import DEFAULT_SCORING_CONFIG

logger = logging.getLogger(__name__)


def hybrid_search(
    query: str,
    weighted_memories: Dict[str, Dict[str, Any]],
    keyword_index: Dict[str, List[str]],
    keyword_graph: Dict[str, Dict[str, int]],
    extract_keywords: Callable[[str], Set[str]],
    expand_keywords: Callable[[List[str], Dict[str, Dict[str, int]], int], List[str]],
    search_by_similarity_fn: Callable[..., List[Dict[str, Any]]],
    passes_recall_filter: Callable[
        [random.Random, float, Dict[str, Any], float, float], bool
    ],
    apply_time_decay: Callable[[float, float], float],
    detect_emotion_fn: Optional[Callable[[str], str]] = None,
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
    """混合搜索：结合关键词、向量相似度和权重的搜索方法"""

    base_keywords = list(extract_keywords(query))
    keywords = expand_keywords(
        base_keywords, keyword_graph, top_k=max(0, int(associative_top_k or 0))
    )

    inferred_emotion = emotion
    if inferred_emotion is None and detect_emotion_fn:
        try:
            detected = detect_emotion_fn(query)
            if detected and detected != "neutral":
                inferred_emotion = detected
        except Exception:
            inferred_emotion = None

    # 增加召回基数，以便后续进行概率过滤
    search_limit = limit * 5 if use_probability else limit * 2

    vector_results = search_by_similarity_fn(
        query,
        limit=search_limit,
        min_similarity=min_similarity,
        min_weight=min_weight,
    )

    results_with_scores = []
    now = time.time()
    local_rng = rng or (
        random.Random(random_seed) if random_seed is not None else random
    )

    for result in vector_results:
        if conflict_filter:
            if result.get("status") == "superseded":
                continue
            if (
                result.get("memory_type") == "preference"
                and result.get("status") != "active"
            ):
                continue

        if exclude_categories and result.get("category") in exclude_categories:
            continue

        if scope:
            mem_scopes = result.get("scopes")
            if mem_scopes is not None and isinstance(mem_scopes, list):
                if scope not in mem_scopes:
                    continue

        # 优先使用摘要内容进行展示
        content = result.get("summary") or result.get("content", "")

        content_lower = content.lower()
        explicit_keywords = result.get("keywords")
        if isinstance(explicit_keywords, list) and explicit_keywords:
            content_lower += " " + " ".join([str(k) for k in explicit_keywords]).lower()

        base_set = set(base_keywords)
        base_match = 0
        assoc_match = 0
        for keyword in keywords:
            if keyword in content_lower:
                if keyword in base_set:
                    base_match += 1
                else:
                    assoc_match += 1
        denom = max(len(base_keywords), 1)
        keyword_score = (
            min((base_match + assoc_match * 0.5) / denom, 1.0) if base_keywords else 0.0
        )

        similarity = float(
            result.get("similarity_score") or result.get("similarity") or 0.0
        )
        weighted_score = result.get("weighted_score")
        if weighted_score is None:
            w = float(result.get("weight") or 0.0)
            ts = float(result.get("timestamp") or 0.0)
            current_weight = apply_time_decay(w, ts)
            weight_score = min(current_weight / 10.0, 1.0)
            weighted_score = (
                similarity * DEFAULT_SCORING_CONFIG.similarity_weight
                + weight_score * DEFAULT_SCORING_CONFIG.weight_score_weight
            )

        emotion_bonus = 0.0
        if inferred_emotion:
            mem_emotions = result.get("emotions")
            if not isinstance(mem_emotions, list):
                mem_emotions = []
            primary = result.get("emotion")
            if isinstance(primary, str) and primary.strip():
                mem_emotions = list(mem_emotions) + [primary.strip().lower()]
            if inferred_emotion in set(
                [str(e).strip().lower() for e in mem_emotions if isinstance(e, str)]
            ):
                emotion_bonus = 0.15

        hybrid_score = (
            (keyword_score * keyword_weight)
            + (float(weighted_score) * (1 - keyword_weight))
            + emotion_bonus
        )

        # 3. 概率过滤逻辑 (模拟人类记忆)
        if use_probability:
            if not passes_recall_filter(
                local_rng, now, result, keyword_score, float(weighted_score)
            ):
                continue

        result["keyword_score"] = keyword_score
        result["hybrid_score"] = hybrid_score
        results_with_scores.append(result)

    # 按混合评分排序并截断
    results_with_scores.sort(key=lambda x: x.get("hybrid_score", 0), reverse=True)
    return results_with_scores[:limit]
