"""
Prompt 系统模块

所有 prompt 相关的东西都放在这里
"""
from .assembler import (
    build_persona_prompt,
    build_persona_prompt_split,
    build_complete_message_list,
)
from .components import (
    build_time_context,
    build_emotion_context,
    build_bionic_state,
    build_food_context,
    build_study_context,
    build_detailed_persona,
)
from .data import (
    get_prompt_data,
    get_template_data,
    get_persona_name_from_filename,
    is_bionic_character,
    get_cached_bionic_state,
)
from .mode_control import (
    determine_mode,
    check_sensitive_mode,
    get_contrastive_prompting_injection,
    get_style_guard,
    get_natural_dialogue_policy,
)
from .qq_integration import (
    get_qq_master_id,
    extract_qq_user_id,
    apply_qq_optimizations,
    load_public_qq_prompt_template,
)
from .user_identification import (
    resolve_user_name,
    resolve_user_name_from_persona_logic,
)
from .context_gathering import (
    get_context_injection,
    prepare_emotion_context,
    prepare_life_stats,
    determine_model_info,
    build_food_context_text,
    get_instruction_injection,
    get_study_folder_history_injection,
)
from .dialogue_examples import (
    get_dialogue_examples,
    tokenize_for_example_rank,
)
from .special_days import (
    correct_relative_holiday_claims,
    get_authoritative_calendar_prompt,
    get_special_day_prompt,
    get_upcoming_birthday_prompt,
    remove_invalid_relative_holiday_clauses,
)
from .qq_peer_context import build_qq_peer_role_context

__all__ = [
    "build_persona_prompt",
    "build_persona_prompt_split",
    "build_complete_message_list",
    "build_time_context",
    "build_emotion_context",
    "build_bionic_state",
    "build_food_context",
    "build_study_context",
    "build_detailed_persona",
    "get_prompt_data",
    "get_template_data",
    "get_persona_name_from_filename",
    "is_bionic_character",
    "get_cached_bionic_state",
    "determine_mode",
    "check_sensitive_mode",
    "get_contrastive_prompting_injection",
    "get_style_guard",
    "get_natural_dialogue_policy",
    "get_qq_master_id",
    "extract_qq_user_id",
    "apply_qq_optimizations",
    "load_public_qq_prompt_template",
    "resolve_user_name",
    "resolve_user_name_from_persona_logic",
    "get_context_injection",
    "prepare_emotion_context",
    "prepare_life_stats",
    "determine_model_info",
    "build_food_context_text",
    "get_instruction_injection",
    "get_study_folder_history_injection",
    "get_dialogue_examples",
    "tokenize_for_example_rank",
    "get_special_day_prompt",
    "correct_relative_holiday_claims",
    "remove_invalid_relative_holiday_clauses",
    "get_authoritative_calendar_prompt",
    "get_upcoming_birthday_prompt",
    "build_qq_peer_role_context",
    "get_dynamic_system_prompt",
    "build_expanded_persona_prompt",
]


def get_dynamic_system_prompt(*args, **kwargs) -> str:
    """
    兼容接口 - 获取动态系统 prompt
    """
    return build_persona_prompt(*args, **kwargs)


def build_expanded_persona_prompt(*args, **kwargs) -> str:
    """
    兼容接口 - 构建扩展的 persona prompt
    """
    template, persona_data = get_template_data(*args, **kwargs)
    detailed = build_detailed_persona(persona_data)
    from .assembler import _merge_template_and_persona
    return _merge_template_and_persona(template, detailed)
