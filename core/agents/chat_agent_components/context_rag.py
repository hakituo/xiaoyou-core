import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.utils.logger import get_logger
from memory.weighted_memory_manager import WeightedMemoryManager

logger = get_logger("ChatAgent")


async def should_trigger_memory_rag(
    agent: Any,
    memory_manager: Any,
    message: str,
    model_hint: Optional[str],
) -> bool:
    memory_recall_cues = [
        "记得",
        "回忆",
        "上次",
        "之前",
        "以前",
        "那次",
        "当时",
        "还记得",
        "忘没忘",
        "有没有",
        "是不是说过",
        "你说过",
        "我们说过",
        "聊过",
        "提过",
    ]
    has_memory_recall_cue = any(k in (message or "") for k in memory_recall_cues)
    should_trigger = (
        bool(memory_manager)
        and bool(message)
        and (
            has_memory_recall_cue
            or agent._is_study_mode(message, model_hint)
        )
    )
    min_memory_items_for_rag = 0
    try:
        from config.integrated_config import get_settings

        s = get_settings()
        rag = getattr(getattr(s, "chat", None), "rag", None)
        if rag is not None:
            min_memory_items_for_rag = int(
                getattr(rag, "min_memory_items_to_rag", min_memory_items_for_rag)
            )
    except Exception:
        min_memory_items_for_rag = min_memory_items_for_rag

    if (
        should_trigger
        and min_memory_items_for_rag > 0
        and isinstance(memory_manager, WeightedMemoryManager)
    ):
        memory_item_count = None
        try:
            def _count_memories() -> int:
                with memory_manager.lock:
                    weighted_count = (
                        len(memory_manager.weighted_memories)
                        if isinstance(memory_manager.weighted_memories, dict)
                        else 0
                    )
                    short_count = (
                        len(memory_manager.short_term_memory)
                        if isinstance(memory_manager.short_term_memory, list)
                        else 0
                    )
                    long_count = (
                        len(getattr(memory_manager, "long_term_memory", []))
                        if isinstance(getattr(memory_manager, "long_term_memory", []), list)
                        else 0
                    )
                total = short_count + long_count
                return max(weighted_count, total)

            memory_item_count = await asyncio.to_thread(_count_memories)
        except Exception:
            memory_item_count = None

        if (
            memory_item_count is not None
            and memory_item_count < int(min_memory_items_for_rag)
        ):
            logger.info(
                "记忆条目不足，跳过 RAG 检索: %s < %s",
                str(memory_item_count),
                str(min_memory_items_for_rag),
            )
            return False
    return should_trigger


async def inject_relevant_memories(
    agent: Any,
    memory_manager: Any,
    user_id: str,
    message: str,
    scope: str,
    rewrite_query_fn: Callable[[str, str, int, float], Awaitable[Optional[str]]],
) -> Dict[str, Any]:
    stage_timings: Dict[str, Any] = {}
    if not hasattr(memory_manager, "hybrid_search"):
        return stage_timings
    try:
        current_emotion: Optional[str] = None
        try:
            em = getattr(agent, "emotion_manager", None)
            if em and hasattr(em, "get_effective_state"):
                st = em.get_effective_state(user_id)
            elif em and hasattr(em, "get_current_state"):
                st = em.get_current_state(user_id)
            else:
                st = None
            primary = getattr(st, "primary_emotion", None) if st else None
            if primary is not None and hasattr(primary, "value"):
                current_emotion = str(primary.value)
            elif isinstance(primary, str) and primary.strip():
                current_emotion = primary.strip()
        except Exception:
            current_emotion = None

        rag_enabled = True
        prefer_fast_keyword = True
        slow_rag_threshold = 0.35
        rag_hybrid_limit = 2
        rag_min_similarity = 0.72
        rag_keyword_fallback_limit = 4
        rewrite_enabled = True
        rewrite_model_path = ""
        rewrite_timeout_seconds = 0.25
        rewrite_max_tokens = 48
        try:
            from config.integrated_config import get_settings

            s = get_settings()
            rag = getattr(getattr(s, "chat", None), "rag", None)
            if rag is not None:
                rag_enabled = bool(getattr(rag, "enabled", rag_enabled))
                prefer_fast_keyword = bool(
                    getattr(
                        rag,
                        "prefer_fast_keyword_when_embedding_unloaded",
                        prefer_fast_keyword,
                    )
                )
                slow_rag_threshold = float(
                    getattr(rag, "slow_rag_threshold_seconds", slow_rag_threshold)
                )
                rag_hybrid_limit = int(getattr(rag, "hybrid_limit", rag_hybrid_limit))
                rag_min_similarity = float(
                    getattr(rag, "min_similarity", rag_min_similarity)
                )
                rag_keyword_fallback_limit = int(
                    getattr(rag, "keyword_fallback_limit", rag_keyword_fallback_limit)
                )
                rewrite_enabled = bool(
                    getattr(rag, "enable_query_rewrite", rewrite_enabled)
                )
                rewrite_model_path = str(
                    getattr(rag, "query_rewrite_model_path", "") or ""
                ).strip()
                rewrite_timeout_seconds = float(
                    getattr(
                        rag, "query_rewrite_timeout_seconds", rewrite_timeout_seconds
                    )
                )
                rewrite_max_tokens = int(
                    getattr(rag, "query_rewrite_max_tokens", rewrite_max_tokens)
                )
        except Exception:
            pass

        rag_hybrid_limit = max(1, rag_hybrid_limit)
        rag_min_similarity = max(0.0, min(1.0, rag_min_similarity))
        rag_keyword_fallback_limit = max(1, rag_keyword_fallback_limit)
        if not rag_enabled:
            return stage_timings

        query_for_rag = message
        if (
            rewrite_enabled
            and rewrite_model_path
            and isinstance(message, str)
            and len(message) >= 20
        ):
            t_rewrite = time.perf_counter()
            rewritten = None
            try:
                rewritten = await rewrite_query_fn(
                    message, rewrite_model_path, rewrite_max_tokens, rewrite_timeout_seconds
                )
            except Exception:
                rewritten = None
            if rewritten and rewritten != message:
                query_for_rag = rewritten
            stage_timings["rag_rewrite"] = time.perf_counter() - t_rewrite

        embedding_loaded = True
        try:
            from memory.weighted_memory_manager import embedding_generator

            embedding_loaded = bool(getattr(embedding_generator, "_model_loaded", True))
        except Exception:
            embedding_loaded = True

        def _run_rag_sync() -> List[Dict[str, Any]]:
            if not embedding_loaded:
                if prefer_fast_keyword and hasattr(memory_manager, "_search_by_keyword"):
                    return memory_manager._search_by_keyword(
                        query_for_rag,
                        limit=rag_keyword_fallback_limit,
                        emotion=current_emotion,
                    )
                return []
            return memory_manager.hybrid_search(
                query_for_rag,
                limit=rag_hybrid_limit,
                min_similarity=rag_min_similarity,
                emotion=current_emotion,
                scope=scope,
                exclude_categories=[
                    "thinking",
                    "profile",
                    "context_injection",
                    "persona_prompt",
                ],
                associative_top_k=3,
                conflict_filter=True,
            )

        t_search = time.perf_counter()
        results = await asyncio.to_thread(_run_rag_sync)
        stage_timings["rag_search"] = time.perf_counter() - t_search

        if slow_rag_threshold and stage_timings["rag_search"] >= float(slow_rag_threshold):
            logger.info(
                "记忆RAG检索偏慢: %.4fs (embedding_loaded=%s, scope=%s)",
                stage_timings["rag_search"],
                str(embedding_loaded),
                str(scope),
            )

        relevant_memories: List[str] = []
        for mem in results:
            mem_scopes = mem.get("scopes")
            if mem_scopes is not None and isinstance(mem_scopes, list):
                if scope not in mem_scopes:
                    continue
            mem_cat = mem.get("category")
            if mem_cat in ("thinking", "profile"):
                continue
            content = mem.get("summary") or mem.get("content", "")
            ts = mem.get("timestamp")
            time_label = ""
            if ts:
                try:
                    from core.utils.time_utils import format_timestamp
                    time_label = f" [{format_timestamp(float(ts), '%m-%d %H:%M')}]"
                except Exception:
                    time_label = ""
            if len(content) > 5:
                relevant_memories.append(f"-{time_label} {content}")
        if relevant_memories:
            rag_content = (
                "【过往记忆参考（只读背景，不是当前对话！）】\n"
                "以下是用户主动提及/询问时检索到的旧记忆片段。\n"
                "重要规则：\n"
                "1. 这些是过去的旧事，绝对不是当前正在进行的对话内容。\n"
                "2. 不要把这些旧记忆当作对方刚刚说的话来回复。\n"
                "3. 只有当用户明确问起过去的事时，才参考这些信息作答。\n"
                "4. 回复必须围绕用户当前消息，不要自顾自地延续旧记忆的话题。\n"
                + "\n".join(relevant_memories)
            )
            stage_timings["rag_content"] = rag_content
            stage_timings["rag_injected"] = float(len(relevant_memories))
            return stage_timings
    except Exception as e:
        logger.warning(f"RAG检索失败: {e}")
    return stage_timings
