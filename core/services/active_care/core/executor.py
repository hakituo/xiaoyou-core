"""Active Care 执行器（薄壳门面）

负责执行主动关怀消息的生成和发送。原 1604 行单文件已按职责拆分为 6 个独立模块：
- history_processor.py: 历史消息纯解析
- input_builder.py: LLM 输入构建
- context_builder.py: 上下文组装 + Prompt
- conversation_router.py: 会话路由
- message_dispatcher.py: 消息分发 + 回调
- reminder_handler.py: 提醒处理

核心调度链路进一步拆分为 3 个阶段模块（2026-09-04）：
- trigger_preparer.py: 触发前置准备（会话路由 → 早安注入 → 上下文 → Prompt）
- generation_pipeline.py: 生成 + 后处理管线
- post_send_handler.py: 发送后收尾（清 pending / 通知服务 / 日记 / 清推迟提醒）

兼容委托层（2026-09-19）：原先留在门面上的 26 个纯转发方法已整体迁入
- executor_compat.py: 兼容入口 + 外部委托方法（以 mixin 方式混入，对外仍可见）

本文件保留 ActiveCareExecutor 类作为门面，实例化上述模块并编排调用：
`trigger_message_with_result` 只保留编排职责（重叠保护 → 准备 → 生成 →
纠偏 → 分发 → 收尾 → 失败回退）。
"""

import time
from typing import Any, Dict, Optional

from config.integrated_config import get_settings
from core.llm.llm_logger import _is_log_full_prompt
from core.utils.logger import get_module_logger
from core.services.active_care.core.executor_compat import ActiveCareCompatMixin
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

# 本文件进一步拆分出的子模块
from core.services.active_care.core.overlap_guard import OverlapGuard
from core.services.active_care.core.morning_pending import MorningPendingInjector
from core.services.active_care.core.trigger_preparer import TriggerPreparer
from core.services.active_care.core.generation_pipeline import GenerationPipeline
from core.services.active_care.core.post_send_handler import PostSendHandler
from core.services.active_care.postprocess.send_content_corrector import (
    SendContentCorrector,
)

logger = get_module_logger("ACTIVE_CARE_EXECUTOR", "active_care_schedule.log")
msg_logger = get_module_logger("ACTIVE_CARE_MSG", "active_care_messages.log")


class ActiveCareExecutor(ActiveCareCompatMixin):
    """Active Care 执行器（门面），负责生成和发送主动关怀消息

    通过组合 6 个子模块实现单一职责，外部 API 完全兼容。
    兼容入口与委托方法来自 ActiveCareCompatMixin，本类只保留编排逻辑。
    """

    def __init__(self, context, storage):
        self.settings = get_settings()
        self.context = context
        self.storage = storage
        self.consecutive_non_responses: Dict[
            str, int
        ] = {}  # per-persona 非响应计数，空字符串key为单QQ兼容
        self.persona_resolver = PersonaResolver(storage)
        self.qq_connection_resolver = QQConnectionResolver()
        self.response_generator = ActiveCareResponseGenerator(self.settings)
        self.hardware_intent_resolver = ActiveCareHardwareIntentResolver()
        self.postprocessor = ActiveCarePostprocessor()
        self.state_persistence = StatePersistence(storage)
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
        # 本文件进一步拆分出的子模块
        self._overlap_guard = OverlapGuard(self.settings)
        self._morning_pending = MorningPendingInjector()
        self._content_corrector = SendContentCorrector()
        # 核心调度三段：准备 / 生成 / 收尾
        self._trigger_preparer = TriggerPreparer(self)
        self._generation_pipeline = GenerationPipeline(self)
        self._post_send_handler = PostSendHandler(self)

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
        self._overlap_guard.record_skip(result.is_interval_blocked, result.legacy_skip_reason)
        return result.delivered

    @staticmethod
    def _is_active_care_enabled_persona(persona_filename: str) -> bool:
        """persona 是否在主动消息角色白名单内。

        权威源是 core/character/runtime_roles.py（读 character_runtime.yaml 的
        autonomous_roles，缺失时回退 app.yaml 的 life_simulation.active_care_enabled_roles）。
        历史上这里尝试从 sleep_manager 导入 _ACTIVE_CARE_ENABLED_ROLES，该常量早已不存在，
        导入必然失败，于是永远走硬编码兜底、配置里新增角色也不生效；现在改为读权威源，
        读不到时才保留原来的三角色兜底。
        """
        from core.services.active_care.shared.text_utils import normalize_persona_token

        token = normalize_persona_token(persona_filename)
        if token.startswith("core_"):
            token = token[len("core_") :]
        role_id = token.split("_", 1)[0].strip().lower()
        if not role_id:
            return True
        try:
            from core.character.runtime_roles import get_autonomous_role_ids

            return role_id in get_autonomous_role_ids()
        except Exception:  # noqa: BLE001
            return role_id in {"aveline", "ling", "ye"}

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

        # 角色白名单：只允许接入 active_care 的角色主动发消息（安卓端目前只
        # 注册了 Aveline/Ling/Ye）。晚安/早安在 SleepManager 已过滤，但常规
        # checker 触发、回归消息等路径都会汇聚到本入口，在这里统一兜底，
        # 避免未注册角色的消息被补投到用户收不到的客户端。
        if persona_filename and not self._is_active_care_enabled_persona(persona_filename):
            logger.info(
                "Active Care: 角色 %s 未接入白名单，跳过主动消息 (%s)",
                persona_filename,
                sys_prompt_type,
            )
            return TriggerMessageResult(
                delivered=False,
                outcome=TriggerOutcome.ROLE_NOT_ENABLED,
                detail=f"persona {persona_filename} 不在 active_care_enabled_roles",
            )

        # 按 persona 独立追踪重叠保护
        persona_key = str(persona_filename or "").strip()
        if not self._check_overlap_guard(sys_prompt_type, now, persona_key=persona_key):
            return TriggerMessageResult(
                delivered=False,
                outcome=TriggerOutcome.OVERLAP_BLOCKED,
            )

        attempt_trigger_ts = now
        self._overlap_guard.record_attempt(persona_key, now)
        msg_logger.info(
            "Active Care EXECUTE -> Intent: %s | Content: %s...",
            sys_prompt_type,
            user_input_mock[:30],
        )

        delivered = False

        # 前置准备：会话路由 → 早安 pending 注入 → 历史/上下文 → Prompt
        prepared = await self._trigger_preparer.prepare(
            sys_prompt_type=sys_prompt_type,
            user_input_mock=user_input_mock,
            reminder_msg=reminder_msg,
            thought=thought,
            device_context=device_context,
            client_type=client_type,
            specific_instruction=specific_instruction,
            persona_filename=persona_filename,
            now=now,
        )

        if _is_log_full_prompt():
            msg_logger.info(
                "Active Care Prompt Breakdown:\n%s",
                prepared.prompt_result.format_breakdown(),
            )
        effective_client_type = str(client_type or "").strip().lower()

        try:
            from core.core_engine.service_singletons import get_aveline_service

            aveline_service = get_aveline_service()
            if aveline_service is None:
                raise RuntimeError("AvelineService could not be initialized")

            post_processed = await self._generation_pipeline.generate_and_postprocess(
                aveline_service=aveline_service,
                sys_prompt_type=sys_prompt_type,
                reply_text=reply_text,
                thought=thought,
                context=prepared.context,
                sys_prompt=prepared.sys_prompt,
                model_user_input=prepared.model_user_input,
                target_conversation_id=prepared.target_conversation_id,
                now=now,
                dynamic_prompt=prepared.dynamic_prompt,
                persona_filename=persona_filename,
            )
            if not post_processed:
                return TriggerMessageResult(
                    delivered=False,
                    outcome=TriggerOutcome.GENERATION_FAILED,
                )

            # Prompt 中的日历锚点是软约束，模型仍可能沿用历史里的错误相对日期。
            # 所有 Active Care 文案在发送前都做确定性事实纠正，但不改变 MDP 动作。
            # 到期提醒/词汇任务为硬目标事件，同样在发送前纠偏。
            # 上述逻辑统一收敛到 SendContentCorrector（send_content_corrector.py）。
            self._content_corrector.correct(
                post_processed,
                sys_prompt_type=sys_prompt_type,
                reminder_msg=reminder_msg,
                now_dt=prepared.now_dt,
            )

            delivered = await self._message_dispatcher.dispatch_message(
                aveline_service,
                post_processed,
                sys_prompt_type,
                device_context,
                prepared.target_conversation_id,
                prepared.original_conversation_id,
                effective_client_type,
                prepared.requested_client_type,
                thought,
                prepared.context,
                now,
                prepared.now_dt,
                planned_topic=planned_topic,
                self_activity=self_activity,
                persona_filename=persona_filename,
            )

            # 发送后收尾（清 pending / 通知服务 / 日记 / 清推迟提醒）
            if delivered:
                await self._post_send_handler.on_delivered(
                    target_conversation_id=prepared.target_conversation_id,
                    morning_pending_injected=prepared.morning_pending_injected,
                    now=now,
                    persona_filename=persona_filename,
                )

            await self._post_send_handler.write_diary(
                sys_prompt_type, post_processed.get("content", ""), thought=thought
            )
            msg_logger.info("Active Care: 已发送 %s 消息并记录日记", sys_prompt_type)

            if delivered and prepared.prompt_result.has_deferred_reminders:
                await self._post_send_handler.clear_deferred_reminders(persona_filename)

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
                self._overlap_guard.rollback_on_failure(
                    attempt_trigger_ts, persona_key, sys_prompt_type
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
        proactive_assignment_mode: bool = False,
        aveline_state: str = "",
        ling_state: str = "",
        role_states: Optional[Dict[str, str]] = None,
        avoid: Optional[list] = None,
    ) -> bool:
        """生成双角色互聊剧本并分发（委托给 PeerScriptGenerator，逻辑拆分至 peer_script_generator.py）

        完整 5 阶段流水线：
        1. _load_peer_config: 加载双QQ配置
        2. _gather_peer_context: 拉取历史/时间/生理状态
        3. _generate_script_llm: LLM 生成剧本（含回退+重试+过滤）
        4. _dispatch_script: 分发到各自QQ
        5. _run_peer_post_hooks: 后处理（日记/事件/巡检/历史/mention）

        留在门面：test_error_20260909_regressions.py 用 AST 静态校验本方法的参数转发契约。
        """
        return await self._peer_script_gen.generate_peer_script(
            role_id=role_id,
            peer_qq_id=peer_qq_id,
            topic=topic,
            situation=situation,
            opening_idea=opening_idea,
            persona_filename=persona_filename,
            negotiation_reminders=negotiation_reminders,
            proactive_assignment_mode=proactive_assignment_mode,
            aveline_state=aveline_state,
            ling_state=ling_state,
            role_states=role_states,
            avoid=avoid,
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
