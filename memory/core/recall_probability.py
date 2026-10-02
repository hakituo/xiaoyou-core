"""
记忆召回概率过滤

核心算法（2026-07-29 升级）：
1. 时间衰减：艾宾浩斯遗忘曲线（幂律衰减）替代分段台阶
   R = (1 + t/τ)^(-β)，τ=24h, β=0.85
   - 1h 后保留率 ≈ 0.94
   - 1d 后保留率 ≈ 0.55
   - 1w 后保留率 ≈ 0.20
   - 1mo 后保留率 ≈ 0.10
2. 召回概率：sigmoid 融合（替代 uniform 基础项）
   在 logit 空间组合 weight/relevance/recency，再 σ 压回 [0,1]
"""
from __future__ import annotations

import math
from typing import Any, Dict

# 艾宾浩斯幂律衰减参数
_TAU_HOURS = 24.0   # 时间常数：1天为参考点
_DECAY_BETA = 0.85  # 衰减指数：控制衰减速率
_MIN_DECAY = 0.05   # 永久保留最低衰减系数

# Sigmoid 中心化偏置：让默认记忆的召回概率约 0.3
_LOGIT_BIAS = -1.5


def _compute_time_decay(hours_age: float) -> float:
    """艾宾浩斯遗忘曲线：幂律衰减 R = (1 + t/τ)^(-β)

    Args:
        hours_age: 记忆年龄（小时）

    Returns:
        float: 衰减系数 [0.05, 1.0]
    """
    if hours_age <= 0:
        return 1.0
    decay = (1.0 + hours_age / _TAU_HOURS) ** (-_DECAY_BETA)
    return max(_MIN_DECAY, decay)


def _sigmoid(x: float) -> float:
    """数值稳定的 sigmoid 函数"""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def passes_recall_filter(
    rng: Any,
    now: float,
    result: Dict[str, Any],
    keyword_score: float,
    weighted_score: float,
) -> bool:
    """概率召回过滤：sigmoid 融合 + 艾宾浩斯衰减

    Args:
        rng: 随机数生成器
        now: 当前时间戳
        result: 记忆字典
        keyword_score: 关键词匹配分
        weighted_score: 权重评分

    Returns:
        bool: 是否通过召回过滤
    """
    is_important = bool(result.get("is_important", False))
    weight = float(result.get("weight", 0) or 0)
    timestamp = float(result.get("timestamp", 0) or 0)
    category = result.get("category")
    memory_type = result.get("memory_type")

    # 硬性保留：重要记忆/偏好/高权重记忆直接通过
    if (
        is_important
        or weight > 7.0
        or category == "preference"
        or memory_type == "preference"
    ):
        return True

    # 1. 连续时间衰减（替代原分段台阶）
    hours_age = (now - timestamp) / 3600.0 if timestamp else 999999.0
    time_decay = _compute_time_decay(hours_age)

    # 2. Sigmoid 概率融合（替代原 uniform 基础项）
    #    在 logit 空间加权组合，避免 uniform 抹掉权重差异
    weight_term = weight / 5.0                                # weight=10 -> +2.0
    relevance = max(float(keyword_score or 0.0), float(weighted_score or 0.0))
    relevance_term = relevance * 2.0                          # [0,1] -> [0,2]
    recency_term = (time_decay - 0.5) * 4.0                   # [0,1] -> [-2,2]

    logit = weight_term + relevance_term + recency_term + _LOGIT_BIAS
    recall_prob = _sigmoid(logit)
    recall_prob = min(recall_prob, 0.9)

    return float(rng.random()) <= recall_prob
