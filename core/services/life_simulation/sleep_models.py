"""角色睡眠运行时数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class SleepPhase(str, Enum):
    """睡眠阶段。"""

    PREPARING_SLEEP = "preparing_sleep"
    FALLING_ASLEEP = "falling_asleep"
    SLEEPING = "sleeping"
    NIGHT_AWAKE = "night_awake"
    STAY_UP_LATE = "stay_up_late"
    SLEEP_LATER = "sleep_later"
    WAKING_UP = "waking_up"
    FULLY_AWAKE = "fully_awake"


class SleepDecision(str, Enum):
    """静默恢复后的离散决策。"""

    RETURN_TO_SLEEP = "return_to_sleep"
    STAY_AWAKE = "stay_awake"
    SLEEP_LATER = "sleep_later"


@dataclass
class SleepEvent:
    """睡眠事件记录。"""

    event_type: str
    ts: float
    detail: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "ts": self.ts,
            "detail": self.detail,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SleepEvent":
        return cls(
            event_type=str(data.get("event_type") or ""),
            ts=float(data.get("ts") or 0.0),
            detail=str(data.get("detail") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class SleepQualityImpact:
    """睡眠质量影响摘要。"""

    level: str = "none"
    duration_hours: float = 0.0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "duration_hours": self.duration_hours,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SleepQualityImpact":
        return cls(
            level=str(data.get("level") or "none"),
            duration_hours=float(data.get("duration_hours") or 0.0),
            reason=str(data.get("reason") or ""),
        )


@dataclass
class NightWakeContext:
    """夜间被唤醒上下文。"""

    wake_ts: float = 0.0
    last_chat_ts: float = 0.0
    silence_window_seconds: int = 180
    wake_reason: str = ""
    messages: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wake_ts": self.wake_ts,
            "last_chat_ts": self.last_chat_ts,
            "silence_window_seconds": self.silence_window_seconds,
            "wake_reason": self.wake_reason,
            "messages": list(self.messages),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NightWakeContext":
        return cls(
            wake_ts=float(data.get("wake_ts") or 0.0),
            last_chat_ts=float(data.get("last_chat_ts") or 0.0),
            silence_window_seconds=int(data.get("silence_window_seconds") or 180),
            wake_reason=str(data.get("wake_reason") or ""),
            messages=list(data.get("messages") or []),
        )


@dataclass
class SleepRuntimeState:
    """角色睡眠运行时状态。"""

    role_id: str
    date: str = ""
    phase: SleepPhase = SleepPhase.FULLY_AWAKE
    planned_sleep_time: str = ""
    planned_wake_time: str = ""
    is_sleeping: bool = False
    actual_sleep_start_ts: float = 0.0
    actual_wakeup_ts: float = 0.0
    last_sleep_duration_hours: float = 0.0
    current_sleep_duration_hours: float = 0.0
    sleep_debt_hours: float = 0.0
    sleep_quality_score: float = 82.0
    sleep_inertia_score: float = 0.0
    nightmare_level: str = "none"
    impact_level: str = "none"
    night_wake_count: int = 0
    overslept: bool = False
    last_wake_ts: float = 0.0
    last_chat_ts: float = 0.0
    stay_up_activity: str = "idle"
    sleep_later_until_ts: float = 0.0
    nightly_done_for_date: str = ""
    patch_pending: bool = False
    recent_events: List[SleepEvent] = field(default_factory=list)
    night_wake: NightWakeContext = field(default_factory=NightWakeContext)
    quality_impact: SleepQualityImpact = field(default_factory=SleepQualityImpact)

    def push_event(self, event_type: str, ts: float, detail: str = "", **metadata: Any) -> None:
        """压入最新事件，保留最近 20 条。"""
        self.recent_events.append(
            SleepEvent(event_type=event_type, ts=ts, detail=detail, metadata=metadata)
        )
        if len(self.recent_events) > 20:
            self.recent_events = self.recent_events[-20:]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role_id": self.role_id,
            "date": self.date,
            "phase": self.phase.value,
            "planned_sleep_time": self.planned_sleep_time,
            "planned_wake_time": self.planned_wake_time,
            "is_sleeping": self.is_sleeping,
            "actual_sleep_start_ts": self.actual_sleep_start_ts,
            "actual_wakeup_ts": self.actual_wakeup_ts,
            "last_sleep_duration_hours": self.last_sleep_duration_hours,
            "current_sleep_duration_hours": self.current_sleep_duration_hours,
            "sleep_debt_hours": self.sleep_debt_hours,
            "sleep_quality_score": self.sleep_quality_score,
            "sleep_inertia_score": self.sleep_inertia_score,
            "nightmare_level": self.nightmare_level,
            "impact_level": self.impact_level,
            "night_wake_count": self.night_wake_count,
            "overslept": self.overslept,
            "last_wake_ts": self.last_wake_ts,
            "last_chat_ts": self.last_chat_ts,
            "stay_up_activity": self.stay_up_activity,
            "sleep_later_until_ts": self.sleep_later_until_ts,
            "nightly_done_for_date": self.nightly_done_for_date,
            "patch_pending": self.patch_pending,
            "recent_events": [item.to_dict() for item in self.recent_events],
            "night_wake": self.night_wake.to_dict(),
            "quality_impact": self.quality_impact.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SleepRuntimeState":
        return cls(
            role_id=str(data.get("role_id") or ""),
            date=str(data.get("date") or ""),
            phase=SleepPhase(str(data.get("phase") or SleepPhase.FULLY_AWAKE.value)),
            planned_sleep_time=str(data.get("planned_sleep_time") or ""),
            planned_wake_time=str(data.get("planned_wake_time") or ""),
            is_sleeping=bool(data.get("is_sleeping")),
            actual_sleep_start_ts=float(data.get("actual_sleep_start_ts") or 0.0),
            actual_wakeup_ts=float(data.get("actual_wakeup_ts") or 0.0),
            last_sleep_duration_hours=float(data.get("last_sleep_duration_hours") or 0.0),
            current_sleep_duration_hours=float(data.get("current_sleep_duration_hours") or 0.0),
            sleep_debt_hours=float(data.get("sleep_debt_hours") or 0.0),
            sleep_quality_score=float(data.get("sleep_quality_score") or 82.0),
            sleep_inertia_score=float(data.get("sleep_inertia_score") or 0.0),
            nightmare_level=str(data.get("nightmare_level") or "none"),
            impact_level=str(data.get("impact_level") or "none"),
            night_wake_count=int(data.get("night_wake_count") or 0),
            overslept=bool(data.get("overslept")),
            last_wake_ts=float(data.get("last_wake_ts") or 0.0),
            last_chat_ts=float(data.get("last_chat_ts") or 0.0),
            stay_up_activity=str(data.get("stay_up_activity") or "idle"),
            sleep_later_until_ts=float(data.get("sleep_later_until_ts") or 0.0),
            nightly_done_for_date=str(data.get("nightly_done_for_date") or ""),
            patch_pending=bool(data.get("patch_pending")),
            recent_events=[
                SleepEvent.from_dict(item)
                for item in list(data.get("recent_events") or [])
                if isinstance(item, dict)
            ],
            night_wake=NightWakeContext.from_dict(dict(data.get("night_wake") or {})),
            quality_impact=SleepQualityImpact.from_dict(
                dict(data.get("quality_impact") or {})
            ),
        )
