"""主动关怀 Prompt 构建兼容门面。"""
# ruff: noqa: F401, F403

from datetime import datetime

from config.integrated_config import get_settings
from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import *
from core.agents.chat_agent_components.persona_system.prompt.fixed_prefix import (
    get_fixed_prefix,
    strip_fixed_prefix,
)
from core.agents.chat_agent_components.persona_system.prompt.sensitive_prefix import (
    select_sensitive_prefix,
)
from core.agents.chat_agent_components.persona_system.prompt import (
    get_authoritative_calendar_prompt,
    get_special_day_prompt,
    get_upcoming_birthday_prompt,
)
from core.services.active_care.prompt.topic_diversity import build_topic_diversity_constraint
from core.services.active_care.shared.tuning import LONG_SILENCE_THRESHOLD_SECONDS
from core.services.active_care.prompt.sections.persona_reminders import (
    _build_other_persona_reminders_text,
)
from core.services.active_care.prompt.sections.assembly import build_active_care_prompt
from core.services.active_care.prompt.sections.constraints import (
    NON_STUDY_ACTIVITY_CATEGORIES,
    NO_INTERROGATION_EXEMPT_TYPES,
    _ACTIVITY_TEXT_MAP,
    _STUDY_TOPIC_ALLOWED_TYPES,
    _build_context_guard,
    _build_continuation_guard,
    _build_dedup_constraint,
    _build_no_interrogation_constraint,
    _build_out_of_context_guard,
    _build_temporal_anchor,
)
from core.services.active_care.prompt.prompt_context_builders import (
    _build_bio_context_text,
    _build_device_context_text,
    _build_food_context_text,
    _build_health_reminder_prompt,
    _build_persona_active_care_examples,
    _build_persona_active_care_style,
    _build_study_context_text,
    _build_today_plan_text,
    build_deferred_reminders_text,
    extract_known_sleep_time_fact,
)
from core.services.active_care.prompt.sections.filtering import (
    POKE_RULE_TYPES,
    _CHAT_CONTEXT_SECTIONS,
    _DYNAMIC_ALWAYS_SECTIONS,
    _DYNAMIC_SECTION_PRIORITY,
    _DYNAMIC_TASK_OPTIONAL,
    _SECTION_KEYWORDS,
    _filter_dynamic_sections,
    _is_poke_type,
    _section_keyword_match,
    _sort_dynamic_sections,
)
from core.services.active_care.prompt.sections.models import (
    ActiveCarePromptBuildResult,
    PromptSection,
)
from core.services.active_care.prompt.sections.tasks import (
    _build_task_block_dynamic,
    _get_auto_heal_brief,
)

__all__ = [
    "ActiveCarePromptBuildResult",
    "NON_STUDY_ACTIVITY_CATEGORIES",
    "NO_INTERROGATION_EXEMPT_TYPES",
    "POKE_RULE_TYPES",
    "PromptSection",
    "_ACTIVITY_TEXT_MAP",
    "_CHAT_CONTEXT_SECTIONS",
    "_DYNAMIC_ALWAYS_SECTIONS",
    "_DYNAMIC_SECTION_PRIORITY",
    "_DYNAMIC_TASK_OPTIONAL",
    "_SECTION_KEYWORDS",
    "_STUDY_TOPIC_ALLOWED_TYPES",
    "_build_bio_context_text",
    "_build_context_guard",
    "_build_continuation_guard",
    "_build_dedup_constraint",
    "_build_device_context_text",
    "_build_food_context_text",
    "_build_health_reminder_prompt",
    "_build_no_interrogation_constraint",
    "_build_other_persona_reminders_text",
    "_build_out_of_context_guard",
    "_build_persona_active_care_examples",
    "_build_persona_active_care_style",
    "_build_study_context_text",
    "_build_task_block_dynamic",
    "_build_temporal_anchor",
    "_build_today_plan_text",
    "_filter_dynamic_sections",
    "_get_auto_heal_brief",
    "_is_poke_type",
    "_section_keyword_match",
    "_sort_dynamic_sections",
    "build_active_care_prompt",
    "build_deferred_reminders_text",
    "extract_known_sleep_time_fact",
    "get_authoritative_calendar_prompt",
    "get_fixed_prefix",
    "get_special_day_prompt",
    "get_upcoming_birthday_prompt",
    "select_sensitive_prefix",
    "strip_fixed_prefix",
]
