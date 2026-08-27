"""共享确定性计划引擎单元测试。"""

from core.services.planning import (
    DeterministicPlanEngine,
    PlanCandidate,
    PlanPolicy,
    PlanWindow,
)


def _signature(result):
    return [
        (
            entry.candidate.key,
            entry.start_minute,
            entry.end_minute,
            round(entry.score, 8),
        )
        for entry in result.scheduled
    ]


def test_same_plan_key_is_stable() -> None:
    engine = DeterministicPlanEngine()
    candidates = [
        PlanCandidate(key=f"item:{index}", title=str(index), duration_minutes=30)
        for index in range(4)
    ]
    kwargs = {
        "plan_key": "user|2099-01-01",
        "candidates": candidates,
        "windows": [PlanWindow.from_hhmm("day", "09:00", "12:00")],
        "policy": PlanPolicy(max_items=3, capacity_minutes=90, buffer_minutes=0),
    }
    assert _signature(engine.schedule(**kwargs)) == _signature(engine.schedule(**kwargs))


def test_different_dates_change_stable_jitter() -> None:
    engine = DeterministicPlanEngine()
    candidate = PlanCandidate(key="same", title="同一候选", duration_minutes=30)
    policy = PlanPolicy()
    first, _ = engine.score_candidate(
        plan_key="owner|2099-01-01",
        candidate=candidate,
        policy=policy,
    )
    second, _ = engine.score_candidate(
        plan_key="owner|2099-01-02",
        candidate=candidate,
        policy=policy,
    )
    assert first != second


def test_fixed_candidate_is_scheduled_first() -> None:
    result = DeterministicPlanEngine().schedule(
        plan_key="fixed",
        candidates=[
            PlanCandidate(
                key="flexible",
                title="高分灵活项",
                duration_minutes=60,
                base_score=100,
            ),
            PlanCandidate(
                key="fixed",
                title="固定项",
                duration_minutes=60,
                base_score=-100,
                fixed_start_minute=9 * 60,
                window_keys=("day",),
            ),
        ],
        windows=[PlanWindow.from_hhmm("day", "09:00", "12:00")],
        policy=PlanPolicy(max_items=1, capacity_minutes=60, buffer_minutes=0),
    )
    assert [entry.candidate.key for entry in result.scheduled] == ["fixed"]


def test_schedule_has_no_time_conflict() -> None:
    result = DeterministicPlanEngine().schedule(
        plan_key="conflict",
        candidates=[
            PlanCandidate(key=f"item:{index}", title=str(index), duration_minutes=40)
            for index in range(4)
        ],
        windows=[PlanWindow.from_hhmm("day", "09:00", "13:00")],
        policy=PlanPolicy(max_items=4, capacity_minutes=160, buffer_minutes=10),
        occupied=[(10 * 60, 10 * 60 + 30)],
    )
    intervals = [
        (entry.start_minute, entry.end_minute) for entry in result.scheduled
    ] + [(10 * 60, 10 * 60 + 30)]
    intervals.sort()
    assert all(left[1] <= right[0] for left, right in zip(intervals, intervals[1:]))


def test_capacity_and_max_items_are_enforced() -> None:
    result = DeterministicPlanEngine().schedule(
        plan_key="limits",
        candidates=[
            PlanCandidate(key=f"item:{index}", title=str(index), duration_minutes=50)
            for index in range(6)
        ],
        windows=[PlanWindow.from_hhmm("day", "08:00", "18:00")],
        policy=PlanPolicy(max_items=3, capacity_minutes=120, buffer_minutes=0),
    )
    assert len(result.scheduled) == 2
    assert result.used_minutes == 100
    assert set(result.rejected.values()) <= {"capacity", "max_items"}


def test_repeat_penalty_lowers_selection_priority() -> None:
    engine = DeterministicPlanEngine()
    repeated = PlanCandidate(key="repeat", title="重复项", duration_minutes=60)
    fresh = PlanCandidate(key="fresh", title="新项", duration_minutes=60)
    policy = PlanPolicy(max_items=1, capacity_minutes=60, repeat_penalty=10.0)
    result = engine.schedule(
        plan_key="repeat-test",
        candidates=[repeated, fresh],
        windows=[PlanWindow.from_hhmm("day", "09:00", "12:00")],
        policy=policy,
        history_counts={"repeat": 3},
    )
    assert result.scheduled[0].candidate.key == "fresh"
    repeated_score, _ = engine.score_candidate(
        plan_key="repeat-test",
        candidate=repeated,
        policy=policy,
        history_count=3,
    )
    fresh_score, _ = engine.score_candidate(
        plan_key="repeat-test",
        candidate=repeated,
        policy=policy,
        history_count=0,
    )
    assert repeated_score < fresh_score
