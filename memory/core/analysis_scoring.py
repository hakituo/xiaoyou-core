"""融合裁决的打分与风险分级（纯函数，不含记忆读写）。

从 ``memory.core.analysis_ops`` 拆出。拆分是纯搬家：未改逻辑、命名与断言。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from memory.core.analysis_types import (
    DEFAULT_FUSION_CONFIG,
    RISK_CATEGORIES,
    RISK_MEMORY_TYPES,
    FusionConfig,
    _clean_category,
    _clean_topics,
)


def _compute_rule_score(
    original_topics: List[str],
    original_category: str,
    config: FusionConfig = DEFAULT_FUSION_CONFIG,
) -> float:
    rule_topic_strength = min(1.0, float(len(original_topics)) / 8.0)
    rule_category_strength = 1.0 if original_category != "uncategorized" else 0.0
    return round(
        min(1.0, max(0.0,
            (config.rule_topic_strength * rule_topic_strength)
            + (config.rule_category_strength * rule_category_strength)
        )),
        4,
    )


def _compute_consistency_score(
    original_topics: List[str],
    ai_topics: List[str],
    original_category: str,
    ai_category: str,
    rule_discourse_label: str,
    ai_discourse_label: str,
    config: FusionConfig = DEFAULT_FUSION_CONFIG,
) -> float:
    topic_union = set(original_topics) | set(ai_topics)
    topic_intersection = set(original_topics) & set(ai_topics)
    topic_consistency = 1.0 if not topic_union else float(len(topic_intersection)) / float(len(topic_union))
    category_consistency = 1.0 if original_category == ai_category else 0.0
    discourse_consistency = 1.0 if rule_discourse_label == ai_discourse_label else 0.0
    return round(
        min(1.0, max(0.0,
            (config.consistency_topic * topic_consistency)
            + (config.consistency_category * category_consistency)
            + (config.consistency_discourse * discourse_consistency)
        )),
        4,
    )


def _compute_stability_score(
    ai_topics: List[str],
    ai_category: str,
    history: List[Dict[str, Any]],
) -> float:
    if not history:
        return 0.7
    same_count = 0
    for h in history:
        ht = _clean_topics(h.get("topics"))
        hc = _clean_category(h.get("category"))
        if set(ht) == set(ai_topics) and hc == ai_category:
            same_count += 1
    return round(float(same_count) / float(len(history)), 4)


def _compute_final_confidence(
    s_rule: float,
    s_ai: float,
    s_consistency: float,
    s_stability: float,
    config: FusionConfig = DEFAULT_FUSION_CONFIG,
) -> float:
    return round(
        min(1.0, max(0.0,
            (config.s_rule * s_rule)
            + (config.s_ai * s_ai)
            + (config.s_consistency * s_consistency)
            + (config.s_stability * s_stability)
        )),
        4,
    )


def _compute_trigger_decision(
    *,
    rule_blocked: bool,
    rule_state_event: str,
    rule_discourse_label: str,
    ai_trigger_allowed: bool,
    ai_state_event: str,
    s_consistency: float,
    config: FusionConfig = DEFAULT_FUSION_CONFIG,
) -> Tuple[str, float]:
    trigger_rule_signal = 0.0 if rule_blocked else (1.0 if rule_state_event != "NONE" else 0.35)
    trigger_ai_signal = 1.0 if (ai_trigger_allowed and ai_state_event != "NONE") else 0.0
    trigger_state_consistency = 1.0 if rule_state_event == ai_state_event else 0.0
    trigger_final_confidence = round(
        min(1.0, max(0.0,
            (config.trigger_rule_signal * trigger_rule_signal)
            + (config.trigger_ai_signal * trigger_ai_signal)
            + (config.trigger_state_consistency * trigger_state_consistency)
            + (config.trigger_consistency * s_consistency)
        )),
        4,
    )
    if rule_blocked or not ai_trigger_allowed or ai_state_event == "NONE":
        trigger_decision = "deny"
    elif trigger_final_confidence >= config.trigger_allow_threshold:
        trigger_decision = "allow"
    else:
        trigger_decision = "manual_review"
    return trigger_decision, trigger_final_confidence


def _assess_risk_level(
    original_category: str,
    ai_category: str,
    memory_type: str,
    override_threshold: float,
    supplement_threshold: float,
) -> Tuple[str, float, float]:
    risk_level = "normal"
    effective_override_threshold = override_threshold
    effective_supplement_threshold = supplement_threshold
    if (
        original_category in RISK_CATEGORIES
        or ai_category in RISK_CATEGORIES
        or memory_type in RISK_MEMORY_TYPES
    ):
        risk_level = "high"
        effective_override_threshold = min(0.95, max(override_threshold, 0.9))
        effective_supplement_threshold = min(
            effective_override_threshold,
            max(supplement_threshold, 0.7),
        )
    elif original_category == "uncategorized" and ai_category != "uncategorized":
        risk_level = "promote_uncategorized"
        effective_supplement_threshold = max(0.45, supplement_threshold)
    return risk_level, effective_override_threshold, effective_supplement_threshold
