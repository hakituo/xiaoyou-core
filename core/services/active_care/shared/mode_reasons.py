"""
主动关怀模式原因取值与提示词类型枚举

从原 `shared/constants.py` 拆出：只放"取值域"定义，纯数据无依赖。
reduced_mode_reason 的权威取值集合于 2026-09-03 上收为单一真相源，
之前 sleep_state / storage / mode_state / life_simulation 各自维护一份
字面量集合，新增或调整原因时容易漏改，导致同一 reason 在不同模块被
归类到不同语义。
"""


class SkipReasons:
    """跳过主动关怀的原因标记。"""

    PRIVATE_MODE = "private_mode_sensitive_persona"


# 已进入低打扰且属于睡眠语义的原因
SLEEP_MODE_REASONS = frozenset({"goodnight", "sleep_hint", "sleep"})
# 已进入低打扰且属于专注/学习/工作语义的原因
FOCUS_MODE_REASONS = frozenset({"focus", "study", "work"})
# 已进入低打扰、但尚未确认睡着（说了晚安还没睡）
QUIET_MODE_REASONS = frozenset({"goodnight", "sleep_hint"})

# probable_sleep 机制已于 2026-07-30 移除（基于长时间无响应推断入睡不科学）。
# 夜间降频依赖 goodnight/sleep_hint。
SLEEP_HINT_REASON = "sleep_hint"


class SysPromptType:
    """系统提示词场景类型。"""

    CHECKING = "checking"
    PLANNED_TOPIC = "planned_topic"
    REMINDER = "reminder"
    WAKE_UP_GREETING = "wake_up_greeting"
    MORNING_REPORT = "morning_report"
    NOTIFICATION_ASSISTANT = "notification_assistant"
    INSOMNIA = "insomnia"
    BIO_COMPLAINT = "bio_complaint"
    USER_HEALTH_REMINDER = "user_health_reminder"
    CURIOUS_QUESTION = "curious_question"
    STARTUP = "startup"
    PROACTIVE_FOLLOW_UP = "proactive_follow_up"
    SHARE_PEER_CHAT = "share_peer_chat"


__all__ = [
    "SkipReasons",
    "SLEEP_MODE_REASONS",
    "FOCUS_MODE_REASONS",
    "QUIET_MODE_REASONS",
    "SLEEP_HINT_REASON",
    "SysPromptType",
]
