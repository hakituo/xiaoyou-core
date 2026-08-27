"""Active Care 执行器（薄壳门面）

负责执行主动关怀消息的生成和发送。原 1604 行单文件已按职责拆分为 6 个独立模块：
- history_processor.py: 历史消息纯解析
- input_builder.py: LLM 输入构建
- context_builder.py: 上下文组装 + Prompt
- conversation_router.py: 会话路由
- message_dispatcher.py: 消息分发 + 回调
- reminder_handler.py: 提醒处理

本文件保留 ActiveCareExecutor 类作为门面，实例化上述模块并委托调用。
外部 API 完全兼容：12 个兼容入口 + 8 个被外部调用的委托方法 + 核心调度方法。
"""
import time
from typing import Any, Dict, List, Optional, Tuple

from config.debug_config import is_debug_enabled
from config.integrated_config import get_settings
from core.llm.llm_logger import _is_log_full_prompt
from core.utils.config_accessor import get_active_care_config
from core.utils.logger import get_module_logger
from core.utils.time_utils import get_current_time, get_time_period
from core.models.hardware import HardwareIntent
from core.services.active_care.core.hardware_intent import ActiveCareHardwareIntentResolver
from core.services.active_care.core.persona_resolver import PersonaResolver
from core.services.active_care.core.qq_connection_resolver import QQConnectionResolver
from core.services.active_care.core.response_generator import ActiveCareResponseGenerator
from core.services.active_care.postprocess.postprocessor import ActiveCarePostprocessor
from core.services.active_care.storage.state_persistence import StatePersistence
# 拆分出的子模块
from core.services.active_care.core.history_processor import HistoryProcessor
from core.services.active_care.core.input_builder import ModelInputBuilder
from core.services.active_care.core.context_builder import TriggerContextBuilder
from core.services.active_care.core.conversation_router import ConversationRouter
from core.services.active_care.core.message_dispatcher import MessageDispatcher
from core.services.active_care.core.reminder_handler import ReminderHandler
from core.services.active_care.core.trigger_result import (
    TriggerMessageResult,
    TriggerOutcome,
)

logger = get_module_logger("ACTIVE_CARE_EXECUTOR", "active_care_schedule.log")
msg_logger = get_module_logger("ACTIVE_CARE_MSG", "active_care_messages.log")


class ActiveCareExecutor:
    """Active Care 执行器（门面），负责生成和发送主动关怀消息

    通过组合 6 个子模块实现单一职责，外部 API 完全兼容。
    """

    def __init__(self, context, storage):
        self.settings = get_settings()
        self.context = context
        self.storage = storage
        self.consecutive_non_responses: Dict[str, int] = {}  # per-persona 非响应计数，空字符串key为单QQ兼容
        self.persona_resolver = PersonaResolver(storage)
        self.qq_connection_resolver = QQConnectionResolver()
        self.response_generator = ActiveCareResponseGenerator(self.settings)
        self.hardware_intent_resolver = ActiveCareHardwareIntentResolver()
        self.postprocessor = ActiveCarePostprocessor()
        self.state_persistence = StatePersistence(storage)
        self._last_trigger_ts_by_persona: Dict[str, float] = {}
        self._last_skip_is_interval_blocked = False
        self._last_skip_reason = ""
        # 双角色互聊剧本生成器（从本类拆分出去的 5 阶段流水线）
        from core.services.active_care.peer_chat.peer_script_generator import PeerScriptGenerator
        self._peer_script_gen = PeerScriptGenerator(self)

        # 拆分出的子模块（整体注入 executor 实例，降低搬迁出错风险）
        self._history_processor = HistoryProcessor()
        self._input_builder = ModelInputBuilder()
        self._context_builder = TriggerContextBuilder(self)
        self._conversation_router = ConversationRouter(self)
        self._message_dispatcher = MessageDispatcher(self)
        self._reminder_handler = ReminderHandler()

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
        self, messages: List[Dict], temperature: float, max_tokens: int, model_path: Optional[str],
    ) -> Dict[str, Any]:
        """处理 LLM 超时（兼容入口）。"""
        return await self.response_generator._handle_llm_timeout(
            messages, temperature, max_tokens, model_path
        )

    async def _handle_reasoning_only_response(
        self, text: str, messages: List[Dict], temperature: float, max_tokens: int, model_path: Optional[str],
    ) -> Dict[str, Any]:
        """处理包含 reasoning 的响应（兼容入口）。"""
        return await self.response_generator._handle_reasoning_only_response(
            text, messages, temperature, max_tokens, model_path
        )

    async def _try_fallback_for_reasoning(
        self, messages: List[Dict], temperature: float, max_tokens: int, model_path: Optional[str],
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

    async def write_diary_entry(
        self, event_type: str, content: str, thought: Optional[str] = None
    ):
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

    # ==================== 核心调度（保留在门面） ====================

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
        """生成响应并执行后处理管线

        Returns:
            后处理结果字典，失败返回 None
        """
        response = await self._get_or_generate_response(
            aveline_service, reply_text, thought, context, sys_prompt,
            model_user_input, target_conversation_id,
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

        await self._message_dispatcher.update_non_response_count(
            target_conversation_id, persona_filename=persona_filename
        )

        post_processed = await self.postprocessor.postprocess(
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
        return post_processed

    async def trigger_message(
        self,
        sys_prompt_type: str,
        user_input_mock: str,
        reminder_msg: Optional[str] = None,
        thought: Optional[str] = None,
        device_context: Optional[Dict[str, Any]] = None,
        client_type: Optional[str] = None,
        reply_text: Optional[str] = None,
        specific_instruction: Optional[str] = None,
        persona_filename: str = "",
        planned_topic: str = "",
        self_activity: bool = False,
    ) -> bool:
        """触发主动关怀消息

        Args:
            persona_filename: 人设文件名，为空时回退到全局 PersonaManager。
                              在双QQ模式下，每个 persona 独立触发。
            planned_topic: 本次决策的计划话题（LLM 决策输出字段），
                          用于题材感知 MDP 记录题材标签。
            self_activity: 是否为角色自发行为（如日程切换告别消息）。
                          True 时不记录题材、不进入 MDP 学习闭环。

        Returns:
            True: 消息已发送
            False: 消息未发送（可能是被间隔保护拦住，也可能是发送失败）
        """
        result = await self.trigger_message_with_result(
            sys_prompt_type=sys_prompt_type,
            user_input_mock=user_input_mock,
            reminder_msg=reminder_msg,
            thought=thought,
            device_context=device_context,
            client_type=client_type,
            reply_text=reply_text,
            specific_instruction=specific_instruction,
            persona_filename=persona_filename,
            planned_topic=planned_topic,
            self_activity=self_activity,
        )
        self._last_skip_is_interval_blocked = result.is_interval_blocked
        self._last_skip_reason = result.legacy_skip_reason
        return result.delivered

    async def trigger_message_with_result(
        self,
        sys_prompt_type: str,
        user_input_mock: str,
        reminder_msg: Optional[str] = None,
        thought: Optional[str] = None,
        device_context: Optional[Dict[str, Any]] = None,
        client_type: Optional[str] = None,
        reply_text: Optional[str] = None,
        specific_instruction: Optional[str] = None,
        persona_filename: str = "",
        planned_topic: str = "",
        self_activity: bool = False,
    ) -> TriggerMessageResult:
        """触发主动关怀消息并返回显式结果。"""
        now = time.time()

        # 按 persona 独立追踪重叠保护
        persona_key = str(persona_filename or "").strip()
        if not self._check_overlap_guard(sys_prompt_type, now, persona_key=persona_key):
            return TriggerMessageResult(
                delivered=False,
                outcome=TriggerOutcome.OVERLAP_BLOCKED,
            )

        attempt_trigger_ts = now
        self._last_trigger_ts_by_persona[persona_key] = now
        msg_logger.info(
            "Active Care EXECUTE -> Intent: %s | Content: %s...",
            sys_prompt_type, user_input_mock[:30],
        )

        now_dt = get_current_time()
        tod = get_time_period()
        delivered = False

        target_conversation_id, original_conversation_id, requested_client_type = (
            await self._conversation_router.resolve_target_conversation(
                client_type, persona_filename=persona_filename
            )
        )

        # 早安主动消息注入用户睡眠期间的待处理消息：
        # 角色醒来发早安时，如果用户昨晚发过消息被静默累积（pending），
        # 把这些消息注入 prompt 让角色能主动提及，发送成功后清空 pending，
        # 避免早安完全不回应昨晚的消息，用户感觉消息"石沉大海"。
        _morning_pending_injected: List[str] = []
        if sys_prompt_type == "good_morning_proactive":
            try:
                from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
                    get_pending_messages as _get_morning_pending,
                )
                _morning_pending_injected = list(
                    _get_morning_pending(target_conversation_id)
                )
                if _morning_pending_injected:
                    _pending_block = "\n".join(
                        f"{i}. {msg}"
                        for i, msg in enumerate(_morning_pending_injected, 1)
                    )
                    _morning_pending_hint = (
                        "\n\n【用户在你睡觉期间发来的、你还没回的消息】\n"
                        f"{_pending_block}\n"
                        "请在起床问候中自然地回应这些消息（可以提及内容、回应对方），"
                        "不要假装没看到，但也不要逐条机械回复。"
                    )
                    specific_instruction = (specific_instruction or "") + _morning_pending_hint
                    msg_logger.info(
                        "Active Care good_morning_proactive: 注入 %d 条睡眠期间待处理消息",
                        len(_morning_pending_injected),
                    )
            except Exception as _pending_err:
                msg_logger.warning(
                    "读取早安 pending 消息失败: %s", _pending_err
                )

        logger.info(
            "Active Care trigger_message: persona_filename=%s, target_cid=%s, original_cid=%s",
            persona_filename, target_conversation_id, original_conversation_id,
        )

        history_msgs = await self._context_builder.get_history_with_cache(
            target_conversation_id, now
        )

        context = await self._context_builder.build_trigger_context(
            history_msgs, target_conversation_id, now, now_dt, tod
        )

        prompt_result, model_user_input = self._context_builder.build_prompt(
            context, sys_prompt_type, user_input_mock, reminder_msg,
            thought, device_context, client_type, specific_instruction
        )
        sys_prompt = prompt_result.prompt
        dynamic_prompt = prompt_result.dynamic_prompt

        if _is_log_full_prompt():
            msg_logger.info("Active Care Prompt Breakdown:\n%s", prompt_result.format_breakdown())
        effective_client_type = str(client_type or "").strip().lower()

        try:
            from core.core_engine.service_singletons import get_aveline_service
            aveline_service = get_aveline_service()
            if aveline_service is None:
                raise RuntimeError("AvelineService could not be initialized")

            post_processed = await self._generate_and_postprocess(
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
            if not post_processed:
                return TriggerMessageResult(
                    delivered=False,
                    outcome=TriggerOutcome.GENERATION_FAILED,
                )

            # Prompt 中的日历锚点是软约束，模型仍可能沿用历史里的错误相对日期。
            # 所有 Active Care 文案在发送前都做确定性事实纠正，但不改变 MDP 动作。
            from core.agents.chat_agent_components.persona_system.prompt import (
                correct_relative_holiday_claims,
                remove_invalid_relative_holiday_clauses,
            )

            original_calendar_content = str(
                post_processed.get("content") or ""
            ).strip()
            corrected_calendar_content = correct_relative_holiday_claims(
                original_calendar_content,
                check_date=now_dt.date(),
            )
            if corrected_calendar_content != original_calendar_content:
                sanitized_calendar_content = remove_invalid_relative_holiday_clauses(
                    original_calendar_content,
                    check_date=now_dt.date(),
                )
                # 若整条都建立在错误节日断言上，至少纠正事实；否则直接删掉
                # 错误短句，避免模型换成“后天七夕”后继续复读同一话题。
                final_calendar_content = (
                    sanitized_calendar_content or corrected_calendar_content
                )
                msg_logger.warning(
                    "Active Care: 发送前纠正错误相对节日日期。before=%s after=%s",
                    original_calendar_content[:160],
                    final_calendar_content[:160],
                )
                post_processed["content"] = final_calendar_content
                post_processed["tts_text"] = final_calendar_content

            # 到期提醒属于硬目标事件，不参与普通上下文话题漂移。
            # 这里只校验 reminder，不改变 MDP 选择的常规主动关怀消息。
            if sys_prompt_type in ("reminder", "focus_nudge") and reminder_msg:
                original_content = str(post_processed.get("content") or "").strip()
                enforced_content = self._reminder_handler.enforce_reminder_target(
                    original_content,
                    reminder_msg,
                )
                if enforced_content != original_content:
                    post_processed["content"] = enforced_content
                    post_processed["tts_text"] = enforced_content
                    post_processed["message_type"] = "text"

            if sys_prompt_type == "usage_limit_exceeded":
                from core.services.active_care.postprocess.event_target_guard import (
                    enforce_usage_limit_target,
                )

                original_content = str(post_processed.get("content") or "").strip()
                enforced_content = enforce_usage_limit_target(
                    original_content,
                    specific_instruction or user_input_mock,
                )
                if enforced_content != original_content:
                    msg_logger.warning(
                        "Active Care: 数字健康硬事件纠偏。before=%s after=%s",
                        original_content[:160],
                        enforced_content[:160],
                    )
                    post_processed["content"] = enforced_content
                    post_processed["tts_text"] = enforced_content
                    post_processed["message_type"] = "text"

            # 昨日日记与聊天历史可能保留旧的词汇数量；最终发送前必须以
            # 当前取词队列和今日复习进度为准，避免完成后仍继续催促。
            from core.services.active_care.postprocess.event_target_guard import (
                enforce_vocabulary_status,
                mentions_vocabulary_topic,
            )

            original_vocab_content = str(post_processed.get("content") or "").strip()
            if mentions_vocabulary_topic(original_vocab_content):
                try:
                    from core.tools.study.english.vocabulary_manager import (
                        get_vocabulary_manager,
                    )

                    vocab_status = get_vocabulary_manager().get_today_review_status()
                    enforced_vocab_content = enforce_vocabulary_status(
                        original_vocab_content,
                        vocab_status,
                    )
                    if enforced_vocab_content != original_vocab_content:
                        msg_logger.warning(
                            "Active Care: 词汇任务事实纠偏。status=%s before=%s after=%s",
                            vocab_status,
                            original_vocab_content[:160],
                            enforced_vocab_content[:160],
                        )
                        post_processed["content"] = enforced_vocab_content
                        post_processed["tts_text"] = enforced_vocab_content
                        post_processed["message_type"] = "text"
                except Exception:
                    msg_logger.warning("Active Care: 词汇任务事实校验失败", exc_info=True)

            delivered = await self._message_dispatcher.dispatch_message(
                aveline_service, post_processed, sys_prompt_type, device_context,
                target_conversation_id, original_conversation_id, effective_client_type,
                requested_client_type, thought, context, now, now_dt,
                planned_topic=planned_topic,
                self_activity=self_activity,
            )

            # 消息发送成功后通知 Active Care 服务更新间隔保护
            if delivered:
                # 早安注入的 pending 已被主动消息回应，清空避免被动回复重复注入
                if _morning_pending_injected:
                    try:
                        from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
                            clear_pending_messages as _clear_morning_pending,
                        )
                        _clear_morning_pending(target_conversation_id)
                        msg_logger.info(
                            "Active Care good_morning_proactive: 已清空 %d 条待处理消息",
                            len(_morning_pending_injected),
                        )
                    except Exception as _clear_err:
                        msg_logger.warning(
                            "清空早安 pending 失败: %s", _clear_err
                        )
                try:
                    from core.services.active_care.core.service import get_active_care_service
                    svc = get_active_care_service()
                    if svc:
                        await svc.on_assistant_message_sent(
                            timestamp=now, persona_filename=persona_filename
                        )
                except Exception as notify_err:
                    msg_logger.warning("Active Care: 通知 on_assistant_message_sent 失败: %s", notify_err)

            await self.write_diary_entry(
                sys_prompt_type, post_processed.get("content", ""), thought=thought
            )
            msg_logger.info("Active Care: 已发送 %s 消息并记录日记", sys_prompt_type)

            # 消息发送成功后清除推迟提醒列表（避免下次重复注入）
            if delivered and prompt_result.has_deferred_reminders:
                try:
                    resolved_scope = None
                    if persona_filename:
                        resolved_scope = self.storage.resolve_scope_from_persona_filename(
                            persona_filename
                        )
                    await self.storage.save_proactive_state(
                        {"deferred_plan_reminders": []},
                        scope=resolved_scope or None,
                    )
                    msg_logger.info("Active Care: 已清除推迟提醒列表")
                except Exception as clear_err:
                    msg_logger.warning("Active Care: 清除推迟提醒列表失败: %s", clear_err)

            if delivered:
                return TriggerMessageResult(
                    delivered=True,
                    outcome=TriggerOutcome.DELIVERED,
                )
            return TriggerMessageResult(
                delivered=False,
                outcome=TriggerOutcome.DISPATCH_FAILED,
            )

        except Exception as e:
            msg_logger.error("Active Care: 发送主动消息失败: %s", e, exc_info=True)
            return TriggerMessageResult(
                delivered=False,
                outcome=TriggerOutcome.EXECUTION_EXCEPTION,
                detail=str(e),
            )
        finally:
            if not delivered:
                overlap_guard_seconds = self._get_overlap_guard_seconds(sys_prompt_type)
                if self._last_trigger_ts_by_persona.get(persona_key, 0.0) == attempt_trigger_ts:
                    self._last_trigger_ts_by_persona[persona_key] = attempt_trigger_ts - overlap_guard_seconds - 1

    def _check_overlap_guard(self, sys_prompt_type: str, now: float, persona_key: str = "") -> bool:
        """检查重叠保护

        Args:
            persona_key: persona 标识，用于按 persona 独立追踪触发时间。
                         为空时使用全局追踪（兼容单QQ模式）。
        """
        # 作息事件触发的必要通知，不受间隔保护限制：
        # - activity_return_proactive: 活动回归通知（中断窗口结束）
        # - sleep_again_proactive: 半夜被叫醒后睡回去的告别
        # - goodnight_proactive: 按作息时间首次入睡的晚安告别
        #    （曾因未豁免被 2400s 间隔保护拦截，导致角色入睡时发不出晚安）
        if sys_prompt_type in (
            "activity_return_proactive",
            "sleep_again_proactive",
            "goodnight_proactive",
            "focus_nudge",  # 专注番茄钟探班：策略层已内置冷却/上限，豁免全局重叠保护
        ):
            return True

        overlap_guard_seconds = self._get_overlap_guard_seconds(sys_prompt_type)
        last_trigger_ts = self._last_trigger_ts_by_persona.get(persona_key, 0.0)

        if (
            sys_prompt_type != "startup"
            and (now - last_trigger_ts) < overlap_guard_seconds
        ):
            logger.warning(
                "Active Care: Trigger skipped to avoid overlap (persona=%s). Last trigger was %ss ago (guard=%ss).",
                persona_key or "global",
                int(now - last_trigger_ts),
                int(overlap_guard_seconds),
            )
            return False
        return True

    def _get_overlap_guard_seconds(self, sys_prompt_type: str) -> int:
        """获取重叠保护秒数（所有类型统一使用 min_gap_seconds）"""
        min_gap_seconds = int(
            get_active_care_config("active_care_min_gap_seconds", default=600, settings=self.settings)
            or 600
        )
        return min_gap_seconds

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
        """获取或生成响应"""
        if reply_text:
            msg_logger.info(f"Active Care: Using pre-generated reply from decision phase: {reply_text[:50]}...")
            try:
                await self._message_dispatcher.persist_proactive_message_fallback(
                    conversation_id=target_conversation_id,
                    content=reply_text,
                    thought=thought,
                )
            except Exception as e:
                logger.warning(f"Active Care: Failed to persist pre-generated reply: {e}")
            return {
                "content": reply_text,
                "full_content": reply_text,
                "message_type": "text",
                "thought": thought,
            }

        msg_logger.info("Active Care: Generating proactive text via isolated LLM path")
        return await self._generate_active_care_response(
            model_user_input=user_input_mock,
            sys_prompt=sys_prompt,
            model_hint=self._get_active_care_model_hint(context["persona_name"]),
            dynamic_prompt=dynamic_prompt,
        )

    async def generate_peer_script(
        self,
        role_id: str,
        peer_qq_id: str,
        topic: str = "",
        situation: str = "",
        opening_idea: str = "",
        persona_filename: str = "",
        negotiation_reminders: list = None,
    ) -> bool:
        """生成双角色互聊剧本并分发（委托给 PeerScriptGenerator，逻辑拆分至 peer_script_generator.py）

        完整 5 阶段流水线：
        1. _load_peer_config: 加载双QQ配置
        2. _gather_peer_context: 拉取历史/时间/生理状态
        3. _generate_script_llm: LLM 生成剧本（含回退+重试+过滤）
        4. _dispatch_script: 分发到各自QQ
        5. _run_peer_post_hooks: 后处理（日记/事件/巡检/历史/mention）
        """
        return await self._peer_script_gen.generate_peer_script(
            role_id=role_id,
            peer_qq_id=peer_qq_id,
            topic=topic,
            situation=situation,
            opening_idea=opening_idea,
            persona_filename=persona_filename,
            negotiation_reminders=negotiation_reminders,
        )


def get_active_care_executor():
    """获取全局 ActiveCareExecutor 实例（从 ActiveCareService 单例获取）

    用于需要直接访问 executor 的场景（如 peer_chat_scheduler、外部测试）。
    如果 ActiveCareService 未初始化，返回 None。

    Returns:
        ActiveCareExecutor 实例或 None
    """
    from core.services.active_care.core.service import get_active_care_service
    service = get_active_care_service()
    return service.executor if service else None
