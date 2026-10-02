"""工作日/休息日完整日程覆盖。

旧 character_daily.yaml 继续作为通用/兼容模板；只有在
character_day_types.yaml 明确配置的角色，才使用两套完整骨架。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from config.character_daily_config import ActivityTemplate, TimeBlock
from core.utils.common import get_project_root
from core.utils.logger import get_logger

logger = get_logger(__name__)

_CONFIG_PATH = Path(get_project_root()) / "config" / "yaml" / "character_day_types.yaml"


@dataclass(frozen=True)
class DayTypeSchedule:
    wake_time: str
    sleep_time: str
    time_blocks: List[TimeBlock] = field(default_factory=list)


@dataclass(frozen=True)
class RoleDayTypeSchedules:
    workday: Optional[DayTypeSchedule] = None
    rest_day: Optional[DayTypeSchedule] = None


def _parse_activity(data: dict) -> ActivityTemplate:
    duration = data.get("duration") or [20, 40]
    return ActivityTemplate(
        activity=str(data.get("activity") or "idle"),
        duration_min=int(duration[0]) if duration else 20,
        duration_max=int(duration[1]) if len(duration) > 1 else int(duration[0]),
        weight=float(data.get("weight", 1.0)),
    )


def _parse_block(data: dict) -> TimeBlock:
    return TimeBlock(
        period=str(data.get("period") or ""),
        start=str(data.get("start") or "00:00"),
        end=str(data.get("end") or "23:59"),
        fixed=[_parse_activity(item) for item in (data.get("fixed") or [])],
        pool=[_parse_activity(item) for item in (data.get("pool") or [])],
    )


def _parse_schedule(data: object) -> Optional[DayTypeSchedule]:
    if not isinstance(data, dict):
        return None
    blocks = [
        _parse_block(item)
        for item in (data.get("time_blocks") or [])
        if isinstance(item, dict)
    ]
    if not blocks:
        return None
    return DayTypeSchedule(
        wake_time=str(data.get("wake_time") or "07:00"),
        sleep_time=str(data.get("sleep_time") or "23:00"),
        time_blocks=blocks,
    )


def load_day_type_schedules() -> Dict[str, RoleDayTypeSchedules]:
    try:
        if not _CONFIG_PATH.exists():
            return {}
        raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        roles = raw.get("roles") if isinstance(raw, dict) else {}
        if not isinstance(roles, dict):
            return {}
        result: Dict[str, RoleDayTypeSchedules] = {}
        for role_id, role_data in roles.items():
            if not isinstance(role_data, dict):
                continue
            result[str(role_id).strip().lower()] = RoleDayTypeSchedules(
                workday=_parse_schedule(role_data.get("workday")),
                rest_day=_parse_schedule(role_data.get("rest_day")),
            )
        return result
    except Exception as exc:  # noqa: BLE001 - 覆盖模板损坏时回退旧日程
        logger.warning("加载 character_day_types.yaml 失败，回退旧日程: %s", exc)
        return {}


def resolve_day_type_schedule(
    role_id: str,
    *,
    is_rest_day: bool,
    schedules: Optional[Dict[str, RoleDayTypeSchedules]] = None,
) -> Optional[DayTypeSchedule]:
    role_schedules = (schedules or load_day_type_schedules()).get(
        str(role_id or "").strip().lower()
    )
    if role_schedules is None:
        return None
    return role_schedules.rest_day if is_rest_day else role_schedules.workday
