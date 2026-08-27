"""主动关怀话题多样性检测

从 prompt_builder.py 拆分而来，包含独立的话题多样性检测功能：
- 话题类别检测
- 关键词重叠计算
- 话题冷却期检查
- 话题多样性约束构建
"""

from typing import Any, Dict, Tuple

from core.services.active_care.shared.constants import TopicKeywords
from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
    TOPIC_DIVERSITY_SLEEP_WARNING,
    TOPIC_DIVERSITY_GREETING_WARNING,
    TOPIC_DIVERSITY_CARE_WARNING,
    TOPIC_DIVERSITY_VEHICLE_WARNING,
    TOPIC_DIVERSITY_FOOD_WARNING,
    TOPIC_DIVERSITY_STUDY_WARNING,
    TOPIC_DIVERSITY_GENERIC_WARNING,
)


def detect_topic_category(text: str) -> str:
    """检测文本所属的话题类别"""
    text_lower = str(text or "").strip().lower()
    if not text_lower:
        return "unknown"
    scores = {}
    for category, keywords in TopicKeywords.__dict__.items():
        if category.startswith("_"):
            continue
        kw_list = getattr(TopicKeywords, category, None)
        if not isinstance(kw_list, list):
            continue
        count = sum(1 for kw in kw_list if kw.lower() in text_lower)
        if count > 0:
            scores[category] = count
    if not scores:
        return "other"
    return max(scores, key=scores.get)


def _compute_keyword_overlap(text_a: str, text_b: str, min_len: int = 2) -> float:
    """计算两段文本的关键词重叠率

    使用2-gram交集占较短文本2-gram总数的比例（containment系数），
    比Jaccard更适合短文本相似度判断——只要一段文本的核心内容被另一段覆盖即可。
    """
    a_lower = str(text_a or "").strip().lower()
    b_lower = str(text_b or "").strip().lower()
    if not a_lower or not b_lower:
        return 0.0
    # 提取2-gram集合
    a_grams = {a_lower[i:i + min_len] for i in range(len(a_lower) - min_len + 1)}
    b_grams = {b_lower[i:i + min_len] for i in range(len(b_lower) - min_len + 1)}
    if not a_grams or not b_grams:
        return 0.0
    intersection = a_grams & b_grams
    # containment: 交集占较短集合的比例
    min_size = min(len(a_grams), len(b_grams))
    return len(intersection) / min_size if min_size else 0.0


def check_topic_cooldown(
    proactive_state: Dict[str, Any],
    current_text: str,
    cooldown_minutes: int = 30,
    max_same_topic_count: int = 3,
    overlap_threshold: float = 0.25,
) -> Tuple[bool, str]:
    """检查当前话题是否处于冷却期

    返回 (是否需要冷却, 话题类别)。
    """
    current_topic = detect_topic_category(current_text)
    recent_contents = proactive_state.get("recent_sent_contents") or []
    if not isinstance(recent_contents, list) or not recent_contents:
        return False, current_topic

    # 已知类别：按类别匹配计数
    if current_topic not in ("other", "unknown"):
        same_topic_count = 0
        for content in recent_contents[:5]:
            if detect_topic_category(content) == current_topic:
                same_topic_count += 1
        if same_topic_count >= max_same_topic_count:
            return True, current_topic
        return False, current_topic

    # 未知类别（other/unknown）：用关键词重叠检测是否在重复同一话题
    overlap_count = 0
    for content in recent_contents[:5]:
        overlap = _compute_keyword_overlap(current_text, content)
        if overlap >= overlap_threshold:
            overlap_count += 1
    if overlap_count >= max_same_topic_count:
        return True, current_topic
    return False, current_topic


def build_topic_diversity_constraint(
    proactive_state: Dict[str, Any],
    current_candidate: str,
) -> str:
    """根据话题冷却状态构建多样性约束提示词"""
    need_cooldown, topic = check_topic_cooldown(proactive_state, current_candidate)
    if not need_cooldown:
        return ""
    alternatives = {
        "SLEEP": TOPIC_DIVERSITY_SLEEP_WARNING,
        "GREETING": TOPIC_DIVERSITY_GREETING_WARNING,
        "CARE": TOPIC_DIVERSITY_CARE_WARNING,
        "VEHICLE": TOPIC_DIVERSITY_VEHICLE_WARNING,
        "FOOD": TOPIC_DIVERSITY_FOOD_WARNING,
        "STUDY": TOPIC_DIVERSITY_STUDY_WARNING,
    }
    result = alternatives.get(topic, "")
    # 兜底：未知类别也触发通用警告
    if not result and topic in ("other", "unknown"):
        result = TOPIC_DIVERSITY_GENERIC_WARNING
    return result
