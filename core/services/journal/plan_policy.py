"""用户主计划的确定性容量与时间窗配置。

``study.daily_study_goal_minutes`` 是每日学习量唯一真源；Journal 只定义日期时间窗、
任务数和可选 ``capacity_ratio``，不再维护另一套 120/180/240 分钟目标。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping

from core.services.planning import PlanWindow
from core.utils.common import get_project_root
from core.utils.logger import get_logger

logger = get_logger("JournalPlanPolicy")

DEFAULT_DAILY_STUDY_GOAL_MINUTES = 420


@dataclass(frozen=True, slots=True)
class JournalDayPolicy:
    """某类日期的计划容量策略。"""

    name: str
    max_items: int
    capacity_minutes: int
    windows: tuple[PlanWindow, ...]
    capacity_ratio: float = 1.0


@dataclass(frozen=True, slots=True)
class JournalPlanSettings:
    """用户主计划算法配置及安全默认值。"""

    daily_goal_minutes: int = DEFAULT_DAILY_STUDY_GOAL_MINUTES
    weekday: JournalDayPolicy = field(
        default_factory=lambda: JournalDayPolicy(
            name="weekday",
            max_items=8,
            capacity_minutes=DEFAULT_DAILY_STUDY_GOAL_MINUTES,
            capacity_ratio=1.0,
            windows=(
                PlanWindow.from_hhmm("morning", "08:00", "12:00"),
                PlanWindow.from_hhmm("afternoon", "14:00", "18:00"),
                PlanWindow.from_hhmm("evening", "19:00", "22:30"),
            ),
        )
    )
    weekend: JournalDayPolicy = field(
        default_factory=lambda: JournalDayPolicy(
            name="weekend",
            max_items=8,
            capacity_minutes=DEFAULT_DAILY_STUDY_GOAL_MINUTES,
            capacity_ratio=1.0,
            windows=(
                PlanWindow.from_hhmm("late_morning", "09:30", "12:00"),
                PlanWindow.from_hhmm("afternoon", "14:30", "18:00"),
                PlanWindow.from_hhmm("evening", "19:30", "22:00"),
            ),
        )
    )
    holiday: JournalDayPolicy = field(
        default_factory=lambda: JournalDayPolicy(
            name="holiday",
            max_items=8,
            capacity_minutes=DEFAULT_DAILY_STUDY_GOAL_MINUTES,
            capacity_ratio=1.0,
            windows=(
                PlanWindow.from_hhmm("late_morning", "10:00", "12:00"),
                PlanWindow.from_hhmm("afternoon", "15:00", "18:00"),
                PlanWindow.from_hhmm("evening", "19:30", "21:30"),
            ),
        )
    )
    holiday_month_days: frozenset[str] = frozenset({"01-01", "05-01", "10-01"})
    holiday_dates: frozenset[str] = frozenset()
    max_carryover_count: int = 2
    max_carryover_items: int = 2
    fallback_core_minutes: int = 75
    fallback_wrapup_minutes: int = 20

    def policy_for(self, target_date: date) -> JournalDayPolicy:
        """节假日优先，其次周末，否则工作日。"""
        if (
            target_date.isoformat() in self.holiday_dates
            or target_date.strftime("%m-%d") in self.holiday_month_days
        ):
            return self.holiday
        if target_date.weekday() >= 5:
            return self.weekend
        return self.weekday


def _parse_windows(
    payload: Any,
    defaults: tuple[PlanWindow, ...],
) -> tuple[PlanWindow, ...]:
    if not isinstance(payload, list):
        return defaults
    windows: list[PlanWindow] = []
    for index, raw in enumerate(payload):
        if not isinstance(raw, Mapping):
            continue
        try:
            windows.append(
                PlanWindow.from_hhmm(
                    str(raw.get("key") or f"window_{index}"),
                    str(raw.get("start") or ""),
                    str(raw.get("end") or ""),
                )
            )
        except (TypeError, ValueError):
            logger.warning("忽略无效 journal_plan 时间窗: %s", raw)
    return tuple(windows) or defaults


def _safe_goal_minutes(value: Any) -> int:
    try:
        return max(60, min(24 * 60, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_DAILY_STUDY_GOAL_MINUTES


def _parse_day_policy(
    name: str,
    payload: Any,
    default: JournalDayPolicy,
    *,
    daily_goal_minutes: int,
) -> JournalDayPolicy:
    data = payload if isinstance(payload, Mapping) else {}
    try:
        ratio = float(data.get("capacity_ratio", default.capacity_ratio))
    except (TypeError, ValueError):
        ratio = default.capacity_ratio
    ratio = max(0.1, min(2.0, ratio))
    capacity = max(30, int(round(daily_goal_minutes * ratio)))
    if "capacity_minutes" in data:
        logger.debug(
            "journal_plan.planning.%s.capacity_minutes 已废弃；"
            "容量改由 study.daily_study_goal_minutes × capacity_ratio 派生",
            name,
        )
    return JournalDayPolicy(
        name=name,
        max_items=max(0, int(data.get("max_items", default.max_items))),
        capacity_minutes=capacity,
        capacity_ratio=ratio,
        windows=_parse_windows(data.get("windows"), default.windows),
    )


def load_journal_plan_settings() -> JournalPlanSettings:
    """从 app.yaml 加载配置；缺失或损坏时完整回退安全默认值。"""
    defaults = JournalPlanSettings()
    try:
        from config.yaml_loader import load_resolved_yaml_config_from_disk

        yaml_path = get_project_root() / "config" / "yaml" / "app.yaml"
        full, _, _ = load_resolved_yaml_config_from_disk(yaml_path)
        study = full.get("study") or {}
        planning = ((full.get("journal_plan") or {}).get("planning") or {})
        if not isinstance(planning, Mapping):
            planning = {}
        daily_goal_minutes = _safe_goal_minutes(
            study.get("daily_study_goal_minutes", defaults.daily_goal_minutes)
            if isinstance(study, Mapping)
            else defaults.daily_goal_minutes
        )
        return JournalPlanSettings(
            daily_goal_minutes=daily_goal_minutes,
            weekday=_parse_day_policy(
                "weekday",
                planning.get("weekday"),
                defaults.weekday,
                daily_goal_minutes=daily_goal_minutes,
            ),
            weekend=_parse_day_policy(
                "weekend",
                planning.get("weekend"),
                defaults.weekend,
                daily_goal_minutes=daily_goal_minutes,
            ),
            holiday=_parse_day_policy(
                "holiday",
                planning.get("holiday"),
                defaults.holiday,
                daily_goal_minutes=daily_goal_minutes,
            ),
            holiday_month_days=frozenset(
                str(value) for value in planning.get("holiday_month_days", [])
            )
            or defaults.holiday_month_days,
            holiday_dates=frozenset(
                str(value) for value in planning.get("holiday_dates", [])
            ),
            max_carryover_count=max(
                0,
                int(
                    planning.get(
                        "max_carryover_count", defaults.max_carryover_count
                    )
                ),
            ),
            max_carryover_items=max(
                0,
                int(planning.get("max_carryover_items", defaults.max_carryover_items)),
            ),
            fallback_core_minutes=max(
                15,
                int(
                    planning.get(
                        "fallback_core_minutes", defaults.fallback_core_minutes
                    )
                ),
            ),
            fallback_wrapup_minutes=max(
                10,
                int(
                    planning.get(
                        "fallback_wrapup_minutes", defaults.fallback_wrapup_minutes
                    )
                ),
            ),
        )
    except Exception as exc:
        logger.debug("加载 journal_plan.planning 失败，使用安全默认值: %s", exc)
        return defaults


__all__ = [
    "DEFAULT_DAILY_STUDY_GOAL_MINUTES",
    "JournalDayPolicy",
    "JournalPlanSettings",
    "load_journal_plan_settings",
]
