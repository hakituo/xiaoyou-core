"""Active Care 早安待处理消息注入器

职责：早安主动消息（good_morning_proactive）注入用户睡眠期间的待处理消息，
并在消息发送成功后清空 pending，避免早安完全不回应昨晚的消息。

从 executor.py 的 trigger_message_with_result 内联块拆分。
"""

from typing import List, Tuple

from core.utils.logger import get_module_logger

# 与 executor 主流程共用独立消息日志文件
msg_logger = get_module_logger("ACTIVE_CARE_MSG", "active_care_messages.log")


class MorningPendingInjector:
    """早安待处理消息注入器"""

    def inject(
        self,
        sys_prompt_type: str,
        target_conversation_id: str,
        specific_instruction: str | None,
    ) -> Tuple[str | None, List[str]]:
        """仅当早安类型时读取并注入 sleep 期间待处理消息

        角色醒来发早安时，如果用户昨晚发过消息被静默累积（pending），
        把这些消息注入 prompt 让角色能主动提及，发送成功后清空 pending，
        避免早安完全不回应昨晚的消息，用户感觉消息"石沉大海"。

        Args:
            target_conversation_id: 目标会话 ID
            specific_instruction: 原始指令（在其后追加注入提示）

        Returns:
            (new_specific_instruction, injected_msgs)
            - new_specific_instruction: 追加注入提示后的指令，未注入时返回原值
            - injected_msgs: 本次注入的消息列表（用于发送成功后清空判断）
        """
        if sys_prompt_type != "good_morning_proactive":
            return specific_instruction, []

        try:
            from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
                get_pending_messages,
            )

            injected = list(get_pending_messages(target_conversation_id))
            if not injected:
                return specific_instruction, []
            pending_block = "\n".join(
                f"{i}. {message}" for i, message in enumerate(injected, 1)
            )
            pending_hint = (
                "\n\n【用户在你睡觉期间发来的、你还没回的消息】\n"
                f"{pending_block}\n"
                "请在起床问候中自然地回应这些消息（可以提及内容、回应对方），"
                "不要假装没看到，但也不要逐条机械回复。"
            )
            msg_logger.info(
                "Active Care good_morning_proactive: 注入 %d 条睡眠期间待处理消息",
                len(injected),
            )
            return (specific_instruction or "") + pending_hint, injected
        except Exception as err:
            msg_logger.warning("读取早安 pending 消息失败: %s", err)
            return specific_instruction, []

    async def clear_if_injected(
        self, target_conversation_id: str, injected_msgs: List[str]
    ) -> None:
        """消息发送成功后清空早安注入的 pending

        Args:
            injected_msgs: 注入的消息列表，为空则跳过（未被注入时无需清空）
        """
        if not injected_msgs:
            return
        try:
            from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
                clear_pending_messages,
            )

            await clear_pending_messages(target_conversation_id)
            msg_logger.info(
                "Active Care good_morning_proactive: 已清空 %d 条待处理消息",
                len(injected_msgs),
            )
        except Exception as clear_err:
            msg_logger.warning("清空早安 pending 失败: %s", clear_err)