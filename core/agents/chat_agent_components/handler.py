"""ChatAgent 非流式消息处理入口（薄壳门面）。

拆分说明（薄壳门面 + 按职责拆子模块）
--------------------------------------
原 1020 行单文件按职责拆成下列子模块，本文件保留 ``handle_message_impl`` 主流程编排
与对外再导出，**对外路径与符号名不变**：

| 子模块 | 职责 |
|---|---|
| ``handler_status_record.py`` | BERT 生活状态记录（起床 / 用餐 / 饮水）与内部触发消息识别 |
| ``handler_modes.py``        | 敏感模式判定、软性回复长度上限、角色状态 → 影响指令 |
| ``handler_tools.py``        | ``ToolRuntime``、native tools 准备与 search_tools schema 扩展 |
| ``handler_tool_calls.py``   | 原生 ``tool_calls`` 与 ``[TOOL_USE: ...]`` 文本协议工具执行 |
| ``handler_llm_loop.py``     | 多轮生成循环（``<think>`` 剥离、截断续写、占位兜底） |
| ``handler_postprocess.py``  | 回复后处理、情绪处理、历史落库与收尾钩子 |

⚠️ 本门面同时是模块级 patch 点：测试会按名替换本模块的
``get_life_simulation_service`` / ``execute_tool_call`` / ``now_str`` / ``datetime``
（``monkeypatch.setattr(handler, "execute_tool_call", ...)``），子模块因此在**调用期**
从本模块取名，不能顶层 from-import 固化。
"""
import asyncio
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List

from core.agents.chat_agent_components.handler_llm_loop import _run_llm_turns
from core.agents.chat_agent_components.handler_modes import (
    _build_affect_instruction,
    _resolve_reply_limits,
    _resolve_sensitive_mode,
)
from core.agents.chat_agent_components.handler_postprocess import (
    _extract_hardware_data,
    _persist_turn,
    _postprocess_response,
    _process_emotion,
    _record_tool_carryover,
)
from core.agents.chat_agent_components.handler_status_record import (
    _record_status_via_bert,
)
from core.agents.chat_agent_components.handler_tools import (
    ToolRuntime,
    _prepare_native_tools,
)
from core.services.life_simulation.service import get_life_simulation_service
from core.utils.logger import get_logger

# 兼容再导出：原单文件模块顶层可见的协作者与工具（供按旧路径引用 / patch）
from core.agents.chat_agent_components.handler_prepare import (
    _inject_affect_instruction,
    _prepare_conversation_messages,
    _resolve_repetition_penalty,
    _resolve_server_side_search,
)
from core.agents.chat_agent_components.handler_status_record import (
    _is_internal_trigger_message as _is_internal_trigger_message,
)
from core.agents.chat_agent_components.handler_status_record import (
    _is_meal_or_drink_self_report as _is_meal_or_drink_self_report,
)
from core.agents.chat_agent_components.handler_tools import (
    _expand_discovered_tool_schemas as _expand_discovered_tool_schemas,
)
from core.agents.chat_agent_components.stream_utils import (
    StreamContextBuilder as StreamContextBuilder,
)
from core.tools.execution import execute_tool_call as execute_tool_call
from core.utils.text_processor import (
    enforce_dialogue_style as enforce_dialogue_style,
    extract_and_strip_emotion as extract_and_strip_emotion,
    strip_parentheses_tags as strip_parentheses_tags,
)
from core.utils.time_utils import now_str as now_str

logger = get_logger("ChatAgent")


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
        # 本请求实际执行过的工具，请求结束时交给 carryover 供下一请求延续
        used_tool_names: List[str] = []

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
        is_trivial_record, system_prompt_override = _record_status_via_bert(
            message, system_prompt_override
        )

        # 如果是琐事记录，且未明确要求跳过存储，则自动跳过存储
        if is_trivial_record and not skip_memory_storage:
            logger.info("Skipping long-term memory storage for trivial status record.")
            skip_memory_storage = True

        try:
            if not message_id:
                message_id = f"msg_{user_id}_{datetime.now().timestamp()}"
            logger.info(f"处理用户 {user_id} 的消息，ID: {message_id}")

            active_tools = []
            from core.tools.tool_visibility import resolve_persona_filename

            tool_persona_filename = resolve_persona_filename()
            tool_mode = "study" if hasattr(agent, "_is_study_mode") and agent._is_study_mode(message, None) else "chat"

            # 普通聊天里的学习行为也进入学习系统：只记低风险证据
            # （提问 / 自述没听懂 / 自称掌握），作答评价仍由 LLM 调 study_record_answer。
            try:
                from core.agents.chat_agent_components.study import observe_learning_message

                await asyncio.to_thread(observe_learning_message, message)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"学习信号自动记录失败（不影响主流程）: {e}")

            active_tools, messages = await _prepare_conversation_messages(
                agent, user_id, message, system_prompt_override, tool_persona_filename
            )

            is_sensitive_mode = await _resolve_sensitive_mode(agent, user_id, message)

            mode = "chat"
            try:
                if hasattr(agent, "_determine_mode"):
                    mode = str(agent._determine_mode(message or "") or mode)
            except Exception:
                mode = "chat"

            # 不限制输出长度，由模型自行决定
            max_tokens = None

            soft_reply_char_limit = _resolve_reply_limits(mode, message)

            affect_instruction = _build_affect_instruction(
                agent, user_id, soft_reply_char_limit, max_tokens
            )
            _inject_affect_instruction(messages, affect_instruction)

            max_turns = 3

            # 判断当前LLM是否使用服务端web_search
            use_server_side_search = _resolve_server_side_search(agent)

            # Dynamic Repetition Penalty for Local/Sensitive Models
            repetition_penalty = _resolve_repetition_penalty(agent, is_sensitive_mode)

            # 准备 native tools（与 streaming.py 对齐，让云模型也能 function calling）
            tools = ToolRuntime(
                persona_filename=tool_persona_filename,
                is_sensitive_mode=is_sensitive_mode,
                used_tool_names=used_tool_names,
            )
            _prepare_native_tools(
                agent, active_tools, tools, tool_mode, use_server_side_search
            )

            turn_result = await _run_llm_turns(
                agent,
                messages,
                tools,
                user_id=user_id,
                message=message,
                max_tokens=max_tokens,
                repetition_penalty=repetition_penalty,
                use_server_side_search=use_server_side_search,
                max_turns=max_turns,
            )
            current_study_data = turn_result.current_study_data

            post = _postprocess_response(
                turn_result.response_content,
                turn_result.collected_image_prompts,
                is_sensitive_mode,
            )
            final_content = post.final_content
            full_content = post.full_content
            emotion_label = post.emotion_label
            image_prompt = post.image_prompt
            voice_id = post.voice_id
            message_type = post.message_type
            ui_content = post.ui_content

            emotion_label, effective, strategy = _process_emotion(
                agent, user_id, full_content, emotion_label
            )

            await _persist_turn(
                agent,
                user_id,
                message,
                full_content,
                final_content,
                message_id,
                turn_result.thought_content,
                save_history,
                skip_memory_storage,
                turn_result.used_placeholder_response,
            )

            # Extract hardware intent from strategy if available
            hardware_data = _extract_hardware_data(strategy)

            # 本请求实际用过的工具交给下一请求延续；变量可能未赋值的分支由取值函数兜住
            _record_tool_carryover(
                user_id,
                lambda: tool_persona_filename,
                lambda: tool_mode,
                used_tool_names,
                active_tools,
            )

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
                "thought": turn_result.thought_content, # Return thought content
            }
        except Exception as e:
            logger.error(f"处理消息时出错: {str(e)}")
            # 异常也提交：已经真正执行过的工具，下一请求重试时仍应直接带上
            _record_tool_carryover(
                user_id,
                lambda: tool_persona_filename,
                lambda: tool_mode,
                used_tool_names,
                active_tools,
            )
            return {
                "success": False,
                "error": str(e),
                "message_id": message_id,
                "user_id": user_id,
            }
