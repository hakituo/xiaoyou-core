from __future__ import annotations

from datetime import datetime
from pathlib import Path

import core.utils.atomic_io as atomic_io

from core.services.life_simulation.sleep_manager import SleepManager
from core.services.life_simulation.sleep_models import SleepPhase, SleepRuntimeState
from core.services.life_simulation.sleep_state_store import SleepStateStore


def _build_manager(tmp_path: Path) -> SleepManager:
    return SleepManager(store=SleepStateStore(tmp_path))


def test_resolve_sleep_window_for_overnight_schedule(tmp_path: Path):
    manager = _build_manager(tmp_path)
    manager._get_planned_minutes = lambda role_id, now: (23 * 60 + 50, 8 * 60 + 14)  # type: ignore[method-assign]

    now = datetime(2026, 6, 28, 16, 0, 0)
    sleep_dt, wake_dt = manager._resolve_sleep_window("aveline", now)
    next_wake_dt = manager._resolve_next_wake_dt("aveline", now)

    assert sleep_dt == datetime(2026, 6, 27, 23, 50, 0)
    assert wake_dt == datetime(2026, 6, 28, 8, 14, 0)
    assert next_wake_dt == datetime(2026, 6, 29, 8, 14, 0)


def test_resolve_sleep_window_for_after_midnight_schedule(tmp_path: Path):
    manager = _build_manager(tmp_path)
    manager._get_planned_minutes = lambda role_id, now: (36, 9 * 60 + 26)  # type: ignore[method-assign]

    now = datetime(2026, 6, 28, 16, 0, 0)
    sleep_dt, wake_dt = manager._resolve_sleep_window("ling", now)
    next_wake_dt = manager._resolve_next_wake_dt("ling", now)

    assert sleep_dt == datetime(2026, 6, 28, 0, 36, 0)
    assert wake_dt == datetime(2026, 6, 28, 9, 26, 0)
    assert next_wake_dt == datetime(2026, 6, 29, 9, 26, 0)


def test_stale_sleeping_state_recovers_to_daytime(tmp_path: Path):
    manager = _build_manager(tmp_path)
    manager._get_planned_minutes = lambda role_id, now: (36, 9 * 60 + 26)  # type: ignore[method-assign]

    state = manager.get_state("ling", now=datetime(2026, 6, 28, 0, 40, 0))
    state.phase = SleepPhase.SLEEPING
    state.is_sleeping = True
    state.actual_sleep_start_ts = datetime(2026, 6, 26, 0, 36, 0).timestamp()
    manager._persist()

    recovered = manager.get_state("ling", now=datetime(2026, 6, 28, 16, 0, 0))

    assert recovered.is_sleeping is False
    assert recovered.phase == SleepPhase.FULLY_AWAKE
    assert recovered.actual_wakeup_ts == datetime(2026, 6, 28, 9, 26, 0).timestamp()
    assert recovered.current_sleep_duration_hours == 0
    assert recovered.last_sleep_duration_hours < 10


def test_sleep_state_store_falls_back_when_replace_is_denied(
    tmp_path: Path,
    monkeypatch,
):
    store = SleepStateStore(tmp_path)
    state = SleepRuntimeState(role_id="ling", date="2026-06-28")
    state.sleep_debt_hours = 0.5
    store.save({"ling": state})

    replace_calls: list[tuple[str, str]] = []

    def _deny_replace(src: str, dst: str) -> None:
        replace_calls.append((src, dst))
        raise PermissionError("[WinError 5] 拒绝访问")

    monkeypatch.setattr(atomic_io.os, "replace", _deny_replace)

    updated = SleepRuntimeState(role_id="ling", date="2026-06-29")
    updated.phase = SleepPhase.FULLY_AWAKE
    updated.sleep_debt_hours = 1.75
    store.save({"ling": updated})

    loaded = store.load()
    assert replace_calls
    assert loaded["ling"].date == "2026-06-29"
    assert loaded["ling"].phase == SleepPhase.FULLY_AWAKE
    assert loaded["ling"].sleep_debt_hours == 1.75
    assert not list(tmp_path.glob("sleep_states.json.tmp_*"))


def test_sleep_state_store_ignores_sync_fsync_descriptor_error(
    tmp_path: Path,
    monkeypatch,
):
    store = SleepStateStore(tmp_path)
    original_open = atomic_io.os.open
    original_fsync = atomic_io.os.fsync

    def _patched_open(path: str, flags: int) -> int:
        if str(path).endswith("sleep_states.json.tmp_fake"):
            return 123456
        return original_open(path, flags)

    def _patched_generate_temp_path(file_path: str) -> str:
        return f"{file_path}.tmp_fake"

    def _patched_fsync(fd: int) -> None:
        if fd == 123456:
            raise OSError(9, "Bad file descriptor")
        original_fsync(fd)

    monkeypatch.setattr(atomic_io, "_generate_temp_path", _patched_generate_temp_path)
    monkeypatch.setattr(atomic_io.os, "open", _patched_open)
    monkeypatch.setattr(atomic_io.os, "fsync", _patched_fsync)

    updated = SleepRuntimeState(role_id="ling", date="2026-06-30")
    updated.phase = SleepPhase.FULLY_AWAKE
    updated.sleep_debt_hours = 2.25
    store.save({"ling": updated})

    loaded = store.load()
    assert loaded["ling"].date == "2026-06-30"
    assert loaded["ling"].phase == SleepPhase.FULLY_AWAKE
    assert loaded["ling"].sleep_debt_hours == 2.25
