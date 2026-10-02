"""主动关怀 Prompt 的任务模板选择。"""

from __future__ import annotations

from typing import Optional

from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
    TASK_ACTIVITY_RETURN_PROACTIVE_TEMPLATE,
    TASK_FOCUS_NUDGE_TEMPLATE,
    TASK_GOOD_MORNING_PROACTIVE_TEMPLATE,
    TASK_GOOD_MORNING_SLEEP_SAFE_TEMPLATE,
    TASK_GOODNIGHT_PROACTIVE_TEMPLATE,
    TASK_INSOMNIA,
    TASK_MORNING_REPORT,
    TASK_NOTIFICATION_ASSISTANT,
    TASK_PLANNED_TOPIC_TEMPLATE,
    TASK_PROACTIVE_CHAT_TEMPLATE,
    TASK_REMINDER_TEMPLATE,
    TASK_SLEEP_AGAIN_PROACTIVE_TEMPLATE,
    TASK_SUPPRESSED_CHAT_TEMPLATE,
    TASK_USAGE_LIMIT_EXCEEDED_TEMPLATE,
    TASK_WAKE_UP_GREETING,
)


def _get_auto_heal_brief() -> str:
    try:
        from core.services.auto_heal.heal_service import get_auto_heal_service

        brief = get_auto_heal_service().get_morning_brief()
        if brief:
            return f"\n\n{brief}\n如果提到了bug修复，可以简单提一下，不用太详细。"
    except Exception:  # noqa: BLE001
        pass
    return ""


def _build_task_block_dynamic(
    sys_prompt_type: str,
    tod: str,
    user_input_mock: str,
    reminder_msg: Optional[str],
    thought: Optional[str],
    specific_instruction: Optional[str] = None,
    sleep_session_active: bool = False,
    morning_report_items: str = "",
) -> str:
    if sys_prompt_type == "reminder" and reminder_msg:
        return TASK_REMINDER_TEMPLATE.format(tod=tod, reminder_msg=reminder_msg)
    if sys_prompt_type == "planned_topic":
        thought_context = f"你的思考：{thought}\n" if thought else ""
        topic_text = (
            user_input_mock if user_input_mock != "[PLANNED_TRIGGER]" else "（根据你的思考自发开始）"
        )
        return TASK_PLANNED_TOPIC_TEMPLATE.format(
            tod=tod, thought_ctx=thought_context, topic_text=topic_text
        )
    if sys_prompt_type == "wake_up_greeting":
        return TASK_WAKE_UP_GREETING.format(tod=tod) + _get_auto_heal_brief()
    if sys_prompt_type == "morning_report":
        report_items = str(morning_report_items or "").strip() or (
            "（本次晨报没有已确认内容：请只自然问候，不自行补充天气/新闻/日程/健康数据）"
        )
        return TASK_MORNING_REPORT.format(tod=tod, report_items=report_items) + _get_auto_heal_brief()
    if sys_prompt_type == "notification_assistant":
        content = user_input_mock.replace("[NOTIFICATION_TRIGGER]:", "").strip()
        return TASK_NOTIFICATION_ASSISTANT.format(tod=tod, notification_content=content)
    if sys_prompt_type == "usage_limit_exceeded":
        event_context = str(specific_instruction or user_input_mock or "").strip()
        return TASK_USAGE_LIMIT_EXCEEDED_TEMPLATE.format(tod=tod, event_context=event_context)
    if sys_prompt_type == "insomnia":
        return TASK_INSOMNIA.format(tod=tod)
    if sys_prompt_type == "goodnight_proactive":
        return TASK_GOODNIGHT_PROACTIVE_TEMPLATE.format(tod=tod)
    if sys_prompt_type == "sleep_again_proactive":
        return TASK_SLEEP_AGAIN_PROACTIVE_TEMPLATE.format(tod=tod)
    if sys_prompt_type == "activity_return_proactive":
        return TASK_ACTIVITY_RETURN_PROACTIVE_TEMPLATE.format(tod=tod)
    if sys_prompt_type == "good_morning_proactive":
        specific_context = f"{specific_instruction}\n" if specific_instruction else ""
        template = (
            TASK_GOOD_MORNING_SLEEP_SAFE_TEMPLATE
            if sleep_session_active
            else TASK_GOOD_MORNING_PROACTIVE_TEMPLATE
        )
        return template.format(tod=tod) + specific_context
    if sys_prompt_type == "share_peer_chat":
        return TASK_PROACTIVE_CHAT_TEMPLATE.format(
            tod=tod,
            thought_ctx=f"你的思考：{thought}\n" if thought else "",
            specific_ctx=f"{specific_instruction}\n" if specific_instruction else "",
        )
    if sys_prompt_type == "focus_nudge" and reminder_msg:
        return TASK_FOCUS_NUDGE_TEMPLATE.format(tod=tod, nudge_msg=reminder_msg)

    thought_context = f"你的思考：{thought}\n" if thought else ""
    thought_lower = str(thought or "").lower()
    suppress_new_topic = any(
        keyword in thought_lower
        for keyword in ["稍后", "不应该", "不该", "打扰", "skip", "don't", "not now", "wait"]
    )
    template = TASK_SUPPRESSED_CHAT_TEMPLATE if suppress_new_topic else TASK_PROACTIVE_CHAT_TEMPLATE
    return template.format(
        tod=tod,
        thought_ctx=thought_context,
        specific_ctx=f"{specific_instruction}\n" if specific_instruction else "",
    )
