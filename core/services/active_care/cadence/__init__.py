"""主动关怀频控层（cadence）

2026-09-04 改造：把"发得太频繁"从单点 cooldown 拆成多层频控守卫。

- CadenceGuard: 全局冷却 / 提问冷却 / 同组题材冷却 / 未回复抑制 / 每日软上限
- topic_groups: 题材分组（吃饭/外卖/饭到了 → meal），防止换措辞绕过冷却
"""
from core.services.active_care.cadence.cadence_guard import (
    CadenceGuard,
    CadenceVerdict,
)
from core.services.active_care.cadence.topic_groups import (
    group_for_topic_label,
    group_for_subtopic,
    is_eligible_for_group_cooldown,
)

__all__ = [
    "CadenceGuard",
    "CadenceVerdict",
    "group_for_topic_label",
    "group_for_subtopic",
    "is_eligible_for_group_cooldown",
]
