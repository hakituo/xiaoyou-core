#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回复生成核心模块。

负责与 ChatAgent 交互生成回复：
- stream_generate_response：流式生成回复（保持原样搬迁，未拆解方法内部逻辑）
- generate_response：非流式生成回复（聚合 stream_chat 输出 + 后处理）

所有函数均为模块级函数，第一参数为 `service`（AvelineService 实例），
与 stream_orchestrator.py 风格保持一致。
"""
from __future__ import annotations

import time
import traceback
from typing import Any, Dict, Optional, Tuple

from core.utils.time_utils import get_current_time
from core.utils.logger import get_logger

logger = get_logger("AVELINE_SERVICE")


async def stream_generate_response(
    service: Any,
    user_input: str,
    conversation_id: str,
    system_prompt: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: float = 0.7,
    model_hint: Optional[str] = None,
    save_history: bool = True,
    user_name: Optional[str] = None,
    length_preference: Optional[str] = None,
    persona_filename: Optional[str] = None,
    service_dynamic_context: Optional[str] = None,
    api_key_env: Optional[str] = None,
    platform: Optional[str] = None,
    history_override: Optional[list[Dict[str, str]]] = None,
):
    """
    Stream response generation
    Yields chunks of text or structured data
    """
    try:
        logger.info(
            f"AvelineService: Start stream_generate_response for {conversation_id}"
        )
        t_start = time.time()

        from core.services.aveline.prompt_policy import build_stream_system_prompt
        final_system_prompt = build_stream_system_prompt(
            service, system_prompt, length_preference
        )

        service_extra_dynamic_context = None
        if system_prompt is None and final_system_prompt:
            service_extra_dynamic_context = final_system_prompt
            final_system_prompt = None

        try:
            should_extract_daily = bool(save_history)
            user_text = str(user_input or "")
            if "[ACTIVE_CARE_" in user_text or "_TRIGGER]" in user_text:
                should_extract_daily = False
            if should_extract_daily:
                from core.services.daily.extractor import get_activity_extractor

                extractor = get_activity_extractor()
                from core.utils.async_tasks import spawn_bg_task
                spawn_bg_task(extractor.analyze_and_record(user_text), name="activity_extraction")
        except Exception as e:
            logger.warning(f"Failed to start passive activity extraction: {e}")

        # 0. Command Check
        t_cmd = time.time()
        cmd_result = await service._handle_command(user_input, conversation_id)
        if cmd_result:
            logger.info(
                f"AvelineService: Command handled in {time.time() - t_cmd:.4f}s"
            )
            yield cmd_result[0]
            return

        # 0.5 Natural Language Control Check (Intent Recognition via BERT)
        # 使用 BERT 进行快速意图识别，并执行相应操作
        # 但不直接返回结果，而是将结果作为 System Prompt 注入到对话中
        try:
            from core.services.intent.service import classify_intent

            # 快速分类意图
            intent_res = await classify_intent(user_input)
            intent_name = intent_res.get("intent", "NONE")

            if intent_name != "NONE":
                logger.info(f"AvelineService: Detected intent {intent_name} ({intent_res.get('confidence')})")

                # 执行意图逻辑 (Mock execution for now, or real logic)
                # 这里我们需要一个 executor 来真正执行操作，并返回执行结果文本
                # 例如：切换模型成功 -> "系统已切换至 Qwen 模型"

                execution_result = ""
                # TODO: 引入 IntentExecutor 来处理具体逻辑
                # 目前简单硬编码几个示例
                if intent_name == "CLEAR_MEMORY":
                    await service.chat_agent.clear_history(conversation_id, mode="short")
                    execution_result = "系统：短期记忆已清除。"
                elif intent_name == "SWITCH_MODEL":
                    # 假设执行成功
                    execution_result = "系统：模型切换指令已接收（模拟）。"
                elif intent_name == "ACTIVE_CARE_SNOOZE":
                    delay_seconds = int((intent_res.get("slots") or {}).get("delay_seconds") or 0)
                    if delay_seconds <= 0:
                        delay_seconds = 1800
                    try:
                        from core.services.active_care.core.service import get_active_care_service

                        active_care_service = get_active_care_service()
                        next_ts = time.time() + float(delay_seconds)
                        await active_care_service.checker.set_next_decision_ts(next_ts)
                        mins = max(1, int(round(delay_seconds / 60)))
                        execution_result = f"系统：已收到，Active Care 将在约 {mins} 分钟后再提醒你。"
                    except Exception as _ac_err:
                        logger.warning(f"AvelineService: failed to apply ACTIVE_CARE_SNOOZE: {_ac_err}")
                        execution_result = "系统：已理解你想稍后再提醒，但这次设置未成功。"

                if execution_result:
                    logger.info(f"AvelineService: Intent executed. Injecting result to context: {execution_result}")

                    intent_injection = f"\n\n[System Event]\nUser triggered intent: {intent_name}\nExecution Result: {execution_result}\nPlease inform the user about this action naturally."
                    if final_system_prompt is not None:
                        final_system_prompt += intent_injection
                    else:
                        service_extra_dynamic_context = (service_extra_dynamic_context or "") + intent_injection

        except Exception as e:
            logger.warning(f"Intent check failed: {e}")

        # Delegate to ChatAgent
        await service._ensure_chat_agent_ready()
        if not service.chat_agent:
            from core.agents.chat_agent import get_default_chat_agent
            service.chat_agent = get_default_chat_agent()

        if not service.chat_agent:
            logger.error("Failed to initialize ChatAgent")
            yield {
                "type": "error",
                "message": "ChatAgent 初始化失败",
                "error_code": "SERVICE_UNAVAILABLE",
                "done": True,
                "details": {"error_type": "ChatAgentNotReady"},
            }
            return

        # final_system_prompt is already set above

        logger.info(
            f"AvelineService: Calling chat_agent.stream_chat after {time.time() - t_start:.4f}s"
        )

        # Use ChatAgent's stream_chat
        # Note: ChatAgent expects user_id, using conversation_id as user_id for now
        t_stream = time.time()
        first_visible_token_received = False

        # 从环境变量获取API key（用于QQ官方机器人独立缓存）
        resolved_api_key = None
        if api_key_env:
            import os
            resolved_api_key = os.getenv(api_key_env)
            if resolved_api_key:
                logger.info(f"AvelineService: Using API key from env: {api_key_env}")

        # 合并 service_extra_dynamic_context 与 service_dynamic_context
        # - service_extra_dynamic_context: 来自 build_stream_system_prompt（service 级 dynamic_context + length_instruction）
        # - service_dynamic_context: 来自上游调用方（chat_handlers 注入的 persona_hint、双角色私聊上下文、说话者身份等）
        # 两者都需要传给 chat_agent.stream_chat，否则 persona_hint 会在最后一公里丢失
        # （见 debug-interrupt-window-missing.md：角色被打断后不知道自己在干什么）
        merged_dynamic_context = service_extra_dynamic_context
        if service_dynamic_context and str(service_dynamic_context or "").strip():
            svc_ctx = str(service_dynamic_context).strip()
            if merged_dynamic_context:
                merged_dynamic_context = f"{merged_dynamic_context}\n\n{svc_ctx}"
            else:
                merged_dynamic_context = svc_ctx

        async for chunk in service.chat_agent.stream_chat(
            user_id=conversation_id,
            message=user_input,
            save_history=save_history,
            model_hint=model_hint,
            system_prompt=final_system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            user_name=user_name,
            persona_filename=persona_filename,
            service_dynamic_context=merged_dynamic_context,
            api_key=resolved_api_key,
            platform=platform,
            history_override=history_override,
        ):
            if not first_visible_token_received:
                is_visible_token = False
                if isinstance(chunk, dict):
                    if chunk.get("type") == "token" and str(
                        chunk.get("content") or ""
                    ):
                        is_visible_token = True
                else:
                    if str(chunk or ""):
                        is_visible_token = True

                if is_visible_token:
                    ttft = time.time() - t_stream
                    logger.info(
                        f"AvelineService: First visible token (TTFT) received in {ttft:.4f}s"
                    )
                    first_visible_token_received = True

                    if service._resource_monitor:
                        service._resource_monitor.record_metric(
                            "llm_ttft",
                            ttft,
                            tags={"model": model_hint or "default"},
                        )

            # [Fix] Ensure chunk is always a dictionary for WebSocket compatibility
            if isinstance(chunk, str):
                yield {"type": "token", "content": chunk, "timestamp": time.time()}
            else:
                yield chunk

        logger.info(
            f"AvelineService: Stream completed in {time.time() - t_start:.4f}s"
        )

    except Exception as e:
        logger.error(
            "stream_generate_response error",
            exc_info=True,
            extra={"conversation_id": conversation_id},
        )
        err_msg = service._friendly_stream_error_message(e)
        details: Dict[str, Any] = {"error_type": type(e).__name__}
        try:
            raw_msg = str(e).strip()
            if raw_msg:
                details["error_message"] = raw_msg[:800]
        except Exception:
            pass
        yield {
            "type": "error",
            "message": err_msg,
            "error_code": "SYSTEM_INTERNAL_ERROR",
            "done": True,
            "details": details,
        }


async def generate_response(
    service: Any,
    user_input: str,
    conversation_id: str,
    system_prompt: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: float = 0.7,
    timeout: Optional[float] = None,
    model_hint: Optional[str] = None,
    save_history: bool = True,
    user_name: Optional[str] = None,
    length_preference: Optional[str] = None,
    platform: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Main entry point for generating responses (Non-streaming)"""

    # 0. Command Check
    cmd_result = await service._handle_command(user_input, conversation_id)
    if cmd_result:
        return cmd_result

    start_time = time.time()
    from core.services.aveline.prompt_policy import build_generation_system_prompt
    final_system_prompt = build_generation_system_prompt(
        service, system_prompt, length_preference
    )

    full_response = ""
    metadata = {
        "status": "success",
        "timestamp": get_current_time().isoformat(),
        "conversation_id": conversation_id,
        "triggers": [],
    }

    try:
        # final_system_prompt is already set above

        # Delegate to ChatAgent
        await service._ensure_chat_agent_ready()
        if not service.chat_agent:
            from core.agents.chat_agent import get_default_chat_agent
            service.chat_agent = get_default_chat_agent()

        # Aggregate stream
        async for chunk in service.chat_agent.stream_chat(
            user_id=conversation_id,
            message=user_input,
            save_history=save_history,
            model_hint=model_hint,
            system_prompt=final_system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            user_name=user_name,
            platform=platform,
        ):
            # Check for errors from the agent/LLM
            if "error" in chunk:
                logger.error(f"Error from ChatAgent stream: {chunk['error']}")
                metadata["status"] = "error"
                metadata["error"] = chunk["error"]
                # Return the error message as the response text so the user sees it
                return f"System Error: {chunk['error']}", metadata

            if "content" in chunk:
                full_response += chunk["content"]

            if "type" in chunk:
                # Collect triggers for metadata
                metadata["triggers"].append(
                    {"type": chunk["type"], "data": chunk.get("data")}
                )

        from core.services.aveline.response_postprocess import postprocess_generated_response
        final_content, metadata = await postprocess_generated_response(
            service,
            user_input=user_input,
            conversation_id=conversation_id,
            full_response=full_response,
            metadata=metadata,
            model_hint=model_hint,
            save_history=save_history,
            start_time=start_time,
        )
        return final_content, metadata

    except Exception as e:
        logger.error(f"generate_response error: {e}")
        traceback.print_exc()
        recovery = "刚刚卡了一下。你要不再发一次？或者我们先换个话题也行。"
        return recovery, {
            "status": "error",
            "error_code": "SYSTEM_INTERNAL_ERROR",
            "details": {"error_type": type(e).__name__},
        }
