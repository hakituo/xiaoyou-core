"""
统一评分工具模块

该模块提供记忆系统的统一评分计算函数，消除代码重复，
确保评分逻辑的一致性和可维护性。

优化内容:
1. 统一混合评分计算
2. 统一召回排序评分
3. 统一衰减计算
"""

import time
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ScoringConfig:
    """评分配置"""
    similarity_weight: float = 0.7
    weight_score_weight: float = 0.3
    emotion_bonus: float = 0.15
    max_weight_score: float = 10.0
    
    source_trust_weight: float = 0.20
    recent_hit_weight: float = 0.20
    correction_penalty_weight: float = 0.15
    base_score_weight: float = 0.55


DEFAULT_SCORING_CONFIG = ScoringConfig()


def compute_hybrid_score(
    memory: Dict[str, Any],
    similarity: float,
    emotion: Optional[str] = None,
    config: Optional[ScoringConfig] = None,
) -> float:
    """
    计算混合评分 (向量相似度 + 权重 + 情绪)
    
    Args:
        memory: 记忆字典
        similarity: 向量相似度 (0.0-1.0)
        emotion: 目标情绪 (可选)
        config: 评分配置
        
    Returns:
        float: 混合评分
    """
    cfg = config or DEFAULT_SCORING_CONFIG
    
    weight_score = min(
        float(memory.get("weight", 1.0) / cfg.max_weight_score),
        1.0
    )
    
    emotion_score = 0.0
    if emotion and emotion in memory.get("emotions", []):
        emotion_score = cfg.emotion_bonus
    
    hybrid_score = (
        similarity * cfg.similarity_weight
        + weight_score * cfg.weight_score_weight
        + emotion_score
    )
    
    return round(hybrid_score, 4)


def compute_hybrid_score_with_result(
    memory: Dict[str, Any],
    similarity: float,
    emotion: Optional[str] = None,
    config: Optional[ScoringConfig] = None,
) -> Dict[str, Any]:
    """
    计算混合评分并更新记忆字典
    
    Args:
        memory: 记忆字典 (会被修改)
        similarity: 向量相似度
        emotion: 目标情绪
        config: 评分配置
        
    Returns:
        Dict[str, Any]: 更新后的记忆字典
    """
    result = dict(memory)
    result["similarity"] = similarity
    result["hybrid_score"] = compute_hybrid_score(result, similarity, emotion, config)
    return result


def score_source_trust(memory: Dict[str, Any]) -> float:
    """
    计算来源信任评分
    
    Args:
        memory: 记忆字典
        
    Returns:
        float: 来源信任评分 (0.0-1.0)
    """
    memory_type = str(memory.get("memory_type") or "dialogue").strip().lower()
    category = str(memory.get("category") or "uncategorized").strip().lower()
    source = str(memory.get("source") or "chat").strip().lower()
    
    if memory_type in {"preference", "state"} or category in {"preference", "state"}:
        return 1.0
    if source in {"journal", "workspace", "active_care", "system_profile"}:
        return 0.9
    if memory_type == "event_summary":
        return 0.82
    if source in {"assistant", "user"}:
        return 0.72
    return 0.6


def score_recent_hit(memory: Dict[str, Any]) -> float:
    """
    计算最近命中评分（连续衰减，替代原分段台阶）

    使用幂律衰减：score = (1 + t/τ)^(-β)
    - τ = 1 小时（参考点）
    - β = 0.5（衰减速率）
    - 1h 后 ≈ 0.71，1d 后 ≈ 0.20，1w 后 ≈ 0.08

    Args:
        memory: 记忆字典

    Returns:
        float: 最近命中评分 (0.05-1.0)
    """
    try:
        hit_ts = float(
            memory.get("last_hit_time")
            or memory.get("last_access_time")
            or 0.0
        )
    except (TypeError, ValueError):
        hit_ts = 0.0

    if hit_ts <= 0:
        return 0.0

    age_seconds = max(0.0, time.time() - hit_ts)
    if age_seconds <= 0:
        return 1.0

    # 幂律衰减：连续函数，避免分段台阶的边界跳变
    hours_age = age_seconds / 3600.0
    decay = (1.0 + hours_age) ** (-0.5)
    return max(0.05, min(1.0, decay))


def score_correction_penalty(memory: Dict[str, Any]) -> float:
    """
    计算修正惩罚评分
    
    Args:
        memory: 记忆字典
        
    Returns:
        float: 修正惩罚评分 (0.0-1.0)
    """
    metadata = memory.get("metadata")
    if not isinstance(metadata, dict):
        return 0.0
    
    decision_trace = metadata.get("decision_trace")
    if isinstance(decision_trace, dict):
        action = str(decision_trace.get("action") or "").strip().lower()
        if action == "rollback":
            return 0.35
        if action == "reject":
            return 0.15
    
    if metadata.get("fuse_last_action") == "rollback":
        return 0.35
    
    return 0.0


def compute_recall_rank_score(
    memory: Dict[str, Any],
    base_score: Optional[float] = None,
    config: Optional[ScoringConfig] = None,
) -> float:
    """
    计算召回排序评分
    
    Args:
        memory: 记忆字典
        base_score: 基础评分 (可选，自动从 memory 提取)
        config: 评分配置
        
    Returns:
        float: 召回排序评分
    """
    cfg = config or DEFAULT_SCORING_CONFIG
    
    if base_score is None:
        base_score = float(
            memory.get("weighted_score")
            or memory.get("hybrid_score")
            or memory.get("similarity")
            or memory.get("weight")
            or 0.0
        )
    
    source_trust = score_source_trust(memory)
    recent_hit = score_recent_hit(memory)
    correction_penalty = score_correction_penalty(memory)
    
    recall_rank_score = (
        cfg.base_score_weight * base_score
        + cfg.source_trust_weight * source_trust
        + cfg.recent_hit_weight * recent_hit
        - cfg.correction_penalty_weight * correction_penalty
    )
    
    return round(recall_rank_score, 4)


def apply_recall_ranking(
    memories: List[Dict[str, Any]],
    limit: int,
    source_layer: str,
    config: Optional[ScoringConfig] = None,
) -> List[Dict[str, Any]]:
    """
    应用召回排序
    
    Args:
        memories: 记忆列表
        limit: 返回数量限制
        source_layer: 来源层标识
        config: 评分配置
        
    Returns:
        List[Dict[str, Any]]: 排序后的记忆列表
    """
    ranked: List[Dict[str, Any]] = []
    
    for memory in memories:
        item = dict(memory)
        recall_rank_score = compute_recall_rank_score(item, config=config)
        
        item["source_layer"] = source_layer
        item["source_trust_score"] = round(score_source_trust(item), 4)
        item["recent_hit_score"] = round(score_recent_hit(item), 4)
        item["correction_penalty"] = round(score_correction_penalty(item), 4)
        item["recall_rank_score"] = recall_rank_score
        
        ranked.append(item)
    
    ranked.sort(
        key=lambda x: (
            float(x.get("recall_rank_score") or 0.0),
            float(x.get("weight") or 0.0),
            float(x.get("timestamp") or 0.0),
        ),
        reverse=True,
    )
    
    return ranked[:limit]


def batch_compute_hybrid_scores(
    memories: List[Dict[str, Any]],
    similarities: List[float],
    emotion: Optional[str] = None,
    config: Optional[ScoringConfig] = None,
) -> List[Dict[str, Any]]:
    """
    批量计算混合评分
    
    Args:
        memories: 记忆列表
        similarities: 相似度列表 (与 memories 一一对应)
        emotion: 目标情绪
        config: 评分配置
        
    Returns:
        List[Dict[str, Any]]: 更新后的记忆列表
    """
    if len(memories) != len(similarities):
        raise ValueError("memories 和 similarities 长度不匹配")
    
    results = []
    for memory, similarity in zip(memories, similarities):
        result = compute_hybrid_score_with_result(memory, similarity, emotion, config)
        results.append(result)
    
    return results


def get_scoring_stats() -> Dict[str, Any]:
    """
    获取评分配置统计信息
    
    Returns:
        Dict[str, Any]: 配置信息
    """
    return {
        "config": {
            "similarity_weight": DEFAULT_SCORING_CONFIG.similarity_weight,
            "weight_score_weight": DEFAULT_SCORING_CONFIG.weight_score_weight,
            "emotion_bonus": DEFAULT_SCORING_CONFIG.emotion_bonus,
            "max_weight_score": DEFAULT_SCORING_CONFIG.max_weight_score,
        },
        "version": "1.0.0",
    }
