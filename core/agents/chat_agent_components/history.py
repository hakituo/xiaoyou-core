import asyncio
import re
import time
import uuid
import json
from typing import Any, Optional, List

from core.managers.session_manager import get_session_manager
from core.services.chat_history_store import get_chat_history_store
from core.utils.logger import get_logger
from core.utils.data_paths import get_daily_dir_for_conversation
from core.utils.time_utils import get_current_time

logger = get_logger("ChatAgent")


_NAME_PATTERNS: List[re.Pattern] = [
    re.compile(
        r"(?:^|[\s，,。！？!?])我叫\s*([A-Za-z0-9_\u4e00-\u9fff]{1,4})(?=$|[\s，,。！？!?])"
    ),
    re.compile(
        r"(?:^|[\s，,。！？!?])叫我\s*([A-Za-z0-9_\u4e00-\u9fff]{1,4})(?=$|[\s，,。！？!?])"
    ),
    re.compile(
        r"(?:^|[\s，,。！？!?])(?:我的名字是|名字是)\s*([A-Za-z0-9_\u4e00-\u9fff]{1,4})(?=$|[\s，,。！？!?])"
    ),
]


def _is_valid_profile_name(value: str) -> bool:
    cand = str(value or "").strip()
    if not cand:
        return False
    if len(cand) > 8:
        return False
    lowered = cand.lower()
    banned_values = {
        "北京",
        "上海",
        "深圳",
        "广州",
        "中国",
        "程序员",
        "学生",
        "高考",
        "说我有点忧郁",
    }
    if cand in banned_values:
        return False
    banned_fragments = [
        "说我",
        "有点",
        "忧郁",
        "喜欢",
        "不喜欢",
        "学习",
        "工作",
        "今天",
        "明天",
        "主人",
        "干什么",
        "什么",
        "一下",
        "好的",
    ]
    if any(frag in cand for frag in banned_fragments):
        return False
    if re.search(r"[，,。！？!?：:\s]", cand):
        return False
    if lowered in {"default", "user", "assistant", "system"}:
        return False
    return True


def _extract_user_profile_facts(text: str) -> List[str]:
    s = str(text or "").strip()
    if not s:
        return []

    facts: List[str] = []

    name = ""
    for p in _NAME_PATTERNS:
        m = p.search(s)
        if m:
            cand = (m.group(1) or "").strip()
            if cand and cand not in {"北京", "上海", "深圳", "广州", "中国", "程序员", "学生"}:
                name = cand
                break
    if name and _is_valid_profile_name(name):
        facts.append(f"用户名字: {name}")

    m_city = re.search(r"在\s*([\u4e00-\u9fff]{1,8})\s*(?:工作|上班)", s)
    if m_city:
        city = (m_city.group(1) or "").strip()
        if city and city not in {"这里", "那边"}:
            facts.append(f"用户工作地点: {city}")

    pref_hits: List[str] = []
    if any(k in s for k in ["自然", "口语", "别太官方", "不要太官方"]):
        pref_hits.append("更自然别太官方")
    if any(k in s for k in ["具体例子", "举例", "例子"]):
        pref_hits.append("喜欢具体例子")
    if any(k in s for k in ["别太长", "简洁", "少废话"]):
        pref_hits.append("偏好简洁")
    if pref_hits:
        facts.append("用户偏好: " + " ".join(dict.fromkeys(pref_hits)))

    return facts


def _extract_topics_from_text_and_strip_tags(text: str) -> tuple[str, List[str]]:
    raw = str(text or "")
    if not raw:
        return "", []
    topic_pattern = re.compile(r"\[TOPIC:\s*(.*?)\]", re.IGNORECASE | re.DOTALL)
    matches = topic_pattern.findall(raw)
    topics: List[str] = []
    for m in matches:
        parts = [t.strip() for t in re.split(r"[,，/、\s]+", str(m)) if t.strip()]
        for t in parts:
            if t not in topics:
                topics.append(t)
    cleaned = topic_pattern.sub("", raw).strip()
    return cleaned, topics


def _normalize_topics(topics: Optional[List[str]]) -> List[str]:
    bad_topics = {"uncategorized", "unknown", "other", "其他", "未分类"}
    normalized: List[str] = []
    for t in topics or []:
        ts = str(t).strip()
        if not ts:
            continue
        if ts.lower() in bad_topics:
            continue
        if ts not in normalized:
            normalized.append(ts)
    return normalized


def _normalize_thought_text(thought: Optional[str], assistant_text: str) -> str:
    raw = str(thought or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"(?i)(?<!<)/think>", "</think>", raw)
    extracted_blocks = re.findall(
        r"<\s*think\s*>(.*?)<\s*/\s*think\s*>", raw, flags=re.DOTALL | re.IGNORECASE
    )
    if extracted_blocks:
        normalized = "\n".join(
            [str(x or "").strip() for x in extracted_blocks if str(x or "").strip()]
        ).strip()
    else:
        normalized = re.sub(r"</?\s*think\s*>", "", raw, flags=re.IGNORECASE).strip()
    assistant_clean = str(assistant_text or "").strip()
    if assistant_clean and normalized.endswith(assistant_clean):
        normalized = normalized[: -len(assistant_clean)].strip()
    marker = f"\n\n{assistant_clean}"
    if assistant_clean and marker in normalized:
        normalized = normalized.split(marker, 1)[0].strip()
    return normalized


def _build_fallback_thought(user_msg: str, assistant_text: str) -> str:
    user_text = str(user_msg or "").strip()
    assistant_clean = str(assistant_text or "").strip()
    if not user_text and not assistant_clean:
        return ""
    if len(user_text) > 80:
        user_text = user_text[:80] + "..."
    if len(assistant_clean) > 80:
        assistant_clean = assistant_clean[:80] + "..."
    if user_text and assistant_clean:
        return f"用户刚刚表达了“{user_text}”，我先回应“{assistant_clean}”，保持对话连续并兼顾情绪。"
    if user_text:
        return f"用户刚刚表达了“{user_text}”，我需要先接住情绪并给出清晰回应。"
    return f"我这轮的主要回复是“{assistant_clean}”，目标是保持上下文连贯。"


def _detect_taxonomy_topics(user_msg: str, assistant_msg: str) -> List[str]:
    text = f"{str(user_msg or '').strip()}\n{str(assistant_msg or '').strip()}".strip()
    if not text:
        return []
    try:
        from memory.core.utils import detect_topics

        return _normalize_topics(detect_topics(text))
    except Exception:
        return []


def _resolve_topic_judgement_mode() -> str:
    mode = "posthoc"
    try:
        from config.integrated_config import get_settings

        configured = str(get_settings().data_ops.topic_judgement_mode or "").strip().lower()
        if configured:
            mode = configured
    except Exception:
        mode = "posthoc"
    if mode not in {"posthoc", "hybrid", "llm_first"}:
        return "posthoc"
    return mode


def _resolve_conversation_defer_analysis() -> bool:
    try:
        from config.integrated_config import get_settings
        settings = get_settings()

        # If bionic delay is enabled, we utilize the "cognitive time" to perform
        # immediate analysis instead of deferring it.
        # This ensures better data consistency at the cost of slight latency,
        # which is masked by the bionic delay anyway.
        if getattr(settings.scheduler, "bio_enable_cognitive_delay", False):
            return False

        return bool(settings.data_ops.conversation_defer_analysis)
    except Exception:
        return True


async def maybe_generate_session_title(
    agent: Any, session_id: str, user_msg: str, assistant_msg: str
) -> None:
    try:
        if hasattr(agent, "get_memory_manager_async"):
            mm = await agent.get_memory_manager_async(session_id)
        else:
            mm = agent._get_memory_manager(session_id)
        history_len = 0
        if hasattr(mm, "get_history"):
            history = await asyncio.to_thread(mm.get_history)
            history_len = len(history)

        if history_len > 2:
            return

        prompt = [
            {
                "role": "system",
                "content": "你是标题生成助手。请根据用户的输入和助手的回答，生成一个简短的会话标题（不超过10个字）。不要包含标点符号，不要包含'标题'二字。直接输出标题内容。",
            },
            {
                "role": "user",
                "content": f"用户: {user_msg}\n助手: {assistant_msg}",
            },
        ]

        title = await agent.llm_module.chat(prompt, temperature=0.3, max_tokens=20)
        title = (
            title.strip()
            .replace('"', "")
            .replace("“", "")
            .replace("”", "")
            .replace("标题：", "")
            .replace("Title:", "")
        )

        if title:
            logger.info(f"为会话 {session_id} 生成标题: {title}")
            get_session_manager().update_session(session_id, title=title)

    except Exception as e:
        logger.warning(f"生成会话标题失败: {e}")


async def save_conversation_history(
    agent: Any,
    user_id: str,
    user_msg: str,
    assistant_msg: str,
    message_id: str,
    model_hint: Optional[str] = None,
    extracted_topics: Optional[List[str]] = None,
    thought: Optional[str] = None,
    persona_filename: Optional[str] = None,
    platform: Optional[str] = None,
) -> None:
    from core.utils.debug_markers import is_debug_context_message
    if is_debug_context_message(assistant_msg):
        logger.warning(f"Intercepted debug/error message from being saved to history: {assistant_msg[:100]}")
        return

    cleaned_assistant_msg, topics_from_assistant_text = _extract_topics_from_text_and_strip_tags(
        assistant_msg
    )
    try:
        from clients.bots.qq.utils import strip_ooc_emoji

        cleaned_assistant_msg = strip_ooc_emoji(
            cleaned_assistant_msg,
            str(persona_filename or ""),
        )
    except Exception:
        pass
    session_id = str(user_id or "")
    is_internal_circle_session = ("__bg__" in session_id) or ("__circle__" in session_id)

    if not user_msg and not cleaned_assistant_msg:
        return

    # 提前判断敏感模式，用于给聊天记录打标记
    _is_sensitive_for_history = False
    if persona_filename:
        _pf_lower = str(persona_filename).replace("\\", "/").lower()
        if _pf_lower.startswith("sensitive/") or "/sensitive/" in _pf_lower:
            _is_sensitive_for_history = True
    if not _is_sensitive_for_history:
        try:
            from core.managers.preference_manager import get_preference_manager
            if get_preference_manager().get_mode() == "privacy":
                _is_sensitive_for_history = True
        except Exception:
            pass

    # 构建聊天记录的 topics（包含 sensitive 标记用于搜索隔离）
    _history_topics = list(extracted_topics or [])
    if _is_sensitive_for_history and "sensitive" not in _history_topics:
        _history_topics.append("sensitive")

    # --- Write to Daily Event Log (Sync with Active Care format) ---
    try:
        if is_internal_circle_session:
            raise RuntimeError("skip_daily_event_for_internal_session")
        now_dt = get_current_time()
        history_store = get_chat_history_store()
        event_refs = {}
        if user_msg:
            event_refs["user"] = history_store.append_event(
                conversation_id=session_id or "default",
                role="user",
                content=user_msg,
                message_id=message_id,
                event_type="chat_message",
                metadata={
                    "source": "chat_agent",
                    "model_hint": model_hint or "",
                    "topics": _history_topics,
                    "platform": platform or "",
                },
                now_dt=now_dt,
            )
        if cleaned_assistant_msg:
            event_refs["assistant"] = history_store.append_event(
                conversation_id=session_id or "default",
                role="assistant",
                content=cleaned_assistant_msg,
                message_id=message_id,
                event_type="chat_reply",
                metadata={
                    "source": "chat_agent",
                    "model_hint": model_hint or "",
                    "topics": _history_topics,
                    "platform": platform or "",
                },
                now_dt=now_dt,
            )
        normalized_thought = _normalize_thought_text(thought, cleaned_assistant_msg)
        if normalized_thought and (not is_internal_circle_session):
            event_refs["thinking"] = history_store.append_event(
                conversation_id=session_id or "default",
                role="system",
                content=normalized_thought,
                message_id=message_id,
                event_type="chat_thought",
                metadata={
                    "source": "chat_agent",
                    "model_hint": model_hint or "",
                    "hidden": True,
                },
                now_dt=now_dt,
            )
        daily_dir = (
            get_daily_dir_for_conversation(session_id or "default")
            / now_dt.strftime("%Y")
            / now_dt.strftime("%m")
            / now_dt.strftime("%d")
            / "events"
        )
        # Use a separate file for chat interactions, or merge if desired. 
        # Using chat_actions.jsonl to keep it distinct but parallel.
        event_file = daily_dir / "active_care_actions.jsonl" # Merge into same file for unified timeline view as user requested "my main program... doesn't have this record"
        event_file = daily_dir / "chat_actions.jsonl"
        
        # Extract mood from tags if present (e.g. [EMO:happy])
        mood = "neutral"
        emo_match = re.search(r"\[EMO:(.*?)\]", assistant_msg)
        if emo_match:
            try:
                # sometimes it is json
                if "{" in emo_match.group(1):
                    mood = json.loads(emo_match.group(1)).get("mood", "neutral")
                else:
                    mood = emo_match.group(1)
            except Exception:
                pass

        from core.utils.debug_markers import is_debug_context_message
        if is_debug_context_message(cleaned_assistant_msg) or is_debug_context_message(user_msg):
            logger.info("Filtered out debug/error message from chat_actions.jsonl")
            return

        payload = {
            "timestamp": now_dt.timestamp(),
            "time": now_dt.strftime("%H:%M:%S"),
            "event_type": "chat_reply",
            "message_id": message_id,
            "conversation_id": session_id or "default",
            "source": "chat_agent",
            "model": model_hint or "unknown",
            "topics": extracted_topics or [],
            "mood": mood,
            "has_thought": bool(str(thought or "").strip()),
            "user_content_length": len(str(user_msg or "")),
            "assistant_content_length": len(str(cleaned_assistant_msg or "")),
            "history_event_refs": event_refs,
        }

        def _append_jsonl() -> None:
            daily_dir.mkdir(parents=True, exist_ok=True)
            with open(event_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")

        asyncio.create_task(asyncio.to_thread(_append_jsonl))
    except Exception as e:
        if str(e) != "skip_daily_event_for_internal_session":
            logger.warning(f"Failed to write chat event log: {e}")
        event_refs = {}

    try:
        if hasattr(agent, "get_memory_manager_async"):
            mm = await agent.get_memory_manager_async(user_id)
        else:
            mm = agent._get_memory_manager(user_id)

        memory_calls = []
        if user_msg:
            try:
                facts = _extract_user_profile_facts(user_msg)
                for f in facts:
                    memory_calls.append(
                        {
                            "content": f,
                            "source": "system_profile",
                            "topics": ["user_instruction", "profile"],
                            "category": "profile",
                            "is_important": True,
                            "metadata": {"extracted": True},
                        }
                    )
            except Exception:
                pass

        is_cloud = False
        if model_hint:
            mh_lower = str(model_hint).lower()
            if mh_lower.startswith("cloud:") or "cloud:" in mh_lower:
                is_cloud = True
            elif any(k in mh_lower for k in ["siliconflow", "dashscope", "openai"]):
                is_cloud = True
            elif "deepseek" in mh_lower and not mh_lower.endswith(".gguf"):
                is_cloud = True
        if not is_cloud and getattr(agent, "llm_module", None) and hasattr(
            agent.llm_module, "get_current_model_name"
        ):
            model_name = str(agent.llm_module.get_current_model_name() or "")
            mn_lower = model_name.lower()
            if mn_lower.startswith("cloud:") or "cloud:" in mn_lower:
                is_cloud = True

        # 检查是否处于 Sensitive 模式
        is_sensitive_mode = False
        
        # 优先使用传入的 persona_filename 判断（per-conversation）
        if persona_filename:
            pf_lower = str(persona_filename).replace("\\", "/").lower()
            if pf_lower.startswith("sensitive/") or "/sensitive/" in pf_lower:
                is_sensitive_mode = True
        
        # 回退：检查全局 PersonaManager
        if not is_sensitive_mode:
            try:
                from core.character.managers.persona_manager import get_persona_manager
                pm = get_persona_manager()
                current_persona = str(pm.get_current_filename() or "").replace("\\", "/").lower()
                if current_persona.startswith("sensitive/") or "/sensitive/" in current_persona:
                    is_sensitive_mode = True
            except Exception:
                pass
        
        # Check PreferenceManager
        try:
            from core.managers.preference_manager import get_preference_manager
            prefs = get_preference_manager()
            if prefs.get_mode() == "privacy":
                is_sensitive_mode = True
        except Exception:
            pass

        try:
            if hasattr(mm, "get_memories_by_topic"):
                mode_memories = await asyncio.to_thread(
                    mm.get_memories_by_topic, "sensitive_mode_control", 1
                )
                if mode_memories and "SENSITIVE_MODE_ON" in mode_memories[0].get("content", ""):
                    is_sensitive_mode = True
        except Exception:
            pass

        is_private = is_sensitive_mode
        um_lower = (user_msg or "").lower()
        if not is_private and um_lower:
            if um_lower.startswith("/sensitive") or um_lower.startswith("/private"):
                is_private = True
            elif "[sensitive]" in um_lower or "[private]" in um_lower:
                is_private = True

        scopes = None
        category = None
        if is_private:
            scopes = ["local"]
            category = "sensitive"
            if is_sensitive_mode:
                scopes = ["local"]

        is_study = bool(agent._is_study_mode(user_msg, model_hint)) if hasattr(agent, "_is_study_mode") else False
        if not is_study and not is_private and user_msg:
            try:
                from memory.core.taxonomy import classify_category
                if classify_category(user_msg) == "learning":
                    is_study = True
            except Exception:
                pass
        if is_study and not is_private:
            category = "learning"

        defer_analysis = _resolve_conversation_defer_analysis()
        topic_mode = _resolve_topic_judgement_mode()
        topics: List[str] = []

        if not defer_analysis:
            stream_topics = _normalize_topics(extracted_topics or [])
            fallback_topics = _normalize_topics(topics_from_assistant_text or [])
            taxonomy_topics = _detect_taxonomy_topics(user_msg, cleaned_assistant_msg)
            if topic_mode == "llm_first":
                source_orders = (stream_topics, fallback_topics, taxonomy_topics)
                for source_topics in source_orders:
                    for t in source_topics:
                        if t not in topics:
                            topics.append(t)
            elif topic_mode == "hybrid":
                source_orders = (taxonomy_topics, fallback_topics, stream_topics)
                for source_topics in source_orders:
                    for t in source_topics:
                        if t not in topics:
                            topics.append(t)
            else:
                for source_topics in (taxonomy_topics, fallback_topics):
                    for t in source_topics:
                        if t not in topics:
                            topics.append(t)
                if not topics:
                    for t in stream_topics:
                        if t not in topics:
                            topics.append(t)

        if (not defer_analysis) and is_study and "study" not in topics:
            topics.append("study")
        if (not defer_analysis) and user_msg and len(user_msg) > 10 and "chat" not in topics:
            topics.append("chat")
        if category == "sensitive" and "sensitive" not in topics:
            topics.append("sensitive")
        if category == "learning" and "learning" not in topics:
            topics.append("learning")

        topics = _normalize_topics(topics)
        topics_for_store = topics if topics else None

        thought_text = _normalize_thought_text(thought, cleaned_assistant_msg)
        thought_source = "model"
        if len(thought_text) > 1500:
            thought_text = thought_text[:1500]

        metadata = {
            "message_id": message_id,
            "model_hint": model_hint,
            "timestamp": time.time(),
            "trace_id": str(uuid.uuid4()),
            "platform": platform or "",
        }
        if thought_text and (not is_internal_circle_session):
            metadata["thought"] = thought_text
            metadata["thought_source"] = thought_source

        if user_msg:
            memory_calls.append(
                {
                    "content": user_msg,
                    "source": "user",
                    "topics": topics_for_store,
                    "scopes": scopes,
                    "category": category,
                    "is_sensitive_mode": is_sensitive_mode,
                    "metadata": {
                        **metadata,
                        "event_ref": event_refs.get("user"),
                        "defer_analysis": defer_analysis,
                    },
                }
            )
        if cleaned_assistant_msg:
            assistant_metadata = {
                **metadata,
                "reply_content": cleaned_assistant_msg,
                "event_ref": event_refs.get("assistant"),
                "defer_analysis": defer_analysis,
            }
            if thought_text:
                assistant_metadata["reasoning_content"] = thought_text
            memory_calls.append(
                {
                    "content": cleaned_assistant_msg,
                    "source": "assistant",
                    "topics": topics_for_store,
                    "scopes": scopes,
                    "category": category,
                    "is_sensitive_mode": is_sensitive_mode,
                    "metadata": assistant_metadata,
                }
            )
        if thought_text and (not is_internal_circle_session):
            memory_calls.append(
                {
                    "content": thought_text,
                    "source": "system",
                    "topics": ["thinking"],
                    "scopes": ["local"],
                    "category": "thinking",
                    "metadata": {
                        "message_id": message_id,
                        "model_hint": model_hint,
                        "timestamp": time.time(),
                        "trace_id": str(uuid.uuid4()),
                        "thought_source": thought_source,
                        "reply_content": cleaned_assistant_msg,
                        "event_ref": event_refs.get("thinking"),
                        "defer_analysis": False,
                        "hidden": True,
                    },
                }
            )

        if memory_calls and hasattr(mm, "add_memory"):
            t0 = time.time()
            mm_user_id = getattr(mm, 'user_id', 'unknown')
            logger.info(f"About to save {len(memory_calls)} memories to mm for user_id={user_id}, mm.user_id={mm_user_id}")

            def _write_all() -> None:
                for i, kwargs in enumerate(memory_calls):
                    try:
                        mid = mm.add_memory(**kwargs)
                        logger.info(f"Saved memory {i+1}/{len(memory_calls)}: mid={mid}, source={kwargs.get('source')}, content_len={len(kwargs.get('content', ''))}")
                    except Exception as e:
                        logger.warning(f"Failed to save memory {i+1}/{len(memory_calls)}: {e}")
                        import traceback
                        logger.warning(f"Traceback: {traceback.format_exc()}")

            await asyncio.to_thread(_write_all)

            if hasattr(mm, "_schedule_save"):
                try:
                    mm._schedule_save()
                except Exception:
                    pass

            logger.info(
                "Saved history for %s (DeferAnalysis: %s, TopicMode: %s, Topics: %s, Scopes: %s) cost=%.4fs",
                str(user_id),
                str(defer_analysis),
                str(topic_mode),
                str(topics),
                str(scopes),
                time.time() - t0,
            )
            if defer_analysis:
                try:
                    from core.services.data_ops.service import get_data_ops_service

                    asyncio.create_task(
                        get_data_ops_service().submit_memory_rule_analysis(
                            user_id=str(user_id), use_queue=True
                        )
                    )
                    asyncio.create_task(
                        get_data_ops_service().submit_memory_ai_shadow_analysis(
                            user_id=str(user_id), use_queue=True
                        )
                    )
                except Exception as schedule_error:
                    logger.warning(
                        "Failed to schedule deferred analysis for %s: %s",
                        str(user_id),
                        str(schedule_error),
                    )

    except Exception as e:
        logger.error(f"保存历史记录失败: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")


async def clear_history(agent: Any, user_id: str, mode: str = "all") -> None:
    try:
        if hasattr(agent, "get_memory_manager_async"):
            mm = await agent.get_memory_manager_async(user_id)
        else:
            mm = agent._get_memory_manager(user_id)
        if hasattr(mm, "clear_memory"):
            mm.clear_memory(mode=mode)
            logger.info(f"Cleared history for user {user_id} with mode {mode}")

            try:
                get_session_manager().delete_kvswap_file(str(user_id))
            except Exception:
                pass

            try:
                from core.services.scheduler.cpp_scheduler_engine import (
                    get_scheduler_engine,
                )

                scheduler_engine = get_scheduler_engine(auto_start=False)
                await scheduler_engine.clear_conversation_cache(str(user_id))
            except Exception as e:
                logger.warning(
                    "Failed to clear runtime LLM cache for %s: %s", user_id, e
                )

            if str(mode or "").strip().lower() == "all":
                try:
                    await asyncio.to_thread(
                        get_chat_history_store().delete_conversation, str(user_id)
                    )
                except Exception as e:
                    logger.warning(f"Failed to delete chat history files for {user_id}: {e}")

                try:
                    await asyncio.to_thread(
                        _delete_daily_event_refs_for_conversation, str(user_id)
                    )
                except Exception as e:
                    logger.warning(f"Failed to delete daily event refs for {user_id}: {e}")

            # Also reset active care state when clearing all memory
            if str(mode or "").strip().lower() == "all":
                try:
                    from core.services.active_care.storage.storage import ActiveCareStorage
                    active_care_storage = ActiveCareStorage()
                    # 清空主动关怀的状态
                    await active_care_storage.save_proactive_state({
                        "last_user_interaction_ts": 0.0,
                        "last_goodnight_ts": 0.0,
                        "last_goodmorning_ts": 0.0,
                        "last_goodnight_probe_ts": 0.0,
                        "last_sent_ts": 0.0,
                        "last_attempt_ts": 0.0,
                        "next_llm_decision_ts": 0.0,
                        "today_sent_events": [],
                        "today_sent_events_date": "",
                        "reduced_mode_active": False,
                        "reduced_mode_reason": "none",
                        "reduced_mode_label": "",
                        "reduced_mode_started_ts": 0.0,
                        "reduced_mode_expected_end_ts": 0.0,
                        "last_sleep_session_start_ts": 0.0,
                        "last_sleep_session_end_ts": 0.0,
                        "last_sleep_session_duration_seconds": 0,
                    })
                    logger.info(f"Cleared active care state for user {user_id}")
                except Exception as e:
                    logger.warning(f"Failed to clear active care state for {user_id}: {e}")

            # Also reset session title to default to reflect cleared history
            try:
                get_session_manager().update_session(str(user_id), title="New Chat")
            except Exception as e:
                logger.warning(f"Failed to reset session title for {user_id}: {e}")
        else:
            logger.warning(
                f"Memory manager for {user_id} does not support clear_memory"
            )
    except Exception as e:
        logger.error(f"Failed to clear history: {e}")


def _delete_daily_event_refs_for_conversation(conversation_id: str) -> None:
    base_daily_dir = get_daily_dir_for_conversation(conversation_id)
    if not base_daily_dir.exists():
        return
    target_cid = str(conversation_id or "").strip()
    for event_file in base_daily_dir.rglob("*.jsonl"):
        if event_file.name not in {"chat_actions.jsonl", "active_care_actions.jsonl"}:
            continue
        try:
            kept_lines: List[str] = []
            changed = False
            for raw_line in event_file.read_text(encoding="utf-8").splitlines():
                line = str(raw_line or "").strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    kept_lines.append(line)
                    continue
                if str(payload.get("conversation_id") or "").strip() == target_cid:
                    changed = True
                    continue
                kept_lines.append(line)
            if changed:
                event_file.write_text(
                    "\n".join(kept_lines) + ("\n" if kept_lines else ""),
                    encoding="utf-8",
                )
        except Exception:
            continue
