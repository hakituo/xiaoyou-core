"""进食系统与角色睡眠/活动状态的联动辅助。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.utils.time_utils import get_current_time

from .sleep_models import SleepPhase

_SLEEP_BLOCK_PHASES = {
    SleepPhase.PREPARING_SLEEP.value,
    SleepPhase.FALLING_ASLEEP.value,
    SleepPhase.SLEEPING.value,
}
_HARD_BLOCK_ACTIVITIES = {
    "sleeping",
    "napping",
    "self_care",
}
_LIMITED_ACTIVITIES = {
    "waking_up",
    "overslept_recovery",
    "sleep_recovery",
    "studying",
    "cooking",
    "shopping",
    "walking",
    "housework",
    "exercising",
}


@dataclass(frozen=True)
class AutoEatGateDecision:
    """自动进食门控结果。"""

    allowed: bool
    reason: str
    target_type: str = ""


def resolve_role_auto_eat_context(
    role_id: str,
    *,
    fallback_activity: str = "idle",
) -> Dict[str, Any]:
    """获取角色自动进食决策需要的统一上下文。"""
    from .sleep_manager import get_sleep_manager

    summary = get_sleep_manager().get_summary(role_id)
    activity = str(fallback_activity or "").strip() or "idle"

    try:
        from core.services.character_daily import get_character_daily_engine

        engine = get_character_daily_engine()
        if engine is not None:
            activity_obj = engine.get_current_activity(role_id)
            activity = str(getattr(activity_obj, "value", activity_obj) or activity)
    except Exception:
        pass

    if not activity and bool(summary.get("is_sleeping")):
        activity = SleepPhase.SLEEPING.value
    return {
        "sleep_summary": summary,
        "current_activity": activity or "idle",
    }


def role_can_late_snack(role_id: str) -> bool:
    """判断角色当前是否允许走夜宵支路。"""
    from .sleep_manager import get_sleep_manager

    summary = get_sleep_manager().get_summary(role_id)
    return str(summary.get("phase") or "") in {
        SleepPhase.STAY_UP_LATE.value,
        SleepPhase.SLEEP_LATER.value,
    }


def evaluate_auto_eat_gate(
    role_id: str,
    *,
    now_ts: float,
    hunger: float,
    thirst: float,
    target_type: str,
    fallback_activity: str = "idle",
    sleep_summary: Optional[Dict[str, Any]] = None,
    current_activity: str = "",
) -> AutoEatGateDecision:
    """根据角色睡眠/活动状态决定当前是否允许自动进食。"""
    context = {}
    if sleep_summary is None or not current_activity:
        context = resolve_role_auto_eat_context(
            role_id,
            fallback_activity=fallback_activity,
        )
    sleep_summary = sleep_summary or context.get("sleep_summary") or {}
    activity = str(current_activity or context.get("current_activity") or fallback_activity or "idle")
    phase = str(sleep_summary.get("phase") or "")
    is_sleeping = bool(sleep_summary.get("is_sleeping"))

    target = str(target_type or "snack")
    critical_hunger = hunger < 18.0
    critical_thirst = thirst < 25.0
    meal_window = _get_meal_window(now_ts)

    if is_sleeping or phase in _SLEEP_BLOCK_PHASES or activity in _HARD_BLOCK_ACTIVITIES:
        return AutoEatGateDecision(
            allowed=False,
            reason=f"{role_id} 当前处于睡眠/不可打扰状态({phase or activity})",
        )

    if phase == SleepPhase.NIGHT_AWAKE.value:
        if critical_thirst:
            return AutoEatGateDecision(True, f"{role_id} 夜醒补水", target_type="drink")
        if critical_hunger:
            return AutoEatGateDecision(True, f"{role_id} 夜醒少量补给", target_type="snack")
        return AutoEatGateDecision(False, f"{role_id} 夜醒但未达到补给阈值")

    if phase == SleepPhase.WAKING_UP.value or activity in {
        "waking_up",
        "overslept_recovery",
        "sleep_recovery",
    }:
        if thirst < 45.0:
            return AutoEatGateDecision(True, f"{role_id} 起床恢复期先补水", target_type="drink")
        if critical_hunger:
            return AutoEatGateDecision(True, f"{role_id} 起床恢复期先轻食", target_type="snack")
        return AutoEatGateDecision(False, f"{role_id} 处于起床恢复期，暂不自动进食")

    if activity in _LIMITED_ACTIVITIES:
        if critical_thirst:
            return AutoEatGateDecision(True, f"{role_id} 忙碌状态优先补水", target_type="drink")
        if critical_hunger:
            return AutoEatGateDecision(True, f"{role_id} 忙碌状态仅允许轻食补给", target_type="snack")
        return AutoEatGateDecision(False, f"{role_id} 当前活动忙碌({activity})，未达到进食阈值")

    if target == "meal" and phase in {
        SleepPhase.STAY_UP_LATE.value,
        SleepPhase.SLEEP_LATER.value,
    } and meal_window == "late_night":
        return AutoEatGateDecision(True, f"{role_id} 深夜熬夜不应吃正餐，降级为轻食", target_type="snack")

    return AutoEatGateDecision(True, f"{role_id} 当前允许自动进食", target_type=target)


def apply_late_snack_penalty(role_id: str, penalty: float = 4.0) -> bool:
    """把夜宵对睡眠质量的影响回写到睡眠事实源。"""
    from .sleep_manager import get_sleep_manager

    sleep_manager = get_sleep_manager()
    now = get_current_time()
    state = sleep_manager.get_state(role_id, now=now)
    if state.phase not in {SleepPhase.STAY_UP_LATE, SleepPhase.SLEEP_LATER, SleepPhase.NIGHT_AWAKE}:
        return False
    state.sleep_quality_score = max(25.0, state.sleep_quality_score - max(0.0, float(penalty or 0.0)))
    state.quality_impact.reason = "late_snack"
    state.push_event("late_snack", now.timestamp(), detail="夜间进食轻微拉低睡眠质量")
    sleep_manager._persist()
    return True


def record_food_event(role_id: str, event: Dict[str, Any]) -> None:
    """写入生命模拟中的进食事件台账。"""
    from .service import get_life_simulation_service

    life_service = get_life_simulation_service()
    if hasattr(life_service, "food_system") and life_service.food_system:
        life_service.food_system.record_food_event(role_id=role_id, **event)


def _get_meal_window(now_ts: float) -> str:
    """延迟导入餐窗逻辑，避免循环依赖。"""
    from .meal_policy import get_meal_window

    return get_meal_window(now_ts)
