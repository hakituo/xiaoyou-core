"""自动进食的餐窗与夜宵策略。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

_MEAL_WINDOWS = (
    ("breakfast", 6 * 60, 9 * 60 + 30),
    ("lunch", 11 * 60, 14 * 60),
    ("dinner", 17 * 60, 20 * 60),
)
_LATE_SNACK_START = 22 * 60 + 30
_LATE_SNACK_END = 2 * 60
_FORMAL_MEAL_MIN_GAP_SECONDS = 4 * 3600


def get_meal_window(now_ts: float) -> str:
    """根据当前时间返回所在餐窗。"""
    now = datetime.fromtimestamp(float(now_ts or 0.0))
    minutes = now.hour * 60 + now.minute
    for name, start, end in _MEAL_WINDOWS:
        if start <= minutes < end:
            return name
    if minutes >= _LATE_SNACK_START or minutes < _LATE_SNACK_END:
        return "late_night"
    return "off_hours"


def is_late_snack_window(now_ts: float) -> bool:
    """当前是否处于夜宵窗口。"""
    return get_meal_window(now_ts) == "late_night"


def should_prefer_formal_meal(
    now_ts: float,
    hunger: float,
    last_meal: Optional[Dict[str, Any]] = None,
) -> bool:
    """判断当前是否应优先触发正餐。"""
    if hunger < 18.0:
        return True
    if get_meal_window(now_ts) not in {"breakfast", "lunch", "dinner"}:
        return False
    if hunger >= 55.0:
        return False
    if not isinstance(last_meal, dict):
        return True
    if str(last_meal.get("food_type") or "") != "meal":
        return True
    last_ts = float(last_meal.get("eaten_at_ts") or 0.0)
    return last_ts <= 0 or (float(now_ts or 0.0) - last_ts) >= _FORMAL_MEAL_MIN_GAP_SECONDS


def _is_same_calendar_day(ts_a: float, ts_b: float) -> bool:
    """两个时间戳是否属于同一自然日。"""
    try:
        return (
            datetime.fromtimestamp(float(ts_a or 0.0)).date()
            == datetime.fromtimestamp(float(ts_b or 0.0)).date()
        )
    except (ValueError, OSError, OverflowError):
        return False


def is_scheduled_meal_due(
    now_ts: float,
    last_meal: Optional[Dict[str, Any]] = None,
) -> bool:
    """按时吃饭触发：当前处于正餐窗，且当天该餐窗尚未吃过正餐。

    与"饿到阈值才吃"解耦：角色每天按点做饭，就应按点吃饭，
    而不是等 hunger 掉到 65 以下（实测 hunger 衰减极慢，几乎永远到不了）。
    同一餐窗当天已吃过正餐则不重复触发。
    """
    window = get_meal_window(now_ts)
    if window not in {"breakfast", "lunch", "dinner"}:
        return False
    if not isinstance(last_meal, dict):
        return True
    if str(last_meal.get("food_type") or "") != "meal":
        return True
    last_window = str(last_meal.get("meal_window") or "")
    last_ts = float(last_meal.get("eaten_at_ts") or 0.0)
    if last_window == window and _is_same_calendar_day(last_ts, now_ts):
        return False
    return True


def resolve_food_decision(
    now_ts: float,
    hunger: float,
    thirst: float,
    last_meal: Optional[Dict[str, Any]] = None,
    allow_late_snack: bool = False,
) -> Dict[str, Any]:
    """输出自动进食应偏向的食物类型与餐次元数据。

    优先级：危急口渴 > 极度饥饿正餐 > 按时吃饭(正餐窗) > 夜宵 > 普通补水 > 零食。
    "按时吃饭"与饥饿阈值解耦：角色每天按点做饭，就该按点吃正餐，
    而不是等 hunger 掉到 65 以下（实测 hunger 衰减极慢，几乎到不了）。
    """
    meal_window = get_meal_window(now_ts)
    if thirst < 25.0:
        return {"target_type": "drink", "meal_window": meal_window, "is_late_snack": False}
    if hunger < 18.0:
        return {"target_type": "meal", "meal_window": meal_window, "is_late_snack": False}
    if is_scheduled_meal_due(now_ts, last_meal):
        return {"target_type": "meal", "meal_window": meal_window, "is_late_snack": False}
    if allow_late_snack and is_late_snack_window(now_ts) and hunger < 55.0:
        return {"target_type": "snack", "meal_window": meal_window, "is_late_snack": True}
    if thirst < 35.0:
        return {"target_type": "drink", "meal_window": meal_window, "is_late_snack": False}
    return {"target_type": "snack", "meal_window": meal_window, "is_late_snack": False}
