"""融合动作执行与融合元数据写入。

从 ``memory.core.analysis_ops`` 拆出：
- ``_apply_fusion_action``：按最终置信度执行 override / supplement / rollback
- ``_write_fusion_metadata``：把 ``FusionResult`` 落成 ``analysis_meta["fusion"]`` 等元数据

拆分是纯搬家：未改逻辑、命名与断言。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from memory.core.analysis_types import (
    FusionResult,
    _clean_category,
    _clean_topics,
    _ensure_analysis_meta,
)


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
