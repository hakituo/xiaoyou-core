"""Active Care 执行器的兼容委托层（mixin）。

历史包袱：executor.py 曾是 1600+ 行单文件，按职责拆分后，service.py、delayed_task
以及若干测试/评估脚本仍在直接调用 executor 的这些私有方法，因此保留为纯转发。

`tests/scripts/active_care/verify_executor_trigger_pipeline_decoupled.py` 会断言这批
方法名必须仍在 ActiveCareExecutor 上可见；以 mixin 方式继承后 hasattr 依旧成立，
所以对外行为零变化，executor.py 只留下真正的编排逻辑。

宿主约定：本 mixin 只读 self 上由 ActiveCareExecutor.__init__ 创建的子模块实例
（settings / response_generator / qq_connection_resolver / _message_dispatcher /
_reminder_handler / _history_processor / _input_builder / _generation_pipeline /
_overlap_guard / _peer_script_gen），本身不持有状态。
"""

from typing import Any, Dict, List, Optional, Tuple

from config.debug_config import is_debug_enabled
from core.utils.config_accessor import get_active_care_config
from core.utils.logger import get_module_logger
from core.models.hardware import HardwareIntent
from core.services.active_care.core.response_generator import ActiveCareResponseGenerator

logger = get_module_logger("ACTIVE_CARE_EXECUTOR", "active_care_schedule.log")


class ActiveCareCompatMixin:
    """兼容入口集合：全部是一行转发，不含业务逻辑。"""

    @property
    def _last_trigger_ts_by_persona(self) -> Dict[str, float]:
        """按 persona 最近触发时间戳（向后兼容：外部 service/delayed_task 直接读写该字典）

        真实状态已归属 OverlapGuard，这里返回其共享字典，保证旧调用方读写一致。
        """
        return self._overlap_guard._last_trigger_ts_by_persona

    # ==================== 兼容入口（委托给已有协作模块） ====================

    @staticmethod
    def _extract_text_from_llm_response(raw) -> str:
        """从 LLM 响应中提取正文（兼容入口）。"""
        return ActiveCareResponseGenerator.extract_text_from_llm_response(raw)

    def _get_active_care_model_hint(self, persona_name: str = "") -> str:
        """获取 Active Care 模型提示"""
        try:
            from config.model_config import get_active_care_content_model

            model = get_active_care_content_model(persona_name)
            if model:
                return model
            return str(
                get_active_care_config("active_care_model_hint", default="", settings=self.settings)
                or ""
            ).strip()
        except Exception:
            if is_debug_enabled("active_care_executor"):
                logger.info("获取Active Care模型提示失败", exc_info=True)
            return ""

    def _get_qq_user_id_from_connections(self) -> str:
        """从 WebSocket 连接中获取 QQ 用户的 ID（向后兼容，返回第一个）"""
        return self.qq_connection_resolver.get_first_user_id()

    def _get_qq_connections(self, *, emit_logs: bool = True) -> List[Dict[str, str]]:
        """从 QQAdapter/QQOfficialAdapter 注册表和 WebSocket 连接中获取所有 QQ 连接（含 persona 信息）"""
        return self.qq_connection_resolver.resolve(emit_logs=emit_logs)

    async def _generate_active_care_response(
        self,
        *,
        model_user_input: str,
        sys_prompt: str,
        model_hint: str,
        dynamic_prompt: str = "",
    ) -> Dict[str, Any]:
        """生成 Active Care 响应（兼容入口，实际逻辑在 response_generator.py）。"""
        return await self.response_generator.generate(
            model_user_input=model_user_input,
            sys_prompt=sys_prompt,
            model_hint=model_hint,
            dynamic_prompt=dynamic_prompt,
        )

    def _resolve_model_path(self, model_hint: str) -> Optional[str]:
        """解析模型路径（兼容入口）。"""
        return self.response_generator._resolve_model_path(model_hint)

    def _get_generation_params(self) -> Tuple[float, int]:
        """获取生成参数（兼容入口）。"""
        return self.response_generator._get_generation_params()

    async def _handle_llm_timeout(
        self,
        messages: List[Dict],
        temperature: float,
        max_tokens: int,
        model_path: Optional[str],
    ) -> Dict[str, Any]:
        """处理 LLM 超时（兼容入口）。"""
        return await self.response_generator._handle_llm_timeout(
            messages, temperature, max_tokens, model_path
        )

    async def _handle_reasoning_only_response(
        self,
        text: str,
        messages: List[Dict],
        temperature: float,
        max_tokens: int,
        model_path: Optional[str],
    ) -> Dict[str, Any]:
        """处理包含 reasoning 的响应（兼容入口）。"""
        return await self.response_generator._handle_reasoning_only_response(
            text, messages, temperature, max_tokens, model_path
        )

    async def _try_fallback_for_reasoning(
        self,
        messages: List[Dict],
        temperature: float,
        max_tokens: int,
        model_path: Optional[str],
    ) -> Dict[str, Any]:
        """推理内容泄漏时尝试 fallback 模型（兼容入口）。"""
        return await self.response_generator._try_fallback_for_reasoning(
            messages, temperature, max_tokens, model_path
        )

    async def _get_fallback_model(self) -> Optional[str]:
        """获取后备模型路径（兼容入口）。"""
        return await self.response_generator._get_fallback_model()

    def determine_hardware_intent(
        self, sys_prompt_type: str, device_context: Dict[str, Any]
    ) -> HardwareIntent:
        """确定硬件意图（兼容入口）。"""
        return self.hardware_intent_resolver.determine(sys_prompt_type, device_context)

    # ==================== 被外部调用的委托方法（向后兼容） ====================

    def get_non_response_count(self, persona_key: str = "") -> int:
        """获取指定 persona 的非响应计数（委托给 MessageDispatcher）"""
        return self._message_dispatcher.get_non_response_count(persona_key)

    def _resolve_persona_key_from_filename(self, persona_filename: str) -> str:
        """根据 persona_filename 解析 persona scope key（委托给 MessageDispatcher）"""
        return self._message_dispatcher.resolve_persona_key_from_filename(persona_filename)

    async def write_diary_entry(self, event_type: str, content: str, thought: Optional[str] = None):
        """写入日记条目（委托给 MessageDispatcher）"""
        await self._message_dispatcher.write_diary_entry(event_type, content, thought=thought)

    async def check_reminders(self):
        """检查到期提醒（委托给 ReminderHandler）"""
        return await self._reminder_handler.check_reminders()

    async def complete_reminder(self, msg_id: str, *, triggered_at: Optional[float] = None) -> bool:
        """完成提醒（委托给 ReminderHandler）"""
        return await self._reminder_handler.complete_reminder(msg_id, triggered_at=triggered_at)

    def format_due_reminder_message(self, reminder: Any) -> str:
        """格式化到期提醒消息（委托给 ReminderHandler）"""
        return self._reminder_handler.format_due_reminder_message(reminder)

    def _build_recent_history_text(
        self, history_msgs: List[Dict[str, Any]], now_ts: Optional[float] = None
    ) -> Tuple[str, str]:
        """构建最近历史记录文本（委托给 HistoryProcessor，测试代码直接调用）"""
        return self._history_processor.build_recent_history_text(history_msgs, now_ts)

    def _build_model_user_input_for_active_care(
        self,
        *,
        user_input_mock: str,
        last_user_message: str,
        last_assistant_message: str,
        last_proactive_assistant_message: str,
        elapsed_seconds: float,
        preferred_language: str,
        sleep_session_active: bool = False,
        is_first_probe: bool = False,
        last_assistant_after_user: bool = False,
    ) -> str:
        """构建模型用户输入（委托给 ModelInputBuilder，测试代码直接调用）"""
        return self._input_builder.build_model_user_input_for_active_care(
            user_input_mock=user_input_mock,
            last_user_message=last_user_message,
            last_assistant_message=last_assistant_message,
            last_proactive_assistant_message=last_proactive_assistant_message,
            elapsed_seconds=elapsed_seconds,
            preferred_language=preferred_language,
            sleep_session_active=sleep_session_active,
            is_first_probe=is_first_probe,
            last_assistant_after_user=last_assistant_after_user,
        )

    # ==================== 生成 / 分发 / 收尾的委托入口 ====================

    async def _generate_and_postprocess(
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
        """生成响应并执行后处理管线（委托给 GenerationPipeline）

        Returns:
            后处理结果字典，失败返回 None
        """
        return await self._generation_pipeline.generate_and_postprocess(
            aveline_service=aveline_service,
            sys_prompt_type=sys_prompt_type,
            reply_text=reply_text,
            thought=thought,
            context=context,
            sys_prompt=sys_prompt,
            model_user_input=model_user_input,
            target_conversation_id=target_conversation_id,
            now=now,
            dynamic_prompt=dynamic_prompt,
            persona_filename=persona_filename,
        )

    async def _get_or_generate_response(
        self,
        aveline_service,
        reply_text: Optional[str],
        thought: Optional[str],
        context: Dict[str, Any],
        sys_prompt: str,
        user_input_mock: str,
        target_conversation_id: str,
        dynamic_prompt: str = "",
    ) -> Dict[str, Any]:
        """获取或生成响应（委托给 GenerationPipeline）"""
        return await self._generation_pipeline.get_or_generate_response(
            aveline_service=aveline_service,
            reply_text=reply_text,
            thought=thought,
            context=context,
            sys_prompt=sys_prompt,
            model_user_input=user_input_mock,
            target_conversation_id=target_conversation_id,
            dynamic_prompt=dynamic_prompt,
        )

    def _check_overlap_guard(self, sys_prompt_type: str, now: float, persona_key: str = "") -> bool:
        """检查重叠保护（委托给 OverlapGuard，逻辑在 overlap_guard.py）"""
        return self._overlap_guard.check(sys_prompt_type, now, persona_key)

    def _get_overlap_guard_seconds(self, sys_prompt_type: str) -> int:
        """获取重叠保护秒数（委托给 OverlapGuard）"""
        return self._overlap_guard.get_guard_seconds(sys_prompt_type)

    # 注：generate_peer_script 仍留在 executor.py 类体内——它是门面主入口，
    # tests/unit/test_error_20260909_regressions.py 用 AST 静态校验其参数转发契约。
