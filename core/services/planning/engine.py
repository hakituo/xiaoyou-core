"""共享的确定性候选评分与贪心排程引擎。

引擎只处理候选、分数、容量和时间冲突，不读取业务数据，也不负责持久化。
用户学习计划与角色日程分别把自己的事实转换成候选后复用这里。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Iterable, Mapping, Optional, Sequence


def stable_fraction(*parts: object) -> float:
    """根据任意稳定键返回 ``[0, 1]`` 的可复现小数。"""
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, "big") / float((1 << 64) - 1)


def stable_int(minimum: int, maximum: int, *parts: object) -> int:
    """在闭区间内生成稳定整数，用于确定性时长等业务参数。"""
    low = int(minimum)
    high = int(maximum)
    if high < low:
        low, high = high, low
    if high == low:
        return low
    span = high - low + 1
    offset = min(span - 1, int(stable_fraction(*parts) * span))
    return low + offset


def hhmm_to_minutes(value: str) -> int:
    """把 HH:MM 转成当天分钟数。"""
    hour, minute = (int(part) for part in value.split(":", 1))
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"无效时间: {value}")
    return hour * 60 + minute


def minutes_to_hhmm(value: int) -> str:
    """把当天分钟数转成 HH:MM；跨午夜值按 24 小时取模。"""
    normalized = int(value) % (24 * 60)
    return f"{normalized // 60:02d}:{normalized % 60:02d}"


@dataclass(frozen=True, slots=True)
class PlanWindow:
    """一个可排程时间窗。"""

    key: str
    start_minute: int
    end_minute: int

    @classmethod
    def from_hhmm(cls, key: str, start: str, end: str) -> "PlanWindow":
        start_minute = hhmm_to_minutes(start)
        end_minute = hhmm_to_minutes(end)
        if end_minute <= start_minute:
            end_minute += 24 * 60
        return cls(key=key, start_minute=start_minute, end_minute=end_minute)


@dataclass(frozen=True, slots=True)
class PlanCandidate:
    """由业务层提供的一项可选计划候选。"""

    key: str
    title: str
    duration_minutes: int
    base_score: float = 0.0
    category: str = "other"
    source: str = "template"
    priority: str = "normal"
    repeat_key: str = ""
    window_keys: tuple[str, ...] = ()
    fixed_start_minute: Optional[int] = None
    score_factors: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlanPolicy:
    """排程约束与统一评分权重。"""

    max_items: int = 6
    capacity_minutes: int = 240
    buffer_minutes: int = 5
    repeat_penalty: float = 7.0
    duration_penalty_per_hour: float = 1.5
    minimum_score: Optional[float] = None
    source_bonuses: Mapping[str, float] = field(
        default_factory=lambda: {
            "manual": 30.0,
            "carryover": 18.0,
            "due": 16.0,
            "weakness": 14.0,
            "template": 0.0,
        }
    )
    priority_bonuses: Mapping[str, float] = field(
        default_factory=lambda: {"high": 12.0, "normal": 4.0, "low": 0.0}
    )


@dataclass(frozen=True, slots=True)
class ScheduledCandidate:
    """完成评分并落入时间窗的候选。"""

    candidate: PlanCandidate
    start_minute: int
    end_minute: int
    score: float
    score_breakdown: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class PlanResult:
    """排程结果及未选原因。"""

    scheduled: tuple[ScheduledCandidate, ...]
    rejected: Mapping[str, str]
    used_minutes: int


class DeterministicPlanEngine:
    """稳定可复现的评分 + 贪心容量排程器。"""

    def schedule(
        self,
        *,
        plan_key: str,
        candidates: Sequence[PlanCandidate],
        windows: Sequence[PlanWindow],
        policy: PlanPolicy,
        history_counts: Optional[Mapping[str, int]] = None,
        occupied: Iterable[tuple[int, int]] = (),
    ) -> PlanResult:
        history = history_counts or {}
        window_map = {window.key: window for window in windows}
        booked = sorted((int(start), int(end)) for start, end in occupied)
        ranked = []
        for candidate in candidates:
            score, breakdown = self.score_candidate(
                plan_key=plan_key,
                candidate=candidate,
                policy=policy,
                history_count=int(history.get(candidate.repeat_key or candidate.key, 0)),
            )
            ranked.append((candidate, score, breakdown))

        ranked.sort(
            key=lambda item: (
                item[0].fixed_start_minute is None,
                -item[1],
                stable_fraction(plan_key, item[0].key),
                item[0].key,
            )
        )

        scheduled: list[ScheduledCandidate] = []
        rejected: dict[str, str] = {}
        used_minutes = 0
        for candidate, score, breakdown in ranked:
            if len(scheduled) >= max(0, policy.max_items):
                rejected[candidate.key] = "max_items"
                continue
            duration = max(1, int(candidate.duration_minutes))
            if used_minutes + duration > max(0, policy.capacity_minutes):
                rejected[candidate.key] = "capacity"
                continue
            if policy.minimum_score is not None and score < policy.minimum_score:
                rejected[candidate.key] = "score"
                continue

            slot = self._find_slot(
                candidate=candidate,
                duration=duration,
                window_map=window_map,
                booked=booked,
                buffer_minutes=max(0, int(policy.buffer_minutes)),
            )
            if slot is None:
                rejected[candidate.key] = "conflict"
                continue
            start_minute, end_minute = slot
            booked.append((start_minute, end_minute))
            booked.sort()
            used_minutes += duration
            scheduled.append(
                ScheduledCandidate(
                    candidate=candidate,
                    start_minute=start_minute,
                    end_minute=end_minute,
                    score=score,
                    score_breakdown=breakdown,
                )
            )

        scheduled.sort(key=lambda item: (item.start_minute, -item.score, item.candidate.key))
        return PlanResult(
            scheduled=tuple(scheduled),
            rejected=rejected,
            used_minutes=used_minutes,
        )

    def score_candidate(
        self,
        *,
        plan_key: str,
        candidate: PlanCandidate,
        policy: PlanPolicy,
        history_count: int = 0,
    ) -> tuple[float, dict[str, float]]:
        """计算候选分数，并保留可诊断的分项。"""
        breakdown = {
            "base": float(candidate.base_score),
            "source": float(policy.source_bonuses.get(candidate.source, 0.0)),
            "priority": float(policy.priority_bonuses.get(candidate.priority, 0.0)),
            "history": -max(0, history_count) * float(policy.repeat_penalty),
            "duration": -(
                max(0, candidate.duration_minutes) / 60.0
            ) * float(policy.duration_penalty_per_hour),
            "daily_jitter": stable_fraction(plan_key, candidate.key) * 2.0 - 1.0,
        }
        for name, value in candidate.score_factors.items():
            breakdown[str(name)] = float(value)
        return sum(breakdown.values()), breakdown

    def _find_slot(
        self,
        *,
        candidate: PlanCandidate,
        duration: int,
        window_map: Mapping[str, PlanWindow],
        booked: Sequence[tuple[int, int]],
        buffer_minutes: int,
    ) -> Optional[tuple[int, int]]:
        if candidate.fixed_start_minute is not None:
            start = int(candidate.fixed_start_minute)
            end = start + duration
            if self._fits_any_window(start, end, candidate.window_keys, window_map) and not self._overlaps(
                start, end, booked, buffer_minutes
            ):
                return start, end
            return None

        keys = candidate.window_keys or tuple(window_map)
        for key in keys:
            window = window_map.get(key)
            if window is None:
                continue
            cursor = window.start_minute
            for start, end in booked:
                if end + buffer_minutes <= cursor:
                    continue
                if start - buffer_minutes >= window.end_minute:
                    break
                if cursor + duration <= start - buffer_minutes:
                    break
                cursor = max(cursor, end + buffer_minutes)
            if cursor + duration <= window.end_minute:
                return cursor, cursor + duration
        return None

    @staticmethod
    def _fits_any_window(
        start: int,
        end: int,
        window_keys: Sequence[str],
        window_map: Mapping[str, PlanWindow],
    ) -> bool:
        keys = window_keys or tuple(window_map)
        return any(
            key in window_map
            and window_map[key].start_minute <= start
            and end <= window_map[key].end_minute
            for key in keys
        )

    @staticmethod
    def _overlaps(
        start: int,
        end: int,
        booked: Sequence[tuple[int, int]],
        buffer_minutes: int,
    ) -> bool:
        return any(
            start < booked_end + buffer_minutes
            and end > booked_start - buffer_minutes
            for booked_start, booked_end in booked
        )

__all__ = [
    "DeterministicPlanEngine",
    "PlanCandidate",
    "PlanPolicy",
    "PlanResult",
    "PlanWindow",
    "ScheduledCandidate",
    "hhmm_to_minutes",
    "minutes_to_hhmm",
    "stable_fraction",
    "stable_int",
]
