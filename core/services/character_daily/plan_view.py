"""角色日常计划展示辅助。

负责把 `DailyPlan` 转成适合工具调用返回的自然语言文本。
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from core.utils.time_utils import get_current_time

from core.services.character_daily.activity_model import (
    ActivityExecutionStatus,
    ActivitySlot,
    ActivityType,
    DailyPlan,
    normalize_datetime_for_reference,
)

ROLE_DISPLAY_NAMES = {
    "aveline": "七濑澪",
    "ling": "Ling",
}

ACTIVITY_DISPLAY_NAMES = {
    ActivityType.SLEEPING: "睡觉",
    ActivityType.WAKING_UP: "起床洗漱",
    ActivityType.BREAKFAST: "吃早饭",
    ActivityType.LUNCH: "吃午饭",
    ActivityType.DINNER: "吃晚饭",
    ActivityType.COOKING: "做饭",
    ActivityType.STUDYING: "学习/做题",
    ActivityType.READING: "看书/看番",
    ActivityType.HOUSEWORK: "做家务",
    ActivityType.NAPPING: "午休",
    ActivityType.WALKING: "散步",
    ActivityType.PHONE_SCROLLING: "刷手机",
    ActivityType.GARDENING: "浇花",
    ActivityType.EXERCISING: "运动/拉伸",
    ActivityType.GAMING: "玩游戏",
    ActivityType.SELF_CARE: "洗澡护肤/整理",
    ActivityType.CREATIVE_HOBBY: "做手工/写写画画",
    ActivityType.SHOPPING: "出门买东西",
    ActivityType.IDLE: "发呆/休息",
    ActivityType.PEER_CHAT: "和同伴聊天",
}


def get_role_display_name(role_id: str) -> str:
    """获取角色展示名。"""
    return ROLE_DISPLAY_NAMES.get(role_id, role_id)


def get_peer_role_id(role_id: str) -> str:
    """根据当前角色获取同伴角色 ID。"""
    return "ling" if role_id == "aveline" else "aveline"


def format_plan_for_tool(
    plan: Optional[DailyPlan],
    *,
    role_id: str,
    detail_level: str = "summary",
    now: Optional[datetime] = None,
) -> str:
    """格式化单个角色的计划。"""
    role_name = get_role_display_name(role_id)
    if not plan:
        return f"{role_name}当前还没有已生成的日常计划。"

    now = now or get_current_time()
    current_slot = plan.find_current_slot(now)
    lines = [f"{role_name}在 {plan.date} 的日常计划："]

    if current_slot:
        lines.append(
            "当前安排："
            f"{_format_slot(current_slot)}（正在进行）"
        )
    elif plan.current_activity:
        current_label = ACTIVITY_DISPLAY_NAMES.get(
            plan.current_activity,
            plan.current_activity.value,
        )
        lines.append(f"当前状态：{current_label}")

    lines.append(f"今日同伴聊天次数：{plan.today_peer_chat_count}")

    if detail_level == "full":
        lines.append("完整时间线：")
        lines.extend(_format_slot_lines(plan.slots))
        return "\n".join(lines)

    upcoming_slots = _pick_summary_slots(plan, now)
    if upcoming_slots:
        lines.append("接下来重点安排：")
        lines.extend(_format_slot_lines(upcoming_slots))
    else:
        lines.append("今天后面的安排暂时为空。")

    return "\n".join(lines)


def _pick_summary_slots(plan: DailyPlan, now: datetime) -> list[ActivitySlot]:
    """选择摘要模式下最值得展示的槽位。"""
    upcoming = [
        slot
        for slot in plan.slots
        if slot.planned_end
        >= normalize_datetime_for_reference(slot.planned_end, now)
    ]
    if upcoming:
        return upcoming[:4]
    return plan.slots[:4]


def _format_slot_lines(slots: Iterable[ActivitySlot]) -> list[str]:
    return [f"- {_format_slot(slot)}" for slot in slots]


def _format_slot(slot: ActivitySlot) -> str:
    activity_label = ACTIVITY_DISPLAY_NAMES.get(slot.activity, slot.activity.value)
    start = slot.planned_start.strftime("%H:%M")
    end = slot.planned_end.strftime("%H:%M")
    flexibility = "灵活" if slot.flexible else "固定"
    chat_hint = "可聊天" if slot.chat_eligible else "不适合聊天"
    status_label = _format_execution_status(slot)
    cooked_hint = ""
    if slot.activity == ActivityType.COOKING and slot.produced_food_ids:
        cooked_hint = f"，产物：{'、'.join(slot.produced_food_ids)}"
    return (
        f"{start}-{end} {activity_label}"
        f"（{flexibility}，{chat_hint}，{status_label}{cooked_hint}）"
    )


def _format_execution_status(slot: ActivitySlot) -> str:
    if slot.execution_status == ActivityExecutionStatus.COMPLETED:
        return "已完成"
    if slot.execution_status == ActivityExecutionStatus.IN_PROGRESS:
        return "进行中"
    return "未开始"
