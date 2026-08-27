"""验证清醒后真实计划活动不会再被误写成 waking_up。"""

from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.services.character_daily.activity_model import (  # noqa: E402
    ActivitySlot,
    ActivityType,
    DailyPlan,
)
from core.services.character_daily.engine import CharacterDailyEngine  # noqa: E402
from core.services.life_simulation.sleep_manager import SleepManager  # noqa: E402
from core.services.life_simulation.sleep_models import SleepPhase  # noqa: E402
from core.services.life_simulation.sleep_state_store import SleepStateStore  # noqa: E402


def _build_engine_with_sleep_manager(sleep_manager: SleepManager) -> CharacterDailyEngine:
    engine = CharacterDailyEngine.__new__(CharacterDailyEngine)
    engine._sleep_manager = sleep_manager
    return engine


def main() -> int:
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

        plan = DailyPlan(
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
        engine = _build_engine_with_sleep_manager(manager)
        engine._update_current_activity(plan, now)

        if plan.current_activity != ActivityType.READING:
            raise AssertionError(
                f"真实计划活动应保持 reading，实际却是 {plan.current_activity.value}"
            )
        if manager.get_activity_override("aveline", now=now) is not None:
            raise AssertionError("fully_awake 不应继续返回 waking_up 覆盖")

    print("OK: fully_awake 后真实计划活动保持 reading，不再误写为 waking_up")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
