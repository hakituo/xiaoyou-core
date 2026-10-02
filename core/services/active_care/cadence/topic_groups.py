"""主动关怀题材分组（topic_group）

2026-09-04 改造：给题材（topic）做标签分组，防止模型"换措辞继续追同一件事"。

背景：同样一条用户状态链可以换无数种措辞：
    吃饭没？  /  外卖点了吗？  /  饭到了吗？
这三个虽然文案不同，但属于同一条"用户状态链"，必须算同一个 topic_group。
否则仅靠 dedup（同义句去重）和 min_gap（固定间隔），模型用换措辞就能绕过冷却。

设计：
- 上游已存在题材分类：`decision/topic_classifier.classify_topic` 产出
  "<intent>:<subtopic>"，subtopic ∈ {sleep/food/study/care/vehicle/greeting/health/peer/task/probe/general}；
- 这里把细粒度 subtopic 进一步收敛成"同一件事"的分组；
- 分组命中的冷却比 subtopic 冷却更保守（宁可 defer，也不错发）。
"""

from typing import Optional

# subtopic（classify_topic 的冒号后半段）→ topic_group
# 关键合并：
# - food → meal：吃饭/外卖/饭到了都算"吃饭这一件事"
# - health/sleep 不合并：喝水提醒与催睡是两件事
# - general/other/unknown 不参与同组冷却（信息量不足以判定"同一件事"）
SUBTOPIC_GROUP_MAP = {
    "food": "meal",
    "sleep": "sleep",
    "study": "study",
    "care": "care",
    "vehicle": "vehicle",
    "greeting": "greeting",
    "health": "health",
    "peer": "social",
    "task": "general",
    "probe": "general",
    "general": "general",
    "none": "general",
    "other": "general",
    "unknown": "general",
}

# topic_group 是否值得参与"同组冷却"。
# general 组几乎可以包含任何内容，参与冷却会误杀正常的新话题。
COOLDOWN_ELIGIBLE_GROUPS = frozenset({
    "meal", "sleep", "study", "care", "vehicle", "greeting", "health", "social",
})

# subtopic 的规范化别名：classify_topic 里 subtopic 可能缺失（默认取 intent），
# 这里兜底给一个空映射，subtopic 为空时视为 general。
_EMPTY_GROUP = "general"


def group_for_subtopic(subtopic: Optional[str]) -> str:
    """把 subtopic 收敛为 topic_group。

    Args:
        subtopic: classify_topic 的冒号后半段；None/空 → general。

    Returns:
        topic_group，如 "meal" / "sleep" / "general"。
    """
    key = str(subtopic or "").strip().lower()
    if not key:
        return _EMPTY_GROUP
    return SUBTOPIC_GROUP_MAP.get(key, _EMPTY_GROUP)


def group_for_topic_label(topic_label: Optional[str]) -> str:
    """从完整题材标签 "<intent>:<subtopic>" 解析 topic_group。

    Args:
        topic_label: classify_topic 的完整输出（含冒号）。

    Returns:
        topic_group；标签非法/无冒号时按 subtopic 直接映射。
    """
    label = str(topic_label or "").strip()
    if not label:
        return _EMPTY_GROUP
    if ":" in label:
        subtopic = label.split(":", 1)[1].strip()
    else:
        subtopic = label
    return group_for_subtopic(subtopic)


def is_eligible_for_group_cooldown(group: Optional[str]) -> bool:
    """该 topic_group 是否值得参与"同组冷却"。"""
    return str(group or "") in COOLDOWN_ELIGIBLE_GROUPS


__all__ = [
    "SUBTOPIC_GROUP_MAP",
    "COOLDOWN_ELIGIBLE_GROUPS",
    "group_for_subtopic",
    "group_for_topic_label",
    "is_eligible_for_group_cooldown",
]
