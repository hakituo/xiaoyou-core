"""AI 影子（ai_shadow）结果的构建、BERT 分析与读写。

从 ``memory.core.analysis_ops`` 拆出，覆盖原文件的「影子结果」关注点：
- ``_build_ai_shadow_dict`` / ``_build_bert_shadow_input``：影子数据与 BERT 输入的构造
- ``_run_bert_shadow_analysis``：BERT 本地推理（延迟导入分析器）
- ``count_pending_analysis`` / ``get_pending_analysis_items`` / ``count_ai_shadow_results``：
  待分析项与影子结果的计数、取件；``attach_ai_shadow_result`` 把结果写回元数据

拆分是纯搬家：未改逻辑、命名与断言。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

from memory.core.analysis_types import (
    _clean_category,
    _clean_topics,
    _ensure_analysis_meta,
    _safe_float,
)
from memory.core.lock_utils import get_read_lock, get_write_lock


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
