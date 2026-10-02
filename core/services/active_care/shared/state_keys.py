"""
主动关怀状态键与状态清理字典构建

从原 `shared/constants.py` 拆出：只保留与持久化状态键相关的内容，
避免"取一个状态键"也要连带加载关键词表、Prompt 模板和 Daily Record 写入逻辑。
"""
from typing import Dict


class StateKeys:
    """持久化状态字典（proactive_state / user_sleep_state）的键名单一真相源。"""

    LAST_GOODNIGHT_TS = "last_goodnight_ts"
    LAST_GOODMORNING_TS = "last_goodmorning_ts"
    LAST_GOODNIGHT_PROBE_TS = "last_goodnight_probe_ts"
    REDUCED_MODE_ACTIVE = "reduced_mode_active"
    REDUCED_MODE_REASON = "reduced_mode_reason"
    REDUCED_MODE_LABEL = "reduced_mode_label"
    REDUCED_MODE_STARTED_TS = "reduced_mode_started_ts"
    REDUCED_MODE_EXPECTED_END_TS = "reduced_mode_expected_end_ts"
    LAST_SENT_TS = "last_sent_ts"
    LAST_SENT_TYPE = "last_sent_type"
    LAST_SENT_TOPIC = "last_sent_topic"
    LAST_SENT_TOPIC_TYPE = "last_sent_topic_type"
    LAST_SENT_CONTENT = "last_sent_content"
    # 标记"角色自发去做事（不需要回复）"的消息，不进入 MDP/学习闭环
    LAST_SENT_SELF_ACTIVITY = "last_sent_self_activity"
    LAST_THOUGHT = "last_thought"
    LAST_ATTEMPT_TS = "last_attempt_ts"
    LAST_ATTEMPT_TYPE = "last_attempt_type"
    LAST_USER_INTERACTION_TS = "last_user_interaction_ts"
    CONSECUTIVE_NON_RESPONSES = "consecutive_non_responses"
    # 2026-09-04 频控改造：上一条主动消息的追踪字段（send/defer 判定用）
    LAST_PROACTIVE_AT = "last_proactive_at"
    LAST_PROACTIVE_TYPE = "last_proactive_type"
    LAST_PROACTIVE_TOPIC = "last_proactive_topic"
    LAST_PROACTIVE_TOPIC_GROUP = "last_proactive_topic_group"
    LAST_PROACTIVE_REPLIED = "last_proactive_replied"
    RECENT_SENT_CONTENTS = "recent_sent_contents"
    LAST_SLEEP_SESSION_START_TS = "last_sleep_session_start_ts"
    LAST_SLEEP_SESSION_END_TS = "last_sleep_session_end_ts"
    LAST_SLEEP_SESSION_DURATION_SECONDS = "last_sleep_session_duration_seconds"
    LAST_SLEEP_SESSION_SOURCE = "last_sleep_session_source"
    LAST_SLEEP_SESSION_KIND = "last_sleep_session_kind"
    LAST_LOW_DISTURBANCE_EXIT_TS = "last_low_disturbance_exit_ts"
    LAST_LOW_DISTURBANCE_EXIT_SOURCE = "last_low_disturbance_exit_source"
    GOODNIGHT_BUT_AWAKE_TS = "goodnight_but_awake_ts"
    GOODNIGHT_BUT_AWAKE_ELAPSED = "goodnight_but_awake_elapsed"
    LAST_GOODNIGHT_SUMMARY_DATE = "last_goodnight_summary_date"
    LAST_GOODNIGHT_SUMMARY_TS = "last_goodnight_summary_ts"
    MODE_REMINDER_ID = "mode_reminder_id"
    NEXT_LLM_DECISION_TS = "next_llm_decision_ts"
    NEXT_LLM_DECISION_SOURCE = "next_llm_decision_source"
    NEXT_LLM_DECISION_WRITTEN_TS = "next_llm_decision_written_ts"
    LAST_PRIORITY_PROBE_SIGNATURE = "last_priority_probe_signature"
    LAST_PRIORITY_PROBE_TS = "last_priority_probe_ts"
    TODAY_SENT_EVENTS_DATE = "today_sent_events_date"
    TODAY_SENT_EVENTS = "today_sent_events"
    PRIVATE_MODE_ACTIVE = "private_mode_active"


def build_reduced_mode_clear_updates() -> Dict:
    """构建退出低打扰模式所需的状态重置字典（5 字段）。

    在 sleep_state / sleep_session_manager / checker 等多处复用，
    避免各写一份字段列表导致漏改。
    """
    return {
        StateKeys.REDUCED_MODE_ACTIVE: False,
        StateKeys.REDUCED_MODE_REASON: "none",
        StateKeys.REDUCED_MODE_LABEL: "",
        StateKeys.REDUCED_MODE_STARTED_TS: 0.0,
        StateKeys.REDUCED_MODE_EXPECTED_END_TS: 0.0,
    }


def build_goodnight_clear_updates() -> Dict:
    """构建退出晚安状态所需的状态重置字典（晚安字段 + 低打扰 5 字段）。"""
    updates = build_reduced_mode_clear_updates()
    updates[StateKeys.LAST_GOODNIGHT_TS] = 0.0
    updates[StateKeys.LAST_GOODNIGHT_PROBE_TS] = 0.0
    return updates


__all__ = [
    "StateKeys",
    "build_reduced_mode_clear_updates",
    "build_goodnight_clear_updates",
]
