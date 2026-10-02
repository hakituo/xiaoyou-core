from __future__ import annotations

from core.services.life_simulation.sleep_food_effects import evaluate_auto_eat_gate
from core.services.life_simulation.sleep_models import SleepPhase


def _sleep_summary(phase: SleepPhase, *, is_sleeping: bool = False) -> dict:
    return {
        "phase": phase.value,
        "is_sleeping": is_sleeping,
    }


def test_sleeping_role_cannot_auto_eat():
    gate = evaluate_auto_eat_gate(
        "aveline",
        now_ts=1751112000.0,
        hunger=8.0,
        thirst=20.0,
        target_type="meal",
        sleep_summary=_sleep_summary(SleepPhase.SLEEPING, is_sleeping=True),
        current_activity="sleeping",
    )

    assert gate.allowed is False
    assert "睡眠" in gate.reason


def test_waking_up_role_prefers_drink():
    gate = evaluate_auto_eat_gate(
        "aveline",
        now_ts=1751081400.0,
        hunger=35.0,
        thirst=30.0,
        target_type="meal",
        sleep_summary=_sleep_summary(SleepPhase.WAKING_UP, is_sleeping=False),
        current_activity="waking_up",
    )

    assert gate.allowed is True
    assert gate.target_type == "drink"


def test_busy_role_blocks_non_critical_eating():
    gate = evaluate_auto_eat_gate(
        "ling",
        now_ts=1751104800.0,
        hunger=34.0,
        thirst=40.0,
        target_type="meal",
        sleep_summary=_sleep_summary(SleepPhase.FULLY_AWAKE, is_sleeping=False),
        current_activity="studying",
    )

    assert gate.allowed is False
    assert "忙碌" in gate.reason


def test_busy_role_allows_critical_drink():
    gate = evaluate_auto_eat_gate(
        "ling",
        now_ts=1751104800.0,
        hunger=34.0,
        thirst=18.0,
        target_type="meal",
        sleep_summary=_sleep_summary(SleepPhase.FULLY_AWAKE, is_sleeping=False),
        current_activity="studying",
    )

    assert gate.allowed is True
    assert gate.target_type == "drink"


def test_night_awake_only_allows_light_refill():
    gate = evaluate_auto_eat_gate(
        "ling",
        now_ts=1751140800.0,
        hunger=16.0,
        thirst=40.0,
        target_type="meal",
        sleep_summary=_sleep_summary(SleepPhase.NIGHT_AWAKE, is_sleeping=False),
        current_activity="idle",
    )

    assert gate.allowed is True
    assert gate.target_type == "snack"
