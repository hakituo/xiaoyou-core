"""主动关怀 Prompt 的静态/动态 section 装配。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from config.integrated_config import get_settings
from core.agents.chat_agent_components.persona_system.prompt import active_care_prompts as prompts
from core.services.active_care.prompt.sections.constraints import NON_STUDY_ACTIVITY_CATEGORIES
from core.services.active_care.prompt.sections.composer import (
    append_optional_sections,
    build_role_activity_anchor,
    build_static_sections,
    resolve_care_role_id,
)
from core.services.active_care.prompt.sections.models import (
    ActiveCarePromptBuildResult,
    PromptSection,
)
from core.services.active_care.prompt.topic_diversity import build_topic_diversity_constraint
from core.services.active_care.shared.tuning import LONG_SILENCE_THRESHOLD_SECONDS


def _compat_module():
    from core.services.active_care.prompt import prompt_builder

    return prompt_builder


def build_active_care_prompt(
    *,
    user_id: Optional[str] = None,
    sys_prompt_type: str,
    user_input_mock: str,
    reminder_msg: Optional[str],
    thought: Optional[str],
    tod: str,
    now: float,
    user_display_name: str,
    persona_prompt: str,
    recent_history_text: str,
    persona_dynamic_prompt: str = "",
    tone_reference_text: str = "",
    sleep_context_text: str = "",
    mode_status_text: str = "",
    goodnight_but_awake_context: str = "",
    preferred_language: str = "auto",
    device_context: Optional[Dict[str, Any]] = None,
    client_type: Optional[str] = None,
    elapsed_seconds: float = 0.0,
    persona_filename: str = "",
    persona_name: str = "",
    last_sent_ts: float = 0.0,
    last_user_ts: float = 0.0,
    last_proactive_assistant_message: str = "",
    last_assistant_message: str = "",
    proactive_state: Optional[Dict[str, Any]] = None,
    repeat_anchors: Optional[List[str]] = None,
    tomorrow_tone: str = "",
    specific_instruction: Optional[str] = None,
    role_activity_text: str = "",
    user_activity: Optional[Dict[str, Any]] = None,
    sleep_session_active: bool = False,
    morning_report_items: str = "",
) -> ActiveCarePromptBuildResult:
    _ = get_settings(), user_display_name
    compat = _compat_module()
    device_context_text, _is_mobile = compat._build_device_context_text(
        now, device_context, client_type
    )
    bio_context_text = compat._build_bio_context_text(user_id)
    food_context_text = compat._build_food_context_text()
    study_context_text = compat._build_study_context_text()
    language = str(preferred_language or "").strip().lower()
    is_long_silence = elapsed_seconds >= LONG_SILENCE_THRESHOLD_SECONDS
    context_guard = compat._build_context_guard(is_long_silence)
    continuation_guard = compat._build_continuation_guard(
        language, recent_history_text, is_long_silence
    )
    if sys_prompt_type == "usage_limit_exceeded":
        context_guard = ""
        continuation_guard = ""

    style_enforcement = prompts.STYLE_ENFORCEMENT_TEMPLATE
    persona_style = compat._build_persona_active_care_style(
        persona_prompt=persona_prompt,
        persona_filename=persona_filename,
        persona_name=persona_name,
    )
    if persona_style:
        style_enforcement += "\n" + persona_style + "\n"
    role_task_examples = compat._build_persona_active_care_examples(
        sys_prompt_type=sys_prompt_type,
        persona_filename=persona_filename,
        persona_name=persona_name,
    )
    task_block = compat._build_task_block_dynamic(
        sys_prompt_type,
        tod,
        user_input_mock,
        reminder_msg,
        thought,
        specific_instruction=specific_instruction,
        sleep_session_active=sleep_session_active,
        morning_report_items=morning_report_items,
    )
    poke_rules = ""
    if compat._is_poke_type(sys_prompt_type):
        poke_rules = (
            prompts.PROACTIVE_SHORT_POKE_RULES
            + prompts.PROACTIVE_SHORT_POKE_EXAMPLES
            + prompts.DIRECT_ASK_ALLOWED
        )

    include_bio = sys_prompt_type in {
        "bio_complaint",
        "user_health_reminder",
        "reminder",
        "morning_report",
    }
    out_of_context_guard = compat._build_out_of_context_guard(user_activity, sys_prompt_type)
    activity_category = (
        str(user_activity.get("category") or "").strip().lower()
        if isinstance(user_activity, dict)
        else ""
    )
    user_off_study = activity_category in NON_STUDY_ACTIVITY_CATEGORIES
    include_study = sys_prompt_type in {
        "planned_topic",
        "curious_question",
        "share_peer_chat",
        "reminder",
        "morning_report",
    } and not user_off_study

    combined_status_text = str(mode_status_text or "")
    if str(sleep_context_text or "").strip():
        combined_status_text += sleep_context_text
    role_activity_anchor = build_role_activity_anchor(role_activity_text)

    temporal_anchor = compat._build_temporal_anchor(now, last_sent_ts, last_user_ts)
    isolate_previous_style = sys_prompt_type == "good_morning_proactive"
    dedup_constraint = (
        ""
        if isolate_previous_style
        else compat._build_dedup_constraint(
            last_proactive_assistant_message,
            last_assistant_message,
            repeat_anchors=repeat_anchors,
        )
    )
    topic_diversity = ""
    if proactive_state:
        candidate = str(last_proactive_assistant_message or last_assistant_message or "")
        topic_diversity = build_topic_diversity_constraint(proactive_state, candidate)

    static_sections = build_static_sections(
        persona_prompt,
        persona_filename,
        style_enforcement,
    )

    role_id = resolve_care_role_id(persona_filename, persona_name)
    dynamic_sections = [
        PromptSection("persona_dynamic_prompt", persona_dynamic_prompt),
        PromptSection("tone_reference_text", tone_reference_text),
        PromptSection("special_days", compat.get_special_day_prompt(role_id=role_id)),
        PromptSection(
            "upcoming_birthdays", compat.get_upcoming_birthday_prompt(role_id=role_id)
        ),
        PromptSection(
            "health_reminder_prompt", compat._build_health_reminder_prompt(sys_prompt_type)
        ),
        PromptSection("context_guard", context_guard),
        PromptSection("continuation_guard", continuation_guard),
        PromptSection("goodnight_but_awake_context", goodnight_but_awake_context),
        PromptSection("bio_context_text", bio_context_text if include_bio else ""),
        PromptSection("food_context_text", food_context_text if include_bio else ""),
        PromptSection("study_context_text", study_context_text if include_study else ""),
        PromptSection("combined_status_text", combined_status_text),
        PromptSection("device_context_text", device_context_text),
        PromptSection(
            "recent_history_text",
            ""
            if sys_prompt_type == "usage_limit_exceeded" or isolate_previous_style
            else recent_history_text,
        ),
        PromptSection("task_block_dynamic", task_block),
        PromptSection("role_task_examples", role_task_examples),
        PromptSection("role_activity_anchor", role_activity_anchor),
        PromptSection(
            "no_interrogation", compat._build_no_interrogation_constraint(sys_prompt_type)
        ),
        PromptSection("short_poke_rules", poke_rules),
        PromptSection("out_of_context_guard", out_of_context_guard),
        PromptSection("temporal_anchor", temporal_anchor),
        PromptSection("dedup_constraint", dedup_constraint),
        PromptSection("topic_diversity", topic_diversity),
        PromptSection("authoritative_calendar", compat.get_authoritative_calendar_prompt()),
    ]
    append_optional_sections(
        dynamic_sections,
        tomorrow_tone=tomorrow_tone,
        user_off_study=user_off_study,
        proactive_state=proactive_state,
        persona_filename=persona_filename,
    )

    query_text = " ".join(
        filter(None, [recent_history_text, user_input_mock, specific_instruction or ""])
    )
    dynamic_sections = compat._filter_dynamic_sections(
        sys_prompt_type, compat._sort_dynamic_sections(dynamic_sections), query_text
    )
    all_sections = static_sections + dynamic_sections
    static_prompt = "".join(
        section.content for section in static_sections if (section.content or "").strip()
    ).strip()
    dynamic_prompt = "".join(
        section.content for section in dynamic_sections if (section.content or "").strip()
    ).strip()
    has_deferred = any(
        section.name == "deferred_reminders"
        for section in dynamic_sections
        if (section.content or "").strip()
    )
    return ActiveCarePromptBuildResult(
        prompt=static_prompt,
        sections=all_sections,
        dynamic_prompt=dynamic_prompt,
        has_deferred_reminders=has_deferred,
    )
