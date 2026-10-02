"""角色日常计划执行态与活动副作用收口。"""

from __future__ import annotations
from core.utils.logger import get_logger


import time
from datetime import datetime

from core.services.character_daily.activity_model import (
    ActivityExecutionStatus,
    ActivitySlot,
    ActivityType,
    DailyPlan,
    normalize_datetime_for_reference,
)
from core.services.life_simulation.meal_policy import get_meal_window

logger = get_logger(__name__)

_MEAL_ACTIVITY_TO_WINDOW = {
    ActivityType.BREAKFAST: "breakfast",
    ActivityType.LUNCH: "lunch",
    ActivityType.DINNER: "dinner",
}
_COOKING_OUTPUTS = {
    "breakfast": {
        "aveline": ("sandwich", "soy_milk"),
        "ling": ("yogurt", "soy_milk"),
        "default": ("sandwich", "soy_milk"),
    },
    "lunch": {
        "aveline": ("fried_rice",),
        "ling": ("sandwich",),
        "default": ("fried_rice",),
    },
    "dinner": {
        "aveline": ("beef_noodle",),
        "ling": ("fried_rice",),
        "default": ("beef_noodle",),
    },
    "off_hours": {
        "default": ("sandwich",),
    },
}


def sync_plan_execution(plan: DailyPlan, now: datetime) -> bool:
    """同步单个计划的执行状态；返回是否有变化。"""
    changed = False
    current_slot = plan.find_current_slot(now)

    for slot in plan.slots:
        if slot is current_slot:
            changed = _mark_slot_in_progress(slot, now) or changed
            continue
        if (
            slot.execution_status == ActivityExecutionStatus.COMPLETED
            and slot.activity == ActivityType.COOKING
            and not slot.produced_food_ids
        ):
            produced_food_ids = _produce_cooking_outputs(plan, slot)
            if produced_food_ids:
                slot.produced_food_ids = produced_food_ids
                changed = True
            continue
        if _slot_is_elapsed(slot, now):
            changed = _mark_slot_completed(plan, slot, now) or changed

    return changed


def _mark_slot_in_progress(slot: ActivitySlot, now: datetime) -> bool:
    changed = False
    if slot.execution_status != ActivityExecutionStatus.IN_PROGRESS:
        slot.execution_status = ActivityExecutionStatus.IN_PROGRESS
        changed = True
    if not slot.started_at:
        normalized_now = normalize_datetime_for_reference(slot.planned_start, now)
        effective_start = max(slot.planned_start, normalized_now)
        slot.started_at = effective_start.isoformat()
        changed = True
    return changed


def _slot_is_elapsed(slot: ActivitySlot, now: datetime) -> bool:
    normalized_now = normalize_datetime_for_reference(slot.planned_end, now)
    return normalized_now >= slot.planned_end


def _mark_slot_completed(plan: DailyPlan, slot: ActivitySlot, now: datetime) -> bool:
    if slot.execution_status == ActivityExecutionStatus.COMPLETED:
        return False

    changed = False
    if not slot.started_at:
        slot.started_at = slot.planned_start.isoformat()
        changed = True
    slot.execution_status = ActivityExecutionStatus.COMPLETED
    slot.completed_at = slot.planned_end.isoformat()
    changed = True

    if slot.activity == ActivityType.COOKING:
        produced_food_ids = _produce_cooking_outputs(plan, slot)
        if produced_food_ids and produced_food_ids != slot.produced_food_ids:
            slot.produced_food_ids = produced_food_ids
    return changed


def _produce_cooking_outputs(plan: DailyPlan, slot: ActivitySlot) -> list[str]:
    if slot.produced_food_ids:
        return list(slot.produced_food_ids)

    try:
        from core.food.data import get_food
        from core.services.life_simulation.service import get_life_simulation_service
    except Exception as exc:
        logger.warning("CharacterDaily: 做饭产物初始化失败: %s", exc)
        return []

    meal_window = _resolve_cooking_meal_window(plan, slot)

    # 优先读 food_cravings（角色嘴馋清单），未匹配再回退到默认 _COOKING_OUTPUTS 映射
    candidate_ids = _resolve_craving_output_ids(meal_window)
    craving_satisfied: list[str] = []
    if not candidate_ids:
        candidate_ids = list(_resolve_cooking_output_ids(plan.role_id, meal_window))
    else:
        craving_satisfied = list(candidate_ids)
    if not candidate_ids:
        return []

    life_service = get_life_simulation_service()
    produced_ids: list[str] = []
    base_ts = max(time.time(), slot.planned_end.timestamp())
    for food_id in candidate_ids:
        food = get_food(food_id)
        if not food:
            logger.warning("CharacterDaily: 做饭产物缺少食物定义: %s", food_id)
            continue
        expire_at = base_ts + float(food.expire_hours) * 3600.0
        try:
            life_service.add_food_to_inventory(food.id, 1, expire_at)
        except Exception as exc:
            logger.warning("CharacterDaily: 做饭产物入库失败 role=%s food=%s err=%s", plan.role_id, food.id, exc)
            continue
        produced_ids.append(food.id)

    # 标记对应的 craving 为已满足（做饭产出方式）
    for food_id in craving_satisfied:
        try:
            life_service.mark_craving_satisfied(food_id, satisfied_by="cooking")
        except Exception as exc:
            logger.warning("CharacterDaily: 标记craving已满足失败 food=%s err=%s", food_id, exc)

    if produced_ids:
        source_tag = "craving" if craving_satisfied else "default"
        logger.info(
            "CharacterDaily: 做饭已产出可食用库存 role=%s meal_window=%s source=%s foods=%s",
            plan.role_id,
            meal_window,
            source_tag,
            ",".join(produced_ids),
        )
    return produced_ids


def _resolve_craving_output_ids(meal_window: str) -> list[str]:
    """从角色嘴馋清单里挑出适合本餐窗的产物（最多 2 个）。

    规则：
    - 早餐窗（breakfast）偏好小吃/粥/早茶点心，允许 drink
    - 午餐/晚餐窗偏好正餐（meal），snack 仅作 fallback
    - 非餐时（off_hours）允许任意类型，但只取最近 1 条
    - 总数上限 2，按 added_at 倒序（最近想要的优先）
    """
    try:
        from core.services.life_simulation.service import get_life_simulation_service
    except Exception:
        return []
    life_service = get_life_simulation_service()
    try:
        cravings = life_service.get_food_cravings(only_active=True)
    except Exception as exc:
        logger.warning("CharacterDaily: 读取cravings失败 err=%s", exc)
        return []
    if not cravings:
        return []

    # 餐窗偏好类型映射
    preferred_types: tuple[str, ...]
    fallback_types: tuple[str, ...]
    max_count: int
    if meal_window == "breakfast":
        preferred_types = ("meal", "snack", "drink")
        fallback_types = ("snack", "drink")
        max_count = 2
    elif meal_window in ("lunch", "dinner"):
        preferred_types = ("meal",)
        fallback_types = ("snack",)
        max_count = 2
    else:  # off_hours
        preferred_types = ("snack", "drink", "meal")
        fallback_types = ()
        max_count = 1

    picked: list[str] = []
    seen: set[str] = set()
    # 第一轮：偏好类型
    for item in cravings:
        if len(picked) >= max_count:
            break
        food_id = str(item.get("food_id") or "").strip()
        food_type = str(item.get("food_type") or "").strip()
        if not food_id or food_id in seen:
            continue
        if food_type in preferred_types:
            picked.append(food_id)
            seen.add(food_id)
    # 第二轮：fallback（仅当首轮没拿满时）
    if len(picked) < max_count and fallback_types:
        for item in cravings:
            if len(picked) >= max_count:
                break
            food_id = str(item.get("food_id") or "").strip()
            food_type = str(item.get("food_type") or "").strip()
            if not food_id or food_id in seen:
                continue
            if food_type in fallback_types:
                picked.append(food_id)
                seen.add(food_id)
    return picked


def _resolve_cooking_meal_window(plan: DailyPlan, slot: ActivitySlot) -> str:
    next_slot = _find_next_slot(plan, slot)
    if next_slot and next_slot.activity in _MEAL_ACTIVITY_TO_WINDOW:
        return _MEAL_ACTIVITY_TO_WINDOW[next_slot.activity]
    return get_meal_window(slot.planned_end.timestamp())


def _find_next_slot(plan: DailyPlan, target_slot: ActivitySlot) -> ActivitySlot | None:
    for index, slot in enumerate(plan.slots):
        if slot is not target_slot:
            continue
        if index + 1 < len(plan.slots):
            return plan.slots[index + 1]
        return None
    return None


def _resolve_cooking_output_ids(role_id: str, meal_window: str) -> tuple[str, ...]:
    mapping = _COOKING_OUTPUTS.get(meal_window) or _COOKING_OUTPUTS["off_hours"]
    role_key = str(role_id or "").strip().lower()
    return tuple(mapping.get(role_key) or mapping.get("default") or ())
