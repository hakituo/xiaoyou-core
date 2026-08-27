"""
时间相关的 prompt 组件
"""
import time
from datetime import datetime
from typing import Any, Optional

from core.utils.logger import get_logger

logger = get_logger("PromptComponents.Time")


def _format_elapsed_human(seconds: int, max_seconds: int = 7 * 24 * 3600) -> str:
    """
    将经过的秒数格式化为人类可读的相对时间文本
    """
    s = max(0, min(int(seconds or 0), max_seconds))
    if s <= 0:
        return "不到1分钟"
    if s < 60:
        return f"{s}秒"
    if s < 3600:
        return f"{s // 60}分钟"
    if s < 86400:
        hours = s // 3600
        minutes = (s % 3600) // 60
        if minutes > 0:
            return f"{hours}小时{minutes}分钟"
        return f"{hours}小时"
    days = s // 86400
    hours = (s % 86400) // 3600
    if hours > 0:
        return f"{days}天{hours}小时"
    return f"{days}天"


def build_time_context(
    current_time: Optional[Any] = None,
    time_period: Optional[str] = None,
    last_conversation_seconds: Optional[int] = None,
) -> str:
    """
    构建时间上下文组件

    Args:
        current_time: 当前时间对象
        time_period: 时间段（如"晚上"）
        last_conversation_seconds: 距上次对话的秒数

    Returns:
        时间上下文字符串
    """
    from core.utils.time_utils import get_current_time, get_time_period

    now = current_time or get_current_time()
    period = time_period or get_time_period()
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")

    parts = []

    if last_conversation_seconds and isinstance(last_conversation_seconds, int) and last_conversation_seconds >= 300:
        elapsed_str = _format_elapsed_human(last_conversation_seconds)
        parts.append(f"距上次对话：{elapsed_str}")

    return "\n".join(parts) if parts else ""


_GAP_THRESHOLD_SECONDS = 300


def build_conversation_gap_context(
    history_messages: list,
    current_ts: Optional[float] = None,
) -> str:
    """
    检测对话中的时间间隔，生成时间上下文提示

    当检测到对话中存在明显的时间间隔时，会生成提示
    帮助LLM正确理解用户的行为（如睡眠时间）

    同时检测"最后一条历史消息到当前时刻"的间隔，
    以感知用户离开后刚回来的场景。

    Args:
        history_messages: 历史消息列表，每条消息应包含 timestamp 字段
        current_ts: 当前时间戳，默认使用 time.time()

    Returns:
        时间上下文提示字符串，如果没有明显间隔则返回空字符串
    """
    from core.utils.time_utils import format_timestamp

    if not history_messages:
        return ""

    current_ts = current_ts or time.time()

    timestamps = []
    for msg in history_messages:
        ts = msg.get("timestamp", 0)
        if ts:
            try:
                ts_float = float(ts)
                if ts_float > 0:
                    timestamps.append(ts_float)
            except (ValueError, TypeError):
                pass

    if not timestamps:
        return ""

    timestamps.sort()

    max_gap_seconds = 0.0
    max_gap_after_ts = 0.0
    max_gap_before_ts = 0.0

    for i in range(1, len(timestamps)):
        prev_ts = timestamps[i - 1]
        curr_ts = timestamps[i]
        gap = curr_ts - prev_ts
        if gap > max_gap_seconds:
            max_gap_seconds = gap
            max_gap_after_ts = curr_ts
            max_gap_before_ts = prev_ts

    last_msg_ts = timestamps[-1]
    gap_to_now_seconds = max(0.0, current_ts - last_msg_ts)
    if gap_to_now_seconds > max_gap_seconds:
        max_gap_seconds = gap_to_now_seconds
        max_gap_after_ts = current_ts
        max_gap_before_ts = last_msg_ts

    if max_gap_seconds < _GAP_THRESHOLD_SECONDS:
        return ""

    gap_str = _format_elapsed_human(int(max_gap_seconds))

    result = (
        f"- ⚠️ 对话存在明显间隔：{format_timestamp(max_gap_before_ts, '%m-%d %H:%M')} "
        f"到 {format_timestamp(max_gap_after_ts, '%m-%d %H:%M')} 之间有约 {gap_str} 的空白。"
    )

    gap_before_dt = datetime.fromtimestamp(max_gap_before_ts)
    gap_after_dt = datetime.fromtimestamp(max_gap_after_ts)
    gap_before_hour = gap_before_dt.hour
    gap_after_hour = gap_after_dt.hour
    gap_hours = max_gap_seconds / 3600

    if gap_hours >= 4:
        if gap_before_hour >= 20 or gap_before_hour < 6:
            result += "\n- 这段间隔跨越了夜间时段，用户很可能在这期间睡觉了。"
        elif gap_after_hour >= 5 and gap_after_hour <= 11 and gap_before_hour < 12:
            result += "\n- 这段间隔跨越了深夜到早晨，用户很可能在睡觉。"
        else:
            result += "\n- 这段间隔较长，用户可能离开了（睡觉、外出或其他活动）。"
    elif gap_hours >= 2:
        if gap_before_hour >= 22 or gap_before_hour < 2:
            result += "\n- 这段间隔在深夜/凌晨，用户可能已经去睡觉了。"
        elif gap_after_hour >= 6 and gap_after_hour <= 10:
            result += "\n- 间隔结束在早上，用户可能刚起床回来。"

    is_gap_to_now = (max_gap_before_ts == last_msg_ts and gap_to_now_seconds >= _GAP_THRESHOLD_SECONDS)
    if is_gap_to_now:
        gap_to_now_str = _format_elapsed_human(int(gap_to_now_seconds))
        result += f"\n- 用户距上次发言已有约 {gap_to_now_str}，刚刚才回来。"

    first_ts = timestamps[0]
    total_elapsed = _format_elapsed_human(int(current_ts - first_ts))
    result += f"\n- 从对话开始（{format_timestamp(first_ts, '%m-%d %H:%M')}）到现在，总共经过了约 {total_elapsed}。"
    result += "\n请根据此间隔理解时间流逝，不要低估实际经过的时间。如果用户刚回来，请自然地回应，不要表现得像忘记了之前的对话。"

    return result
