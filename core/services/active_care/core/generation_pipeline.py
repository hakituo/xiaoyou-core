"""Active Care 生成与后处理管线

从 `executor.py` 拆出两个核心调度方法：
- `_get_or_generate_response`  → `GenerationPipeline.get_or_generate_response`
- `_generate_and_postprocess`  → `GenerationPipeline.generate_and_postprocess`

这一段的职责边界是"把 Prompt 变成可发送的后处理结果"：
优先复用决策阶段预生成的文案，否则走隔离的 LLM 路径；拿到响应后
只执行内容后处理（净化/去重/泄漏检测）。发送计数、非响应计数与历史持久化
必须等最终 freshness 校验和真实分发成功后再做，避免已经过期的 candidate 留下副作用。
它不关心触发时机（重叠保护）与发送后的收尾（日记/通知/清 pending），
那两部分分别在 `overlap_guard.py` 与 `post_send_handler.py`。
"""

from typing import Any, Dict, Optional

from core.utils.logger import get_module_logger

logger = get_module_logger("ACTIVE_CARE_EXECUTOR", "active_care_schedule.log")
msg_logger = get_module_logger("ACTIVE_CARE_MSG", "active_care_messages.log")


class GenerationPipeline:
    """生成 + 后处理管线

    构造器接收 executor 门面实例，通过它访问 message_dispatcher、
    response_generator、postprocessor 与模型提示解析。
    """

    def __init__(self, executor):
        self._executor = executor

    async def get_or_generate_response(
        self,
        *,
        aveline_service,
        reply_text: Optional[str],
        thought: Optional[str],
        context: Dict[str, Any],
        sys_prompt: str,
        model_user_input: str,
        target_conversation_id: str,
        dynamic_prompt: str = "",
    ) -> Dict[str, Any]:
        """获取或生成响应。

        决策阶段已生成文案时直接复用。这里不再提前持久化：真正的主动消息
        只有通过发送前 freshness 校验且分发成功后，才允许进入历史与状态闭环。
        """
        executor = self._executor

        if reply_text:
            msg_logger.info(
                "Active Care: Using pre-generated reply from decision phase: %s...",
                reply_text[:50],
            )
            return {
                "content": reply_text,
                "full_content": reply_text,
                "message_type": "text",
                "thought": thought,
            }

        msg_logger.info("Active Care: Generating proactive text via isolated LLM path")
        return await executor._generate_active_care_response(
            model_user_input=model_user_input,
            sys_prompt=sys_prompt,
            model_hint=executor._get_active_care_model_hint(context["persona_name"]),
            dynamic_prompt=dynamic_prompt,
        )

    async def generate_and_postprocess(
        self,
        *,
        aveline_service,
        sys_prompt_type: str,
        reply_text: Optional[str],
        thought: Optional[str],
        context: Dict[str, Any],
        sys_prompt: str,
        model_user_input: str,
        target_conversation_id: str,
        now: float,
        dynamic_prompt: str = "",
        persona_filename: str = "",
    ) -> Optional[Dict[str, Any]]:
        """生成响应并执行后处理管线

        Returns:
            后处理结果字典，失败返回 None
        """
        executor = self._executor

        response = await self.get_or_generate_response(
            aveline_service=aveline_service,
            reply_text=reply_text,
            thought=thought,
            context=context,
            sys_prompt=sys_prompt,
            model_user_input=model_user_input,
            target_conversation_id=target_conversation_id,
            dynamic_prompt=dynamic_prompt,
        )

        if response.get("error") or not str(response.get("content") or "").strip():
            logger.warning(
                "Active Care: Generation failed or returned empty content/error. "
                "error=%s, content_len=%d. Aborting.",
                response.get("error"),
                len(str(response.get("content") or "")),
            )
            return None

        # 确保 chat_agent 已初始化完成
        if hasattr(aveline_service, "_ensure_chat_agent_ready"):
            await aveline_service._ensure_chat_agent_ready()

        agent = getattr(aveline_service, "chat_agent", None)
        if agent is None:
            raise RuntimeError("ChatAgent is not initialized in AvelineService")

        return await executor.postprocessor.postprocess(
            response=response,
            agent=agent,
            aveline_service=aveline_service,
            sys_prompt_type=sys_prompt_type,
            target_conversation_id=target_conversation_id,
            preferred_language=context["preferred_language"],
            repeat_anchors=context["repeat_anchors"],
            last_user_message=context["last_user_message"],
            last_proactive_assistant_message=context["last_proactive_assistant_message"],
            sleep_session_active=context["sleep_session_active"],
            sleep_confirmed_by_silence=context["sleep_confirmed_by_silence"],
            known_sleep_time=context["known_sleep_time"],
            now_ts=now,
        )


__all__ = ["GenerationPipeline"]
