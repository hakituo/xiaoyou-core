from __future__ import annotations

from core.services.life_simulation.life_stats import resolve_vitals_decay


def test_sleeping_decay_is_much_lower_than_old_model():
    hunger_decay, thirst_decay = resolve_vitals_decay("sleeping", sleep_phase="sleeping")

    assert hunger_decay < 0.08
    assert thirst_decay < 0.1


def test_busy_decay_is_higher_than_idle_decay():
    idle_hunger, idle_thirst = resolve_vitals_decay("idle")
    busy_hunger, busy_thirst = resolve_vitals_decay("studying")

    assert busy_hunger > idle_hunger
    assert busy_thirst > idle_thirst


def test_waking_up_decay_is_lower_than_busy_decay():
    waking_hunger, waking_thirst = resolve_vitals_decay(
        "waking_up",
        sleep_phase="waking_up",
    )
    busy_hunger, busy_thirst = resolve_vitals_decay("studying")

    assert waking_hunger < busy_hunger
    assert waking_thirst < busy_thirst


def test_severe_sleep_impact_only_adds_small_penalty():
    normal_hunger, normal_thirst = resolve_vitals_decay("idle", impact_level="none")
    severe_hunger, severe_thirst = resolve_vitals_decay("idle", impact_level="severe")

    assert severe_hunger > normal_hunger
    assert severe_thirst > normal_thirst
    assert round(severe_thirst - normal_thirst, 4) <= 0.03
