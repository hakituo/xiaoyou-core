import asyncio
from typing import Any, Dict, List, Optional, Tuple

from core.utils.logger import get_logger
from memory.weighted_memory_manager import WeightedMemoryManager

logger = get_logger("ChatAgent")


def select_message_tools(
    message: str, *, mode: str = "chat", include_web_search: bool = True,
    persona_filename: Optional[str] = None,
) -> List[str]:
    """兼容入口；角色常驻、按需范围和文本路由统一由工具策略管理。"""
    from core.tools.tool_policy import select_role_tools

    return select_role_tools(
        message, persona_filename=persona_filename, mode=mode,
        include_web_search=include_web_search,
    )


def _consume_carryover(
    user_id: Optional[str], persona_filename: Optional[str], mode: str
) -> List[str]:
    """取出上一请求延续下来的工具名；没有 conversation_id 时不延续。"""
    if not user_id:
        return []
    try:
        from core.tools.tool_carryover import (
            ToolCarryoverManager,
            get_tool_carryover_manager,
        )
        from core.utils.data.scope_registry import resolve_persona_slug_scope

        key = ToolCarryoverManager.build_key(
            user_id, resolve_persona_slug_scope(persona_filename), mode
        )
        return get_tool_carryover_manager().get(key)
    except Exception as e:  # noqa: BLE001
        logger.debug("读取工具延续状态失败，按无延续处理: %s", e)
        return []


async def prepare_active_tools(
    agent: Any, message: str, model_hint: Optional[str],
    persona_filename: Optional[str] = None, user_id: Optional[str] = None,
) -> List[str]:
    # 判断是否使用服务端web_search（智谱等厂商的原生搜索）
    use_server_side_search = False
    try:
        from config.model_config import should_use_server_side_web_search, is_web_search_enabled
        if is_web_search_enabled() and hasattr(agent, "llm_module"):
            current_model = agent.llm_module.get_current_model_name()
            current_provider = ""
            if current_model and current_model.startswith("cloud:"):
                parts = current_model.split(":", 2)
                if len(parts) >= 2:
                    current_provider = parts[1]
            model_name = current_model.split(":")[-1] if ":" in current_model else current_model
            use_server_side_search = should_use_server_side_web_search(current_provider, model_name)
    except Exception:
        pass

    mode = "chat"
    if hasattr(agent, "_is_study_mode") and agent._is_study_mode(message, model_hint):
        mode = "study"

    # 服务端搜索时不在本地工具列表中添加 web_search；其余工具按本轮意图注入。
    web_search_enabled = False
    if not use_server_side_search:
        try:
            from config.model_config import is_web_search_enabled
            web_search_enabled = bool(is_web_search_enabled())
        except Exception:
            web_search_enabled = True
    from core.tools.tool_visibility import resolve_persona_filename

    effective_persona = resolve_persona_filename(persona_filename)
    active_tools = select_message_tools(
        message,
        mode=mode,
        include_web_search=web_search_enabled,
        persona_filename=effective_persona,
    )

    # 跨请求延续：上一请求真正用过的按需工具，这一请求直接带上，省掉一次 discovery。
    # 这里只产出候选名，不做权限判断——后面 filter_tool_names 照旧会过滤，
    # carryover 不构成授权。
    carried = _consume_carryover(user_id, effective_persona, mode)
    if carried:
        active_tools = list(dict.fromkeys([*active_tools, *carried]))

    if not message:
        return active_tools

    msg_lower = message.lower()
    vocab_keywords = [
        "单词",
        "英语",
        "背诵",
        "复习",
        "word",
        "vocabulary",
        "study",
        "exam",
        "grade",
    ]
    should_check_vocab = mode == "study" or any(k in msg_lower for k in vocab_keywords)

    if should_check_vocab and getattr(agent, "vocab_manager", None):
        try:
            stats = await asyncio.to_thread(agent.vocab_manager.get_stats)
            due_count = stats.get("due_words", 0)
            if due_count > 0:
                await asyncio.to_thread(agent.vocab_manager.get_daily_words, limit=3)
        except Exception as e:
            logger.warning(f"Failed to check vocab status: {e}")

    return active_tools


async def resolve_persona_prompt(
    agent: Any,
    memory_manager: Any,
    user_id: str,
    message: str,
    active_tools: List[str],
    user_name: Optional[str],
    persona_filename: Optional[str] = None,
) -> str:
    persona_system_prompt = ""
    persona_signature = ""
    effective_persona_filename = str(persona_filename or "").strip()
    try:
        from core.character.managers.persona_manager import get_persona_manager
        pm = get_persona_manager()
        sig_filename = effective_persona_filename or str(pm.get_current_filename() or "").strip()
        sig_revision = int(getattr(pm, 'get_revision', lambda: 0)() or 0)
        persona_signature = f"{sig_filename}@{sig_revision}"
    except Exception:
        if effective_persona_filename:
            persona_signature = f"{effective_persona_filename}@0"
        else:
            persona_signature = ""

    existing_persona_ids: List[str] = []
    if isinstance(memory_manager, WeightedMemoryManager):
        try:
            def _get_persona_cache():
                return memory_manager.get_memories_by_topic("persona_base_prompt", limit=5)

            existing = await asyncio.to_thread(_get_persona_cache)
            for item in existing or []:
                if not isinstance(item, dict):
                    continue
                item_id = item.get("id")
                if item_id:
                    existing_persona_ids.append(str(item_id))
        except Exception:
            existing_persona_ids = []

    if not persona_system_prompt and hasattr(agent, "_get_dynamic_system_prompt"):
        try:
            mode = None
            if hasattr(agent, "_determine_mode"):
                mode = str(agent._determine_mode(message) or "").strip() or None
            try:
                # memory_manager 必须透传，否则 get_context_injection 拿不到已有实例，
                # 会额外装载一份全量记忆数据（历史问题：每轮对话泄漏一份，RSS 涨到 9GB+）
                persona_system_prompt = await asyncio.to_thread(
                    agent._get_dynamic_system_prompt,
                    user_id=user_id,
                    active_tools=active_tools,
                    mode=mode,
                    message=message,
                    user_name=user_name,
                    persona_filename=effective_persona_filename or None,
                    memory_manager=memory_manager,
                )
                persona_system_prompt = str(persona_system_prompt or "").strip()
            except TypeError:
                persona_system_prompt = await asyncio.to_thread(
                    agent._get_dynamic_system_prompt,
                    user_id=user_id,
                    active_tools=active_tools,
                    mode=mode,
                    message=message,
                )
                persona_system_prompt = str(persona_system_prompt or "").strip()
        except Exception:
            persona_system_prompt = ""

    if not persona_system_prompt:
        try:
            from core.character.managers.persona_manager import get_persona_manager

            pm = get_persona_manager()
            if effective_persona_filename:
                persona_data = pm.get_persona_by_filename(effective_persona_filename)
            else:
                persona_data = pm.get_current_persona()
            if isinstance(persona_data, dict):
                persona_system_prompt = str(persona_data.get("system_prompt_template") or "").strip()
        except Exception:
            persona_system_prompt = ""

    if not persona_system_prompt:
        try:
            from core.character.aveline import get_aveline_system_prompt_template

            persona_system_prompt = str(get_aveline_system_prompt_template() or "").strip()
        except Exception:
            persona_system_prompt = ""

    if not persona_system_prompt:
        persona_system_prompt = str(getattr(agent.config, "system_prompt", "") or "").strip()

    if persona_system_prompt and isinstance(memory_manager, WeightedMemoryManager):
        # [OPTIMIZATION] 不要每次都去存/删 persona_prompt，只在签名改变时存一次，极大减少 I/O 阻塞
        try:
            def _write_persona_prompt_if_needed() -> None:
                # Check if we already have the latest signature
                needs_update = True
                for mid in list(existing_persona_ids):
                    try:
                        mem = memory_manager.weighted_memories.get(mid)
                        if mem and mem.get("metadata", {}).get("persona_signature") == persona_signature:
                            needs_update = False
                            break
                        else:
                            memory_manager.delete_message(mid)
                    except Exception:
                        pass
                
                if not needs_update:
                    return

                memory_manager.add_memory(
                    content=persona_system_prompt,
                    source="system",
                    topics=["persona_base_prompt"],
                    category="persona_prompt",
                    weight=1.0,
                    is_important=False,
                    metadata={
                        "hidden": True,
                        "persona_signature": persona_signature,
                        "user_name": user_name,
                        "conversation_id": user_id,
                        "is_system_cache": True,
                    },
                )
                # persona_prompt 已通过 _NON_DIALOGUE_CATEGORIES 过滤,
                # 不会进入 short_term_memory,无需再调整位置

            # fire and forget，不要阻塞主流程
            asyncio.create_task(asyncio.to_thread(_write_persona_prompt_if_needed))
        except Exception:
            pass

    return persona_system_prompt


def detect_cloud_mode(agent: Any, model_hint: Optional[str]) -> bool:
    is_cloud = False
    if model_hint:
        mh_lower = model_hint.lower()
        if mh_lower.startswith("cloud:") or "cloud:" in mh_lower:
            is_cloud = True
        elif any(k in mh_lower for k in ["siliconflow", "dashscope", "openai"]):
            is_cloud = True
        elif "deepseek" in mh_lower and not mh_lower.endswith(".gguf"):
            is_cloud = True
    if (
        not is_cloud
        and getattr(agent, "llm_module", None)
        and hasattr(agent.llm_module, "get_current_model_name")
    ):
        model_name = str(agent.llm_module.get_current_model_name())
        mn_lower = model_name.lower()
        if mn_lower.startswith("cloud:") or "cloud:" in mn_lower:
            is_cloud = True
    return is_cloud


async def resolve_scope_and_sensitive_mode(
    memory_manager: Any,
    user_id: str,
    scope_override: Optional[str],
    is_cloud: bool,
    messages: List[Dict[str, str]],
    persona_filename: Optional[str] = None,
) -> Tuple[str, bool]:
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
            current_persona = str(pm.get_current_filename() or "").replace("\\", "/", -1).lower()
            if current_persona.startswith("sensitive/") or "/sensitive/" in current_persona:
                is_sensitive_mode = True
        except Exception:
            pass
        
    # Check PreferenceManager
    if not is_sensitive_mode:
        try:
            from core.managers.preference_manager import get_preference_manager
            prefs = get_preference_manager()
            if prefs.get_mode() == "privacy":
                is_sensitive_mode = True
        except Exception:
            pass

    try:
        mm = memory_manager
        if not is_sensitive_mode and mm is not None and hasattr(mm, "get_memories_by_topic"):
            def _get_sensitive_mode():
                return mm.get_memories_by_topic("sensitive_mode_control", limit=8)

            logger.info("[Context Build] Acquiring sensitive mode from mm (via to_thread)...")
            try:
                mode_memories = await asyncio.wait_for(
                    asyncio.to_thread(_get_sensitive_mode), timeout=10.0
                )
            except asyncio.TimeoutError:
                logger.error("[Context Build] TIMEOUT: get_memories_by_topic took >10s! Lock contention?")
                mode_memories = None
            from core.agents.chat_agent_components.persona_system.prompt.mode_control import (
                resolve_memory_mode_toggle,
            )

            if resolve_memory_mode_toggle(mode_memories) is True:
                is_sensitive_mode = True
                logger.info(f"User {user_id} is in SENSITIVE_MODE")
    except Exception as e:
        logger.warning(f"Failed to check Sensitive mode: {e}")

    scope = scope_override or ("cloud" if is_cloud else "local")
    if is_sensitive_mode:
        scope = "local"
    return scope, is_sensitive_mode
