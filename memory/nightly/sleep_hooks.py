"""nightly 与角色睡眠状态的轻量桥接。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Union

TargetDate = Union[date, datetime, str]


def _normalize_target_date(target_date: TargetDate) -> str:
    """统一把 nightly 日期转换为 YYYY-MM-DD 字符串。"""
    if isinstance(target_date, datetime):
        return target_date.strftime("%Y-%m-%d")
    if isinstance(target_date, date):
        return target_date.strftime("%Y-%m-%d")
    return str(target_date or "").strip()


def mark_roles_nightly_done(target_date: TargetDate) -> None:
    """为角色睡眠系统写入当日 nightly 完成标记。"""
    date_str = _normalize_target_date(target_date)
    if not date_str:
        return

    from core.services.life_simulation.sleep_manager import get_sleep_manager

    sleep_manager = get_sleep_manager()
    for role_id in ("aveline", "ling"):
        sleep_manager.mark_nightly_done(role_id, date_str)
