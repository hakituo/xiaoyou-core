"""CharacterDaily 的 Nightly 预生成任务。"""

from __future__ import annotations

import datetime
from typing import Any

from core.character.runtime_roles import filter_autonomous_roles
from core.services.character_daily.activity_instance import (
    ActivityInstanceResolver,
    ActivityInstanceStore,
)
from core.services.character_daily.config import load_schedule_templates
from core.services.character_daily.daily_plan import DailyPlanGenerator
from core.services.character_daily.state import DailyStateStore
from core.utils.logger import get_logger

logger = get_logger(__name__)


def prepare_activity_instances_for_date(
    target_date: datetime.date,
    *,
    instance_store: ActivityInstanceStore | None = None,
) -> dict[str, Any]:
    """为目标日期的自主生活角色预生成 ActivityInstance。

    Nightly 在前一晚调用。DailyPlan 仍由 CharacterDaily 自己负责；这里只用同一
    确定性生成器得到目标日槽位，然后把“今天具体怎么发生”提前解析并落盘。
    即使服务次日重启，聊天拿到的也是同一天同一份生活事实。
    """
    templates = load_schedule_templates()
    generator = DailyPlanGenerator(templates)
    role_ids = filter_autonomous_roles(generator.role_ids)
    date_str = target_date.strftime("%Y-%m-%d")
    previous_date_str = (target_date - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    previous_state = DailyStateStore().load()
    resolver = ActivityInstanceResolver()
    store = instance_store or ActivityInstanceStore()

    generated_roles: list[str] = []
    skipped_roles: list[str] = []
    resolved_count = 0
    persisted_count = 0

    for role_id in role_ids:
        previous_plan = None
        if previous_state.date == previous_date_str:
            previous_plan = previous_state.get_plan(role_id)
        try:
            plan = generator.generate(
                role_id,
                date_str,
                previous_plan=previous_plan,
            )
            if plan is None:
                skipped_roles.append(role_id)
                continue
            instances = resolver.resolve_plan(plan)
            resolved_count += len(instances)
            persisted_count += store.save_many(instances)
            generated_roles.append(role_id)
        except Exception as exc:  # noqa: BLE001 - 单角色失败不能拖垮整个 Nightly
            logger.warning(
                "Nightly ActivityInstance 生成失败 role=%s date=%s: %s",
                role_id,
                date_str,
                exc,
                exc_info=True,
            )
            skipped_roles.append(role_id)

    logger.info(
        "Nightly ActivityInstance 完成 date=%s roles=%s resolved=%d persisted=%d skipped=%s",
        date_str,
        generated_roles,
        resolved_count,
        persisted_count,
        skipped_roles,
    )
    return {
        "date": date_str,
        "roles": generated_roles,
        "skipped_roles": skipped_roles,
        "resolved_count": resolved_count,
        "persisted_count": persisted_count,
    }
