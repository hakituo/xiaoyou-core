"""
Active Care 模块统一常量定义
集中管理状态键、关键词列表、默认值、共享工具函数等，消除魔法字符串和重复代码
"""
import re
import time
from typing import Dict, List
from core.utils.timestamp_utils import format_message_age
from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
    ACTION_PROMPT_VARIANTS,
    BIO_COMPLAINT_PROMPT_TEMPLATES,
    DEFAULT_ACTION_PROMPT,
    CORE_CONSTRAINTS,
    SLEEP_CONSTRAINTS_TEMPLATE,
    QUIET_MODE_INSTRUCTION,
    GOODNIGHT_REDUCED_MODE_INSTRUCTION,
    REDUCED_MODE_INSTRUCTION_TEMPLATE,
)


class StateKeys:
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


class SkipReasons:
    PRIVATE_MODE = "private_mode_sensitive_persona"


def build_reduced_mode_clear_updates() -> Dict:
    return {
        StateKeys.REDUCED_MODE_ACTIVE: False,
        StateKeys.REDUCED_MODE_REASON: "none",
        StateKeys.REDUCED_MODE_LABEL: "",
        StateKeys.REDUCED_MODE_STARTED_TS: 0.0,
        StateKeys.REDUCED_MODE_EXPECTED_END_TS: 0.0,
    }


def build_goodnight_clear_updates() -> Dict:
    updates = build_reduced_mode_clear_updates()
    updates[StateKeys.LAST_GOODNIGHT_TS] = 0.0
    updates[StateKeys.LAST_GOODNIGHT_PROBE_TS] = 0.0
    return updates


class GoodnightNegationPatterns:
    NEGATION_PREFIXES = [
        "没说", "没有说", "没跟你说", "没和你说",
        "不是", "又不是", "并非",
        "还没", "还没有", "并未",
        "不想", "不要", "不愿",
        "怎么会", "为什么觉得", "为什么说",
        "哪有", "哪来的", "谁说",
    ]
    NEGATION_COMBOS = [
        "没说晚安", "没有说晚安", "没跟你说晚安", "没和你说晚安",
        "不是晚安", "又不是晚安",
        "还没睡", "还没有睡", "没睡", "没有睡",
        "不想睡", "不要睡", "不愿睡",
        "怎么觉得我睡了", "为什么觉得我睡了",
        "怎么会觉得我睡了", "为什么说我睡了",
        "哪有睡", "谁说我睡了", "谁说晚安",
        "没睡觉", "没有睡觉", "还没睡觉",
    ]


class GoodnightKeywords:
    PRIMARY = [
        "晚安", "睡觉", "睡了", "要睡", "睡啦", "睡咯",
        "先睡", "我要睡", "我先睡", "去睡了", "睡觉了",
        "sleep", "good night",
    ]
    EXTENDED = [
        "晚安", "睡觉", "睡了", "要睡", "睡啦", "睡咯",
        "先睡", "我要睡", "我先睡", "去睡了", "睡觉了",
        "别回了", "不用回", "已离线",
        "睡吧", "睡了啊", "睡了么", "睡没", "睡着了",
        "准备睡", "这就睡", "这就去睡", "这就睡了",
        "这就睡觉", "这就去睡觉", "这就睡了啊",
        "这就睡觉了", "这就去睡了", "这就去睡觉",
        "这就睡了么", "这就睡觉了么",
        "sleep", "good night",
    ]


class GoodmorningKeywords:
    ALL = [
        "早安", "早上好", "起床", "起来了", "刚起来", "醒了", "我醒了", "醒啦",
        "good morning", "morning",
    ]


class SleepHintKeywords:
    ALL = [
        "没回就是睡", "不回就是睡", "没回就是睡了", "不回就是睡了",
        "没回就是睡着", "不回就是睡着", "没回就是睡着了", "不回就是睡着了",
        "没回就是去睡", "不回就是去睡", "没回就是去睡了", "不回就是去睡了",
        "没回说明睡了", "不回说明睡了", "没回说明睡着了", "不回说明睡着了",
        "没回就是困了", "不回就是困了",
        "不回就是不在", "没回就是不在",
        "回不了就是睡了", "回不了就是睡",
        "没动静就是睡了", "没动静就是睡",
    ]


class AwakePresenceKeywords:
    ALL = [
        "在呢", "我在", "在线", "醒了", "我醒了", "起床", "起来了", "刚起来", "起了",
        "到家", "刚到", "上班", "在公司",
        "早安", "早上好", "good morning",
    ]


class AccidentalReplyPatterns:
    SHORT = [
        "嗯", "嗯嗯", "嗯哼", "哦", "噢", "呵", "哈",
        "好", "行", "ok", "诶", "额",
        "。。", "...", "～", "~",
    ]
    EXTENDED = [
        "嗯", "嗯嗯", "嗯哼", "哦", "噢", "呵", "哈",
        "好", "行", "ok", "哦", "诶", "额",
        "。。", "...", "～", "~", "。", ".",
        "👋", "🌙", "😴", "💤", "🫡",
    ]


class FocusEnterKeywords:
    ALL = [
        "我要学习了", "我去学习了", "开始学习",
        "我要工作了", "我去工作了", "我去忙了",
        "我先忙了", "开始专注",
    ]


class FocusExitKeywords:
    ALL = [
        "我忙完了", "忙完了", "学习完了", "学完了",
        "工作结束", "收工了",
    ]


class TopicKeywords:
    SLEEP = [
        "睡", "熬夜", "晚睡", "不睡", "休息", "睡觉", "困了",
        "tired", "sleep", "bedtime",
        "凌晨", "深夜", "身体不好", "对身体", "健康", "早点休息",
        "快去睡", "该睡了", "还不睡", "别熬夜", "少熬夜", "伤身", "伤身体",
        "stay up", "up late",
    ]
    GREETING = [
        "在吗", "在呢", "在不在", "嗨", "你好", "hey", "hello", "早上好",
        "晚安", "早安", "还在", "醒着", "awake",
    ]
    CARE = [
        "关心", "想你了", "想你", "担心", "miss", "在乎", "惦记",
        "最近怎么样", "过得如何", "还好吗",
    ]
    VEHICLE = [
        "车", "开车", "加油", "油耗", "汽油", "92", "95", "98",
        "油站", "加油站", "油费", "油钱", "油价", "标号", "耐烧",
        "斯巴鲁", "驾驶", "司机", "买车", "驾车", "排量",
        "car", "gas", "fuel", "mileage", "driving",
    ]
    FOOD = [
        "吃", "饭", "美食", "菜", "外卖", "零食", "水果", "喝",
        "早餐", "午餐", "晚餐", "宵夜", "火锅", "烧烤", "奶茶",
        "和牛", "牛肉", "海鲜", "料理",
        "food", "eat", "meal", "hungry",
    ]
    STUDY = [
        "学习", "作业", "考试", "复习", "预习", "课本", "笔记",
        "数学", "英语", "物理", "化学", "历史", "地理", "政治",
        "study", "homework", "exam", "learn",
    ]


class SysPromptType:
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


DEFAULT_NEXT_CHECK_SECONDS = 300
DEFAULT_MIN_GAP_SECONDS = 600
DEFAULT_DAILY_LIMIT = 20
DEFAULT_USER_QUIET_SECONDS = 300
DEFAULT_TONE_REFERENCE_MAX_CHARS = 3000
DEFAULT_GENERATION_TEMPERATURE = 0.65
DEFAULT_GENERATION_MAX_TOKENS = 220
DEFAULT_DECISION_TEMPERATURE = 0.45
DEFAULT_BANDIT_EPSILON = 0.2
SILENCE_BREAKER_SECONDS = 1800
REMINDER_MAX_CONSECUTIVE_RETRIES = 3
REMINDER_RETRY_BACKOFF_BASE_SECONDS = 300
GOODNIGHT_INITIAL_QUIET_SECONDS = 1800
ACCIDENTAL_REPLY_WINDOW_SECONDS = 300
ACCIDENTAL_REPLY_MAX_LENGTH = 4
LONG_SILENCE_THRESHOLD_SECONDS = 1800
RECENT_HISTORY_LIMIT = 8
RECENT_HISTORY_CONTENT_MAX_CHARS = 180

BACKOFF_BASE = 1.8
BACKOFF_CAP = 12.0
MAX_CONSECUTIVE_NON_RESPONSES_BEFORE_SKIP = 4
JITTER_LOW_RATIO = 0.9
JITTER_HIGH_RATIO = 1.1
INTERVAL_MIN_SECONDS = 30

AUTO_WAKE_MAX_HOURS = 14
GOODNIGHT_SIGNAL_GAP_SECONDS = 300
MIN_QUIET_EVEN_INCOMPLETE_SECONDS = 180
USER_MESSAGE_MAX_AGE_SECONDS = 300

PROBABLE_SLEEP_SILENCE_NIGHT_SECONDS = 7200
PROBABLE_SLEEP_SILENCE_MORNING_SECONDS = 10800
PROBABLE_SLEEP_SILENCE_EVENING_SECONDS = 3600
PROBABLE_SLEEP_NIGHT_HOUR_START = 0
PROBABLE_SLEEP_NIGHT_HOUR_END = 6
PROBABLE_SLEEP_MORNING_HOUR_START = 6
PROBABLE_SLEEP_MORNING_HOUR_END = 10
PROBABLE_SLEEP_EVENING_HOUR_START = 18
PROBABLE_SLEEP_EVENING_HOUR_END = 24
PROBABLE_SLEEP_PROBE_GAP_SECONDS = 3600  # 保留：sleep_hint 探针间隔仍在用
SLEEP_HINT_REASON = "sleep_hint"
# probable_sleep 机制已于 2026-07-30 移除（基于长时间无响应推断入睡不科学），
# PROBABLE_SLEEP_REASON 常量及其相关逻辑已删除。夜间降频依赖 goodnight/sleep_hint。

EMOTION_INTERVAL_MULTIPLIERS: Dict[str, tuple] = {
    "sad": (1.0, 0.8),
    "tired": (1.0, 0.8),
    "lost": (1.0, 0.8),
    "wronged": (1.0, 0.8),
    "angry": (1.0, 0.8),
    "happy": (1.0, -0.3),
    "excited": (1.0, -0.3),
    "coquetry": (1.0, -0.3),
    "anxious": (0.8, 0.0),
}


def calculate_non_response_backoff(non_response_count: int) -> float:
    """非响应退避乘数（Equal Jitter 算法）

    AWS 推荐的 Equal Jitter 策略：
    - 取指数退避值的一半作为确定性下界
    - 另一半作为随机上界
    - 既保留指数退避的均值，又最大化随机性

    相比原版 `pow(1.8, n)`，方差从 ~5% 提升到 ~25%，
    避免 AI 主动关怀形成可预测的"机械模式"。

    Args:
        non_response_count: 连续无响应次数

    Returns:
        float: 退避乘数（>=1.0，n=0 时返回 1.0）
    """
    import random

    n = max(0, int(non_response_count or 0))
    if n <= 0:
        return 1.0
    expo = min(pow(BACKOFF_BASE, n), BACKOFF_CAP)
    # Equal Jitter：确定性下界 + 随机上界
    # 下限保护为 1.0，避免"退避反而加速"的语义错误
    return max(1.0, expo / 2.0 + random.uniform(0.0, expo / 2.0))


def build_sleep_status_description(
    *,
    sleep_session_active: bool = False,
    quiet_mode_active: bool = False,
    reduced_mode_active: bool = False,
    reduced_mode_reason: str = "none",
    has_late_night_activity: bool = False,
    hours_since_late_night: int = -1,
    latest_late_night_hour: int = -1,
    now_hour: int = -1,
) -> str:
    """
    统一构建睡眠状态描述文本

    在 decision.py 和 executor.py 中复用，消除重复的描述构建逻辑
    """
    if sleep_session_active:
        return "【用户已进入睡眠模式】用户已说过晚安，正在睡眠中。可以发送轻量关怀消息（如'想你了'、'晚安'），但禁止追问任务或画像，禁止连续打扰。"
    if quiet_mode_active:
        return "【用户处于静默时段】用户已说过晚安但可能还没入睡。可以发送简短关怀，保持低打扰。"
    # probable_sleep 分支已于 2026-07-30 移除
    if (
        has_late_night_activity
        and 0 <= now_hour < 12
        and hours_since_late_night >= 0
        and hours_since_late_night < 6
    ):
        late_hour_text = f"{latest_late_night_hour}点" if latest_late_night_hour >= 0 else "凌晨"
        return (
            f"【用户可能刚睡不久】用户在{late_hour_text}左右有对话（{hours_since_late_night}小时前），"
            f"可能晚睡或通宵。当前早上{now_hour}点，优先假设用户还在睡觉或刚睡不久。"
            f"禁止发送'醒了没/起床了没'类消息，仅允许轻量陪伴如'想你了'。"
        )
    return "【用户未进入睡眠模式】用户还没有说晚安，可能还醒着。"


_FOCUS_PRESENCE_PATTERNS = [
    r"(我|咱|本人).{0,4}(在学习|学习中|在复习|在刷题|在做题|在背书|在写作业)",
    r"(我|咱|本人).{0,4}(在工作|在上班|在开会|在写代码|在忙|忙着)",
    r"(先|正在).{0,4}(学习|复习|刷题|做题|工作|上班|开会|写代码)",
]


def is_focus_presence_statement(text: str) -> bool:
    """
    检查文本是否是专注状态陈述

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


_DURATION_UNIT_HOURS = {"小时", "h", "hour", "hours"}
_DURATION_MIN_SECONDS = 5 * 60
_DURATION_MAX_SECONDS = 8 * 3600


def extract_duration_seconds(text: str) -> int:
    """
    从文本中提取时长（秒）

    统一 focus_state.py._extract_duration 和 mode_state.py._extract_expected_end_ts 中的重复逻辑。
    限制在 5 分钟到 8 小时之间。

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
    """
    从文本中提取预期结束时间戳

    基于 extract_duration_seconds，返回当前时间 + 时长的绝对时间戳。

    Args:
        text: 用户文本

    Returns:
        float: 预期结束时间戳，未找到返回 0.0
    """
    seconds = extract_duration_seconds(text)
    return time.time() + float(seconds) if seconds > 0 else 0.0


def normalize_persona_token(filename: str) -> str:
    """
    将人设文件名标准化为 token

    统一 context.py、storage.py、persona_resolver.py 中的重复实现。
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
    """
    从 conversation_id 中提取人设 token

    统一 context.py、storage.py、persona_resolver.py 中的重复实现。

    Args:
        conversation_id: 会话 ID

    Returns:
        str: 人设 token，未找到返回空字符串
    """
    cid = str(conversation_id or "").strip().lower()
    if "__persona__" not in cid:
        return ""
    return cid.split("__persona__", 1)[1].split("__", 1)[0].strip("_")


ACTION_PROMPT_VARIANTS: Dict[str, List[str]] = ACTION_PROMPT_VARIANTS


def format_bio_complaint_prompt(urgent_needs: List[str]) -> str:
    import random
    needs_str = ", ".join(urgent_needs) if urgent_needs else "体温/功耗/内存占用略高"
    fallback_str = ", ".join(urgent_needs) if urgent_needs else "有点累/发烫"
    run_str = ", ".join(urgent_needs) if urgent_needs else "运行不畅"
    variants = [
        t.format(needs_str=needs_str, fallback_str=fallback_str, run_str=run_str)
        for t in BIO_COMPLAINT_PROMPT_TEMPLATES
    ]
    return random.choice(variants)


def get_action_prompt(action: str) -> str:
    import random
    variants = ACTION_PROMPT_VARIANTS.get(action)
    if variants:
        return random.choice(variants)
    return DEFAULT_ACTION_PROMPT


def format_duration_human(seconds: int) -> str:
    """
    将秒数格式化为人类可读的时长文本

    统一 decision.py、executor.py、decision_executor.py 中的重复格式化逻辑。
    限制在 0 ~ max_seconds 之间。

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
    """
    将经过的秒数格式化为人类可读的相对时间文本

    统一 decision.py 中内联的 elapsed_seconds 格式化逻辑。
    实际调用 core.agents.chat_agent_components.persona_system.prompt.components._format_elapsed_human

    Args:
        seconds: 经过秒数
        max_seconds: 最大限制秒数（默认7天）

    Returns:
        str: 如 "2小时30分钟"、"5天"
    """
    from core.agents.chat_agent_components.persona_system.prompt.components import _format_elapsed_human
    return _format_elapsed_human(seconds, max_seconds)


# 向后兼容别名，实际实现在 core.utils.timestamp_utils.format_message_age
format_message_age_human = format_message_age


def build_quiet_mode_instruction(
    quiet_mode_active: bool,
    reduced_mode_active: bool,
    reduced_mode_reason: str,
) -> str:
    if quiet_mode_active:
        return QUIET_MODE_INSTRUCTION
    if reduced_mode_active:
        if reduced_mode_reason == "goodnight":
            return GOODNIGHT_REDUCED_MODE_INSTRUCTION
        # probable_sleep 分支已于 2026-07-30 移除
        else:
            return REDUCED_MODE_INSTRUCTION_TEMPLATE.format(reason=reduced_mode_reason)
    return ""


def build_core_constraints() -> str:
    return CORE_CONSTRAINTS


def build_sleep_constraints(sleep_session: Dict) -> str:
    if not sleep_session:
        return ""
    return SLEEP_CONSTRAINTS_TEMPLATE


def normalize_content(s: str) -> str:
    return " ".join(str(s or "").strip().lower().split())


def sync_sleep_to_daily_record(
    sleep_start_ts: float,
    wakeup_ts: float,
    min_duration_seconds: float = 1800,
) -> bool:
    if sleep_start_ts <= 0:
        return False
    duration_seconds = wakeup_ts - sleep_start_ts
    if duration_seconds < min_duration_seconds:
        return False
    try:
        from datetime import datetime
        sleep_dt = datetime.fromtimestamp(sleep_start_ts)
        wakeup_dt = datetime.fromtimestamp(wakeup_ts)
        sleep_hhmm = sleep_dt.strftime("%H:%M")
        wakeup_hhmm = wakeup_dt.strftime("%H:%M")
        from core.services.daily.manager import DailyActivityManager
        daily_mgr = DailyActivityManager()
        daily_mgr.record_sleep(sleep_hhmm)
        daily_mgr.record_wakeup(wakeup_hhmm, source="active_care_session")
        return True
    except Exception:
        return False
