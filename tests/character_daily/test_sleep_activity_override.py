"""睡眠状态对角色计划活动覆盖的回归测试。"""

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from core.services.character_daily.activity_model import (
    ActivitySlot,
    ActivityType,
    DailyPlan,
)
from core.services.character_daily.engine import CharacterDailyEngine
from core.services.life_simulation.sleep_manager import SleepManager
from core.services.life_simulation.sleep_models import SleepPhase
from core.services.life_simulation.sleep_state_store import SleepStateStore


def _build_engine_with_sleep_manager(sleep_manager: SleepManager) -> CharacterDailyEngine:
    engine = CharacterDailyEngine.__new__(CharacterDailyEngine)
    engine._sleep_manager = sleep_manager
    return engine


def _build_reading_plan(now: datetime) -> DailyPlan:
    return DailyPlan(
        role_id="aveline",
        date=now.strftime("%Y-%m-%d"),
        slots=[
            ActivitySlot(
                activity=ActivityType.READING,
                planned_start=now.replace(hour=11, minute=0, second=0, microsecond=0),
                planned_end=now.replace(hour=12, minute=0, second=0, microsecond=0),
                chat_eligible=True,
            )
        ],
    )


def test_fully_awake_no_longer_overrides_planned_activity() -> None:
    now = datetime(2026, 7, 4, 11, 15, 0)
    with TemporaryDirectory() as tmp_dir:
        manager = SleepManager(store=SleepStateStore(Path(tmp_dir)))
        state = manager.get_state("aveline", now=now)
        state.phase = SleepPhase.FULLY_AWAKE
        state.is_sleeping = False
        state.actual_wakeup_ts = (now - timedelta(hours=4)).timestamp()
        state.last_wake_ts = state.actual_wakeup_ts
        state.sleep_inertia_score = 30.0
        state.impact_level = "severe"
        manager._persist()

        plan = _build_reading_plan(now)
        engine = _build_engine_with_sleep_manager(manager)

        engine._update_current_activity(plan, now)

        assert plan.current_activity == ActivityType.READING


def test_waking_up_override_only_keeps_short_window() -> None:
    now = datetime(2026, 7, 4, 7, 12, 0)
    with TemporaryDirectory() as tmp_dir:
        manager = SleepManager(store=SleepStateStore(Path(tmp_dir)))
        state = manager.get_state("aveline", now=now)
        state.phase = SleepPhase.WAKING_UP
        state.is_sleeping = False
        state.actual_wakeup_ts = (now - timedelta(minutes=5)).timestamp()
        state.last_wake_ts = state.actual_wakeup_ts
        state.sleep_inertia_score = 24.0
        manager._persist()

        assert manager.get_activity_override("aveline", now=now) == "waking_up"

        state.actual_wakeup_ts = (now - timedelta(minutes=35)).timestamp()
        state.last_wake_ts = state.actual_wakeup_ts
        manager._persist()

        assert manager.get_activity_override("aveline", now=now) is None


def test_sleep_recovery_keeps_idle_gap_when_no_real_slot() -> None:
    now = datetime(2026, 7, 4, 10, 20, 0)
    with TemporaryDirectory() as tmp_dir:
        manager = SleepManager(store=SleepStateStore(Path(tmp_dir)))
        state = manager.get_state("aveline", now=now)
        state.phase = SleepPhase.FULLY_AWAKE
        state.is_sleeping = False
        state.actual_wakeup_ts = (now - timedelta(hours=2)).timestamp()
        state.last_wake_ts = state.actual_wakeup_ts
        state.sleep_inertia_score = 18.0
        state.impact_level = "medium"
        manager._persist()

        plan = DailyPlan(role_id="aveline", date=now.strftime("%Y-%m-%d"), slots=[])
        engine = _build_engine_with_sleep_manager(manager)

        engine._update_current_activity(plan, now)

        assert plan.current_activity == ActivityType.SLEEP_RECOVERY


def test_fully_awake_with_overslept_does_not_enter_dnd() -> None:
    """角色被 /wake 唤醒后 phase=fully_awake，但 overslept 标记未清，
    不应继续按 overslept_recovery（DND）处理，否则 reply_policy 会静默累积消息。

    复现 issue：用户 /wake 后发消息，reply_policy 仍判定 dnd_sleeping_silent。
    """
    now = datetime(2026, 7, 4, 13, 25, 0)
    with TemporaryDirectory() as tmp_dir:
        manager = SleepManager(store=SleepStateStore(Path(tmp_dir)))
        state = manager.get_state("aveline", now=now)
        state.phase = SleepPhase.FULLY_AWAKE
        state.is_sleeping = False
        state.actual_wakeup_ts = (now - timedelta(hours=6)).timestamp()
        state.last_wake_ts = state.actual_wakeup_ts
        state.overslept = True  # 残留的睡过头标记
        state.sleep_inertia_score = 5.0
        state.impact_level = "none"
        manager._persist()

        plan = DailyPlan(role_id="aveline", date=now.strftime("%Y-%m-%d"), slots=[])
        engine = _build_engine_with_sleep_manager(manager)

        engine._update_current_activity(plan, now)

        assert plan.current_activity != ActivityType.OVERSLEPT_RECOVERY
        # 空闲计划且 impact_level=none，应直接走 planned_activity（IDLE）
        assert plan.current_activity == ActivityType.IDLE


def test_night_awake_with_overslept_does_not_enter_dnd() -> None:
    """半夜被 /wake 叫醒后 phase=night_awake，即便 overslept=True 也不应进入 DND。"""
    now = datetime(2026, 7, 4, 13, 25, 0)
    with TemporaryDirectory() as tmp_dir:
        manager = SleepManager(store=SleepStateStore(Path(tmp_dir)))
        state = manager.get_state("aveline", now=now)
        state.phase = SleepPhase.NIGHT_AWAKE
        state.is_sleeping = False
        state.actual_wakeup_ts = (now - timedelta(minutes=10)).timestamp()
        state.last_wake_ts = state.actual_wakeup_ts
        state.overslept = True
        manager._persist()

        plan = DailyPlan(role_id="aveline", date=now.strftime("%Y-%m-%d"), slots=[])
        engine = _build_engine_with_sleep_manager(manager)

        engine._update_current_activity(plan, now)

        assert plan.current_activity != ActivityType.OVERSLEPT_RECOVERY


def test_waking_up_with_overslept_keeps_overslept_recovery() -> None:
    """phase=waking_up 时 overslept 标记仍应生效，保持原 DND 行为。"""
    now = datetime(2026, 7, 4, 7, 50, 0)
    with TemporaryDirectory() as tmp_dir:
        manager = SleepManager(store=SleepStateStore(Path(tmp_dir)))
        state = manager.get_state("aveline", now=now)
        state.phase = SleepPhase.WAKING_UP
        state.is_sleeping = False
        state.actual_wakeup_ts = (now - timedelta(minutes=5)).timestamp()
        state.last_wake_ts = state.actual_wakeup_ts
        state.overslept = True
        state.sleep_inertia_score = 5.0
        state.impact_level = "none"
        manager._persist()

        plan = DailyPlan(role_id="aveline", date=now.strftime("%Y-%m-%d"), slots=[])
        engine = _build_engine_with_sleep_manager(manager)

        engine._update_current_activity(plan, now)

        assert plan.current_activity == ActivityType.OVERSLEPT_RECOVERY
