"""Active Care 触发前置准备（会话路由 → 早安注入 → 上下文 → Prompt）

从 `executor.py` 的 `trigger_message_with_result` 内联块拆分。

这四步是纯粹的"取数 + 组装"：只读取会话路由、历史、上下文与 Prompt 构建器，
不参与生成、后处理、分发和任何状态回写。单独成模块后，调度主干
（`trigger_message_with_result`）只剩编排，上下文来源的演进（例如替换历史
缓存策略、增删注入步骤）不再需要改动发送链路。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.utils.logger import get_module_logger
from core.utils.time_utils import get_current_time, get_time_period

logger = get_module_logger("ACTIVE_CARE_EXECUTOR", "active_care_schedule.log")


@dataclass
class PreparedTrigger:
    """一次 trigger_message 的前置准备结果（纯数据，便于单测与调试）。"""

    # 会话路由结果
    target_conversation_id: str
    original_conversation_id: str
    requested_client_type: str
    # 早安 pending 注入结果（发送成功后据此清空）
    morning_pending_injected: List[str] = field(default_factory=list)
    # 经过早安注入后的最终指令（Prompt 与发送前纠偏都要用这一份）
    specific_instruction: Optional[str] = None
    # 决策上下文（生成、后处理、分发共用）
    context: Dict[str, Any] = field(default_factory=dict)
    # Prompt 构建结果
    prompt_result: Any = None
    sys_prompt: str = ""
    dynamic_prompt: str = ""
    model_user_input: str = ""
    # 时刻信息（发送前纠偏与分发要用同一份，避免跨调用时间漂移）
    now_dt: Any = None
    tod: str = ""


class TriggerPreparer:
    """触发前置准备器

    构造器接收 executor 门面实例，通过它访问已拆分的协作子模块
    （conversation_router / context_builder / morning_pending）。
    """

    def __init__(self, executor):
        self._executor = executor

    async def prepare(
        self,
        *,
        sys_prompt_type: str,
        user_input_mock: str,
        reminder_msg: Optional[str],
        thought: Optional[str],
        device_context: Optional[Dict[str, Any]],
        client_type: Optional[str],
        specific_instruction: Optional[str],
        persona_filename: str,
        now: float,
    ) -> PreparedTrigger:
        """完成会话路由 → 早安注入 → 历史/上下文 → Prompt 四步准备。

        Args:
            persona_filename: 人设文件名，用于按 persona 解析目标会话
            now: 本次触发的时间戳（与后续分发共用同一时刻）

        Returns:
            PreparedTrigger: 后续生成/分发所需的全部前置产物
        """
        executor = self._executor
        now_dt = get_current_time()
        tod = get_time_period()

        target_conversation_id, original_conversation_id, requested_client_type = (
            await executor._conversation_router.resolve_target_conversation(
                client_type, persona_filename=persona_filename
            )
        )

        # 早安主动消息注入用户睡眠期间的待处理消息：
        # 角色醒来发早安时，如果用户昨晚发过消息被静默累积（pending），
        # 把这些消息注入 prompt 让角色能主动提及，发送成功后清空 pending，
        # 避免早安完全不回应昨晚的消息，用户感觉消息"石沉大海"。
        injected_instruction, morning_pending_injected = executor._morning_pending.inject(
            sys_prompt_type, target_conversation_id, specific_instruction
        )

        logger.info(
            "Active Care trigger_message: persona_filename=%s, target_cid=%s, original_cid=%s",
            persona_filename, target_conversation_id, original_conversation_id,
        )

        history_msgs = await executor._context_builder.get_history_with_cache(
            target_conversation_id, now
        )

        context = await executor._context_builder.build_trigger_context(
            history_msgs, target_conversation_id, now, now_dt, tod
        )

        prompt_result, model_user_input = executor._context_builder.build_prompt(
            context, sys_prompt_type, user_input_mock, reminder_msg,
            thought, device_context, client_type, injected_instruction,
        )

        return PreparedTrigger(
            target_conversation_id=target_conversation_id,
            original_conversation_id=original_conversation_id,
            requested_client_type=requested_client_type,
            morning_pending_injected=morning_pending_injected,
            specific_instruction=injected_instruction,
            context=context,
            prompt_result=prompt_result,
            sys_prompt=prompt_result.prompt,
            dynamic_prompt=prompt_result.dynamic_prompt,
            model_user_input=model_user_input,
            now_dt=now_dt,
            tod=tod,
        )


__all__ = ["PreparedTrigger", "TriggerPreparer"]
