import asyncio
import json
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict

from core.services.life_simulation.service import get_life_simulation_service
from core.utils.logger import get_logger
from core.utils.text_processor import extract_and_strip_emotion, enforce_dialogue_style, strip_parentheses_tags
from core.utils.time_utils import now_str
from core.agents.chat_agent_components.stream_utils import StreamContextBuilder

logger = get_logger("ChatAgent")


def _expand_discovered_tool_schemas(
    agent: Any,
    tool_name: str,
    tool_result: Any,
    available_tool_names: list[str],
    native_tool_names: list[str],
):
    """解析 search_tools 结果，并只为权限内候选构建下一轮 schema。"""
    if tool_name != "search_tools":
        return native_tool_names, None
    try:
        discovery_payload = json.loads(str(tool_result))
    except (TypeError, ValueError):
        return native_tool_names, None

    allowed_names = set(available_tool_names)
    discovered_names = [
        str(item.get("name", "")).strip()
        for item in discovery_payload.get("tools", [])
        if isinstance(item, dict)
        and str(item.get("name", "")).strip() in allowed_names
    ]
    if not discovered_names:
        return native_tool_names, None

    expanded_names = list(dict.fromkeys(native_tool_names + discovered_names))
    expanded_schemas = agent.tool_registry.get_openai_tools(
        include_names=expanded_names
    )
    logger.info(
        "[Native Tools] 非流式工具发现后扩展 schema: %s",
        ", ".join(discovered_names),
    )
    return expanded_names, expanded_schemas


def _is_internal_trigger_message(text: str) -> bool:
    raw = str(text or "")
    upper = raw.upper()
    if "_TRIGGER]" in upper:
        return True
    if "[LAST_USER_MESSAGE]:" in upper:
        return True
    if "[ACTIVE_CARE_CONTEXT_CONTINUATION]" in upper:
        return True
    if "[NOTIFICATION_TRIGGER]" in upper:
        return True
    if "[SYSTEM EVENT]" in upper:
        return True
    return False


def _is_meal_or_drink_self_report(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    if _is_internal_trigger_message(raw):
        return False
    lower = raw.lower()
    if "？" in raw or "?" in raw:
        return False
    zh_pattern = re.search(
        r"(我(刚|才|已经|都)?|今天我|刚刚).{0,8}(喝|吃|饮|进食)",
        raw,
    )
    if zh_pattern:
        return True
    en_pattern = re.search(
        r"\b(i|i'm|i am|i've|i just|i already)\b.{0,24}\b(ate|eat|drank|drink|drinking)\b",
        lower,
    )
    if en_pattern:
        return True
    return False


async def handle_message_impl(
    agent: Any,
    user_id: str,
    message: str,
    message_id: str = None,
    system_prompt_override: str = None,
    save_history: bool = True,
    skip_memory_storage: bool = False,
) -> Dict[str, Any]:
    async with agent._lock:
        start_time = time.time()
        if not agent.is_initialized:
            await agent.initialize()

        current_study_data = None  # 用于存储本次对话触发的高光文件数据

        trigger_start = time.time()
        trigger_response = await agent._check_triggers(user_id, message)
        logger.info(f"Check triggers took: {time.time() - trigger_start:.4f}s")

        if trigger_response:
            if not message_id:
                message_id = f"msg_{user_id}_{datetime.now().timestamp()}"

            try:
                if save_history and not skip_memory_storage:
                    await agent._save_conversation_history(
                        user_id, message, trigger_response, message_id
                    )
            except Exception as e:
                logger.warning(f"Failed to save trigger history: {e}")

            return {
                "response": trigger_response,
                "conversation_id": user_id,
                "emotion": "happy",
                "message_id": str(uuid.uuid4()),
            }

        try:
            get_life_simulation_service().update_interaction()
        except Exception:
            pass

        # --- BERT Intent Analysis for Status Recording (Wakeup/Meal) ---
        # 如果是记录生活状态的意图，我们需要阻止这些琐事进入 Weighted Memory
        # 我们通过设置 skip_memory_storage = True 来实现
        # 但是我们仍然需要 LLM 的回复，只是不存入长期记忆
        # 这里的 skip_memory_storage 参数控制的是 LLM 对话后的存储
        
        is_trivial_record = False
        
        try:
            internal_trigger_message = _is_internal_trigger_message(message)
            from core.services.data_ops.bert_analyzer import get_bert_analyzer
            from core.services.workspace.status_manager import get_user_status_manager
            
            analyzer = get_bert_analyzer()
            # We only care about specific intents here
            candidates = ["RECORD_WAKEUP", "RECORD_MEAL", "RECORD_DRINK"]
            analysis = analyzer.analyze_intent(message, candidates=candidates)
            
            intent = analysis.get("intent")
            # Increase confidence threshold to avoid false positives for trivial chat
            # "今天天气不错" might trigger some intent with low confidence
            confidence = analysis.get("confidence", 0.0)
            
            # Require higher confidence for skipping memory
            # Also check for "Wakeup" specific keywords to avoid false positive like "今天天气不错"
            if internal_trigger_message:
                logger.info("Skipped BERT status record for internal trigger message.")
            elif intent == "RECORD_WAKEUP" and confidence > 0.7:
                is_wakeup = any(k in message for k in ["醒", "起", "早安"])
                if not is_wakeup:
                    # BERT false positive
                    logger.info(f"Ignored BERT Wakeup false positive: {message} (conf={confidence:.2f})")
                else:
                    # Record Wakeup
                    manager = get_user_status_manager()
                    time_str = now_str("%H:%M")
                    manager.add_status("今日起床", f"时间: {time_str}", duration_days=1)
                    logger.info(f"Recorded Wakeup via BERT: {time_str}")
                    
                    # Add a system hint so LLM knows
                    from core.agents.chat_agent_components.persona_system.prompt.service_prompts import HANDLER_WAKE_UP_NOTIFICATION
                    system_prompt_override = (system_prompt_override or "") + HANDLER_WAKE_UP_NOTIFICATION.format(time_str=time_str)
                    is_trivial_record = True
                
            elif intent == "RECORD_MEAL" and confidence > 0.7:
                if not _is_meal_or_drink_self_report(message):
                    logger.info(
                        "Ignored BERT meal intent: message is not explicit self-report."
                    )
                    intent = "NONE"
                else:
                # Record Meal
                    manager = get_user_status_manager()
                    time_str = now_str("%H:%M")
                    
                    food = message
                    remove_kws = [
                        "吃饭", "吃了", "吃过", "吃点", "吃", "喝了", "喝点", "喝",
                        "早饭", "早餐", "午饭", "午餐", "晚饭", "晚餐", "夜宵", "宵夜", 
                        "东西", "饿了", "饱了", "正在", "在", "下午茶", "点心", "零食",
                        "我", "你", "啊", "了", "的", "呢", "吧", "嘛", "哦", "嗯"
                    ]
                    for kw in remove_kws:
                         food = food.replace(kw, "")
                    food = food.strip() 
                    
                    if not food or len(food) < 2:
                        m = re.search(r"(?:吃|喝)(?:了|点|过)?([^，。！？,\n]+)", message)
                        if m:
                            food = m.group(1).strip()
                        else:
                            food = "未说明具体食物"

                    meal_name = "用餐记录"
                    hour = datetime.now().hour
                    
                    is_snack = any(k in message for k in ["零食", "点心", "下午茶", "蛋糕", "饼干", "薯片", "奶茶", "咖啡"])
                    
                    if is_snack:
                        meal_name = "零食/加餐"
                    else:
                        if 5 <= hour < 10:
                            meal_name = "早餐"
                        elif 11 <= hour < 14:
                            meal_name = "午餐"
                        elif 17 <= hour < 21:
                            meal_name = "晚餐"
                        elif hour >= 21 or hour < 5:
                            meal_name = "夜宵"
                    
                    manager.add_status(meal_name, f"内容: {food} (时间: {time_str})", duration_days=1)
                    logger.info(f"Recorded Meal via BERT: {meal_name} - {food}")

                    try:
                        from core.services.daily.manager import get_daily_manager
                        daily_mgr = get_daily_manager()
                        daily_mgr.record_meal(meal_name, food)
                    except Exception as e:
                        logger.warning(f"Failed to sync meal to daily record: {e}")

                    from core.agents.chat_agent_components.persona_system.prompt.service_prompts import HANDLER_EAT_NOTIFICATION
                    system_prompt_override = (system_prompt_override or "") + HANDLER_EAT_NOTIFICATION.format(food=food, meal_name=meal_name)
                    is_trivial_record = True

            elif intent == "RECORD_DRINK" and confidence > 0.7:
                if not _is_meal_or_drink_self_report(message):
                    logger.info(
                        "Ignored BERT drink intent: message is not explicit self-report."
                    )
                    intent = "NONE"
                else:
                # Record Drink
                    manager = get_user_status_manager()
                    time_str = now_str("%H:%M")
                    
                    amount = 200
                    m = re.search(r"(\d+)(ml|毫升|升|L|杯|瓶|口)", message, re.IGNORECASE)
                    if m:
                        val = int(m.group(1))
                        unit = m.group(2).lower()
                        if unit in ["升", "l"]:
                            val *= 1000
                        elif unit in ["杯", "瓶"]:
                            val *= 250
                        elif unit in ["口"]:
                            val = 50
                        amount = val
                    
                    statuses = manager._load_statuses()
                    current_total = 0
                    for s in statuses:
                        if s["name"] == "今日饮水":
                            m_exist = re.search(r"(\d+)ml", s["description"])
                            if m_exist:
                                current_total = int(m_exist.group(1))
                            break
                    
                    new_total = current_total + amount
                    manager.add_status("今日饮水", f"已喝 {new_total}ml (最近: {time_str})", duration_days=1)
                    
                    try:
                        from core.services.daily.manager import get_daily_manager
                        daily_mgr = get_daily_manager()
                        daily_mgr.record_drink("drink", f"喝水 {amount}ml")
                    except Exception as e:
                        logger.warning(f"Failed to sync drink to daily record: {e}")

                    logger.info(f"Recorded Drink via BERT: {amount}ml (Total: {new_total}ml)")
                    from core.agents.chat_agent_components.persona_system.prompt.service_prompts import HANDLER_DRINK_NOTIFICATION
                    system_prompt_override = (system_prompt_override or "") + HANDLER_DRINK_NOTIFICATION.format(amount=amount, new_total=new_total)
                    is_trivial_record = True
        
        except Exception as e:
            logger.error(f"Failed to record status via BERT: {e}")

        # 如果是琐事记录，且未明确要求跳过存储，则自动跳过存储
        if is_trivial_record and not skip_memory_storage:
            logger.info("Skipping long-term memory storage for trivial status record.")
            skip_memory_storage = True
            
        try:
            if not message_id:
                message_id = f"msg_{user_id}_{datetime.now().timestamp()}"
            logger.info(f"处理用户 {user_id} 的消息，ID: {message_id}")

            active_tools = []
            try:
                # 只在需要保存历史时才构建带 message_id 的历史
                # 这样即使不保存，也能生成回复，但不会污染 Weighted Memory
                # _build_conversation_history 主要是为了获取上下文给 LLM
                # 真正的保存是在最后的 _save_conversation_history
                
                from core.agents.chat_agent_components.context_persona import prepare_active_tools

                active_tools = await prepare_active_tools(agent, message, None)
                messages = await agent._build_conversation_history(
                    user_id,
                    message,
                    system_prompt=system_prompt_override,
                    active_tools=active_tools,
                )
            except Exception as e:
                # Fallback
                logger.warning(f"Build history failed, trying fallback: {e}")
                messages = [{"role": "user", "content": message}]

            is_sensitive_mode = False
            try:
                from core.managers.preference_manager import get_preference_manager
                from config.integrated_config import get_settings

                prefs = get_preference_manager()
                if prefs.get_mode() == "privacy":
                    is_sensitive_mode = True
                
                # Rule: Local model -> Sensitive mode automatically
                settings = get_settings()
                provider = settings.model.llm.provider
                # Check provider or if using local text path
                if provider == "local" or (provider == "custom" and not settings.model.llm.base_url):
                     # Double check if it's actually a local GGUF or similar
                     if settings.model.text_path and (settings.model.text_path.endswith(".gguf") or "local" in str(settings.model.text_path).lower()):
                         is_sensitive_mode = True
                         logger.info("Local model detected, auto-enabling SENSITIVE/NSFW mode.")
                     elif provider == "local":
                         is_sensitive_mode = True
                         logger.info("Local provider detected, auto-enabling SENSITIVE/NSFW mode.")

            except Exception as e:
                logger.warning(f"Failed to check mode/settings: {e}")

            cid = str(user_id or "").strip() or "default"
            if cid and not is_sensitive_mode:
                try:
                    if hasattr(agent, "get_memory_manager_async"):
                        mm = await agent.get_memory_manager_async(cid)
                    else:
                        mm = agent._get_memory_manager(cid)
                    if hasattr(mm, "get_memories_by_topic"):
                        mode_memories = mm.get_memories_by_topic(
                            "sensitive_mode_control", limit=1
                        )
                        if mode_memories and "SENSITIVE_MODE_ON" in str(
                            mode_memories[0].get("content", "") or ""
                        ):
                            is_sensitive_mode = True
                except Exception:
                    pass

            msg_lower = str(message or "").lower()
            if not is_sensitive_mode:
                if (
                    "/sensitive" in msg_lower
                    or "[sensitive]" in msg_lower
                    or "开启sensitive" in msg_lower
                    or "/private" in msg_lower
                    or "[private]" in msg_lower
                    or "/nsfw" in msg_lower
                    or "[nsfw]" in msg_lower
                    or "开启nsfw" in msg_lower
                ):
                    is_sensitive_mode = True

            mode = "chat"
            try:
                if hasattr(agent, "_determine_mode"):
                    mode = str(agent._determine_mode(message or "") or mode)
            except Exception:
                mode = "chat"

            wants_long = False
            if message:
                wants_long = StreamContextBuilder.detect_wants_long(message)

            # 不限制输出长度，由模型自行决定
            max_tokens = None

            soft_reply_char_limit = None
            if mode != "study" and (not wants_long):
                msg_len = len((message or "").strip())
                if msg_len <= 6:
                    soft_reply_char_limit = 80
                elif msg_len <= 12:
                    soft_reply_char_limit = 120
                elif msg_len <= 24:
                    soft_reply_char_limit = 180

            life_level = 1
            mood_score = 80.0
            shyness_score = 0.0
            immune_damage = 0.0
            is_sick = False
            intimacy_level = 0.1
            try:
                life_service = get_life_simulation_service()
                try:
                    life_service.update_interaction(xp_gain=10)
                except TypeError:
                    life_service.update_interaction()

                life_state = getattr(life_service, "life_stats", {}) or {}
                mood_score = float(life_state.get("mood_score", mood_score) or mood_score)
                shyness_score = float(
                    life_state.get("shyness_score", shyness_score) or shyness_score
                )
                immune_damage = float(
                    life_state.get("immune_damage", immune_damage) or immune_damage
                )
                is_sick = bool(life_state.get("is_sick", False))
                life_level = int(life_state.get("level", life_level) or life_level)

                if getattr(agent, "dependency_manager", None):
                    try:
                        intimacy_level = float(
                            agent.dependency_manager.get_intimacy_level() or intimacy_level
                        )
                    except Exception:
                        intimacy_level = intimacy_level

                try:
                    agent.emotion_manager.ingest_life_stats(
                        user_id,
                        {
                            "mood_score": mood_score,
                            "shyness_score": shyness_score,
                            "immune_damage": immune_damage,
                            "is_sick": is_sick,
                            "level": life_level,
                        },
                        intimacy_level=intimacy_level,
                    )
                except Exception:
                    pass
            except Exception:
                pass

            affect_instruction = ""
            try:
                affect_instruction = agent.emotion_manager.build_dialogue_affect_instruction(
                    life_level=life_level,
                    mood_score=mood_score,
                    shyness_score=shyness_score,
                    immune_damage=immune_damage,
                    is_sick=is_sick,
                    intimacy_level=intimacy_level,
                    soft_reply_char_limit=soft_reply_char_limit,
                    max_tokens=max_tokens,
                )
            except Exception:
                affect_instruction = ""

            if affect_instruction and messages:
                insert_at = 0
                if (
                    isinstance(messages[0], dict)
                    and messages[0].get("role") == "system"
                    and messages[0].get("content")
                ):
                    insert_at = 1
                messages.insert(insert_at, {"role": "system", "content": affect_instruction})

            max_turns = 3
            current_turn = 0
            response_content = ""
            collected_image_prompts = []

            # 判断当前LLM是否使用服务端web_search
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

            # Dynamic Repetition Penalty for Local/Sensitive Models
            # Llama 3.2 Stheno and other small RP models often need higher penalty to avoid loops
            repetition_penalty = agent.config.repetition_penalty if hasattr(agent.config, "repetition_penalty") else 1.08
            if is_sensitive_mode:
                repetition_penalty = max(repetition_penalty, 1.15)

            forced_no_think_retry = False
            used_placeholder_response = False
            thought_content = None

            # 准备 native tools（与 streaming.py 对齐，让云模型也能 function calling）
            openai_tools = None
            available_tool_names = []
            native_tool_names = []
            if hasattr(agent, "tool_registry") and agent.tool_registry:
                from core.tools.tool_visibility import filter_tool_names

                available_tool_names = filter_tool_names(
                    agent.tool_registry.get_active_tools(),
                    tool_registry=agent.tool_registry,
                    is_sensitive_mode=is_sensitive_mode,
                )
                native_tool_names = list(active_tools)
                native_tool_names = filter_tool_names(
                    native_tool_names,
                    tool_registry=agent.tool_registry,
                    is_sensitive_mode=is_sensitive_mode,
                )
                if use_server_side_search:
                    available_tool_names = [
                        name for name in available_tool_names if name != "web_search"
                    ]
                    native_tool_names = [
                        name for name in native_tool_names if name != "web_search"
                    ]
                openai_tools = agent.tool_registry.get_openai_tools(
                    include_names=native_tool_names
                )
                if openai_tools:
                    schema_chars = len(
                        json.dumps(
                            openai_tools,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    )
                    logger.info(
                        "[Native Tools] 非流式路径注册 %d 个工具, schema_chars=%d",
                        len(openai_tools),
                        schema_chars,
                    )

            while current_turn < max_turns:
                llm_start = time.time()
                logger.info(f"Starting LLM generation (turn {current_turn}) with rep_penalty={repetition_penalty}")
                llm_chat_kwargs = {
                    "temperature": agent.config.temperature,
                    "max_tokens": max_tokens,
                    "repetition_penalty": repetition_penalty,
                }
                if use_server_side_search:
                    llm_chat_kwargs["web_search_enabled"] = True
                if openai_tools:
                    llm_chat_kwargs["tools"] = openai_tools
                    llm_chat_kwargs["tool_choice"] = "auto"
                response_payload = await agent.llm_module.chat(
                    messages,
                    **llm_chat_kwargs,
                )
                logger.info(
                    f"LLM generation took: {time.time() - llm_start:.4f}s"
                )

                response_content = ""
                finish_reason = None

                if isinstance(response_payload, Dict):
                    response_content = response_payload.get("response", "")
                    finish_reason = response_payload.get("finish_reason")
                    if response_payload.get("status") == "error":
                        logger.error(f"LLM Error: {response_payload.get('error')}")
                    
                    # Handle DeepSeek R1 reasoning_content
                    if response_payload.get("reasoning_content"):
                        thought_content = response_payload.get("reasoning_content")
                else:
                    response_content = str(response_payload)

                response_content = re.sub(
                    r"(?i)(?<!<)/think>", "</think>", response_content
                )
                think_blocks = re.findall(
                    r"<think>(.*?)</think>", response_content, flags=re.DOTALL | re.IGNORECASE
                )
                if think_blocks:
                    merged_think = "\n".join(
                        [str(item or "").strip() for item in think_blocks if str(item or "").strip()]
                    ).strip()
                    if merged_think:
                        if thought_content:
                            thought_content = f"{thought_content}\n{merged_think}"
                        else:
                            thought_content = merged_think
                    response_content = re.sub(
                        r"<think>.*?</think>", "", response_content, flags=re.DOTALL | re.IGNORECASE
                    ).strip()

                unclosed_idx = response_content.lower().find("<think>")
                if unclosed_idx >= 0:
                    dangling_think = response_content[unclosed_idx + len("<think>") :].strip()
                    if dangling_think:
                        if thought_content:
                            thought_content = f"{thought_content}\n{dangling_think}"
                        else:
                            thought_content = dangling_think
                    response_content = response_content[:unclosed_idx].strip()

                if (not response_content.strip()) and thought_content and (not forced_no_think_retry):
                    forced_no_think_retry = True
                    # 不再注入提到think标签的system消息（反而会让模型注意到标签并模仿输出）
                    current_turn += 1
                    continue

                if (not response_content.strip()) and thought_content and forced_no_think_retry:
                    response_content = "我在。刚刚处理了一下上下文，现在可以继续了。"
                    used_placeholder_response = True

                # 处理 function calling 模式返回的 tool_calls（云模型原生工具调用）
                native_tool_calls = None
                if isinstance(response_payload, Dict):
                    native_tool_calls = response_payload.get("tool_calls")
                if native_tool_calls and (not response_content.strip() or finish_reason == "tool_calls"):
                    for tc in native_tool_calls:
                        tc_id = tc.get("id", f"tc_{current_turn}")
                        fn_info = tc.get("function", {})
                        tool_name = fn_info.get("name", "")
                        tool_args_str = fn_info.get("arguments", "{}")
                        tool = agent.tool_registry.get_tool(tool_name) if hasattr(agent, "tool_registry") else None
                        if tool:
                            logger.info(f"[Native Tool] 非流式执行: {tool_name}")
                            tool.set_runtime_context({
                                "agent": agent,
                                "user_id": user_id,
                                "scope": "sensitive" if is_sensitive_mode else "sfw",
                                "allowed_tool_names": available_tool_names,
                            })
                            try:
                                tool_args = json.loads(tool_args_str) if tool_args_str else {}
                                tool_result = await tool.run(**tool_args)
                            except Exception as e:
                                tool_result = f"Error: {str(e)}"
                                logger.error(f"[Native Tool] 非流式执行失败: {e}")

                            native_tool_names, expanded_schemas = (
                                _expand_discovered_tool_schemas(
                                    agent,
                                    tool_name,
                                    tool_result,
                                    available_tool_names,
                                    native_tool_names,
                                )
                            )
                            if expanded_schemas is not None:
                                openai_tools = expanded_schemas

                            # 检查 study_data_highlight
                            if isinstance(tool_result, str) and '"type": "study_data_highlight"' in tool_result:
                                try:
                                    parsed_result = json.loads(tool_result)
                                    if parsed_result.get("type") == "study_data_highlight":
                                        current_study_data = parsed_result.get("data")
                                        tool_result = f"[已在前端展示文件: {current_study_data.get('filePath')}]"
                                except Exception:
                                    pass

                            assistant_msg = {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [{
                                    "id": tc_id,
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": tool_args_str,
                                    }
                                }]
                            }
                            if thought_content:
                                assistant_msg["reasoning_content"] = thought_content
                            messages.append(assistant_msg)
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": str(tool_result),
                            })
                        else:
                            logger.warning(f"[Native Tool] 未知工具: {tool_name}")
                    current_turn += 1
                    continue

                tool_match = re.search(
                    r"\[TOOL_USE:\s*({.*?})\]", response_content, re.DOTALL
                )

                if tool_match:
                    json_str = tool_match.group(1)
                    try:
                        tool_call = json.loads(json_str)
                        tool_name = tool_call.get("name")
                        tool_args = tool_call.get("arguments", {})

                        tool = agent.tool_registry.get_tool(tool_name)
                        if tool:
                            logger.info(
                                f"Executing tool {tool_name} with args {tool_args}"
                            )
                            # Inject runtime context so tools can access agent/user_id/scope
                            tool.set_runtime_context({
                                "agent": agent,
                                "user_id": user_id,
                                "scope": "sensitive" if is_sensitive_mode else "sfw",
                                "allowed_tool_names": available_tool_names,
                            })
                            tool_start = time.time()
                            tool_result = await tool.run(**tool_args)
                            logger.info(
                                f"Tool execution took: {time.time() - tool_start:.4f}s"
                            )

                            native_tool_names, expanded_schemas = (
                                _expand_discovered_tool_schemas(
                                    agent,
                                    tool_name,
                                    tool_result,
                                    available_tool_names,
                                    native_tool_names,
                                )
                            )
                            if expanded_schemas is not None:
                                openai_tools = expanded_schemas

                            # 检查是否是 study_data_highlight 类型的输出
                            if isinstance(tool_result, str) and '"type": "study_data_highlight"' in tool_result:
                                try:
                                    parsed_result = json.loads(tool_result)
                                    if parsed_result.get("type") == "study_data_highlight":
                                        current_study_data = parsed_result.get("data")
                                        # 简化给 LLM 的输出，避免 token 浪费，因为前端已经展示了
                                        tool_result = f"[已在前端展示文件: {current_study_data.get('filePath')}]"
                                except Exception as e:
                                    logger.warning(f"Failed to parse study_data_highlight: {e}")

                            if tool_name == "generate_image":
                                img_match_tool = re.search(
                                    r"\[GEN_IMG:\s*(.*?)\]", str(tool_result)
                                )
                                if img_match_tool:
                                    collected_image_prompts.append(
                                        img_match_tool.group(1)
                                    )

                            messages.append(
                                {"role": "assistant", "content": response_content}
                            )
                            messages.append(
                                {
                                    "role": "system",
                                    "content": f"工具“{tool_name}”输出：\n{tool_result}\n\n请基于该信息继续对话。",
                                }
                            )

                            current_turn += 1
                            continue
                        messages.append(
                            {
                                "role": "system",
                                "content": f"Error: Tool '{tool_name}' not found.",
                            }
                        )
                        current_turn += 1
                        continue
                    except Exception as e:
                        messages.append(
                            {
                                "role": "system",
                                "content": f"Error parsing tool call: {e}",
                            }
                        )
                        current_turn += 1
                        continue

                if finish_reason == "length" and response_content.strip() and current_turn < max_turns - 1:
                    logger.warning(
                        f"LLM output truncated (finish_reason=length), attempting continuation. "
                        f"Current length: {len(response_content)} chars"
                    )
                    messages.append({"role": "assistant", "content": response_content})
                    messages.append({
                        "role": "system",
                        "content": "你的回复被截断了，请自然地继续说完，不要重复已说的内容。",
                    })
                    current_turn += 1
                    continue

                break

            final_content, emotion_label = extract_and_strip_emotion(response_content)
            # 剥离AI模仿上下文时间戳格式自行生成的时间戳（如 [23:10]、[05-22 01:45] 或 [2025-05-22 01:45]）
            # 全局匹配，不仅匹配行首，也匹配回复中间出现的时间戳
            _ai_ts_pattern = re.compile(r"\[(?:\d{2,4}(?:-\d{2}){1,2}\s+)?\d{2}:\d{2}(?::\d{2})?(?:\s*\([^)]+\))?\]\s*")
            final_content = _ai_ts_pattern.sub("", final_content)

            # 剥离 MiniMax-M2.5 等模型输出的 [TOOL_CALL]...[/TOOL_CALL] 格式
            if "[TOOL_CALL]" in final_content and "[/TOOL_CALL]" in final_content:
                _tc_pattern = re.compile(r"\[TOOL_CALL\](.*?)\[/TOOL_CALL\]", re.DOTALL)
                _extracted = []
                for _m in _tc_pattern.finditer(final_content):
                    _text_match = re.search(r'--text\s+["\u201c](.+?)["\u201d]', _m.group(1), re.DOTALL)
                    if _text_match:
                        _extracted.append(_text_match.group(1).strip())
                _cleaned = _tc_pattern.sub("", final_content).strip()
                if _extracted:
                    final_content = " ".join(_extracted)
                elif _cleaned:
                    final_content = _cleaned
            # 保存包含情感标签的完整内容用于 TTS
            full_content = final_content

            image_prompt = None
            voice_id = None

            img_match = re.search(r"\[GEN_IMG:\s*(.*?)\]", final_content)
            if img_match:
                image_prompt = img_match.group(1)
                final_content = final_content.replace(img_match.group(0), "")
                full_content = full_content.replace(img_match.group(0), "")

            if not image_prompt and collected_image_prompts:
                image_prompt = collected_image_prompts[-1]

            # 语音检测逻辑：支持 [VOICE] 标签，同时兼容全角括号 ［VOICE］
            voice_match = re.search(r"[\[［]VOICE(?:[：:]\s*(.*?))?[\]］]", final_content, re.IGNORECASE)
            message_type = "text"
            if voice_match:
                voice_id = voice_match.group(1) or None
                final_content = final_content.replace(voice_match.group(0), "")
                full_content = full_content.replace(voice_match.group(0), "")
                message_type = "voice"
            
            # 如果没有显式标签，但情绪比较强烈且字数较少，也可以自动转语音（对齐自主决策逻辑）
            if message_type == "text" and emotion_label and emotion_label != "neutral":
                if len(final_content) < 50: # 短句更容易触发语音
                    # 这里可以根据配置决定是否开启自动语音，目前保持保守，仅在有标签时触发，
                    # 或者后续增加一个 probability 判断
                    pass

            final_content = final_content.strip()
            full_content = full_content.strip()

            final_content = enforce_dialogue_style(
                final_content,
                max_chars=None,
                at_start=True,
                skip_breathing=(not is_sensitive_mode),
                replace_emoji_with_kaomoji=True,
            )
            # 对 full_content 同样应用风格强化，但保留情感标签
            full_content = enforce_dialogue_style(
                full_content,
                max_chars=None,
                at_start=True,
                skip_breathing=(not is_sensitive_mode),
                replace_emoji_with_kaomoji=True,
            )

            # 在发送给前端的内容中移除情感标签 (情绪词)
            # 同时也确保移除了 <think> 标签（如果之前没有处理干净，例如在 full_content 中）
            # 注意：full_content 应该只包含最终的对话内容（可能带 [EMO]），不应包含 <think>
            
            # Remove <think> from full_content just in case
            full_content = re.sub(r"<think>.*?</think>", "", full_content, flags=re.DOTALL).strip()
            final_content = re.sub(r"<think>.*?</think>", "", final_content, flags=re.DOTALL).strip()
            
            ui_content = strip_parentheses_tags(final_content)

            effective = None
            emo_start = time.time()
            try:
                # 使用智能情绪检测器（关键词 + BERT），不再依赖 LLM 标签
                agent.emotion_manager.process_text(user_id, full_content)
                effective = agent.emotion_manager.get_effective_state(user_id)
                if effective and effective.primary_emotion:
                    emotion_label = effective.primary_emotion.value

                strategy = agent.emotion_manager.get_response_strategy(user_id)
            except Exception as e:
                logger.warning(f"情绪管理器处理失败: {e}")
                strategy = None
            logger.info(f"Emotion processing took: {time.time() - emo_start:.4f}s")

            try:
                if save_history and not skip_memory_storage and (not used_placeholder_response):
                    save_start = time.time()
                    await agent._save_conversation_history(
                        user_id, message, full_content, message_id, thought=thought_content
                    )
                    logger.info(f"Save history took: {time.time() - save_start:.4f}s")
                elif used_placeholder_response:
                    logger.info(
                        f"Skipped saving history for message {message_id} (placeholder response)"
                    )
                elif skip_memory_storage:
                    logger.info(f"Skipped saving history for message {message_id} (skip_memory_storage=True)")
            except Exception as e:
                logger.warning(f"Failed to save conversation history: {e}")

            asyncio.create_task(
                agent._maybe_generate_session_title(user_id, message, full_content)
            )

            # 调用自我改进系统记录对话轮次
            if save_history and not skip_memory_storage and (not used_placeholder_response):
                try:
                    from core.services.self_improvement.service import get_self_improvement_service
                    # 根据 user_id 推断 scope
                    from core.utils.data_paths import resolve_data_scope_from_conversation_id
                    scope = resolve_data_scope_from_conversation_id(user_id, default="user")
                    si = get_self_improvement_service(scope=scope)
                    # 异步调用 on_turn_end，不阻塞主流程
                    asyncio.create_task(si.on_turn_end(
                        user_text=message,
                        assistant_text=final_content,
                    ))
                except Exception as e:
                    logger.debug(f"自我改进系统调用失败（不影响主流程）: {e}")

            # Extract hardware intent from strategy if available
            hardware_data = None
            if strategy and strategy.metadata:
                # Check for standardized HardwareIntent
                if "hardware_intent" in strategy.metadata:
                    hw_intent = strategy.metadata["hardware_intent"]
                    if hasattr(hw_intent, "to_dict"):
                        hardware_data = hw_intent.to_dict()
                
                # Fallback to legacy metadata if standardized one is missing but legacy keys exist
                if not hardware_data and ("vibration_pattern" in strategy.metadata or "light_color" in strategy.metadata):
                    # We might want to construct a temporary HardwareIntent or just pass it through
                    # For now, let's just pass the metadata as is if it contains hardware keys, 
                    # but ideally we should normalize it.
                    # Since we updated EmotionResponder to ALWAYS produce HardwareIntent, this fallback is mostly for safety.
                    hardware_data = strategy.metadata

            logger.info(
                f"为用户 {user_id} 生成响应，消息ID: {message_id}, 情绪: {emotion_label}"
            )
            logger.info(
                f"Total handle_message time: {time.time() - start_time:.4f}s"
            )
            return {
                "success": True,
                "content": ui_content,
                "full_content": full_content,
                "emotion": emotion_label,
                "emotion_internal": (effective.sub_emotions if effective else None),
                "image_prompt": image_prompt,
                "voice_id": voice_id,
                "message_type": message_type,
                "message_id": message_id,
                "user_id": user_id,
                "timestamp": datetime.now().timestamp(),
                "hardware": hardware_data, # Add hardware control data to response
                "studyData": current_study_data,  # 注入学习资料高光数据
                "processing_time": time.time() - start_time,
                "thought": thought_content, # Return thought content
            }
        except Exception as e:
            logger.error(f"处理消息时出错: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "message_id": message_id,
                "user_id": user_id,
            }
