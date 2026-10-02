"""主动关怀动态 Prompt section 的白名单、关键词门控与排序。"""

from __future__ import annotations

from typing import Dict, List, Tuple

from core.services.active_care.prompt.sections.models import PromptSection

POKE_RULE_TYPES = frozenset(
    {
        "proactive_chat",
        "curious_question",
        "share_thought",
        "emotional_support",
        "gossip_share",
        "weather_complaint",
        "share_peer_chat",
        "planned_topic",
        "checking",
    }
)
_DYNAMIC_ALWAYS_SECTIONS = frozenset(
    {
        "persona_dynamic_prompt",
        "combined_status_text",
        "temporal_anchor",
        "dedup_constraint",
        "task_block_dynamic",
        "role_task_examples",
        "recent_history_text",
        "device_context_text",
        "no_interrogation",
        "short_poke_rules",
    }
)
_CHAT_CONTEXT_SECTIONS = frozenset(
    {
        "tone_reference_text",
        "health_reminder_prompt",
        "context_guard",
        "continuation_guard",
        "role_activity_anchor",
        "out_of_context_guard",
        "topic_diversity",
        "authoritative_calendar",
        "tomorrow_tone",
        "today_plan",
        "study_context_text",
        "deferred_reminders",
        "other_persona_reminders",
        "special_days",
        "upcoming_birthdays",
    }
)
_DYNAMIC_TASK_OPTIONAL: Dict[str, frozenset] = {
    task: _CHAT_CONTEXT_SECTIONS
    for task in (
        "proactive_chat",
        "curious_question",
        "share_thought",
        "emotional_support",
        "gossip_share",
        "weather_complaint",
        "share_peer_chat",
        "planned_topic",
        "checking",
    )
}
_DYNAMIC_TASK_OPTIONAL.update(
    {
        "reminder": frozenset(
            {
                "context_guard",
                "continuation_guard",
                "out_of_context_guard",
                "today_plan",
                "deferred_reminders",
                "other_persona_reminders",
                "authoritative_calendar",
                "special_days",
            }
        ),
        "wake_up_greeting": frozenset(
            {
                "special_days",
                "upcoming_birthdays",
                "authoritative_calendar",
                "tomorrow_tone",
                "today_plan",
                "tone_reference_text",
            }
        ),
        "good_morning_proactive": frozenset(
            {
                "special_days",
                "upcoming_birthdays",
                "authoritative_calendar",
                "tomorrow_tone",
                "today_plan",
                "tone_reference_text",
            }
        ),
        "morning_report": frozenset(
            {
                "special_days",
                "upcoming_birthdays",
                "authoritative_calendar",
                "tomorrow_tone",
                "today_plan",
                "tone_reference_text",
                "deferred_reminders",
            }
        ),
        "bio_complaint": frozenset({"bio_context_text", "authoritative_calendar"}),
        "user_health_reminder": frozenset(
            {
                "bio_context_text",
                "food_context_text",
                "authoritative_calendar",
                "out_of_context_guard",
            }
        ),
        "notification_assistant": frozenset(
            {"authoritative_calendar", "tone_reference_text", "out_of_context_guard"}
        ),
        "usage_limit_exceeded": frozenset(
            {"authoritative_calendar", "out_of_context_guard"}
        ),
        "insomnia": frozenset(
            {"authoritative_calendar", "tone_reference_text", "goodnight_but_awake_context"}
        ),
        "goodnight_proactive": frozenset({"authoritative_calendar"}),
        "sleep_again_proactive": frozenset({"authoritative_calendar"}),
        "activity_return_proactive": frozenset(
            {"authoritative_calendar", "tone_reference_text", "role_activity_anchor"}
        ),
        "focus_nudge": frozenset({"authoritative_calendar", "out_of_context_guard"}),
    }
)
_SECTION_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "authoritative_calendar": (
        "周",
        "星期",
        "明天",
        "后天",
        "今天几号",
        "日历",
        "安排",
        "几号",
        "日期",
        "节日",
        "生日",
        "放假",
        "计划",
        "时间",
    ),
    "today_plan": (
        "计划",
        "安排",
        "学习",
        "复习",
        "健身",
        "开会",
        "上班",
        "上课",
        "任务",
        "作业",
        "论文",
        "实验",
        "考试",
        "考研",
    ),
    "tomorrow_tone": ("明天", "明日", "安排", "计划", "行程", "基调"),
    "study_context_text": ("学习", "复习", "考研", "考试", "作业", "论文", "实验", "读书"),
}
_DYNAMIC_SECTION_PRIORITY = {
    **{
        name: 1
        for name in (
            "combined_status_text",
            "goodnight_but_awake_context",
            "bio_context_text",
            "food_context_text",
            "study_context_text",
            "device_context_text",
            "special_days",
            "upcoming_birthdays",
        )
    },
    "task_block_dynamic": 2,
    "health_reminder_prompt": 2,
    **{
        name: 3
        for name in (
            "context_guard",
            "continuation_guard",
            "recent_history_text",
            "out_of_context_guard",
            "no_interrogation",
            "role_activity_anchor",
            "dedup_constraint",
            "temporal_anchor",
            "authoritative_calendar",
            "today_plan",
            "deferred_reminders",
            "other_persona_reminders",
        )
    },
    "persona_dynamic_prompt": 4,
    "tone_reference_text": 4,
    "tomorrow_tone": 4,
    "short_poke_rules": 5,
    "topic_diversity": 5,
    "role_task_examples": 6,
}


def _is_poke_type(sys_prompt_type: str) -> bool:
    prompt_type = str(sys_prompt_type or "").strip()
    if prompt_type.endswith("_safe"):
        prompt_type = prompt_type[: -len("_safe")]
    return prompt_type in POKE_RULE_TYPES


def _section_keyword_match(query_text: str, keywords: Tuple[str, ...]) -> bool:
    normalized = str(query_text or "").lower()
    return not keywords or any(keyword in normalized for keyword in keywords)


def _filter_dynamic_sections(
    sys_prompt_type: str,
    sections: List[PromptSection],
    query_text: str = "",
) -> List[PromptSection]:
    allowed_optional = _DYNAMIC_TASK_OPTIONAL.get(str(sys_prompt_type or "").strip())
    if allowed_optional is None:
        return sections
    is_free_chat = allowed_optional == _CHAT_CONTEXT_SECTIONS
    filtered = []
    for section in sections:
        if section.name not in _DYNAMIC_ALWAYS_SECTIONS and section.name not in allowed_optional:
            continue
        keywords = _SECTION_KEYWORDS.get(section.name)
        if is_free_chat and keywords is not None and str(query_text or "").strip():
            if not _section_keyword_match(query_text, keywords):
                continue
        filtered.append(section)
    return filtered


def _sort_dynamic_sections(sections: List[PromptSection]) -> List[PromptSection]:
    return sorted(sections, key=lambda section: _DYNAMIC_SECTION_PRIORITY.get(section.name, 3))
