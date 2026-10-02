"""
Active Care 共享常量兼容门面（2026-09-03 解耦）

原 `constants.py` 把状态键、关键词表、数值阈值、文本工具、Prompt 构建器和
Daily Record 写入混在一个文件里，导致"只想取一个状态键"也要连带导入 Prompt
模板与 Daily 模块，既拖慢冷启动也埋下循环导入隐患。

现按职责拆分为以下原子模块，新代码请直接引用对应模块：
    - `state_keys.py`       StateKeys / build_reduced_mode_clear_updates / build_goodnight_clear_updates
    - `keywords.py`         晚安、早安、专注、题材等关键词与匹配模式
    - `mode_reasons.py`     低打扰原因取值域、SkipReasons、SysPromptType
    - `tuning.py`           通用数值阈值（间隔/生成/提醒/退避/抖动）
    - `sleep_thresholds.py` 睡眠与晚安相关窗口阈值
    - `scheduling_utils.py` 退避等调度纯函数
    - `text_utils.py`       文本归一化、时长解析/格式化、人设 token
    - `prompt_helpers.py`   Prompt 片段构建器
    - `daily_record_sync.py` 睡眠区间回写 Daily Record（唯一带 IO 的模块）

本文件仅做向后兼容的集中 re-export，不再包含任何实现。
"""
from core.services.active_care.shared.daily_record_sync import sync_sleep_to_daily_record
from core.services.active_care.shared.keywords import (
    AccidentalReplyPatterns,
    AwakePresenceKeywords,
    FocusEnterKeywords,
    FocusExitKeywords,
    GoodmorningKeywords,
    GoodnightKeywords,
    GoodnightNegationPatterns,
    SleepHintKeywords,
    TopicKeywords,
)
from core.services.active_care.shared.mode_reasons import (
    FOCUS_MODE_REASONS,
    QUIET_MODE_REASONS,
    SLEEP_HINT_REASON,
    SLEEP_MODE_REASONS,
    SkipReasons,
    SysPromptType,
)
from core.services.active_care.shared.prompt_helpers import (
    ACTION_PROMPT_VARIANTS,
    build_core_constraints,
    build_quiet_mode_instruction,
    build_sleep_constraints,
    build_sleep_status_description,
    format_bio_complaint_prompt,
    get_action_prompt,
)
from core.services.active_care.shared.scheduling_utils import calculate_non_response_backoff
from core.services.active_care.shared.sleep_thresholds import (
    AUTO_WAKE_MAX_HOURS,
    GOODNIGHT_INITIAL_QUIET_SECONDS,
    GOODNIGHT_SIGNAL_GAP_SECONDS,
    MIN_QUIET_EVEN_INCOMPLETE_SECONDS,
    PROBABLE_SLEEP_EVENING_HOUR_END,
    PROBABLE_SLEEP_EVENING_HOUR_START,
    PROBABLE_SLEEP_MORNING_HOUR_END,
    PROBABLE_SLEEP_MORNING_HOUR_START,
    PROBABLE_SLEEP_NIGHT_HOUR_END,
    PROBABLE_SLEEP_NIGHT_HOUR_START,
    PROBABLE_SLEEP_PROBE_GAP_SECONDS,
    PROBABLE_SLEEP_SILENCE_EVENING_SECONDS,
    PROBABLE_SLEEP_SILENCE_MORNING_SECONDS,
    PROBABLE_SLEEP_SILENCE_NIGHT_SECONDS,
)
from core.services.active_care.shared.state_keys import (
    StateKeys,
    build_goodnight_clear_updates,
    build_reduced_mode_clear_updates,
)
from core.services.active_care.shared.text_utils import (
    extract_duration_seconds,
    extract_expected_end_ts,
    extract_persona_token,
    format_duration_human,
    format_elapsed_human,
    format_message_age_human,
    is_focus_presence_statement,
    normalize_content,
    normalize_persona_token,
)
from core.services.active_care.shared.tuning import (
    ACCIDENTAL_REPLY_MAX_LENGTH,
    ACCIDENTAL_REPLY_WINDOW_SECONDS,
    BACKOFF_BASE,
    BACKOFF_CAP,
    DEFAULT_BANDIT_EPSILON,
    DEFAULT_DAILY_LIMIT,
    DEFAULT_DECISION_TEMPERATURE,
    DEFAULT_GENERATION_MAX_TOKENS,
    DEFAULT_GENERATION_TEMPERATURE,
    DEFAULT_MIN_GAP_SECONDS,
    DEFAULT_NEXT_CHECK_SECONDS,
    DEFAULT_TONE_REFERENCE_MAX_CHARS,
    DEFAULT_USER_QUIET_SECONDS,
    EMOTION_INTERVAL_MULTIPLIERS,
    INTERVAL_MIN_SECONDS,
    JITTER_HIGH_RATIO,
    JITTER_LOW_RATIO,
    LONG_SILENCE_THRESHOLD_SECONDS,
    MAX_CONSECUTIVE_NON_RESPONSES_BEFORE_SKIP,
    RECENT_HISTORY_CONTENT_MAX_CHARS,
    RECENT_HISTORY_LIMIT,
    REMINDER_MAX_CONSECUTIVE_RETRIES,
    REMINDER_RETRY_BACKOFF_BASE_SECONDS,
    SILENCE_BREAKER_SECONDS,
    USER_MESSAGE_MAX_AGE_SECONDS,
)

__all__ = [
    # state_keys
    "StateKeys",
    "build_reduced_mode_clear_updates",
    "build_goodnight_clear_updates",
    # keywords
    "GoodnightNegationPatterns",
    "GoodnightKeywords",
    "GoodmorningKeywords",
    "SleepHintKeywords",
    "AwakePresenceKeywords",
    "AccidentalReplyPatterns",
    "FocusEnterKeywords",
    "FocusExitKeywords",
    "TopicKeywords",
    # mode_reasons
    "SkipReasons",
    "SLEEP_MODE_REASONS",
    "FOCUS_MODE_REASONS",
    "QUIET_MODE_REASONS",
    "SLEEP_HINT_REASON",
    "SysPromptType",
    # tuning
    "DEFAULT_NEXT_CHECK_SECONDS",
    "DEFAULT_MIN_GAP_SECONDS",
    "DEFAULT_DAILY_LIMIT",
    "DEFAULT_USER_QUIET_SECONDS",
    "DEFAULT_TONE_REFERENCE_MAX_CHARS",
    "DEFAULT_GENERATION_TEMPERATURE",
    "DEFAULT_GENERATION_MAX_TOKENS",
    "DEFAULT_DECISION_TEMPERATURE",
    "DEFAULT_BANDIT_EPSILON",
    "SILENCE_BREAKER_SECONDS",
    "REMINDER_MAX_CONSECUTIVE_RETRIES",
    "REMINDER_RETRY_BACKOFF_BASE_SECONDS",
    "ACCIDENTAL_REPLY_WINDOW_SECONDS",
    "ACCIDENTAL_REPLY_MAX_LENGTH",
    "LONG_SILENCE_THRESHOLD_SECONDS",
    "RECENT_HISTORY_LIMIT",
    "RECENT_HISTORY_CONTENT_MAX_CHARS",
    "BACKOFF_BASE",
    "BACKOFF_CAP",
    "MAX_CONSECUTIVE_NON_RESPONSES_BEFORE_SKIP",
    "JITTER_LOW_RATIO",
    "JITTER_HIGH_RATIO",
    "INTERVAL_MIN_SECONDS",
    "USER_MESSAGE_MAX_AGE_SECONDS",
    "EMOTION_INTERVAL_MULTIPLIERS",
    # sleep_thresholds
    "AUTO_WAKE_MAX_HOURS",
    "GOODNIGHT_SIGNAL_GAP_SECONDS",
    "GOODNIGHT_INITIAL_QUIET_SECONDS",
    "MIN_QUIET_EVEN_INCOMPLETE_SECONDS",
    "PROBABLE_SLEEP_SILENCE_NIGHT_SECONDS",
    "PROBABLE_SLEEP_SILENCE_MORNING_SECONDS",
    "PROBABLE_SLEEP_SILENCE_EVENING_SECONDS",
    "PROBABLE_SLEEP_NIGHT_HOUR_START",
    "PROBABLE_SLEEP_NIGHT_HOUR_END",
    "PROBABLE_SLEEP_MORNING_HOUR_START",
    "PROBABLE_SLEEP_MORNING_HOUR_END",
    "PROBABLE_SLEEP_EVENING_HOUR_START",
    "PROBABLE_SLEEP_EVENING_HOUR_END",
    "PROBABLE_SLEEP_PROBE_GAP_SECONDS",
    # scheduling_utils
    "calculate_non_response_backoff",
    # text_utils
    "normalize_content",
    "is_focus_presence_statement",
    "extract_duration_seconds",
    "extract_expected_end_ts",
    "normalize_persona_token",
    "extract_persona_token",
    "format_duration_human",
    "format_elapsed_human",
    "format_message_age_human",
    # prompt_helpers
    "ACTION_PROMPT_VARIANTS",
    "get_action_prompt",
    "format_bio_complaint_prompt",
    "build_core_constraints",
    "build_sleep_constraints",
    "build_quiet_mode_instruction",
    "build_sleep_status_description",
    # daily_record_sync
    "sync_sleep_to_daily_record",
]
