"""
主动关怀文本处理工具（归一化 / 时长解析 / 人设 token / 时长格式化）

从原 `shared/constants.py` 拆出：全部为无状态纯函数，统一了原本散落在
focus_state / mode_state / context / storage / persona_resolver / decision /
executor 中的重复实现。
"""
import re
import time

from core.utils.timestamp_utils import format_message_age

_FOCUS_PRESENCE_PATTERNS = [
    r"(我|咱|本人).{0,4}(在学习|学习中|在复习|在刷题|在做题|在背书|在写作业)",
    r"(我|咱|本人).{0,4}(在工作|在上班|在开会|在写代码|在忙|忙着)",
    r"(先|正在).{0,4}(学习|复习|刷题|做题|工作|上班|开会|写代码)",
]

_DURATION_UNIT_HOURS = {"小时", "h", "hour", "hours"}
_DURATION_MIN_SECONDS = 5 * 60
_DURATION_MAX_SECONDS = 8 * 3600


# ── 文本归一化 ──────────────────────────────────────────────
def normalize_content(s: str) -> str:
    """归一化为比较用文本：去首尾空白、折叠内部空白、统一小写。"""
    return " ".join(str(s or "").strip().lower().split())


# ── 专注状态识别 ────────────────────────────────────────────
def is_focus_presence_statement(text: str) -> bool:
    """检查文本是否是专注状态陈述。

    统一 focus_state.py 和 mode_state.py 中的重复实现。
    排除"你在学习/你在工作"等第二人称陈述。

    Args:
        text: 用户文本

    Returns:
        bool: 是否是专注状态陈述
    """
    raw = str(text or "").strip()
    if not raw:
        return False
    if "你在学习" in raw or "你在工作" in raw:
        return False
    for pat in _FOCUS_PRESENCE_PATTERNS:
        if re.search(pat, raw, flags=re.IGNORECASE):
            return True
    return False


# ── 时长解析 ────────────────────────────────────────────────
def extract_duration_seconds(text: str) -> int:
    """从文本中提取时长（秒）。

    统一 focus_state.py._extract_duration 和 mode_state.py._extract_expected_end_ts
    中的重复逻辑，限制在 5 分钟到 8 小时之间。

    Args:
        text: 用户文本

    Returns:
        int: 时长（秒），未找到返回 0
    """
    try:
        match = re.search(r"(\d{1,3})\s*(分钟|分|小时|h|hour|hours)", text)
        if not match:
            return 0
        value = int(match.group(1))
        unit = str(match.group(2) or "").lower()
        seconds = value * 3600 if unit in _DURATION_UNIT_HOURS else value * 60
        return max(_DURATION_MIN_SECONDS, min(seconds, _DURATION_MAX_SECONDS))
    except Exception:
        return 0


def extract_expected_end_ts(text: str) -> float:
    """从文本中提取预期结束时间戳（当前时间 + 提取到的时长）。

    Args:
        text: 用户文本

    Returns:
        float: 预期结束时间戳，未找到返回 0.0
    """
    seconds = extract_duration_seconds(text)
    return time.time() + float(seconds) if seconds > 0 else 0.0


# ── 人设 token ──────────────────────────────────────────────
def normalize_persona_token(filename: str) -> str:
    """将人设文件名标准化为 token。

    统一 context / storage / persona_resolver / conversation_resolver 中的重复实现。
    保留中文、字母、数字和下划线，其余替换为下划线。

    Args:
        filename: 人设文件名或路径

    Returns:
        str: 标准化后的 token
    """
    raw = str(filename or "").strip().replace("\\", "/")
    stem = raw.rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    return re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff]+", "_", stem).strip("_").lower()


def extract_persona_token(conversation_id: str) -> str:
    """从 conversation_id 中提取人设 token。

    Args:
        conversation_id: 会话 ID

    Returns:
        str: 人设 token，未找到返回空字符串
    """
    cid = str(conversation_id or "").strip().lower()
    if "__persona__" not in cid:
        return ""
    return cid.split("__persona__", 1)[1].split("__", 1)[0].strip("_")


# ── 时长格式化 ──────────────────────────────────────────────
def format_duration_human(seconds: int) -> str:
    """将秒数格式化为人类可读的时长文本。

    统一 decision.py、executor.py、decision_executor.py 中的重复格式化逻辑。

    Args:
        seconds: 时长（秒）

    Returns:
        str: 如 "2小时30分钟"、"45分钟"、"不到1分钟"
    """
    s = max(0, int(seconds or 0))
    if s <= 0:
        return "不到1分钟"
    hours = s // 3600
    minutes = (s % 3600) // 60
    if hours > 0 and minutes > 0:
        return f"{hours}小时{minutes}分钟"
    if hours > 0:
        return f"{hours}小时"
    if minutes > 0:
        return f"{minutes}分钟"
    return f"{s}秒"


def format_elapsed_human(seconds: int, max_seconds: int = 7 * 24 * 3600) -> str:
    """将经过的秒数格式化为人类可读的相对时间文本。

    Args:
        seconds: 经过秒数
        max_seconds: 最大限制秒数（默认7天）

    Returns:
        str: 如 "2小时30分钟"、"5天"
    """
    from core.agents.chat_agent_components.persona_system.prompt.components import (
        _format_elapsed_human,
    )
    return _format_elapsed_human(seconds, max_seconds)


# 向后兼容别名，实际实现在 core.utils.timestamp_utils.format_message_age
format_message_age_human = format_message_age


__all__ = [
    "normalize_content",
    "is_focus_presence_statement",
    "extract_duration_seconds",
    "extract_expected_end_ts",
    "normalize_persona_token",
    "extract_persona_token",
    "format_duration_human",
    "format_elapsed_human",
    "format_message_age_human",
]
