"""待分析记忆的规则分析与结果应用（锁外准备 + 锁内落库）。

从 ``memory.core.analysis_ops`` 拆出：
- ``_prepare_pending_analysis``：锁外做规则分析并构造 BERT 输入（耗时操作）
- ``_apply_pending_analysis_result``：写锁内把分析结果应用到记忆记录

拆分是纯搬家：未改逻辑、命名与断言。
"""
from __future__ import annotations

from typing import Any, Dict, List

from memory.core.analysis_shadow import _build_ai_shadow_dict, _build_bert_shadow_input
from memory.core.analysis_types import (
    DISCOURSE_WEIGHT_PENALTIES,
    _clean_category,
    _clean_topics,
    _ensure_analysis_meta,
    _safe_float,
)
from memory.core.discourse import analyze_discourse, infer_state_event


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
