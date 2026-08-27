"""
Prompt 纯拼装器

这个文件只做一件事：纯粹的 prompt 拼装！
不做数据获取、不做模式判断、只做拼装！

【缓存优化策略 - 关键设计】
DeepSeek Prompt Caching 基于前缀匹配，连续相同的 token 前缀才能命中缓存。

核心原则：
  1. system 消息必须100%静态（人设、性格、语言风格 —— 跨请求不变）
  2. 所有动态内容（时间、情绪、状态、记忆等）必须放到 user 消息前缀中
  3. 历史消息紧随其后，多轮对话天然命中缓存

错误设计（导致缓存失效）：
  [system: 静态+动态混合] → [history] → [user]
  问题：动态内容改变导致整个 system 消息变化，前缀匹配失败

正确设计（缓存命中率 ~90%+）：
  [system: 纯静态人设] → [history] → [user: 动态前缀 + 用户消息]
  优势：system 消息100%稳定，历史消息前缀稳定，只有最后一条 user 消息变化
"""
from typing import Any, Dict, List, Optional, Tuple

from core.tools.tool_visibility import filter_tool_names
from core.utils.logger import get_logger
from .special_days import (
    get_authoritative_calendar_prompt,
    get_special_day_prompt,
    get_upcoming_birthday_prompt,
)

from .data import (
    get_prompt_data,
    is_bionic_character,
    get_cached_bionic_state,
)
from .components import (
    build_time_context,
    build_emotion_context,
    build_food_context,
    build_study_context,
    build_user_bio_context_for_chat,
    build_mentioned_people_injection,
    finalize_and_clean_prompt,
)
from .context_gathering import get_tool_injection
from .self_improvement_prompts import build_self_improvement_prompt

logger = get_logger("PromptAssembler")


def _history_message_is_proactive(message: Dict[str, Any]) -> bool:
    """判断历史消息是否为主动关怀消息。"""
    metadata = message.get("metadata") or {}
    return bool(
        message.get("is_proactive")
        or (isinstance(metadata, dict) and metadata.get("is_proactive"))
        or (
            isinstance(metadata, dict)
            and str(metadata.get("type") or "").strip().lower() == "proactive"
        )
        or str(message.get("type") or "").strip().lower() == "proactive"
        or str(message.get("event_type") or "").strip().lower() == "proactive_message"
        or "[主动消息]" in str(message.get("content", ""))
    )


def _build_active_care_handoff_context(
    history_messages: List[Dict[str, Any]],
) -> Tuple[bool, Optional[str], bool]:
    """构建主动关怀到主对话的衔接上下文。"""
    has_proactive = False
    last_proactive_content: Optional[str] = None
    last_visible_role = ""
    last_visible_is_proactive = False

    for item in history_messages:
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        is_proactive = role == "assistant" and _history_message_is_proactive(item)
        if is_proactive:
            has_proactive = True
            # 提取纯内容：去除 [主动消息] 标记和 "（心想：...）" 内心独白前缀
            pure_content = content.replace("[主动消息]", "").strip()
            if pure_content.startswith("（心想："):
                # 找到内心独白结束位置（"\n\n" 或 "）" 后的实际内容）
                sep_idx = pure_content.find("\n\n")
                if sep_idx >= 0:
                    pure_content = pure_content[sep_idx:].strip()
                else:
                    # 没有换行分隔，尝试去掉 "（心想：...）" 前缀
                    close_idx = pure_content.find("）")
                    if close_idx >= 0:
                        pure_content = pure_content[close_idx + 1:].strip()
            last_proactive_content = pure_content
        last_visible_role = role
        last_visible_is_proactive = is_proactive

    is_replying_to_proactive = bool(
        last_visible_role == "assistant"
        and last_visible_is_proactive
        and last_proactive_content
    )
    return has_proactive, last_proactive_content, is_replying_to_proactive


def build_persona_prompt(
    agent: Any,
    user_id: Optional[str] = None,
    active_tools: Optional[List[str]] = None,
    mode: Optional[str] = None,
    message: Optional[str] = None,
    user_name: Optional[str] = None,
    persona_filename: Optional[str] = None,
) -> str:
    """
    构建完整的 persona system prompt（兼容旧接口）

    注意：此方法将静态和动态内容合并为一个字符串，
    如需分离以优化缓存命中率，请使用 build_persona_prompt_split()
    """
    static_part, dynamic_part = build_persona_prompt_split(
        agent=agent, user_id=user_id, active_tools=active_tools,
        mode=mode, message=message, user_name=user_name,
        persona_filename=persona_filename,
    )
    combined = static_part
    if dynamic_part:
        combined += dynamic_part
    return combined


def build_persona_prompt_split(
    agent: Any,
    user_id: Optional[str] = None,
    active_tools: Optional[List[str]] = None,
    mode: Optional[str] = None,
    message: Optional[str] = None,
    user_name: Optional[str] = None,
    memory_manager: Any = None,
    _is_sensitive_mode: Optional[bool] = None,
    persona_filename: Optional[str] = None,
) -> Tuple[str, str]:
    """
    构建分离的静态/动态 persona prompt

    【缓存优化核心】
    将 persona prompt 拆分为：
    - static_part: 人设模板 + 对话示例（跨请求不变，可被缓存）
    - dynamic_part: 时间、情绪、仿生体状态等（每次请求都变，不可缓存）

    这样在消息列表中，static_part 可以作为稳定前缀，
    后面的历史消息也能命中缓存，大幅提升 Prompt Caching 命中率。

    Returns:
        (static_part, dynamic_part) 元组
    """
    data = get_prompt_data(
        agent, user_id, message, user_name,
        memory_manager=memory_manager,
        _is_sensitive_mode=_is_sensitive_mode,
        persona_filename=persona_filename,
    )

    base_prompt = data.base_template

    # 【缓存优化关键】dialogue_injection（对话示例）基于用户消息动态选择，
    # 不能放在 static_part（system 消息）中，否则每条不同消息都会改变 system 内容，
    # 导致 DeepSeek Prompt Caching 前缀匹配完全失效。
    # 现在将 dialogue_injection 移到 dynamic_part（user 消息前缀）中。
    dialogue_injection_text = ""
    if data.dialogue_injection:
        dialogue_injection_text = (
            "【参考对话（只学习语气、节奏和用词，不要照抄内容）】\n"
            + data.dialogue_injection
        )

    base_prompt = _clean_placeholder(base_prompt)

    static_part = finalize_and_clean_prompt(
        base_prompt,
        is_qq_source=data.is_qq_source,
        resolved_user_name=data.resolved_user_name,
    )

    injection_blocks = []

    # 【缓存优化】模式提示（学习模式等）不再注入 system message（static_part），
    # 而是作为 <system-reminder> 块放进 user 消息前缀（dynamic_part）。
    # 这样 system 消息跨用户、跨模式保持字节级一致，进/出模式不再让整段前缀失效，
    # 多轮对话与模式切换均能稳定命中 DeepSeek Prompt Caching。
    # （注：intimate_tool 已删除，无对应注入源，见 UPDATES.md 历史记录）
    if user_id:
        # 学习模式prompt注入
        try:
            from core.tools.study_mode_tool import get_study_prompt_for_injection
            _study = get_study_prompt_for_injection(user_id)
            if _study:
                injection_blocks.append(
                    "<system-reminder>\n" + _study.strip() + "\n</system-reminder>"
                )
        except ImportError:
            pass

    # 对话示例（基于用户消息动态选择，放在 dynamic_part 以保护缓存前缀）
    if dialogue_injection_text:
        injection_blocks.append(dialogue_injection_text)

    special_day_prompt = get_special_day_prompt()
    if special_day_prompt:
        injection_blocks.append(special_day_prompt)

    # 绝对日期锚点每轮都存在，用于压过历史/记忆中的过期相对日期。
    injection_blocks.append(get_authoritative_calendar_prompt())

    upcoming_birthday_prompt = get_upcoming_birthday_prompt()
    if upcoming_birthday_prompt:
        injection_blocks.append(upcoming_birthday_prompt)

    time_context = build_time_context(
        last_conversation_seconds=data.last_conversation_seconds
    )
    if time_context:
        injection_blocks.append(time_context)

    emotion_primary, emotion_intensity, emotion_confidence, emotion_sub_json = data.emotion_data
    emotion_context = build_emotion_context(
        emotion_primary, emotion_intensity, emotion_confidence, emotion_sub_json
    )
    if emotion_context:
        injection_blocks.append(emotion_context)

    if is_bionic_character(data.persona_filename):
        # 获取角色间关系数据
        actor_life_states = data.life_sim_state.get("actor_life_states") if isinstance(data.life_sim_state, dict) else None
        actor_relationships = data.life_sim_state.get("actor_relationships") if isinstance(data.life_sim_state, dict) else None
        role_sleep_states = data.life_sim_state.get("role_sleep_states") if isinstance(data.life_sim_state, dict) else None

        bionic_state = get_cached_bionic_state(
            data.life_stats, data.cpu_temp, data.ram_usage,
            actor_life_states=actor_life_states,
            actor_relationships=actor_relationships,
            role_sleep_states=role_sleep_states,
            current_persona_name=data.persona_name or "",
        )
        if bionic_state:
            injection_blocks.append(bionic_state)

    # 食物系统（所有角色都有饱腹/口渴，不仅仅是仿生体）
    food_context = build_food_context(data.life_stats)
    if food_context:
        injection_blocks.append(food_context)

    study_context = build_study_context(data.mode == "study")
    if study_context:
        injection_blocks.append(study_context)

    # 人物档案注入：扫描消息文本，按需注入被提及人物的档案摘要
    mentioned_people = build_mentioned_people_injection(message or "", user_id)
    if mentioned_people:
        injection_blocks.append(mentioned_people)

    filtered_active_tools = filter_tool_names(
        active_tools or [],
        tool_registry=getattr(agent, "tool_registry", None),
        persona_filename=data.persona_filename,
        persona_data=data.persona_data,
        mode=data.mode,
        is_sensitive_mode=data.is_sensitive_mode,
    )

    # 工具使用引导（当 search_chat_history 等工具被激活时，注入优先级提示）
    tool_injection = get_tool_injection(
        agent,
        None,
        filtered_active_tools,
        persona_filename=data.persona_filename,
    )
    if tool_injection:
        injection_blocks.append(tool_injection)

    # 云模型已通过原生 function schema 收到工具定义，不再在文本 prompt 中重复一份。
    # 本地模型没有原生 schema，仍保留精简工具说明作为兼容路径。
    if (
        not getattr(data, "is_cloud_model", True)
        and filtered_active_tools
        and hasattr(agent, "tool_registry")
        and agent.tool_registry
    ):
        concise_tool_prompt = agent.tool_registry.get_concise_tool_prompt(
            include_names=filtered_active_tools
        )
        if concise_tool_prompt:
            injection_blocks.append(concise_tool_prompt)

    # 自我改进系统指令注入
    try:
        from config.integrated_config import get_settings
        si_settings = get_settings().self_improvement
        if si_settings.enabled and si_settings.prompt_injection:
            si_prompt = build_self_improvement_prompt(
                include_correction=si_settings.correction_detection,
                include_learning=si_settings.learning_log,
                include_not_to_save=si_settings.core_memory,
                include_drift=si_settings.drift_guard,
            )
            if si_prompt:
                injection_blocks.append(si_prompt)

            # 注入 MEMORY.md 核心记忆内容（按 scope 隔离，复用 CoreMemory.build_injection_text_sync）
            # 复用正式方法而非手动拼装，避免重复造轮子；且 build_injection_text_sync 在全空时返回空字符串
            if si_settings.core_memory:
                try:
                    from core.services.self_improvement.service import get_self_improvement_service
                    # scope 优先从 conversation_id 解析（稳定，多会话并发安全），
                    # 失败时回退到 persona_manager（有并发覆盖风险，聊胜于无）
                    scope = "user"
                    if user_id:
                        try:
                            from core.utils.conversation_labels import get_conversation_label_info
                            info = get_conversation_label_info(user_id)
                            resolved = info.get("storage_scope")
                            if resolved in {"aveline", "ling", "user"}:
                                scope = resolved
                            elif resolved == "dual_role":
                                # peer_chat：根据 conversation_id 中的 persona token 决定主角色
                                cid_lower = user_id.lower()
                                if "__persona__" in cid_lower:
                                    persona_token = cid_lower.split("__persona__", 1)[1].split("__", 1)[0]
                                    scope = "ling" if "ling" in persona_token else "aveline"
                        except Exception:
                            pass
                    if scope == "user":
                        # user scope 也尝试用 persona_manager 兜底，确保角色对话能拿到角色级 MEMORY.md
                        try:
                            from core.utils.data_paths import _resolve_scope_from_active_persona
                            scope = _resolve_scope_from_active_persona()
                        except Exception:
                            pass
                    si = get_self_improvement_service(scope=scope)
                    memory_text = si.build_prompt_injection_sync()  # 同步调用（本函数是同步的）
                    if memory_text:  # 空字符串表示无内容，不注入
                        injection_blocks.append(memory_text)
                except Exception:
                    pass
    except Exception:
        pass

    dynamic_part = _apply_budget_logic(
        base_prompt="",
        injection_blocks=injection_blocks,
        prompt_budget=None,
        dialogue_injection="",
    )

    return static_part, dynamic_part


def build_complete_message_list(
    agent: Any,
    user_id: Optional[str] = None,
    message: Optional[str] = None,
    user_name: Optional[str] = None,
    history_messages: Optional[List[Dict[str, str]]] = None,
    state_context: Optional[str] = None,
    sensitive_injections: Optional[List[str]] = None,
    is_qq_session: bool = False,
    is_sensitive_mode: bool = False,
    extra_dynamic_context: Optional[str] = None,
    memory_manager: Any = None,
    persona_filename: Optional[str] = None,
    active_tools: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """
    构建缓存友好的消息列表

    【缓存优化核心 - 关键修正】
    DeepSeek Prompt Caching 基于前缀匹配，从第 0 个 token 开始连续相同才算命中。

    之前的错误设计：
      [system: 静态+动态混合] → [history] → [user]
      问题：动态内容改变导致整个 system 消息变化，前缀匹配完全失效

    现在的正确设计（缓存命中率 ~90%+）：
      [system: 纯静态人设] → [history] → [user: 动态前缀 + 用户消息]
      
      优势：
      1. system 消息100%静态，每次请求完全相同 → 100%命中缓存
      2. 历史消息前缀稳定 → 多轮对话天然命中
      3. 只有最后一条 user 消息变化 → 仅需计算最后一小部分
    
    DeepSeek 缓存规则：
    - 缓存基于前缀匹配，从第 0 个 token 开始连续相同才算命中
    - 多轮对话天然命中：第 N 轮会命中第 N-1 轮的缓存前缀
    - system 消息只能在开头（DeepSeek 限制）
    - 缓存以 64 tokens 为存储单元
    """
    from core.utils.time_utils import get_current_time, get_time_period

    messages: List[Dict[str, str]] = []
    history_messages = history_messages or []
    sensitive_injections = sensitive_injections or []

    static_prompt, dynamic_prompt = build_persona_prompt_split(
        agent=agent,
        user_id=user_id,
        message=message,
        user_name=user_name,
        active_tools=active_tools,
        memory_manager=memory_manager,
        _is_sensitive_mode=is_sensitive_mode if is_sensitive_mode else None,
        persona_filename=persona_filename,
    )

    # 【缓存优化关键】system 消息只包含静态内容，确保100%稳定可缓存
    if static_prompt:
        messages.append({"role": "system", "content": static_prompt})

    messages.extend(history_messages)

    # 检测历史中是否存在主动消息，用于后续注入行为指引
    has_proactive_in_history, last_proactive_content, is_replying_to_proactive = (
        _build_active_care_handoff_context(history_messages)
    )

    # 【缓存优化关键】所有动态内容合并到 user 消息前缀中
    # 这样 system 消息和历史消息前缀都稳定，只有最后一条 user 消息变化
    if message:
        current_ts = get_current_time()

        user_content_parts = []

        # 1. 当前时间（放在动态上下文最前面，不放在用户消息前面，避免模型模仿输出时间戳）
        user_content_parts.append(f"当前时间：{current_ts.strftime('%Y-%m-%d %H:%M')}（{get_time_period()}）")

        # 2. 【环境】合并块：所有状态/画像/身份/氛围信息合并为一个块，减少注意力稀释
        #    原来：12个【】块 → 现在：3个（环境/记忆/用户消息）
        env_parts = []

        # 动态 persona 上下文（情绪、仿生体状态、学习状态等）
        if dynamic_prompt:
            env_parts.append(dynamic_prompt)

        # 状态上下文
        if state_context:
            env_parts.append(state_context)

        # 用户生活画像（吃饭/睡觉/生病等持续性状态 + 今日日程摘要）
        bio_context = build_user_bio_context_for_chat(user_id=user_id)
        if bio_context:
            env_parts.append(bio_context)

        # 主动消息上下文衔接指引（仅在历史中有主动消息时注入）
        # 让主 LLM 理解 [主动消息] 标记的含义，避免“自己回答自己”
        if has_proactive_in_history:
            proactive_hint = (
                "【主动消息说明】对话历史中标记为[主动消息]的Assistant消息是你在用户沉默时主动发送的，"
                "不是对用户消息的回复。"
            )
            if is_replying_to_proactive and last_proactive_content:
                proactive_hint += (
                    "最近一条可见Assistant消息就是主动消息，用户当前这句大概率是在回应它。"
                    f"上一条主动消息：{last_proactive_content[:120]}。"
                    "请把它当成同一段私聊的自然来回：承接用户当前态度，必要时轻轻接住或追问，"
                    "不要解释“主动关怀/系统/自动发送”，不要突然换话题。"
                )
            else:
                proactive_hint += (
                    "请围绕用户当前的消息自然回应，不要复述主动消息的内容，"
                    "不要像在回答自己刚才发的话。"
                )
            env_parts.append(proactive_hint)

        # 模式提示（学习模式等）已移到 user 消息前缀（build_persona_prompt_split 的
        # dynamic_part 中作为 <system-reminder> 注入），system 保持纯静态以最大化缓存命中

        # extra_dynamic_context：说话者身份 + 双角色私聊 + affect/daily_summary 等，合并进环境
        if extra_dynamic_context:
            remaining = extra_dynamic_context
            # 提取说话者身份
            if "【说话者身份】" in remaining:
                id_parts = remaining.split("【说话者身份】", 1)
                remaining = id_parts[0].strip()
                sender_part = "【说话者身份】" + id_parts[1].strip()
                # 从说话者身份中提取双角色私聊
                after_peer = sender_part.split("【双角色私聊模式】", 1)
                env_parts.append(after_peer[0].strip())
                if len(after_peer) > 1:
                    env_parts.append("【双角色私聊模式】" + after_peer[1].strip())
            # 提取双角色私聊（如果没在说话者身份里）
            if "【双角色私聊模式】" in remaining:
                parts = remaining.split("【双角色私聊模式】", 1)
                remaining = parts[0].strip()
                env_parts.append("【双角色私聊模式】" + parts[1].strip())
            # 剩余内容（affect_instruction、daily_summary、tomorrow_tone 等）
            if remaining.strip():
                env_parts.append(remaining.strip())

        if env_parts:
            user_content_parts.append("\n\n【环境】\n" + "\n".join(env_parts))

        # 3. 【记忆】合并块：敏感记忆
        memory_parts = []
        for injection in sensitive_injections:
            if injection:
                memory_parts.append(injection)
        if memory_parts:
            user_content_parts.append("\n\n【记忆】\n" + "\n".join(memory_parts))

        # 4. 用户实际消息
        user_content_parts.append(f"\n\n【用户消息】\n{message}")

        user_content = "".join(user_content_parts)
        messages.append({"role": "user", "content": user_content})

    static_len = len(static_prompt) if static_prompt else 0
    dynamic_len = len(dynamic_prompt) if dynamic_prompt else 0
    logger.info(
        "CompleteMessageList: StaticLen=%d, DynamicLen=%d, HistoryCount=%d, TotalMessages=%d, UserPrefixLen=%d",
        static_len, dynamic_len, len(history_messages), len(messages),
        len(messages[-1]["content"]) if messages and messages[-1].get("role") == "user" else 0,
    )

    try:
        from core.llm.llm_logger import log_llm_call_stats
        log_llm_call_stats(
            provider="assembler",
            model="prompt_build",
            messages=messages,
            stream=False,
            extra={
                "static_len": static_len,
                "dynamic_len": dynamic_len,
                "history_count": len(history_messages),
                "user_prefix_len": len(messages[-1]["content"]) if messages and messages[-1].get("role") == "user" else 0,
            },
        )
    except Exception as e:
        logger.warning("日志完整prompt时出错：%s", e)

    return messages


# ========== 内部拼装函数 ==========

def _merge_template_and_persona(template: str, detailed_persona: str) -> str:
    """
    合并模板和详细人设
    """
    if not detailed_persona:
        return template
        
    if "{detailed_persona}" in template:
        return template.replace("{detailed_persona}", detailed_persona)
    elif "【运行状态】" in template:
        parts = template.split("【运行状态】", 1)
        return parts[0].rstrip() + detailed_persona + "\n\n【运行状态】" + parts[1]
    elif template:
        return template.rstrip() + "\n\n" + detailed_persona
    else:
        return detailed_persona


def _clean_placeholder(template: str) -> str:
    """
    清理不需要的占位符
    """
    result = str(template or "").strip()
    
    if "{memory_echo}" in result:
        result = result.replace("{memory_echo}", "")
    
    # 移除【仿生体状态】（移到动态内容里）
    if "【仿生体状态】" in result:
        idx = result.find("【仿生体状态】")
        end = idx
        while end < len(result) and result[end] != '\n':
            end += 1
        while end < len(result) and result[end] in '\n\r':
            end += 1
        result = result[:idx] + result[end:]
        result = result.rstrip()
    
    return result


def _apply_budget_logic(
    base_prompt: str,
    injection_blocks: List[str],
    prompt_budget: Optional[int],
    dialogue_injection: str,
) -> str:
    """
    应用 prompt 预算逻辑
    
    【纯拼装逻辑】
    """
    if prompt_budget is None:
        return base_prompt + "".join(injection_blocks)
    
    # 如果有对话示例，先为它预留空间
    if dialogue_injection and len(base_prompt) + len(dialogue_injection) > prompt_budget:
        reserved = min(len(dialogue_injection), prompt_budget)
        base_prompt = base_prompt[: max(0, prompt_budget - reserved)]
    
    # 基础模板已经超预算
    if len(base_prompt) > prompt_budget:
        return base_prompt[:prompt_budget]
    
    # 有剩余预算，尽量多加组件
    remaining = max(0, prompt_budget - len(base_prompt))
    extra_injections = ""
    for block in injection_blocks:
        if not block or remaining <= 0:
            continue
        if len(block) <= remaining:
            extra_injections += block
            remaining -= len(block)
            continue
        extra_injections += block[:remaining]
        remaining = 0
        break
    
    return base_prompt + extra_injections
