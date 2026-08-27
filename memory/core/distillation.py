# Memory Distillation Module (Consolidation and Trimming)

import time
from typing import List, Dict, Any, Callable


def _calculate_message_score(msg: Dict[str, Any], current_time: float) -> float:
    """计算消息的综合评分，用于决定保留优先级
    
    评分公式：基础分 + 权重分 + 时间分
    - 基础分：重要消息 +100，确保优先保留
    - 权重分：weight * 10，权重越高分数越高
    - 时间分：基于时间戳的衰减分，越新分数越高
    """
    score = 0.0
    
    # 重要消息基础分
    if msg.get("is_important"):
        score += 100.0
    
    # 权重分
    weight = float(msg.get("weight", 0) or 0)
    score += weight * 10.0
    
    # 时间分（最近1小时内的消息加分）
    timestamp = float(msg.get("timestamp", 0) or 0)
    if timestamp > 0:
        age_hours = (current_time - timestamp) / 3600.0
        # 最近1小时内的消息有额外加分
        if age_hours < 1.0:
            score += 50.0 * (1.0 - age_hours)
        elif age_hours < 24.0:
            score += 10.0 * (1.0 - age_hours / 24.0)
    
    return score


def trim_short_term_memory(
    short_term_memory: List[Dict[str, Any]],
    max_short_term: int,
    detect_topics_fn: Callable[[str], List[str]],
    trim_threshold: int = None,
) -> tuple:
    """
    修剪短期记忆，综合考虑重要性和时间近度

    核心原则：
    1. 重要消息（is_important=True）有更高保留优先级，但仍有配额上限
    2. 高权重消息（weight高）优先保留
    3. 最近的消息优先保留（马尔科夫性质）

    策略：
    1. 将消息分为"重要"和"普通"两类，各占配额上限的 50%/50%
    2. 每类内部按综合评分（权重+时间）选择保留
    3. 如果某类消息不足配额，剩余配额让给另一类

    Args:
        short_term_memory: 短期记忆列表
        max_short_term: 最大保留条数（存储上限）
        detect_topics_fn: 话题检测函数
        trim_threshold: 修剪触发阈值，超过此数量触发修剪，修剪后保留此数量。默认与 max_short_term 相同

    Returns:
        tuple: (修剪后的短期记忆列表, 被移除的消息列表)
    """
    effective_threshold = trim_threshold if trim_threshold is not None else max_short_term

    if len(short_term_memory) <= effective_threshold:
        return short_term_memory, []

    try:
        short_term_memory.sort(key=lambda x: x.get("timestamp", 0))
    except Exception:
        pass

    current_time = time.time()

    # 分离重要消息和普通消息
    important_msgs = []
    normal_msgs = []
    for msg in short_term_memory:
        if msg.get("is_important"):
            important_msgs.append(msg)
        else:
            normal_msgs.append(msg)

    # important 消息最多占 50% 配额,避免全部 important 时 trim 无效
    # 如果 important 消息不足配额,剩余让给普通消息
    important_quota = min(len(important_msgs), effective_threshold // 2)
    normal_quota = effective_threshold - important_quota

    # 按综合评分选择消息(important 消息在 _calculate_message_score 中已有 +100 基础分)
    kept_important = _select_by_score(important_msgs, important_quota, current_time)
    kept_normal = _select_by_score(normal_msgs, normal_quota, current_time)

    # 合并去重
    kept_ids = set()
    merged = []
    for msg in kept_important + kept_normal:
        mid = msg.get("id")
        if mid and mid in kept_ids:
            continue
        if mid:
            kept_ids.add(mid)
        merged.append(msg)

    merged.sort(key=lambda x: x.get("timestamp", 0))

    removed = [m for m in short_term_memory if m.get("id") not in kept_ids]

    return merged, removed


def _select_by_score(messages: List[Dict[str, Any]], quota: int, current_time: float) -> List[Dict[str, Any]]:
    """按综合评分选择消息，评分高的优先保留"""
    if len(messages) <= quota:
        return list(messages)

    # 计算每条消息的评分
    scored_msgs = []
    for msg in messages:
        score = _calculate_message_score(msg, current_time)
        scored_msgs.append((score, msg))
    
    # 按评分降序排序，选择前quota条
    scored_msgs.sort(key=lambda x: x[0], reverse=True)
    return [msg for _, msg in scored_msgs[:quota]]
