from __future__ import annotations

import datetime
import time
import uuid
import logging
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Callable, Tuple

from memory.core.record_ops import merge_tags as _merge_tags

logger = logging.getLogger(__name__)

# 这些类别是系统注入/缓存,不是对话内容,不进入短期对话记忆
# 与 search_memory_tool.py 的 exclude_categories 保持一致
# sensitive 也排除: 敏感内容只进 weighted_memories(用于检索),不污染上下文注入
# diary 也排除: 日记是总结性内容,不是对话,通过 retrieval 检索 weighted_memories 使用
_NON_DIALOGUE_CATEGORIES = frozenset(
    {"thinking", "profile", "context_injection", "persona_prompt", "sensitive", "diary"}
)
_NON_PERSISTENT_WEIGHTED_CATEGORIES = frozenset(
    {"thinking", "context_injection", "persona_prompt"}
)


def is_short_term_dialogue(memory: Dict[str, Any]) -> bool:
    """判断记录是否属于可注入上下文的短期对话。"""
    if not isinstance(memory, dict):
        return False

    category = str(memory.get("category") or "").strip().lower()
    memory_type = str(memory.get("memory_type") or "").strip().lower()
    role = str(memory.get("role") or "").strip().lower()
    source = str(memory.get("source") or "").strip().lower()
    content = str(memory.get("content") or "").strip()

    if not content or category in _NON_DIALOGUE_CATEGORIES:
        return False
    if memory_type != "dialogue" or role not in {"user", "assistant"}:
        return False
    if source in {"system", "system_summary", "workspace"}:
        return False
    return True


def _normalize_for_dedupe(content: str) -> str:
    return " ".join(str(content or "").strip().lower().split())


def _is_low_value_for_weighted(
    *,
    content: str,
    source: str,
    category: Optional[str],
    is_important: bool,
    metadata: Optional[Dict[str, Any]],
) -> bool:
    if is_important:
        return False
    text = str(content or "").strip()
    if not text:
        return True
    cat = str(category or "").strip().lower()
    src = str(source or "").strip().lower()
    if cat in {"sensitive", "thinking", "profile", "preference", "diary"}:
        return False
    if src in {"system_profile", "journal", "workspace"}:
        return False
    meta = metadata if isinstance(metadata, dict) else {}
    if bool(meta.get("analysis_pending")):
        return False
    normalized = _normalize_for_dedupe(text)
    low_value_tokens = {
        "嗯", "哦", "好", "好的", "ok", "okay",
        "收到", "知道了", "明白", "哈哈", "hhh",
        "1", "。", "？", "!",
    }
    if normalized in low_value_tokens:
        return True
    if len(text) <= 2:
        return True
    return False


def _build_dedupe_key(
    normalized_content: str, source_key: str, category_key: str
) -> str:
    return f"{normalized_content}\x00{source_key}\x00{category_key}"


@dataclass
class MemoryContext:
    weighted_memories: Dict[str, Dict[str, Any]]
    short_term_memory: List[Dict[str, Any]]
    category_index: Dict[str, List[str]]
    important_prompts: List[Dict[str, Any]]
    sensitive_memories: List[Dict[str, Any]]
    topic_weights: Dict[str, float]
    emotion_memory_map: Dict[str, List[Dict[str, Any]]]
    weight_calculator: Any
    detect_topics_fn: Callable[[str], List[str]]
    detect_emotion_fn: Callable[[str], str]
    classify_category_fn: Callable[[str], str]
    extract_user_preferences_fn: Callable[[str], None]
    extract_preference_updates_fn: Callable[[str], List[Dict[str, Any]]]
    upsert_preference_locked_fn: Callable[..., Optional[str]]
    normalize_memory_record_fn: Callable[
        [Dict[str, Any]], Tuple[Dict[str, Any], bool]
    ]
    mark_keyword_index_dirty_fn: Callable[[str], None]
    schedule_save_fn: Callable[[], None]
    schedule_trim_fn: Callable[[], None]
    update_topic_index_fn: Callable[[], None]
    update_topic_index_incremental_fn: Optional[Callable[[Dict[str, Any]], None]] = None
    vector_search_enabled: bool = False
    generate_embedding_fn: Optional[Callable[[Any], Any]] = None
    embedding_to_base64_fn: Optional[Callable[[Any], str]] = None
    content_dedupe_index: Optional[Dict[str, str]] = None


@dataclass
class MemoryInput:
    content: str = ""
    topics: Optional[List[str]] = None
    emotions: Optional[List[str]] = None
    is_important: bool = False
    source: str = "chat"
    category: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    scopes: Optional[List[str]] = None
    user_id: str = "default"
    is_sensitive_mode: bool = False


def _filter_system_injection(
    content: str, metadata: Optional[Dict[str, Any]]
) -> bool:
    if not content or not content.strip():
        logger.warning("Attempted to add empty memory content; skipping")
        return True

    is_trusted_source = False
    if metadata and isinstance(metadata, dict):
        is_proactive = metadata.get("is_proactive")
        is_active_care = (
            metadata.get("original_source") == "active_care"
        )
        if is_proactive or is_active_care:
            is_trusted_source = True

    if not is_trusted_source and (
        content.strip().startswith("# Role Definition")
        or content.strip().startswith("[SYSTEM]")
        or "You are Aveline" in content
        or "你是 Aveline" in content
        or "你是 **Aveline" in content
    ):
        logger.info(
            "Filtered out system prompt/injection from memory storage"
        )
        return True

    try:
        from core.utils.debug_markers import is_debug_context_message
        if is_debug_context_message(content):
            logger.info(
                "Filtered out debug/error message from memory "
                f"storage: {content[:100]}"
            )
            return True
    except ImportError:
        pass

    return False


def _resolve_legacy_kwargs(
    legacy_kwargs: Dict[str, Any], inp: MemoryInput
) -> Tuple[str, str, bool, List[str]]:
    role = inp.source
    source = inp.source
    is_important = inp.is_important
    topics = list(inp.topics) if inp.topics else []

    if legacy_kwargs:
        legacy_topic = legacy_kwargs.get("topic")
        if legacy_topic is not None:
            if isinstance(legacy_topic, str):
                topics.append(legacy_topic)
            elif isinstance(legacy_topic, list):
                normalized = [
                    str(t) for t in legacy_topic if t is not None
                ]
                if normalized:
                    topics.extend(normalized)

        legacy_role = legacy_kwargs.get("role")
        if isinstance(legacy_role, str) and legacy_role:
            role = legacy_role
            if not source or source == "chat":
                source = legacy_role

        legacy_importance = legacy_kwargs.get("importance")
        if legacy_importance is not None and not is_important:
            if isinstance(legacy_importance, bool):
                is_important = legacy_importance
            elif isinstance(legacy_importance, (int, float)):
                if 0 <= legacy_importance <= 1:
                    is_important = legacy_importance >= 0.8
                else:
                    is_important = legacy_importance >= 1

    return role, source, is_important, topics


def _build_memory_record(
    *,
    memory_id: str,
    content: str,
    topics: List[str],
    emotions: List[str],
    primary_emotion: str,
    is_important: bool,
    source: str,
    role: str,
    category: str,
    is_sensitive: bool,
    weight: float,
    metadata: Dict[str, Any],
    scopes: List[str],
) -> Dict[str, Any]:
    effective_scopes = ["local"] if is_sensitive else scopes

    memory = {
        "id": memory_id,
        "content": content,
        "timestamp": time.time(),
        "created_at": datetime.datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "last_access_time": time.time(),
        "weight": weight,
        "topics": topics or [],
        "emotions": emotions or [],
        "emotion": primary_emotion,
        "is_important": is_important,
        "source": source,
        "role": role,
        "category": "sensitive" if is_sensitive else category,
        "summary": None,
        "search_keywords": [],
        "display_tags": [],
        "keywords": [],
        "is_distilled": False,
        "metadata": metadata,
        "scopes": list(effective_scopes),
        "embedding": None,
    }
    tag_seed: List[str] = []
    for topic in (topics or []):
        ts = str(topic or "").strip()
        if ts and ts not in tag_seed:
            tag_seed.append(ts)
    memory["display_tags"] = tag_seed[:6]
    return memory


def _check_duplicate(
    ctx: MemoryContext,
    content: str,
    source: str,
    category: str,
) -> str:
    normalized_content = _normalize_for_dedupe(content)
    source_key = str(source or "").strip().lower()
    category_key = (
        str(category or "").strip().lower() or "uncategorized"
    )
    dedupe_key = _build_dedupe_key(
        normalized_content, source_key, category_key
    )
    if ctx.content_dedupe_index is not None:
        return ctx.content_dedupe_index.get(dedupe_key, "")
    for mid, wm in ctx.weighted_memories.items():
        wm_content = _normalize_for_dedupe(wm.get("content", ""))
        wm_source = str(
            wm.get("source", "")
        ).strip().lower()
        wm_category = (
            str(wm.get("category", "")).strip().lower()
            or "uncategorized"
        )
        if (
            wm_content == normalized_content
            and wm_source == source_key
            and wm_category == category_key
        ):
            return str(mid)
    return ""


def _handle_duplicate(
    ctx: MemoryContext,
    duplicate_id: str,
    memory: Dict[str, Any],
    topics: List[str],
    emotions: List[str],
    is_important: bool,
    category: str,
    weight: float,
) -> None:
    existing = ctx.weighted_memories.get(duplicate_id)
    if isinstance(existing, dict):
        old_w = float(existing.get("weight", 0.0) or 0.0)
        existing["weight"] = max(old_w, float(weight))
        existing["last_access_time"] = time.time()
        old_imp = existing.get("is_important", False)
        existing["is_important"] = bool(old_imp or is_important)
        existing["topics"] = _merge_tags(
            existing.get("topics", []), topics or [], limit=8
        )
        existing["display_tags"] = _merge_tags(
            existing.get("display_tags", []),
            existing.get("topics", []),
            limit=8,
        )
        existing["emotions"] = _merge_tags(
            existing.get("emotions", []),
            emotions or [],
            limit=4,
        )
        if is_important and existing.get("category") != "profile":
            cat = existing.get("category") or category
            existing["category"] = cat
        existing, _ = ctx.normalize_memory_record_fn(existing)
        ctx.weighted_memories[duplicate_id] = existing
        ctx.mark_keyword_index_dirty_fn(duplicate_id)


def _extract_preferences_for_user(
    ctx: MemoryContext,
    content: str,
    source: str,
    memory_id: str,
    timestamp: float,
) -> None:
    if source != "user":
        return
    try:
        ctx.extract_user_preferences_fn(content)
    except Exception as e:
        logger.debug(f"偏好提取(extract_user_preferences)失败: {e}")
    try:
        updates = ctx.extract_preference_updates_fn(content)
        for u in updates:
            ctx.upsert_preference_locked_fn(
                key=u.get("key"),
                polarity=bool(u.get("polarity")),
                source_memory_id=memory_id,
                timestamp=timestamp,
            )
    except Exception as e:
        logger.debug(f"偏好提取失败: {e}")


def _index_new_memory(
    ctx: MemoryContext,
    memory_id: str,
    memory: Dict[str, Any],
    content: str,
    source: str,
    category: str,
    is_sensitive: bool,
    is_important: bool,
    topics: List[str],
    emotions: List[str],
    weight: float,
    defer_analysis: bool,
) -> None:
    if category:
        ctx.category_index[category].append(memory_id)
    else:
        ctx.category_index["uncategorized"].append(memory_id)

    # short_term 只保存真实的 user/assistant 对话。摘要、思考、画像、
    # workspace 注入等内容仍可进入 weighted memory，但不能污染近期上下文。
    if is_short_term_dialogue(memory):
        ctx.short_term_memory.append(memory)

    _extract_preferences_for_user(
        ctx, content, source, memory_id, memory.get("timestamp", time.time())
    )

    should_store_weighted = not _is_low_value_for_weighted(
        content=content,
        source=source,
        category=category,
        is_important=is_important,
        metadata=memory.get("metadata", {}),
    )
    if category in _NON_PERSISTENT_WEIGHTED_CATEGORIES:
        should_store_weighted = False
    if should_store_weighted or is_sensitive:
        ctx.weighted_memories[memory_id] = memory
        normalized_content = _normalize_for_dedupe(content)
        source_key = str(source or "").strip().lower()
        category_key = (
            str(category or "").strip().lower() or "uncategorized"
        )
        dedupe_key = _build_dedupe_key(normalized_content, source_key, category_key)
        if ctx.content_dedupe_index is not None:
            ctx.content_dedupe_index[dedupe_key] = memory_id
        ctx.mark_keyword_index_dirty_fn(memory_id)

        if (
            (not is_sensitive)
            and (not defer_analysis)
            and (
                weight >= 6.0
                or (is_important and "user_instruction" in topics)
            )
        ):
            if not any(
                m["content"] == content
                for m in ctx.important_prompts
            ):
                ctx.important_prompts.append(memory)
                logger.info(
                    "记忆晋升至第3层 (重要提示词): "
                    f"{content[:30]}... (权重: {weight})"
                )

        if (not is_sensitive) and (not defer_analysis):
            for topic in topics:
                prev = ctx.topic_weights.get(topic, 0.0)
                ctx.topic_weights[topic] = prev + 0.1

            if emotions:
                for emotion in emotions:
                    ctx.emotion_memory_map.setdefault(
                        emotion, []
                    ).append(
                        {
                            "memory_id": memory_id,
                            "relevance_score": 0.8,
                        }
                    )


def add_memory_locked(
    content: str,
    weighted_memories: Dict[str, Dict[str, Any]],
    short_term_memory: List[Dict[str, Any]],
    category_index: Dict[str, List[str]],
    important_prompts: List[Dict[str, Any]],
    sensitive_memories: List[Dict[str, Any]],
    topic_weights: Dict[str, float],
    emotion_memory_map: Dict[str, List[Dict[str, Any]]],
    weight_calculator: Any,
    detect_topics_fn: Callable[[str], List[str]],
    detect_emotion_fn: Callable[[str], str],
    classify_category_fn: Callable[[str], str],
    extract_user_preferences_fn: Callable[[str], None],
    extract_preference_updates_fn: Callable[[str], List[Dict[str, Any]]],
    upsert_preference_locked_fn: Callable[..., Optional[str]],
    normalize_memory_record_fn: Callable[
        [Dict[str, Any]], Tuple[Dict[str, Any], bool]
    ],
    mark_keyword_index_dirty_fn: Callable[[str], None],
    schedule_save_fn: Callable[[], None],
    schedule_trim_fn: Callable[[], None],
    update_topic_index_fn: Callable[[], None],
    vector_search_enabled: bool,
    generate_embedding_fn: Optional[Callable[[Any], Any]],
    embedding_to_base64_fn: Optional[Callable[[Any], str]],
    content_dedupe_index: Optional[Dict[str, str]] = None,
    update_topic_index_incremental_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
    topics: List[str] = None,
    emotions: List[str] = None,
    is_important: bool = False,
    source: str = "chat",
    category: str = None,
    metadata: Dict[str, Any] = None,
    scopes: Optional[List[str]] = None,
    user_id: str = "default",
    is_sensitive_mode: bool = False,
    **legacy_kwargs: Any,
) -> Tuple[str, bool]:
    ctx = MemoryContext(
        weighted_memories=weighted_memories,
        short_term_memory=short_term_memory,
        category_index=category_index,
        important_prompts=important_prompts,
        sensitive_memories=sensitive_memories,
        topic_weights=topic_weights,
        emotion_memory_map=emotion_memory_map,
        weight_calculator=weight_calculator,
        detect_topics_fn=detect_topics_fn,
        detect_emotion_fn=detect_emotion_fn,
        classify_category_fn=classify_category_fn,
        extract_user_preferences_fn=extract_user_preferences_fn,
        extract_preference_updates_fn=extract_preference_updates_fn,
        upsert_preference_locked_fn=upsert_preference_locked_fn,
        normalize_memory_record_fn=normalize_memory_record_fn,
        mark_keyword_index_dirty_fn=mark_keyword_index_dirty_fn,
        schedule_save_fn=schedule_save_fn,
        schedule_trim_fn=schedule_trim_fn,
        update_topic_index_fn=update_topic_index_fn,
        update_topic_index_incremental_fn=update_topic_index_incremental_fn,
        vector_search_enabled=vector_search_enabled,
        generate_embedding_fn=generate_embedding_fn,
        embedding_to_base64_fn=embedding_to_base64_fn,
        content_dedupe_index=content_dedupe_index,
    )
    inp = MemoryInput(
        content=content,
        topics=topics,
        emotions=emotions,
        is_important=is_important,
        source=source,
        category=category,
        metadata=metadata,
        scopes=scopes,
        user_id=user_id,
        is_sensitive_mode=is_sensitive_mode,
    )
    return _add_memory_core(ctx, inp, legacy_kwargs)


def _add_memory_core(
    ctx: MemoryContext,
    inp: MemoryInput,
    legacy_kwargs: Dict[str, Any],
) -> Tuple[str, bool]:
    if _filter_system_injection(inp.content, inp.metadata):
        return ("", False)

    role, source, is_important, topics = _resolve_legacy_kwargs(
        legacy_kwargs, inp
    )
    category = inp.category
    metadata = inp.metadata
    emotions = inp.emotions

    memory_id = str(uuid.uuid4())
    metadata = metadata.copy() if isinstance(metadata, dict) else {}
    defer_analysis = bool(metadata.get("defer_analysis", False))

    if topics is None:
        topics = (
            [] if defer_analysis else ctx.detect_topics_fn(inp.content)
        )
    if emotions is None:
        emotions = (
            []
            if defer_analysis
            else [ctx.detect_emotion_fn(inp.content)]
        )

    primary_emotion = "neutral"
    if isinstance(emotions, list) and emotions:
        first = emotions[0]
        if isinstance(first, str) and first.strip():
            primary_emotion = first.strip().lower()

    if not category:
        category = (
            "uncategorized"
            if defer_analysis
            else ctx.classify_category_fn(inp.content)
        )

    if (not defer_analysis) and category and category not in topics:
        topics.append(category)

    is_sensitive = (
        category == "sensitive"
        or (topics and ("sensitive" in topics))
        or inp.is_sensitive_mode
    )

    if defer_analysis:
        weight = 1.0
        metadata["analysis_pending"] = True
        metadata["analysis_source"] = "data_ops"
        metadata["analysis_meta"] = {
            "state": "pending",
            "defer_analysis": True,
            "source": "data_ops",
            "created_at": time.time(),
            "updated_at": time.time(),
        }
    else:
        weight = ctx.weight_calculator.calculate_initial_weight(
            inp.content, is_important, topics, emotions
        )

    effective_scopes = (
        inp.scopes
        if isinstance(inp.scopes, list) and inp.scopes
        else ["local", "cloud"]
    )

    memory = _build_memory_record(
        memory_id=memory_id,
        content=inp.content,
        topics=topics,
        emotions=emotions,
        primary_emotion=primary_emotion,
        is_important=is_important,
        source=source,
        role=role,
        category=category,
        is_sensitive=is_sensitive,
        weight=weight,
        metadata=metadata,
        scopes=effective_scopes,
    )
    memory, _ = ctx.normalize_memory_record_fn(memory)

    if (
        ctx.vector_search_enabled
        and inp.content
        and ctx.generate_embedding_fn
        and ctx.embedding_to_base64_fn
    ):
        try:
            embedding = ctx.generate_embedding_fn(inp.content)
            memory["embedding"] = ctx.embedding_to_base64_fn(embedding)
        except Exception as e:
            logger.error(f"生成记忆向量嵌入失败: {e}")

    duplicate_id = _check_duplicate(ctx, inp.content, source, category)

    if duplicate_id:
        _handle_duplicate(
            ctx, duplicate_id, memory, topics, emotions,
            is_important, category, weight,
        )
        return (duplicate_id, True)

    _index_new_memory(
        ctx, memory_id, memory, inp.content, source, category,
        is_sensitive, is_important, topics, emotions, weight,
        defer_analysis,
    )

    ctx.schedule_trim_fn()
    if ctx.update_topic_index_incremental_fn is not None:
        ctx.update_topic_index_incremental_fn(memory)
    else:
        ctx.update_topic_index_fn()

    logger.info(
        f"已添加权重记忆，ID: {memory_id}, "
        f"权重: {weight}, 话题: {topics}"
    )
    return (memory_id, True)
