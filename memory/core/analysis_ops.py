import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple
from memory.core.discourse import analyze_discourse, infer_state_event
from memory.core.lock_utils import get_read_lock, get_write_lock


@dataclass(frozen=True)
class FusionConfig:
    """融合裁决配置，替代硬编码字典"""
    s_rule: float = 0.40
    s_ai: float = 0.20
    s_consistency: float = 0.30
    s_stability: float = 0.10

    consistency_topic: float = 0.55
    consistency_category: float = 0.20
    consistency_discourse: float = 0.25

    trigger_rule_signal: float = 0.40
    trigger_ai_signal: float = 0.35
    trigger_state_consistency: float = 0.15
    trigger_consistency: float = 0.10

    rule_topic_strength: float = 0.6
    rule_category_strength: float = 0.4

    trigger_allow_threshold: float = 0.72


DEFAULT_FUSION_CONFIG = FusionConfig()

BLOCKED_DISCOURSE_LABELS = frozenset({
    "RETROSPECTIVE_SELF_REPORT",
    "FUTURE_PLAN",
    "HYPOTHETICAL",
    "REPORTED_SPEECH",
    "INSTRUCTION",
    "QUESTION",
})

RISK_CATEGORIES = frozenset({"preference", "sensitive", "state"})
RISK_MEMORY_TYPES = frozenset({"preference", "sensitive", "state", "profile"})

DISCOURSE_WEIGHT_PENALTIES = {
    "INSTRUCTION": -0.4,
    "QUESTION": -0.4,
    "REPORTED_SPEECH": -0.4,
    "HYPOTHETICAL": -0.25,
    "FUTURE_PLAN": -0.25,
    "RETROSPECTIVE_SELF_REPORT": -0.1,
}


@dataclass
class FusionResult:
    """融合裁决结果，替代 _write_fusion_metadata 的 20+ 参数"""
    action: str = "reject"
    final_confidence: float = 0.0
    s_rule: float = 0.0
    s_ai: float = 0.0
    s_consistency: float = 0.0
    s_stability: float = 0.0
    trigger_final_confidence: float = 0.0
    trigger_decision: str = "deny"
    rule_discourse_label: str = "GENERIC_CHAT"
    rule_state_event: str = "NONE"
    ai_discourse_label: str = "GENERIC_CHAT"
    ai_state_event: str = "NONE"
    override_threshold: float = 0.75
    supplement_threshold: float = 0.5
    effective_override_threshold: float = 0.75
    effective_supplement_threshold: float = 0.5
    risk_level: str = "normal"
    allow_override: bool = False
    original_category: str = "uncategorized"
    original_topics: List[str] = field(default_factory=list)
    ai_category: str = "uncategorized"
    ai_topics: List[str] = field(default_factory=list)
    memory_type: str = "dialogue"
    now_ts: float = 0.0


def _ensure_analysis_meta(metadata: Dict[str, Any]) -> Dict[str, Any]:
    analysis_meta = metadata.get("analysis_meta")
    if not isinstance(analysis_meta, dict):
        analysis_meta = {}
        metadata["analysis_meta"] = analysis_meta
    return analysis_meta


def _safe_float(value: Any, default: float = 0.0, min_val: float = 0.0, max_val: float = 1.0) -> float:
    try:
        return max(min_val, min(max_val, float(value)))
    except Exception:
        return default


def _clean_topics(topics: Any, limit: int = 8) -> List[str]:
    result = []
    for t in (topics or []):
        ts = str(t).strip()
        if ts and ts not in result:
            result.append(ts)
    return result[:limit]


def _clean_category(category: Any) -> str:
    return str(category or "uncategorized").strip() or "uncategorized"


def _build_ai_shadow_dict(
    *,
    topics: List[str],
    category: str,
    confidence: float,
    weight_delta: float,
    discourse_label: str = "GENERIC_CHAT",
    state_event: str = "NONE",
    trigger_allowed: bool = False,
    reason: str = "",
    source: str = "llm",
    status: str = "ok",
    latency_ms: float = 0.0,
    version: str = "s_ai_shadow_v1",
    updated_at: float = 0.0,
) -> Dict[str, Any]:
    return {
        "topics": topics[:8],
        "category": category,
        "confidence": confidence,
        "weight_delta": weight_delta,
        "bert_topics": topics[:8],
        "bert_category": category,
        "discourse_label": discourse_label,
        "state_event": state_event,
        "trigger_allowed": trigger_allowed,
        "reason": reason[:256],
        "source": source,
        "status": status,
        "latency_ms": round(float(latency_ms or 0.0), 2),
        "version": version,
        "updated_at": updated_at,
    }


def _build_bert_shadow_input(
    manager: Any,
    *,
    content: str,
    category: str,
    topics: List[str],
    weight: float,
    memory: Dict[str, Any],
) -> str:
    candidate = dict(memory)
    candidate["content"] = str(content or "").strip()
    candidate["category"] = str(category or "uncategorized").strip() or "uncategorized"
    candidate["topics"] = [str(item).strip() for item in topics if str(item).strip()]
    candidate["weight"] = float(weight or 0.0)
    normalized, _ = manager._normalize_memory_record(candidate)
    readable_title = str(normalized.get("readable_title") or "").strip()
    readable_summary = str(normalized.get("readable_summary") or "").strip()
    normalized_topics = [
        str(item).strip() for item in (normalized.get("topics") or []) if str(item).strip()
    ]
    sections = []
    if readable_title:
        sections.append(f"标题：{readable_title}")
    if readable_summary:
        sections.append(f"摘要：{readable_summary}")
    if normalized.get("category"):
        sections.append(f"规则分类：{normalized.get('category')}")
    if normalized_topics:
        sections.append(f"规则主题：{'、'.join(normalized_topics[:6])}")
    sections.append(f"原文：{str(content or '').strip()}")
    return "\n".join(section for section in sections if section)


def _run_bert_shadow_analysis(
    bert_input_text: str,
) -> Dict[str, Any]:
    from core.services.data_ops.bert_analyzer import get_bert_analyzer

    started_at = time.time()
    analyzer = get_bert_analyzer()
    result = analyzer.analyze(bert_input_text)
    latency_ms = round((time.time() - started_at) * 1000.0, 2)
    if not isinstance(result, dict):
        result = {}

    topics = _clean_topics(result.get("topics"))
    category = _clean_category(result.get("category"))
    confidence = _safe_float(result.get("confidence"), 0.0, 0.0, 1.0)
    weight_delta = _safe_float(result.get("weight_delta"), 0.0, -2.0, 2.0)
    discourse_label = str(result.get("discourse_label") or "GENERIC_CHAT").strip() or "GENERIC_CHAT"
    state_event = str(result.get("state_event") or "NONE").strip() or "NONE"
    source = str(result.get("source") or "bert_local").strip() or "bert_local"
    reason = str(result.get("reason") or "").strip()
    status = "ok"
    if reason in {"bert_model_not_loaded", "embedding_failed", "empty_content"}:
        status = "skipped"
    return {
        "topics": topics[:8],
        "category": category,
        "confidence": confidence,
        "weight_delta": weight_delta,
        "discourse_label": discourse_label,
        "state_event": state_event,
        "trigger_allowed": bool(result.get("trigger_allowed", False)),
        "reason": reason or "bert_shadow",
        "source": source,
        "status": status,
        "latency_ms": latency_ms,
        "input_text": bert_input_text,
    }


def count_pending_analysis(manager: Any) -> int:
    counter = getattr(manager, '_pending_analysis_count', None)
    if counter is not None:
        return counter
    with get_read_lock(manager):
        count = 0
        for m in manager.weighted_memories.values():
            metadata = m.get("metadata")
            if isinstance(metadata, dict) and bool(metadata.get("analysis_pending", False)):
                count += 1
        return count


def get_pending_analysis_items(manager: Any, limit: int = 16) -> List[Dict[str, Any]]:
    max_items = max(1, int(limit))
    with get_read_lock(manager):
        pending_items: List[Tuple[float, Dict[str, Any]]] = []
        for memory_id, memory in manager.weighted_memories.items():
            metadata = memory.get("metadata")
            if not isinstance(metadata, dict):
                continue
            if not bool(metadata.get("analysis_pending", False)):
                continue
            pending_items.append(
                (
                    float(memory.get("timestamp") or 0.0),
                    {
                        "memory_id": memory_id,
                        "content": str(memory.get("content") or ""),
                        "rule_topics": list(memory.get("topics") or []),
                        "rule_category": str(memory.get("category") or "uncategorized"),
                        "rule_weight": float(memory.get("weight") or 0.0),
                    },
                )
            )
        pending_items.sort(key=lambda x: x[0])
        return [item for _, item in pending_items[:max_items]]


def attach_ai_shadow_result(
    manager: Any,
    memory_id: str,
    *,
    ai_topics: List[str],
    ai_category: str,
    ai_confidence: float,
    ai_weight_delta: float = 0.0,
    ai_discourse_label: str = "",
    ai_state_event: str = "",
    ai_trigger_allowed: bool = False,
    ai_reason: str = "",
    source: str = "llm",
    status: str = "ok",
    latency_ms: float = 0.0,
) -> bool:
    with get_write_lock(manager):
        memory = manager.weighted_memories.get(str(memory_id))
        if not isinstance(memory, dict):
            return False
        metadata = memory.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        ai_topics_clean = _clean_topics(ai_topics)
        ai_category_clean = _clean_category(ai_category)
        confidence = _safe_float(ai_confidence, 0.0, 0.0, 1.0)
        weight_delta = _safe_float(ai_weight_delta, 0.0, -2.0, 2.0)
        now_ts = time.time()

        shadow_dict = _build_ai_shadow_dict(
            topics=ai_topics_clean,
            category=ai_category_clean,
            confidence=confidence,
            weight_delta=weight_delta,
            discourse_label=str(ai_discourse_label or "").strip() or "GENERIC_CHAT",
            state_event=str(ai_state_event or "").strip() or "NONE",
            trigger_allowed=bool(ai_trigger_allowed),
            reason=str(ai_reason or ""),
            source=str(source or "llm"),
            status=str(status or "ok"),
            latency_ms=latency_ms,
            updated_at=now_ts,
        )
        # 维护 O(1) 计数器: 新增 ai_shadow 时递增
        previous_ai_shadow = metadata.get("ai_shadow")
        had_ai_shadow = isinstance(previous_ai_shadow, dict)
        metadata["ai_shadow"] = shadow_dict
        if not had_ai_shadow and hasattr(manager, '_ai_shadow_count'):
            manager._ai_shadow_count += 1

        analysis_meta = _ensure_analysis_meta(metadata)
        history = []
        if isinstance(previous_ai_shadow, dict):
            prev_history = previous_ai_shadow.get("history")
            if isinstance(prev_history, list):
                history = list(prev_history)
            history.append(
                {
                    "topics": list(previous_ai_shadow.get("topics") or [])[:8],
                    "category": str(previous_ai_shadow.get("category") or "uncategorized"),
                    "confidence": float(previous_ai_shadow.get("confidence") or 0.0),
                }
            )
        history = history[-3:]
        shadow_dict["history"] = history
        analysis_meta["ai_shadow"] = shadow_dict
        analysis_meta["state"] = "ai_shadow_done"
        analysis_meta["updated_at"] = now_ts
        memory["metadata"] = metadata
        manager._mark_keyword_index_dirty_locked(str(memory_id))
        manager.last_modified_time = now_ts
    manager._schedule_save()
    return True


def count_ai_shadow_results(manager: Any) -> int:
    counter = getattr(manager, '_ai_shadow_count', None)
    if counter is not None:
        return counter
    with get_read_lock(manager):
        count = 0
        for m in manager.weighted_memories.values():
            metadata = m.get("metadata")
            if not isinstance(metadata, dict):
                continue
            ai_shadow = metadata.get("ai_shadow")
            if isinstance(ai_shadow, dict):
                count += 1
        return count


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


def _apply_fusion_action(
    *,
    memory: Dict[str, Any],
    memory_id: str,
    original_topics: List[str],
    original_category: str,
    original_weight: float,
    ai_topics: List[str],
    ai_category: str,
    weight_delta: float,
    final_confidence: float,
    effective_override_threshold: float,
    effective_supplement_threshold: float,
    allow_override: bool,
    rollback_snapshot: Dict[str, Any],
    now_ts: float,
) -> Tuple[str, bool, bool]:
    action = "reject"
    changed = False
    rolled_back = False
    analysis_meta = _ensure_analysis_meta(memory.get("metadata") or {})

    if final_confidence >= effective_override_threshold and allow_override:
        action = "override"
        analysis_meta["override_snapshot"] = {
            "topics": original_topics[:8],
            "category": original_category,
            "weight": original_weight,
            "captured_at": now_ts,
        }
        if ai_topics:
            memory["topics"] = ai_topics[:8]
        if ai_category:
            memory["category"] = ai_category
        if abs(weight_delta) > 0:
            memory["weight"] = max(
                0.1, min(20.0, float(memory.get("weight") or 0.0) + weight_delta)
            )
        changed = True
    elif final_confidence >= effective_supplement_threshold:
        action = "supplement"
        merged_topics = list(original_topics)
        for t in ai_topics:
            if t not in merged_topics:
                merged_topics.append(t)
        memory["topics"] = merged_topics[:8]
        if original_category == "uncategorized" and ai_category != "uncategorized":
            memory["category"] = ai_category
        if abs(weight_delta) > 0:
            memory["weight"] = max(
                0.1, min(20.0, float(memory.get("weight") or 0.0) + weight_delta)
            )
        display_tags = [str(t).strip() for t in memory.get("display_tags") or []]
        display_tags = [t for t in display_tags if t]
        for t in ai_topics:
            if t not in display_tags:
                display_tags.append(t)
        memory["display_tags"] = display_tags[:8]
        changed = True
    elif rollback_snapshot:
        snapshot_topics = _clean_topics(rollback_snapshot.get("topics"))
        snapshot_category = _clean_category(rollback_snapshot.get("category"))
        try:
            snapshot_weight = float(rollback_snapshot.get("weight") or 0.0)
        except Exception:
            snapshot_weight = original_weight
        if snapshot_topics:
            memory["topics"] = snapshot_topics[:8]
        memory["category"] = snapshot_category
        memory["weight"] = max(0.1, min(20.0, snapshot_weight))
        action = "rollback"
        changed = True
        rolled_back = True
        analysis_meta.pop("override_snapshot", None)

    return action, changed, rolled_back


def _write_fusion_metadata(
    *,
    memory: Dict[str, Any],
    ai_shadow: Dict[str, Any],
    result: FusionResult,
) -> None:
    """写入融合裁决元数据

    注意：ai_shadow 参数会被就地修改（添加 fuse_version/fuse_action/fuse_updated_at），
    因为 ai_shadow 是 metadata["ai_shadow"] 的引用，修改会直接反映到 metadata 中。
    """
    metadata = memory.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    analysis_meta = _ensure_analysis_meta(metadata)

    # 统一写入 analysis_meta["fusion"]，消除三重冗余
    fusion_data = {
        "action": result.action,
        "final_confidence": result.final_confidence,
        "s_rule": result.s_rule,
        "s_ai": result.s_ai,
        "s_consistency": result.s_consistency,
        "s_stability": result.s_stability,
        "trigger_final_confidence": result.trigger_final_confidence,
        "trigger_decision": result.trigger_decision,
        "rule_discourse_label": result.rule_discourse_label,
        "rule_state_event": result.rule_state_event,
        "ai_discourse_label": result.ai_discourse_label,
        "ai_state_event": result.ai_state_event,
        "override_min_confidence": result.override_threshold,
        "supplement_min_confidence": result.supplement_threshold,
        "effective_override_min_confidence": result.effective_override_threshold,
        "effective_supplement_min_confidence": result.effective_supplement_threshold,
        "risk_level": result.risk_level,
        "allow_override": bool(result.allow_override),
        "version": "s_fuse_v1",
        "updated_at": result.now_ts,
    }
    analysis_meta["fusion"] = fusion_data
    analysis_meta["state"] = "fusion_done"
    analysis_meta["last_action"] = result.action
    analysis_meta["updated_at"] = result.now_ts

    # 保留 metadata 顶层快捷字段（被 scoring_utils 等外部模块读取）
    metadata["fuse_source"] = "s_fuse_v1"
    metadata["fuse_last_action"] = result.action
    metadata["fuse_updated_at"] = result.now_ts
    metadata["decision_trace"] = {
        "rule_category": result.original_category,
        "rule_topics": result.original_topics[:8],
        "bert_category": result.ai_category,
        "bert_topics": result.ai_topics[:8],
        "memory_type": result.memory_type,
        "risk_level": result.risk_level,
        "action": result.action,
        "final_confidence": result.final_confidence,
        "effective_override_min_confidence": result.effective_override_threshold,
        "effective_supplement_min_confidence": result.effective_supplement_threshold,
        "trigger_decision": result.trigger_decision,
        "updated_at": result.now_ts,
        "version": "s_decision_trace_v1",
    }

    # ai_shadow 仅保留版本标记，详细数据统一从 analysis_meta["fusion"] 读取
    ai_shadow["fuse_version"] = "s_fuse_v1"
    ai_shadow["fuse_action"] = result.action
    ai_shadow["fuse_updated_at"] = result.now_ts
    metadata["ai_shadow"] = ai_shadow
    memory["metadata"] = metadata


def apply_ai_shadow_adjudication(
    manager: Any,
    *,
    limit: int = 16,
    override_min_confidence: float = 0.75,
    supplement_min_confidence: float = 0.5,
    allow_override: bool = False,
) -> Dict[str, Any]:
    max_items = max(1, int(limit))
    override_threshold = max(0.0, min(1.0, float(override_min_confidence)))
    supplement_threshold = max(0.0, min(1.0, float(supplement_min_confidence)))
    if supplement_threshold > override_threshold:
        supplement_threshold = override_threshold

    with get_write_lock(manager):
        candidate_ids: List[str] = []
        pending_all = 0
        for memory_id, memory in manager.weighted_memories.items():
            metadata = memory.get("metadata")
            if not isinstance(metadata, dict):
                continue
            ai_shadow = metadata.get("ai_shadow")
            if not isinstance(ai_shadow, dict):
                continue
            if str(ai_shadow.get("fuse_version") or "").strip() == "s_fuse_v1":
                continue
            pending_all += 1
            candidate_ids.append(memory_id)
        candidate_ids = candidate_ids[:max_items]
        if not candidate_ids:
            return {
                "processed": 0,
                "pending_before": pending_all,
                "pending_after": 0,
                "applied": 0,
                "rejected": 0,
                "updated_ids": [],
            }

        updated_ids: List[str] = []
        applied = 0
        rejected = 0
        rolled_back = 0
        now_ts = time.time()
        for memory_id in candidate_ids:
            memory = manager.weighted_memories.get(memory_id)
            if not isinstance(memory, dict):
                continue
            metadata = memory.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            ai_shadow = metadata.get("ai_shadow")
            if not isinstance(ai_shadow, dict):
                continue
            analysis_meta = _ensure_analysis_meta(metadata)

            confidence = _safe_float(ai_shadow.get("confidence"), 0.0, 0.0, 1.0)
            ai_topics = _clean_topics(ai_shadow.get("topics"))
            ai_category = _clean_category(ai_shadow.get("category"))
            weight_delta = _safe_float(ai_shadow.get("weight_delta"), 0.0, -2.0, 2.0)

            original_topics = _clean_topics(memory.get("topics"))
            original_category = _clean_category(memory.get("category"))
            original_weight = float(memory.get("weight") or 0.0)

            metadata_rule = metadata.get("analysis_meta") if isinstance(metadata, dict) else None
            rule_blocked = False
            rule_discourse_label = "GENERIC_CHAT"
            rule_state_event = "NONE"
            if isinstance(metadata_rule, dict):
                rule_block = metadata_rule.get("rule")
                if isinstance(rule_block, dict):
                    rule_discourse_label = str(
                        rule_block.get("discourse_label") or "GENERIC_CHAT"
                    ).strip() or "GENERIC_CHAT"
                    rule_state_event = str(
                        rule_block.get("state_event") or "NONE"
                    ).strip() or "NONE"
                    rule_blocked = rule_state_event == "NONE" and rule_discourse_label in BLOCKED_DISCOURSE_LABELS

            s_rule = _compute_rule_score(original_topics, original_category)
            s_ai = confidence
            ai_discourse_label = str(ai_shadow.get("discourse_label") or "GENERIC_CHAT").strip() or "GENERIC_CHAT"
            ai_state_event = str(ai_shadow.get("state_event") or "NONE").strip() or "NONE"
            ai_trigger_allowed = bool(ai_shadow.get("trigger_allowed", False))

            s_consistency = _compute_consistency_score(
                original_topics, ai_topics,
                original_category, ai_category,
                rule_discourse_label, ai_discourse_label,
            )

            ai_meta = analysis_meta.get("ai_shadow")
            history = []
            if isinstance(ai_meta, dict):
                if isinstance(ai_meta.get("history"), list):
                    history = list(ai_meta.get("history"))

            s_stability = _compute_stability_score(ai_topics, ai_category, history)
            final_confidence = _compute_final_confidence(s_rule, s_ai, s_consistency, s_stability)

            trigger_decision, trigger_final_confidence = _compute_trigger_decision(
                rule_blocked=rule_blocked,
                rule_state_event=rule_state_event,
                rule_discourse_label=rule_discourse_label,
                ai_trigger_allowed=ai_trigger_allowed,
                ai_state_event=ai_state_event,
                s_consistency=s_consistency,
            )

            memory_type = str(memory.get("memory_type") or "dialogue").strip().lower()
            risk_level, effective_override_threshold, effective_supplement_threshold = _assess_risk_level(
                original_category, ai_category, memory_type,
                override_threshold, supplement_threshold,
            )

            rollback_snapshot = analysis_meta.get("override_snapshot")
            if not isinstance(rollback_snapshot, dict):
                rollback_snapshot = {}

            action, changed, was_rolled_back = _apply_fusion_action(
                memory=memory,
                memory_id=memory_id,
                original_topics=original_topics,
                original_category=original_category,
                original_weight=original_weight,
                ai_topics=ai_topics,
                ai_category=ai_category,
                weight_delta=weight_delta,
                final_confidence=final_confidence,
                effective_override_threshold=effective_override_threshold,
                effective_supplement_threshold=effective_supplement_threshold,
                allow_override=allow_override,
                rollback_snapshot=rollback_snapshot,
                now_ts=now_ts,
            )
            if was_rolled_back:
                rolled_back += 1

            if changed:
                new_category = _clean_category(memory.get("category"))
                if original_category != new_category:
                    if original_category in manager.category_index:
                        if memory_id in manager.category_index[original_category]:
                            manager.category_index[original_category].remove(memory_id)
                    if memory_id not in manager.category_index[new_category]:
                        manager.category_index[new_category].append(memory_id)
                applied += 1
            else:
                rejected += 1

            fusion_result = FusionResult(
                action=action,
                final_confidence=final_confidence,
                s_rule=s_rule,
                s_ai=s_ai,
                s_consistency=s_consistency,
                s_stability=s_stability,
                trigger_final_confidence=trigger_final_confidence,
                trigger_decision=trigger_decision,
                rule_discourse_label=rule_discourse_label,
                rule_state_event=rule_state_event,
                ai_discourse_label=ai_discourse_label,
                ai_state_event=ai_state_event,
                override_threshold=override_threshold,
                supplement_threshold=supplement_threshold,
                effective_override_threshold=effective_override_threshold,
                effective_supplement_threshold=effective_supplement_threshold,
                risk_level=risk_level,
                allow_override=allow_override,
                original_category=original_category,
                original_topics=original_topics,
                ai_category=ai_category,
                ai_topics=ai_topics,
                memory_type=memory_type,
                now_ts=now_ts,
            )

            _write_fusion_metadata(
                memory=memory,
                ai_shadow=ai_shadow,
                result=fusion_result,
            )
            manager._mark_keyword_index_dirty_locked(memory_id)
            updated_ids.append(memory_id)

        manager.last_modified_time = now_ts
        pending_after = max(0, pending_all - len(updated_ids))

    if updated_ids:
        manager._schedule_save()
    return {
        "processed": len(updated_ids),
        "pending_before": pending_all,
        "pending_after": pending_after,
        "applied": applied,
        "rejected": rejected,
        "rolled_back": rolled_back,
        "updated_ids": updated_ids,
    }


def _prepare_pending_analysis(
    manager: Any,
    memory_id: str,
    memory: Dict[str, Any],
    now_ts: float,
) -> Dict[str, Any]:
    """准备待分析记忆的规则分析和BERT输入（无需持锁）

    将耗时的规则分析和BERT推理从此函数中提取出来，
    以便在锁外执行，避免长时间持有写锁阻塞其他操作。

    Returns:
        包含分析输入和中间结果的字典，供 _apply_pending_analysis_result 使用
    """
    content = str(memory.get("content") or "").strip()
    if not content:
        return {"skip": True, "memory_id": memory_id, "empty_content": True}

    old_category = _clean_category(memory.get("category"))
    topics = _clean_topics(manager._detect_topics(content))
    category = manager._classify_category(content) or "uncategorized"
    if category not in topics and category != "uncategorized":
        topics.append(category)
    topics = list(dict.fromkeys(topics))

    discourse = analyze_discourse(content)
    discourse_label = str(discourse.get("discourse_label") or "GENERIC_CHAT")

    emotions = [manager._detect_emotion(content)]
    emotions = [str(e).strip() for e in emotions if str(e).strip()]
    weight = manager.weight_calculator.calculate_initial_weight(
        content,
        bool(memory.get("is_important", False)),
        topics,
        emotions,
    )

    penalty = DISCOURSE_WEIGHT_PENALTIES.get(discourse_label, 0.0)
    if penalty < 0:
        weight = max(0.1, weight + penalty)

    search_keywords = sorted(list(manager._extract_keywords(content)))
    display_tags: List[str] = []
    for t in topics:
        if t and t not in display_tags:
            display_tags.append(t)
    for kw in search_keywords:
        if kw and kw not in display_tags:
            display_tags.append(kw)

    # 构建BERT输入（不执行推理）
    bert_input_text = _build_bert_shadow_input(
        manager,
        content=content,
        category=category,
        topics=topics,
        weight=weight,
        memory=memory,
    )

    return {
        "skip": False,
        "memory_id": memory_id,
        "empty_content": False,
        "content": content,
        "old_category": old_category,
        "topics": topics,
        "category": category,
        "discourse": discourse,
        "discourse_label": discourse_label,
        "emotions": emotions,
        "weight": weight,
        "search_keywords": search_keywords,
        "display_tags": display_tags,
        "bert_input_text": bert_input_text,
        "now_ts": now_ts,
    }


def _apply_pending_analysis_result(
    manager: Any,
    memory_id: str,
    memory: Dict[str, Any],
    prep: Dict[str, Any],
    bert_shadow: Dict[str, Any],
    now_ts: float,
) -> bool:
    """将分析结果应用到记忆记录（需要在写锁内执行）"""
    if prep.get("empty_content"):
        metadata = memory.get("metadata") or {}
        if isinstance(metadata, dict):
            if bool(metadata.get("analysis_pending", False)):
                if hasattr(manager, '_pending_analysis_count'):
                    manager._pending_analysis_count = max(0, manager._pending_analysis_count - 1)
            metadata["analysis_pending"] = False
            metadata["analysis_error"] = "empty_content"
            metadata["analysis_completed_at"] = now_ts
            analysis_meta = _ensure_analysis_meta(metadata)
            analysis_meta["state"] = "rule_failed"
            analysis_meta["error"] = "empty_content"
            analysis_meta["updated_at"] = now_ts
            memory["metadata"] = metadata
        return False

    topics = prep["topics"]
    category = prep["category"]
    emotions = prep["emotions"]
    weight = prep["weight"]
    search_keywords = prep["search_keywords"]
    display_tags = prep["display_tags"]
    discourse = prep["discourse"]
    discourse_label = prep["discourse_label"]
    old_category = prep["old_category"]

    memory["topics"] = topics
    memory["category"] = category
    memory["emotions"] = emotions
    memory["emotion"] = emotions[0] if emotions else "neutral"
    memory["weight"] = weight
    memory["search_keywords"] = search_keywords[:32]
    memory["keywords"] = search_keywords[:32]
    memory["display_tags"] = display_tags[:8]
    memory["last_access_time"] = now_ts

    metadata = memory.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    if bool(metadata.get("analysis_pending", False)):
        if hasattr(manager, '_pending_analysis_count'):
            manager._pending_analysis_count = max(0, manager._pending_analysis_count - 1)
    metadata["analysis_pending"] = False
    metadata["analysis_source"] = "rule_worker"
    metadata["analysis_completed_at"] = now_ts
    metadata["analysis_version"] = "s_rule_v1"
    analysis_meta = _ensure_analysis_meta(metadata)
    analysis_meta["rule"] = {
        "topics": topics[:8],
        "category": category,
        "weight": weight,
        "discourse_label": discourse_label,
        "state_event": infer_state_event(prep["content"], discourse),
        "version": "s_rule_v1",
        "completed_at": now_ts,
    }

    # 应用BERT推理结果
    bert_topics = _clean_topics(bert_shadow.get("topics"))
    bert_category = _clean_category(bert_shadow.get("category"))
    bert_confidence = _safe_float(bert_shadow.get("confidence"), 0.0, 0.0, 1.0)
    bert_weight_delta = _safe_float(bert_shadow.get("weight_delta"), 0.0, -2.0, 2.0)

    analysis_meta["bert_shadow"] = {
        "input_text": prep["bert_input_text"],
        "topics": bert_topics[:8],
        "category": bert_category,
        "confidence": bert_confidence,
        "weight_delta": bert_weight_delta,
        "discourse_label": str(bert_shadow.get("discourse_label") or "GENERIC_CHAT"),
        "state_event": str(bert_shadow.get("state_event") or "NONE"),
        "trigger_allowed": bool(bert_shadow.get("trigger_allowed", False)),
        "reason": str(bert_shadow.get("reason") or "")[:256],
        "source": str(bert_shadow.get("source") or "bert_local"),
        "status": str(bert_shadow.get("status") or "ok"),
        "latency_ms": float(bert_shadow.get("latency_ms") or 0.0),
        "version": "s_bert_shadow_v1",
        "updated_at": now_ts,
    }

    if str(bert_shadow.get("status") or "ok") == "ok":
        metadata["ai_shadow"] = _build_ai_shadow_dict(
            topics=bert_topics,
            category=bert_category,
            confidence=bert_confidence,
            weight_delta=bert_weight_delta,
            discourse_label=str(bert_shadow.get("discourse_label") or "GENERIC_CHAT"),
            state_event=str(bert_shadow.get("state_event") or "NONE"),
            trigger_allowed=bool(bert_shadow.get("trigger_allowed", False)),
            reason=str(bert_shadow.get("reason") or ""),
            source=str(bert_shadow.get("source") or "bert_local"),
            status=str(bert_shadow.get("status") or "ok"),
            latency_ms=float(bert_shadow.get("latency_ms") or 0.0),
            updated_at=now_ts,
        )
        if hasattr(manager, '_ai_shadow_count'):
            manager._ai_shadow_count += 1
        analysis_meta["state"] = "ai_shadow_done"
    else:
        analysis_meta["state"] = "rule_done"
    analysis_meta["updated_at"] = now_ts
    memory["metadata"] = metadata

    if old_category != category:
        if old_category in manager.category_index:
            if memory_id in manager.category_index[old_category]:
                manager.category_index[old_category].remove(memory_id)
        if memory_id not in manager.category_index[category]:
            manager.category_index[category].append(memory_id)

    for topic in topics:
        manager.topic_weights[topic] += weight * 0.1
    for emotion in emotions:
        manager.emotion_memory_map[emotion].append(
            {"memory_id": memory_id, "relevance_score": 0.8}
        )

    manager._mark_keyword_index_dirty_locked(memory_id)
    return True


def process_pending_analysis(manager: Any, limit: int = 32) -> Dict[str, Any]:
    max_items = max(1, int(limit))

    # 阶段1：读锁内收集待分析记忆的内容快照
    with get_read_lock(manager):
        pending_items: List[Tuple[float, str]] = []
        for memory_id, memory in manager.weighted_memories.items():
            metadata = memory.get("metadata")
            if not isinstance(metadata, dict):
                continue
            if not bool(metadata.get("analysis_pending", False)):
                continue
            pending_items.append((float(memory.get("timestamp") or 0.0), memory_id))
        pending_items.sort(key=lambda x: x[0])
        pending_ids = [mid for _, mid in pending_items[:max_items]]

        if not pending_ids:
            return {
                "processed": 0,
                "pending_before": 0,
                "pending_after": 0,
                "updated_ids": [],
            }

        # 快照待分析记忆的内容（仅复制必要字段）
        memory_snapshots: Dict[str, Dict[str, Any]] = {}
        for mid in pending_ids:
            mem = manager.weighted_memories.get(mid)
            if isinstance(mem, dict):
                memory_snapshots[mid] = {
                    "content": mem.get("content", ""),
                    "category": mem.get("category"),
                    "is_important": mem.get("is_important", False),
                    "metadata": mem.get("metadata"),
                }

    pending_before = len(pending_items)

    # 阶段2：锁外执行规则分析和BERT推理（耗时操作）
    prep_results: Dict[str, Dict[str, Any]] = {}
    bert_results: Dict[str, Dict[str, Any]] = {}
    for memory_id in pending_ids:
        snapshot = memory_snapshots.get(memory_id)
        if not isinstance(snapshot, dict):
            continue
        # 构造临时memory对象用于分析
        temp_memory = dict(snapshot)
        prep = _prepare_pending_analysis(manager, memory_id, temp_memory, time.time())
        prep_results[memory_id] = prep
        if not prep.get("skip") and not prep.get("empty_content"):
            # BERT推理在锁外执行
            bert_results[memory_id] = _run_bert_shadow_analysis(prep["bert_input_text"])

    # 阶段3：写锁内应用分析结果
    now_ts = time.time()
    updated_ids: List[str] = []
    with get_write_lock(manager):
        for memory_id in pending_ids:
            memory = manager.weighted_memories.get(memory_id)
            if not isinstance(memory, dict):
                continue
            prep = prep_results.get(memory_id)
            if not prep:
                continue
            bert_shadow = bert_results.get(memory_id, {})
            if _apply_pending_analysis_result(
                manager, memory_id, memory, prep, bert_shadow, now_ts
            ):
                updated_ids.append(memory_id)

        manager.last_modified_time = now_ts
        pending_after = max(0, pending_before - len(updated_ids))

    if updated_ids:
        manager._schedule_save()
    return {
        "processed": len(updated_ids),
        "pending_before": pending_before,
        "pending_after": pending_after,
        "updated_ids": updated_ids,
    }
