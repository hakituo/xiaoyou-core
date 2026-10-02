"""批量融合裁决：把已落库的 AI 影子结果与规则分析结果做融合。

从 ``memory.core.analysis_ops`` 拆出，原样搬移 ``apply_ai_shadow_adjudication``
（原文件最长的一段）。拆分是纯搬家：未改逻辑、命名与断言。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from memory.core.analysis_fusion import _apply_fusion_action, _write_fusion_metadata
from memory.core.analysis_scoring import (
    _assess_risk_level,
    _compute_consistency_score,
    _compute_final_confidence,
    _compute_rule_score,
    _compute_stability_score,
    _compute_trigger_decision,
)
from memory.core.analysis_types import (
    BLOCKED_DISCOURSE_LABELS,
    FusionResult,
    _clean_category,
    _clean_topics,
    _ensure_analysis_meta,
    _safe_float,
)
from memory.core.lock_utils import get_write_lock


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
