"""主动关怀题材（话题类型）分类器。

目标：把"她发我的类型"纳入强化学习闭环。

设计（按用户确认）：
- intent 作主类（share_thought / curious_question / bio_complaint / emotional_support /
  share_peer_chat / user_health_reminder / do_nothing ...）
- 再用 prompt/topic_diversity.detect_topic_category 从 planned_topic / 实际发送内容
  补一个"题材"子类型（sleep/food/study/care/vehicle/greeting/other）
- 两者拼接成 MDP 用的最终 topic 标签，如 "share_thought+food"

复用已有轮子：detect_topic_category 已用 TopicKeywords 做文本题材分类
（用于话题去重冷却），这里直接复用它，不再重复实现关键词匹配。
不做任何 LLM 调用；失败静默降级为 intent 主类。
"""
from typing import Optional

from core.utils.logger import get_logger
from core.services.active_care.prompt.topic_diversity import detect_topic_category

logger = get_logger("ACTIVE_CARE_TOPIC")


# intent 主类 → 默认题材（当无法从 planned_topic 抽取时）
_INTENT_DEFAULT_TOPIC = {
    "share_thought": "general",
    "curious_question": "probe",
    "bio_complaint": "health",
    "emotional_support": "care",
    "share_peer_chat": "peer",
    "user_health_reminder": "health",
    "do_nothing": "none",
    "reminder": "task",
    "planned_topic": "task",
    "wake_up_greeting": "greeting",
    "morning_report": "greeting",
    "goodnight_proactive": "sleep",
    "activity_return_proactive": "general",
}

# detect_topic_category 返回的大写类别 → MDP 题材槽位小写
_CATEGORY_TO_SLOT = {
    "SLEEP": "sleep",
    "GREETING": "greeting",
    "CARE": "care",
    "VEHICLE": "vehicle",
    "FOOD": "food",
    "STUDY": "study",
}


def classify_topic(intent: str, planned_topic: str = "", sent_content: str = "") -> str:
    """给一条主动关怀消息派生题材标签。

    Args:
        intent: 决策动作（如 share_thought）。
        planned_topic: LLM 决策输出的 planned_topic 字段（可能为空）。
        sent_content: 实际发送内容（可选，用于兜底抽取）。

    Returns:
        topic 标签，格式 "<intent>:<subtopic>"，
        例如 "share_thought:food"、"curious_question:study"、"bio_complaint:health"。
        无子类型时为 "share_thought:general"。
    """
    primary = str(intent or "").strip() or "share_thought"
    default_sub = _INTENT_DEFAULT_TOPIC.get(primary, "general")

    sub = None
    # 先尝试 planned_topic（最贴近"她打算聊什么"）
    if planned_topic:
        sub = _normalize_category(detect_topic_category(planned_topic))
    # 再尝试实际发送内容兜底
    if sub is None and sent_content:
        sub = _normalize_category(detect_topic_category(sent_content))

    if sub is None:
        sub = default_sub

    return f"{primary}:{sub}"


def topic_to_state_slot(topic: str) -> str:
    """把完整 topic 标签压缩为 MDP 状态用的题材槽位。

    只取子类型部分（冒号后），因为 intent 已在动作空间里体现；
    题材槽位回答"上次她发了什么类型的内容"。
    """
    if not topic or ":" not in topic:
        return "general"
    return topic.split(":", 1)[1] or "general"


def _normalize_category(category: str) -> Optional[str]:
    """把 detect_topic_category 的输出映射为题材槽位。

    Args:
        category: detect_topic_category 的输出（SLEEP/FOOD/.../other/unknown）

    Returns:
        小写题材槽位；other/unknown/空返回 None（交给 intent 主类兜底）
    """
    key = str(category or "").strip().upper()
    if not key or key in ("OTHER", "UNKNOWN"):
        return None
    return _CATEGORY_TO_SLOT.get(key)
