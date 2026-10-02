"""Active Care 发送后收尾（清 pending / 通知服务 / 写日记 / 清推迟提醒）

从 `executor.py` 的 `trigger_message_with_result` 内联块拆分。

发送成功后要做的四件事原本散落在调度方法尾部，且三处都各自包了一层
try/except 吞异常，导致"到底收尾了没有"无法一眼看全。收拢到本模块后，
调度主干只剩三次显式调用，收尾失败的影响面（只记日志、不影响 delivered）
集中在一处可审查。
"""

from typing import List, Optional

from core.utils.logger import get_module_logger

logger = get_module_logger("ACTIVE_CARE_EXECUTOR", "active_care_schedule.log")
msg_logger = get_module_logger("ACTIVE_CARE_MSG", "active_care_messages.log")


class PostSendHandler:
    """发送后收尾处理器

    构造器接收 executor 门面实例，通过它访问 storage 与 message_dispatcher。
    """

    def __init__(self, executor):
        self._executor = executor

    async def on_delivered(
        self,
        *,
        target_conversation_id: str,
        morning_pending_injected: List[str],
        now: float,
        persona_filename: str = "",
    ) -> None:
        """消息已送达时的收尾：清空早安 pending + 通知服务更新间隔保护。"""
        executor = self._executor

        # 早安注入的 pending 已被主动消息回应，清空避免被动回复重复注入
        await executor._morning_pending.clear_if_injected(
            target_conversation_id, morning_pending_injected
        )

        try:
            from core.services.active_care.core.service import get_active_care_service

            svc = get_active_care_service()
            if svc:
                await svc.on_assistant_message_sent(
                    timestamp=now, persona_filename=persona_filename
                )
        except Exception as notify_err:
            msg_logger.warning(
                "Active Care: 通知 on_assistant_message_sent 失败: %s", notify_err
            )

    async def write_diary(
        self,
        sys_prompt_type: str,
        content: str,
        thought: Optional[str] = None,
    ) -> None:
        """记录主动消息日记（无论是否送达都记录，便于排查"生成了但没发出"）。"""
        executor = self._executor
        await executor._message_dispatcher.write_diary_entry(
            sys_prompt_type, content, thought=thought
        )

    async def clear_deferred_reminders(self, persona_filename: str = "") -> None:
        """清除推迟提醒列表，避免下次重复注入（仅在确实包含推迟提醒时调用）。"""
        executor = self._executor
        try:
            resolved_scope = None
            if persona_filename:
                resolved_scope = executor.storage.resolve_scope_from_persona_filename(
                    persona_filename
                )
            await executor.storage.save_proactive_state(
                {"deferred_plan_reminders": []},
                scope=resolved_scope or None,
            )
            msg_logger.info("Active Care: 已清除推迟提醒列表")
        except Exception as clear_err:
            msg_logger.warning("Active Care: 清除推迟提醒列表失败: %s", clear_err)


__all__ = ["PostSendHandler"]
