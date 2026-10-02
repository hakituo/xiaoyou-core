"""Active Care 发送前内容修正

职责：在消息发送前，对生成结果做确定性的事实纠正，避免模型沿用错误日期/已过期目标。

覆盖 3 类修正（均不改变 MDP 动作，只改发送文案）：
1. 日历相对节日纠正（含无效断言清理）
2. 到期提醒目标强制（reminder / focus_nudge）
3. 词汇任务状态事实纠偏（提及词汇话题时）

数字健康（usage_limit_exceeded）不再做文案纠偏：原先的「拼应用名前缀 / 防声称
强退」兜底会产出「哔哩哔哩：B站快两小时了」这类系统通知式文案，与角色口吻冲突，
已移除，改为完全信任模型输出（prompt 内已约束不得声称设备执行结果）。

从 executor.py 的 trigger_message_with_result 内联块拆分。
"""

from core.agents.chat_agent_components.persona_system.prompt import (
    correct_relative_holiday_claims,
    remove_invalid_relative_holiday_clauses,
)
from core.utils.logger import get_module_logger

# 与 executor 主流程共用独立消息日志文件
msg_logger = get_module_logger("ACTIVE_CARE_MSG", "active_care_messages.log")


class SendContentCorrector:
    """发送前内容修正器：收敛各类确定性事实纠偏规则"""

    def correct(
        self,
        post_processed: dict,
        *,
        sys_prompt_type: str,
        reminder_msg: str | None,
        now_dt,
    ) -> dict:
        """按场景对发送前文案做确定性纠正

        Args:
            post_processed: 后处理结果 dict（含 content/tts_text/message_type 等）
            sys_prompt_type: 主动关怀类型
            reminder_msg: 到期提醒原文（reminder / focus_nudge 场景）
            now_dt: 当前时间（用于日历事实纠正的 check_date）

        Returns:
            修正后的 post_processed（原地修改）
        """
        # Prompt 中的日历锚点是软约束，模型仍可能沿用历史里的错误相对日期。
        # 所有 Active Care 文案在发送前都做确定性事实纠正，但不改变 MDP 动作。
        self._correct_calendar(post_processed, now_dt)

        # 到期提醒属于硬目标事件，不参与普通上下文话题漂移。
        if sys_prompt_type in ("reminder", "focus_nudge") and reminder_msg:
            self._enforce_reminder(post_processed, reminder_msg)

        # 昨日日记与聊天历史可能保留旧的词汇数量；最终发送前必须以
        # 当前取词队列和今日复习进度为准，避免完成后仍继续催促。
        self._enforce_vocabulary(post_processed)

        return post_processed

    def _correct_calendar(self, post_processed: dict, now_dt) -> None:
        """纠正错误的相对节日日期断言"""
        original_calendar_content = str(post_processed.get("content") or "").strip()
        corrected_calendar_content = correct_relative_holiday_claims(
            original_calendar_content,
            check_date=now_dt.date(),
        )
        if corrected_calendar_content == original_calendar_content:
            return
        sanitized_calendar_content = remove_invalid_relative_holiday_clauses(
            original_calendar_content,
            check_date=now_dt.date(),
        )
        # 若整条都建立在错误节日断言上，至少纠正事实；否则直接删掉
        # 错误短句，避免模型换成"后天七夕"后继续复读同一话题。
        final_calendar_content = sanitized_calendar_content or corrected_calendar_content
        msg_logger.warning(
            "Active Care: 发送前纠正错误相对节日日期。before=%s after=%s",
            original_calendar_content[:160],
            final_calendar_content[:160],
        )
        post_processed["content"] = final_calendar_content
        post_processed["tts_text"] = final_calendar_content

    def _enforce_reminder(self, post_processed: dict, reminder_msg: str) -> None:
        """强制到期提醒目标内容"""
        from core.services.active_care.core.reminder_handler import ReminderHandler

        original_content = str(post_processed.get("content") or "").strip()
        # enforce_reminder_target 为实例方法（不依赖 self），临时构造即可
        enforced_content = ReminderHandler().enforce_reminder_target(
            original_content,
            reminder_msg,
        )
        if enforced_content != original_content:
            post_processed["content"] = enforced_content
            post_processed["tts_text"] = enforced_content
            post_processed["message_type"] = "text"

    def _enforce_vocabulary(self, post_processed: dict) -> None:
        """词汇任务状态事实纠偏（仅当内容提及词汇话题时）"""
        from core.services.active_care.postprocess.event_target_guard import (
            enforce_vocabulary_status,
            mentions_vocabulary_topic,
        )

        original_vocab_content = str(post_processed.get("content") or "").strip()
        if not mentions_vocabulary_topic(original_vocab_content):
            return
        try:
            from core.tools.study.english.vocabulary_manager import (
                get_vocabulary_manager,
            )

            vocab_status = get_vocabulary_manager().get_today_review_status()
            enforced_vocab_content = enforce_vocabulary_status(
                original_vocab_content,
                vocab_status,
            )
            if enforced_vocab_content == original_vocab_content:
                return
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
