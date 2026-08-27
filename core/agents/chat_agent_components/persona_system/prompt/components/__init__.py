"""
Prompt 组件包

将原 components.py（1000+ 行）拆分为多个子模块，
通过此 __init__.py 统一 re-export，外部导入路径不变。
"""

# 时间相关
from .time_context import (
    build_time_context,
    build_conversation_gap_context,
    _format_elapsed_human,
    _GAP_THRESHOLD_SECONDS,
)

# 仿生体状态 + 食物 + 情绪 + 学习
from .bionic_state import (
    build_bionic_state,
    _build_sibling_relationship_context,
    build_food_context,
    build_emotion_context,
    build_study_context,
)

# 用户生物/生活画像
from .user_bio import (
    _build_user_status_and_daily,
    build_bio_context_for_active_care,
    _extract_known_sleep_time_fact,
    build_user_bio_context_for_chat,
    build_study_context_for_active_care,
)

# 详细人设构建
from .detailed_persona import (
    build_detailed_persona,
    _calculate_age_from_birth_date,
)

# 人物档案注入（提及人物时按需注入）
from .people_profiles import (
    build_mentioned_people_injection,
)

# Prompt 清理和辅助
from .prompt_helpers import (
    finalize_and_clean_prompt,
)

# Prompt 模板常量
from .templates import (
    CONTEXT_COMPRESS_SYSTEM_PROMPT,
    RAG_REWRITE_SYSTEM_PROMPT,
    JOURNAL_DAILY_SUMMARY_SYSTEM_PROMPT,
    JOURNAL_DAILY_SUMMARY_USER_PROMPT_TEMPLATE,
    JOURNAL_DAILY_SUMMARY_PROMPT_TEMPLATE,
    LING_DAILY_SUMMARY_SYSTEM_PROMPT,
    LING_DAILY_SUMMARY_USER_PROMPT_TEMPLATE,
    STUDY_DAILY_SUMMARY_PROMPT_TEMPLATE,
    JOURNAL_MONTHLY_SUMMARY_PROMPT_TEMPLATE,
    JOURNAL_MEMORY_DISTILL_PROMPT_TEMPLATE,
    JOURNAL_LLM_DIARY_PROMPT_TEMPLATE,
    PRIORITY_ANALYSIS_SYSTEM_PROMPT,
)

# 明日学习生活计划
from .plan_prompts import (
    PLAN_GENERATION_SYSTEM_PROMPT as PLAN_GENERATION_SYSTEM_PROMPT,
    PLAN_GENERATION_USER_PROMPT_TEMPLATE as PLAN_GENERATION_USER_PROMPT_TEMPLATE,
)
