"""
角色日常活动状态同步辅助。

负责在活动切换时及时落盘，避免磁盘状态长期停留在过时的瞬时态。
"""

from datetime import datetime
from typing import Callable, Iterable

from core.services.character_daily.activity_model import DailyPlan, DailyState


def sync_current_activities(
    state: DailyState,
    role_ids: Iterable[str],
    updater: Callable[[DailyPlan, datetime], None],
    store,
    now: datetime,
    execution_updater: Callable[[DailyPlan, datetime], bool] | None = None,
) -> bool:
    """刷新当前活动；若有变更则保存状态。"""
    changed = False
    for role_id in role_ids:
        plan = state.get_plan(role_id)
        if not plan:
            continue

        previous = plan.current_activity
        updater(plan, now)
        if plan.current_activity != previous:
            changed = True
        if execution_updater and execution_updater(plan, now):
            changed = True

    if changed:
        store.save(state)
    return changed
