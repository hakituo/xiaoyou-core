"""主动关怀 Prompt 的场景、时间与去重约束。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
    CONTEXT_GUARD_CONTINUATION,
    CONTEXT_GUARD_LONG_SILENCE,
    CONTINUATION_GUARD_EN,
    CONTINUATION_GUARD_ZH,
    DEDUP_CONSTRAINT_TEMPLATE,
    DEDUP_MULTI_CONSTRAINT_TEMPLATE,
    NO_INTERROGATION_CONSTRAINT,
    OUT_OF_CONTEXT_TOPIC_GUARD_TEMPLATE,
    TEMPORAL_ANCHOR_TEMPLATE,
)

NO_INTERROGATION_EXEMPT_TYPES = frozenset(
    {
        "goodnight_proactive",
        "sleep_again_proactive",
        "activity_return_proactive",
        "good_morning_proactive",
        "wake_up_greeting",
        "morning_report",
        "notification_assistant",
        "usage_limit_exceeded",
        "insomnia",
        "focus_nudge",
        "bio_complaint",
    }
)
NON_STUDY_ACTIVITY_CATEGORIES = frozenset(
    {"working", "gaming", "entertainment", "browsing", "communicating"}
)
_ACTIVITY_TEXT_MAP = {
    "working": "工作/处理事务",
    "gaming": "打游戏",
    "entertainment": "看视频或听音乐放松",
    "browsing": "上网浏览",
    "communicating": "跟人聊天",
}
_STUDY_TOPIC_ALLOWED_TYPES = frozenset({"reminder"})


def _build_out_of_context_guard(
    user_activity: Optional[Dict[str, Any]], sys_prompt_type: str
) -> str:
    if not isinstance(user_activity, dict) or not user_activity:
        return ""
    category = str(user_activity.get("category") or "").strip().lower()
    if category not in NON_STUDY_ACTIVITY_CATEGORIES:
        return ""
    if str(sys_prompt_type or "").strip() in _STUDY_TOPIC_ALLOWED_TYPES:
        return ""
    app_name = str(user_activity.get("display_name") or "").strip()
    base_text = _ACTIVITY_TEXT_MAP.get(category, "做别的事")
    activity_text = f"{base_text}（{app_name}）" if app_name else base_text
    return OUT_OF_CONTEXT_TOPIC_GUARD_TEMPLATE.format(activity_text=activity_text)


def _build_no_interrogation_constraint(sys_prompt_type: str) -> str:
    if str(sys_prompt_type or "").strip() in NO_INTERROGATION_EXEMPT_TYPES:
        return ""
    return NO_INTERROGATION_CONSTRAINT


def _build_context_guard(is_long_silence: bool) -> str:
    return CONTEXT_GUARD_LONG_SILENCE if is_long_silence else CONTEXT_GUARD_CONTINUATION


def _build_continuation_guard(
    language: str, recent_history_text: str, is_long_silence: bool = False
) -> str:
    if not str(recent_history_text or "").strip() or is_long_silence:
        return ""
    return CONTINUATION_GUARD_EN if language == "en" else CONTINUATION_GUARD_ZH


def _build_temporal_anchor(now: float, last_sent_ts: float, last_user_ts: float) -> str:
    from core.agents.chat_agent_components.persona_system.prompt.components import (
        _format_elapsed_human,
    )

    try:
        from core.utils.time_utils import get_current_time

        now_text = datetime.fromtimestamp(float(now), get_current_time().tzinfo).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except Exception:  # noqa: BLE001
        now_text = ""
    parts = []
    if now_text:
        parts.extend(
            [
                f"当前本地时间：{now_text}",
                "若不确定钟点，不要编造具体时分，所有时间必须与此锚点一致",
            ]
        )
    if last_sent_ts > 0:
        elapsed = int(max(0.0, now - last_sent_ts))
        parts.append(f"距你上次主动发消息：{_format_elapsed_human(elapsed) if elapsed > 0 else '未知'}")
    if last_user_ts > 0:
        elapsed = int(max(0.0, now - last_user_ts))
        parts.append(f"距他最近一条消息：{_format_elapsed_human(elapsed) if elapsed > 0 else '未知'}")
    if last_user_ts > 0 and now - last_user_ts > 1800:
        parts.append("他很久没说话了，先确认他是否在忙，别急着抛话题")
    if not parts:
        return ""
    return TEMPORAL_ANCHOR_TEMPLATE.format(
        anchor_lines="\n".join(f"- {part}" for part in parts)
    )


def _build_dedup_constraint(
    last_proactive_assistant_message: str,
    last_assistant_message: str,
    repeat_anchors: Optional[List[str]] = None,
) -> str:
    from core.utils.debug_markers import is_debug_context_message

    anchors = []
    for item in repeat_anchors or []:
        text = str(item or "").strip()
        if not text or is_debug_context_message(text) or "[DEBUG_ERROR]" in text:
            continue
        anchors.append(text)
        if len(anchors) >= 5:
            break
    if anchors:
        lines = []
        for index, text in enumerate(anchors, start=1):
            clipped = text[:120] + "..." if len(text) > 120 else text
            lines.append(f"- 参考锚点{index}：{clipped}")
        return DEDUP_MULTI_CONSTRAINT_TEMPLATE.format(anchor_lines="\n".join(lines))

    anchor = str(last_proactive_assistant_message or "").strip()
    label = "上一条主动消息"
    if not anchor or is_debug_context_message(anchor) or "[DEBUG_ERROR]" in anchor:
        anchor = str(last_assistant_message or "").strip()
        label = "最近一条助手消息"
    if not anchor or is_debug_context_message(anchor) or "[DEBUG_ERROR]" in anchor:
        return ""
    if len(anchor) > 180:
        anchor = anchor[:180] + "..."
    return DEDUP_CONSTRAINT_TEMPLATE.format(label=label, anchor=anchor)
