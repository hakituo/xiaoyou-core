import asyncio
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger
from core.agents.chat_agent_components.context_budget import (
    apply_cloud_history_budget as _apply_cloud_history_budget,
)
from core.agents.chat_agent_components.context_budget import (
    apply_local_context_budget as _apply_local_context_budget,
)
from core.agents.chat_agent_components.context_budget import (
    fetch_history_for_scope as _fetch_history_for_scope,
)
from core.agents.chat_agent_components.context_budget import (
    inject_sensitive_memories as _inject_sensitive_memories,
)
from core.agents.chat_agent_components.context_budget import (
    inject_thinking_store as _inject_thinking_store,
)
from core.agents.chat_agent_components.context_persona import (
    detect_cloud_mode as _detect_cloud_mode,
)
from core.agents.chat_agent_components.context_persona import (
    prepare_active_tools as _prepare_active_tools,
)
from core.agents.chat_agent_components.context_persona import (
    resolve_persona_prompt as _resolve_persona_prompt,
)
from core.agents.chat_agent_components.context_persona import (
    resolve_scope_and_sensitive_mode as _resolve_scope_and_sensitive_mode,
)
from core.tools.tool_visibility import filter_tool_names
from memory.weighted_memory_manager import WeightedMemoryManager

logger = get_logger("ChatAgent")


_rag_rewrite_llm = None
_rag_rewrite_llm_lock = asyncio.Lock()
_rag_rewrite_inference_lock = asyncio.Lock()
_rag_rewrite_llm_task = None
_rag_rewrite_load_failed_until = 0.0

_context_compress_llm = None
_context_compress_llm_lock = asyncio.Lock()
_context_compress_inference_lock = asyncio.Lock()
_context_compress_llm_task = None
_context_compress_load_failed_until = 0.0


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    s = str(text)
    m = re.search(r"\{[\s\S]*\}", s)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _resolve_project_path(path: str) -> str:
    p = str(path or "").strip()
    if not p:
        return p
    if os.path.isabs(p):
        return p
    try:
        from core.utils.common import get_project_root

        root = str(get_project_root())
    except Exception:
        root = os.getcwd()
    return os.path.join(root, p)


def _safe_float(v: Any, default: float) -> float:
    try:
        x = float(v)
        if x > 0:
            return x
    except Exception:
        return float(default)
    return float(default)


def _safe_int(v: Any, default: int) -> int:
    try:
        x = int(v)
        if x > 0:
            return x
    except Exception:
        return int(default)
    return int(default)


def _split_sentences(text: str) -> List[str]:
    s = str(text or "").strip()
    if not s:
        return []
    parts = re.split(r"(?<=[。！？!?；;\n])\s*", s)
    out = [p.strip() for p in parts if p and p.strip()]
    return out


def _score_sentence(sentence: str, role: str) -> float:
    s = str(sentence or "")
    if not s.strip():
        return 0.0

    score = 0.0
    if role == "user":
        score += 1.0
    if re.search(r"\d", s):
        score += 2.0
    if re.search(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}", s):
        score += 2.0
    if re.search(r"(我叫|名字|生日|住在|地址|电话|手机号|邮箱|学校|公司|工作|喜欢|讨厌|不喜欢|过敏|禁忌|不要|禁止|记住|以后)", s):
        score += 3.0
    if len(s) >= 18:
        score += 0.5
    return score


def _heuristic_compress_history(history: List[Dict[str, Any]], max_chars: int) -> str:
    max_chars = max(200, int(max_chars))
    candidates: List[Dict[str, Any]] = []
    for m in history:
        role = str(m.get("role") or m.get("source") or "").strip() or "unknown"
        role = role if role in ("user", "assistant", "system") else "system"
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        for sent in _split_sentences(content):
            candidates.append(
                {
                    "role": role,
                    "sent": sent,
                    "score": _score_sentence(sent, role),
                }
            )

    candidates.sort(key=lambda x: (x.get("score", 0.0), len(str(x.get("sent") or ""))), reverse=True)

    lines: List[str] = []
    used = 0
    for item in candidates:
        role = item.get("role") or "system"
        sent = str(item.get("sent") or "").strip()
        if not sent:
            continue
        if len(sent) > 220:
            sent = sent[:220].rstrip() + "..."
        line = f"- ({role}) {sent}"
        if used + len(line) + 1 > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
        if len(lines) >= 14:
            break

    if not lines:
        raw = " ".join([str(m.get("content") or "").strip() for m in history if str(m.get("content") or "").strip()])
        raw = re.sub(r"\s+", " ", raw).strip()
        return raw[:max_chars]

    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars].rstrip()
    return out


async def _schedule_context_compress_llm_load(model_path: str) -> None:
    global _context_compress_llm, _context_compress_llm_task, _context_compress_load_failed_until

    if _context_compress_llm is not None or _context_compress_llm_task is not None:
        return
    if time.time() < float(_context_compress_load_failed_until or 0.0):
        return

    async with _context_compress_llm_lock:
        if _context_compress_llm is not None or _context_compress_llm_task is not None:
            return
        if time.time() < float(_context_compress_load_failed_until or 0.0):
            return

        async def _load() -> None:
            global _context_compress_llm, _context_compress_llm_task, _context_compress_load_failed_until
            try:
                try:
                    from llama_cpp import Llama
                except Exception:
                    _context_compress_load_failed_until = time.time() + 60
                    return

                mp = _resolve_project_path(model_path)
                if not mp or not os.path.exists(mp):
                    _context_compress_load_failed_until = time.time() + 60
                    return

                n_threads = int(os.environ.get("XIAOYOU_CONTEXT_COMPRESS_THREADS") or "0")
                if n_threads <= 0:
                    try:
                        n_threads = max(1, min(os.cpu_count() or 4, 4))
                    except Exception:
                        n_threads = 4

                def _create_llm_with_threads():
                    return Llama(
                        model_path=mp,
                        n_ctx=768,
                        n_gpu_layers=0,
                        n_threads=n_threads,
                        verbose=False,
                    )

                def _create_llm_default():
                    return Llama(
                        model_path=mp,
                        n_ctx=768,
                        n_gpu_layers=0,
                        verbose=False,
                    )

                try:
                    _context_compress_llm = await asyncio.to_thread(_create_llm_with_threads)
                except TypeError:
                    _context_compress_llm = await asyncio.to_thread(_create_llm_default)
                except Exception:
                    _context_compress_llm = None
                    _context_compress_load_failed_until = time.time() + 60
            finally:
                _context_compress_llm_task = None

        _context_compress_llm_task = asyncio.create_task(_load())


async def _get_context_compress_llm(model_path: str):
    if _context_compress_llm is not None:
        return _context_compress_llm
    await _schedule_context_compress_llm_load(model_path)
    return _context_compress_llm


async def _compress_history_block(
    history: List[Dict[str, Any]],
    max_chars: int,
    model_path: str,
    max_tokens: int,
    timeout_seconds: float,
    api_model: Optional[str] = None,
) -> str:
    max_chars = max(200, int(max_chars))
    if not history:
        return ""

    # 构建压缩用的文本片段
    snippet_lines: List[str] = []
    for m in history:
        role = str(m.get("role") or m.get("source") or "").strip() or "unknown"
        if role not in ("system", "user", "assistant"):
            role = "system"
        c = str(m.get("content") or "").strip()
        if not c:
            continue
        if len(c) > 420:
            c = c[:420] + "..."
        # 标记重要消息，帮助LLM优先保留
        importance_marker = ""
        if m.get("is_important"):
            importance_marker = " [!]"
        elif float(m.get("weight", 0) or 0) >= 3.0:
            importance_marker = " [*]"
        snippet_lines.append(f"[{role}]{importance_marker} {c}")
    snippet = "\n".join(snippet_lines).strip()
    if not snippet:
        return ""

    from core.agents.chat_agent_components.persona_system.prompt.components import CONTEXT_COMPRESS_SYSTEM_PROMPT
    sys_prompt = CONTEXT_COMPRESS_SYSTEM_PROMPT

    # 优先使用API模型（如果配置了）
    api_model_str = str(api_model or "").strip()
    if api_model_str and api_model_str.startswith("cloud:"):
        try:
            from core.llm import get_llm_module
            llm_module = get_llm_module()
            
            async def _run_api_infer() -> str:
                result = await llm_module.chat(
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": snippet},
                    ],
                    model_path=api_model_str,
                    max_tokens=int(max_tokens),
                    temperature=0.0,
                )
                content = ""
                if isinstance(result, dict):
                    content = result.get("response", "")
                else:
                    content = str(result or "")
                return str(content or "").strip()
            
            raw = await asyncio.wait_for(_run_api_infer(), timeout=max(0.5, float(timeout_seconds)))
            obj = _extract_json_object(raw)
            if isinstance(obj, dict):
                summary = str(obj.get("summary") or "").strip()
                facts = obj.get("facts")
                open_q = obj.get("open_questions")
                
                lines: List[str] = []
                if summary:
                    lines.append(str(summary))
                if isinstance(facts, list):
                    for it in facts[:8]:
                        t = str(it or "").strip()
                        if t:
                            lines.append(f"- {t}")
                if isinstance(open_q, list):
                    qs = []
                    for it in open_q[:5]:
                        t = str(it or "").strip()
                        if t:
                            qs.append(t)
                    if qs:
                        lines.append("未解决：" + "；".join(qs))
                
                out = "\n".join(lines).strip()
                if out:
                    if len(out) > max_chars:
                        out = out[:max_chars].rstrip()
                    logger.info("Context compress via API model %s: %d chars", api_model_str, len(out))
                    return out
        except Exception as e:
            logger.warning("API model compress failed, falling back: %s", e)

    # 回退到本地模型
    mp = str(model_path or "").strip()
    if not mp:
        return _heuristic_compress_history(history, max_chars=max_chars)

    llm = await _get_context_compress_llm(mp)
    if llm is None:
        return _heuristic_compress_history(history, max_chars=max_chars)

    async def _run_infer() -> str:
        async with _context_compress_inference_lock:
            result = await asyncio.to_thread(
                llm.create_chat_completion,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": snippet},
                ],
                max_tokens=int(max_tokens),
                temperature=0.0,
                top_p=0.9,
            )
        content = ""
        try:
            content = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
        except Exception:
            content = ""
        return str(content or "").strip()

    try:
        raw = await asyncio.wait_for(_run_infer(), timeout=max(0.05, float(timeout_seconds)))
    except Exception:
        return _heuristic_compress_history(history, max_chars=max_chars)

    obj = _extract_json_object(raw)
    if not isinstance(obj, dict):
        return _heuristic_compress_history(history, max_chars=max_chars)

    summary = str(obj.get("summary") or "").strip()
    facts = obj.get("facts")
    open_q = obj.get("open_questions")

    lines: List[str] = []
    if summary:
        lines.append(str(summary))

    if isinstance(facts, list):
        for it in facts[:8]:
            t = str(it or "").strip()
            if t:
                lines.append(f"- {t}")

    if isinstance(open_q, list):
        qs = []
        for it in open_q[:5]:
            t = str(it or "").strip()
            if t:
                qs.append(t)
        if qs:
            lines.append("未解决：" + "；".join(qs))

    out = "\n".join(lines).strip()
    if not out:
        out = _heuristic_compress_history(history, max_chars=max_chars)
    if len(out) > max_chars:
        out = out[:max_chars].rstrip()
    return out


async def _schedule_rag_rewrite_llm_load(model_path: str) -> None:
    global _rag_rewrite_llm, _rag_rewrite_llm_task, _rag_rewrite_load_failed_until

    if _rag_rewrite_llm is not None or _rag_rewrite_llm_task is not None:
        return
    if time.time() < float(_rag_rewrite_load_failed_until or 0.0):
        return

    async with _rag_rewrite_llm_lock:
        if _rag_rewrite_llm is not None or _rag_rewrite_llm_task is not None:
            return
        if time.time() < float(_rag_rewrite_load_failed_until or 0.0):
            return

        async def _load() -> None:
            global _rag_rewrite_llm, _rag_rewrite_llm_task, _rag_rewrite_load_failed_until
            try:
                try:
                    from llama_cpp import Llama
                except Exception:
                    _rag_rewrite_load_failed_until = time.time() + 60
                    return

                mp = _resolve_project_path(model_path)
                if not mp or not os.path.exists(mp):
                    _rag_rewrite_load_failed_until = time.time() + 60
                    return

                n_threads = int(os.environ.get("XIAOYOU_RAG_REWRITE_THREADS") or "0")
                if n_threads <= 0:
                    try:
                        n_threads = max(1, min(os.cpu_count() or 4, 4))
                    except Exception:
                        n_threads = 4

                def _create_llm_with_threads():
                    return Llama(
                        model_path=mp,
                        n_ctx=512,
                        n_gpu_layers=0,
                        n_threads=n_threads,
                        verbose=False,
                    )

                def _create_llm_default():
                    return Llama(
                        model_path=mp,
                        n_ctx=512,
                        n_gpu_layers=0,
                        verbose=False,
                    )

                try:
                    _rag_rewrite_llm = await asyncio.to_thread(_create_llm_with_threads)
                except TypeError:
                    _rag_rewrite_llm = await asyncio.to_thread(_create_llm_default)
                except Exception:
                    _rag_rewrite_llm = None
                    _rag_rewrite_load_failed_until = time.time() + 60
            finally:
                _rag_rewrite_llm_task = None

        _rag_rewrite_llm_task = asyncio.create_task(_load())


async def _get_rag_rewrite_llm(model_path: str):
    if _rag_rewrite_llm is not None:
        return _rag_rewrite_llm
    await _schedule_rag_rewrite_llm_load(model_path)
    return _rag_rewrite_llm


async def _rewrite_rag_query(
    message: str,
    model_path: str,
    max_tokens: int,
    timeout_seconds: float,
) -> Optional[str]:
    llm = await _get_rag_rewrite_llm(model_path)
    if llm is None:
        return None

    from core.agents.chat_agent_components.persona_system.prompt.components import RAG_REWRITE_SYSTEM_PROMPT
    sys_prompt = RAG_REWRITE_SYSTEM_PROMPT

    async def _run_infer() -> str:
        async with _rag_rewrite_inference_lock:
            result = await asyncio.to_thread(
                llm.create_chat_completion,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": str(message or "").strip()},
                ],
                max_tokens=int(max_tokens),
                temperature=0.0,
                top_p=0.9,
            )
        content = ""
        try:
            content = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
        except Exception:
            content = ""
        return str(content or "").strip()

    try:
        raw = await asyncio.wait_for(_run_infer(), timeout=max(0.05, float(timeout_seconds)))
    except Exception:
        return None

    obj = _extract_json_object(raw)
    query = ""
    if isinstance(obj, dict):
        query = str(obj.get("query") or "").strip()
    if not query:
        query = str(raw or "").strip()

    query = query.strip().strip("\"'")
    if not query:
        return None
    if len(query) > 160:
        query = query[:160].strip()
    return query or None


async def perform_context_summary(
    agent: Any,
    user_id: str,
    memory_manager: WeightedMemoryManager,
    scope: Optional[str] = None,
) -> None:
    try:
        def _read_memories():
            lock_ctx = memory_manager._rw_lock.read_lock() if getattr(memory_manager, '_use_rw_lock', False) else memory_manager.lock
            with lock_ctx:
                if not scope:
                    return list(memory_manager.short_term_memory)
                else:
                    filtered: List[Dict[str, Any]] = []
                    for m in memory_manager.short_term_memory:
                        scopes = m.get("scopes")
                        if scopes is None:
                            filtered.append(m)
                            continue
                        if isinstance(scopes, list) and scope in scopes:
                            filtered.append(m)
                    return filtered

        memories = await asyncio.to_thread(_read_memories)

        filtered_memories: List[Dict[str, Any]] = []
        for m in memories:
            if not isinstance(m, dict):
                continue
            source = str(m.get("source") or "").strip().lower()
            
            # 多模态内容处理：剥离图片base64，只保留文本
            raw_content = m.get("content")
            if isinstance(raw_content, list):
                text_parts = []
                for item in raw_content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                    elif isinstance(item, dict) and item.get("type") == "image_url":
                        text_parts.append("[图片]")
                content = " ".join(text_parts).strip()
            else:
                content = str(raw_content or "").strip()
                if "data:image" in content and len(content) > 1000:
                    content = "[包含图片的复杂消息]"

            topics = {
                str(t).strip().lower()
                for t in (m.get("topics") or [])
                if str(t).strip()
            }
            if source == "system_summary":
                continue
            if content.startswith("【历史摘要】"):
                continue
            if "daily_summary" in topics:
                continue
            if content.startswith("已生成 ") and "每日学习总结" in content:
                continue
            
            # 创建一个浅拷贝并更新content，避免修改原始记忆对象（如果需要保留原样）
            # 或者直接修改它，但这里我们只在做摘要时使用清理过的文本
            clean_m = dict(m)
            clean_m["content"] = content
            filtered_memories.append(clean_m)

        if len(filtered_memories) < 30:
            return

        logger.info(f"检测到上下文长度达到 {len(filtered_memories)}，触发摘要逻辑...")

        to_summarize = filtered_memories[:-8]
        if not to_summarize:
            return

        text_block = "\n".join(
            [f"{m.get('source', 'unknown')}: {m.get('content', '')}" for m in to_summarize]
        )

        prompt: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": "You are a memory compressor. Summarize the following conversation segment into a concise paragraph. Capture key events, emotions, and facts. Output ONLY the summary text.",
            },
            {"role": "user", "content": f"Summarize this:\n{text_block}"},
        ]

        summary = ""
        if getattr(agent, "summary_llm", None):
            summary = await agent.summary_llm.chat(prompt, temperature=0.3)
        else:
            history_like = [
                {
                    "role": str(m.get("source") or "user"),
                    "content": str(m.get("content") or ""),
                }
                for m in to_summarize
            ]
            summary = _heuristic_compress_history(history_like, max_chars=420)

        if not summary:
            return

        logger.info(f"生成摘要成功: {summary[:50]}...")

        def _remove_summarized_memories():
            write_lock_ctx = memory_manager._rw_lock.write_lock() if getattr(memory_manager, '_use_rw_lock', False) else memory_manager.lock
            with write_lock_ctx:
                current_memories = memory_manager.short_term_memory
                ids_to_remove = {m["id"] for m in to_summarize}
                memory_manager.short_term_memory = [
                    m for m in current_memories if m["id"] not in ids_to_remove
                ]

        await asyncio.to_thread(_remove_summarized_memories)

        await asyncio.to_thread(
            memory_manager.add_memory,
            content=f"【历史摘要】 {summary}",
            source="system_summary",
            is_important=True,
            topics=["summary", "history_offload"],
            scopes=[scope] if scope else None,
        )
    except Exception as e:
        logger.error(f"执行上下文摘要失败: {e}")


async def build_conversation_history(
    agent: Any,
    user_id: str,
    message: Any,
    model_hint: Optional[str] = None,
    scope_override: Optional[str] = None,
    system_prompt_override: Optional[str] = None,
    user_name: Optional[str] = None,
    persona_filename: Optional[str] = None,
    extra_dynamic_context: Optional[str] = None,
    history_override: Optional[List[Dict[str, str]]] = None,
    active_tools_override: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    构建对话历史，调用统一的 prompt_construction 接口
    
    【架构设计】
    - 只负责获取上下文、历史消息等数据
    - prompt 构建全部交给 prompt_construction.py 中的统一接口
    """
    user_message = message
    message_text = ""
    if isinstance(message, list):
        for item in message:
            if item.get("type") == "text":
                message_text += item.get("text", "")
    else:
        message_text = str(message or "")

    if hasattr(agent, "get_memory_manager_async"):
        memory_manager = await agent.get_memory_manager_async(user_id)
    else:
        memory_manager = agent._get_memory_manager(user_id)

    t_total = time.perf_counter()
    t_last_checkpoint = t_total
    timings: Dict[str, float] = {}

    # 1. 获取必要的上下文数据
    active_tools = (
        list(active_tools_override)
        if active_tools_override is not None
        else await _prepare_active_tools(agent, message_text, model_hint)
    )
    
    # 解析 persona prompt（如果有覆盖）
    if isinstance(system_prompt_override, str) and system_prompt_override.strip():
        persona_system_prompt = system_prompt_override.strip()
    else:
        # 通过 resolve_persona_prompt 获取（缓存优化）
        persona_system_prompt = await _resolve_persona_prompt(
            agent=agent,
            memory_manager=memory_manager,
            user_id=user_id,
            message=message_text,
            active_tools=active_tools,
            user_name=user_name,
            persona_filename=persona_filename,
        )

    t_now = time.perf_counter()
    timings["persona_init"] = t_now - t_last_checkpoint
    t_last_checkpoint = t_now

    # 2. 确定模式和范围
    is_cloud = _detect_cloud_mode(agent, model_hint)
    logger.info(f"[Context Build] is_cloud mode: {is_cloud}, model_hint: {model_hint}")
    
    # 传递 persona_system_prompt 作为临时消息列表，用于解析模式
    temp_messages = []
    if persona_system_prompt:
        temp_messages.append({"role": "system", "content": persona_system_prompt})
    
    logger.info("[Context Build] Resolving scope and sensitive mode...")
    scope, is_sensitive_mode = await _resolve_scope_and_sensitive_mode(
        memory_manager=memory_manager,
        user_id=user_id,
        scope_override=scope_override,
        is_cloud=is_cloud,
        messages=temp_messages,
        persona_filename=persona_filename,
    )
    logger.info(f"[Context Build] scope={scope}, is_sensitive_mode={is_sensitive_mode}")

    current_mode = (
        "study"
        if hasattr(agent, "_is_study_mode") and agent._is_study_mode(message_text, model_hint)
        else "chat"
    )
    active_tools = filter_tool_names(
        active_tools,
        tool_registry=getattr(agent, "tool_registry", None),
        persona_filename=persona_filename,
        mode=current_mode,
        is_sensitive_mode=is_sensitive_mode,
    )

    if memory_manager and isinstance(memory_manager, WeightedMemoryManager):
        asyncio.create_task(perform_context_summary(agent, user_id, memory_manager, scope=scope))

    t_now = time.perf_counter()
    timings["sensitive_check"] = t_now - t_last_checkpoint
    t_last_checkpoint = t_now

    # 3. 获取历史消息
    t_history_fetch = time.perf_counter()
    is_study_mode = current_mode == "study"
    if not is_study_mode and message_text:
        try:
            from memory.core.taxonomy import classify_category
            if classify_category(message_text) == "learning":
                is_study_mode = True
        except Exception:
            pass
    logger.info(f"[Context Build] Fetching history for scope={scope}, is_study_mode={is_study_mode}...")
    if history_override is not None:
        history = [
            {"role": item["role"], "content": item["content"]}
            for item in history_override
            if isinstance(item, dict)
            and item.get("role") in {"user", "assistant"}
            and str(item.get("content") or "").strip()
        ]
    else:
        history = await _fetch_history_for_scope(memory_manager, user_id, scope, is_sensitive_mode=is_sensitive_mode, is_study_mode=is_study_mode, persona_filename=persona_filename or "")
    logger.info(f"[Context Build] Fetched {len(history)} history items")
    t_now = time.perf_counter()
    timings["history_fetch"] = t_now - t_history_fetch
    t_last_checkpoint = t_now

    if is_cloud and history:
        history = _apply_cloud_history_budget(history, message_text)

    # 4. 收集动态注入（state_context、敏感记忆等）
    state_context = None
    sensitive_injections = []
    if isinstance(memory_manager, WeightedMemoryManager):
        # 4a. 从用户消息中自动提取日常行为状态（吃饭/洗澡/吃药等）
        if message_text:
            try:
                await asyncio.to_thread(memory_manager.state_tracker.auto_update_from_text, message_text)
            except Exception as e:
                logger.debug(f"PersistentStateTracker auto_update 失败: {e}")
        # 4b. 获取状态上下文注入 prompt
        try:
            state_context = await asyncio.to_thread(memory_manager.get_state_context)
        except Exception as e:
            logger.warning(f"Failed to get state context: {e}")

    # 注入 thinking store（仅限本地）
    if not is_cloud:
        thinking_msgs = []
        await _inject_thinking_store(memory_manager, thinking_msgs)
        sensitive_injections.extend([msg["content"] for msg in thinking_msgs if msg.get("content")])

    # 应用本地上下文预算（仅限本地）
    if not is_cloud:
        budget_msgs = []
        history, user_message = await _apply_local_context_budget(
            history=history,
            messages=budget_msgs,
            user_message=user_message,
            active_tools=active_tools,
            compress_history_fn=_compress_history_block,
        )
        sensitive_injections.extend([msg["content"] for msg in budget_msgs if msg.get("content")])

    t_now = time.perf_counter()
    timings["context_slice"] = t_now - t_last_checkpoint
    t_last_checkpoint = t_now

    # 注入敏感记忆
    sensitive_msgs = []
    await _inject_sensitive_memories(
        memory_manager=memory_manager,
        is_sensitive_mode=is_sensitive_mode,
        messages=sensitive_msgs,
    )
    sensitive_injections.extend([msg["content"] for msg in sensitive_msgs if msg.get("content")])

    t_now = time.perf_counter()
    timings["sensitive_inject"] = t_now - t_last_checkpoint
    t_last_checkpoint = t_now

    # 5. 确定是否是 QQ 会话
    uid_lower = str(user_id or "").strip().lower()
    is_qq_session = bool(
        uid_lower.startswith("group_")
        or uid_lower.startswith("private_")
        or uid_lower.startswith("qq_")
        or uid_lower == "default_user"
    )

    # 6. 调用统一的 prompt 系统构建消息列表！
    # 导入统一接口（新架构）
    from .persona_system.prompt import build_complete_message_list
    
    messages = build_complete_message_list(
        agent=agent,
        user_id=user_id,
        message=message_text,
        user_name=user_name,
        history_messages=history,
        state_context=state_context,
        sensitive_injections=sensitive_injections,
        is_qq_session=is_qq_session,
        is_sensitive_mode=is_sensitive_mode,
        extra_dynamic_context=extra_dynamic_context,
        memory_manager=memory_manager,
        persona_filename=persona_filename,
        active_tools=active_tools,
    )

    total_cost = time.perf_counter() - t_total
    timings["final_process"] = total_cost - sum(timings.values())
    
    # 统计最终发送给LLM的消息
    final_num_messages = len(messages)
    final_total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    logger.info(f"[Final Context] 最终消息数量: {final_num_messages}, 最终总字符数: {final_total_chars}")
    
    if total_cost >= 0.0:
        timing_str = ", ".join([f"{k}: {v:.4f}s" for k, v in timings.items()])
        logger.info(
            f"build_conversation_history SLOW: {total_cost:.4f}s. Details: {timing_str}"
        )

    return messages
