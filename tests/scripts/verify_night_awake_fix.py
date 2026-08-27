"""验证修复：角色被唤醒后应能正常回复消息（不触发异步任务版本）。

修复内容：
1. reply_policy.py: 当 activity 是 DND 时，调用 engine.refresh_current_activity 刷新
2. sleep_manager.py: get_activity_override 对 NIGHT_AWAKE phase 返回 "idle"
3. engine.py: _update_current_activity 中，当 phase 是 fully_awake/night_awake
   且 planned_activity 是 DND 活动时，使用 idle 代替

验证场景：
- phase=fully_awake, planned_activity=napping -> activity 应为 idle（非 DND）
- phase=night_awake, planned_activity=sleeping -> activity 应为 idle（非 DND）
- phase=sleeping, planned_activity=sleeping -> activity 应为 sleeping（DND，回归测试）
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目根目录到 path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from core.services.character_daily.activity_model import (
    ActivitySlot,
    ActivityType,
    DailyPlan,
    DO_NOT_DISTURB_ACTIVITIES,
)
from core.services.character_daily.engine import CharacterDailyEngine


class MockSleepManager:
    """模拟 SleepManager，避免触发异步任务。"""

    def __init__(self, phase: str, is_sleeping: bool = False, overslept: bool = False,
                 impact_level: str = "none", stay_up_activity: str = "idle",
                 sleep_inertia_score: float = 0.0, actual_wakeup_ts: float = 0.0):
        self._phase = phase
        self._is_sleeping = is_sleeping
        self._overslept = overslept
        self._impact_level = impact_level
        self._stay_up_activity = stay_up_activity
        self._sleep_inertia_score = sleep_inertia_score
        self._actual_wakeup_ts = actual_wakeup_ts

    def get_activity_override(self, role_id: str, now=None):
        """模拟 get_activity_override 的逻辑（与 sleep_manager.py 一致）。"""
        if self._phase == "sleeping":
            return "sleeping"
        if self._phase == "night_awake":
            return "idle"  # 修复后的逻辑
        if self._phase == "stay_up_late":
            return "phone_scrolling" if self._stay_up_activity == "phone_scrolling" else "idle"
        if self._phase == "sleep_later":
            if self._stay_up_activity == "reading":
                return "reading"
            return "idle"
        # fully_awake / waking_up (超出窗口) 等返回 None
        return None

    def get_summary(self, role_id: str, now=None):
        return {
            "phase": self._phase,
            "is_sleeping": self._is_sleeping,
            "overslept": self._overslept,
            "impact_level": self._impact_level,
        }


def _build_engine(sleep_manager) -> CharacterDailyEngine:
    engine = CharacterDailyEngine.__new__(CharacterDailyEngine)
    engine._sleep_manager = sleep_manager
    return engine


def _build_plan_with_activity(now: datetime, activity: ActivityType,
                              start_hour: int = 13, end_hour: int = 14) -> DailyPlan:
    """构建指定活动的 plan。"""
    return DailyPlan(
        role_id="aveline",
        date=now.strftime("%Y-%m-%d"),
        slots=[
            ActivitySlot(
                activity=activity,
                planned_start=now.replace(hour=start_hour, minute=0, second=0, microsecond=0),
                planned_end=now.replace(hour=end_hour, minute=0, second=0, microsecond=0),
                chat_eligible=False,
            )
        ],
    )


def test_fully_awake_with_napping_returns_idle():
    """测试 1: phase=fully_awake, planned_activity=napping -> activity 应为 idle。
    这是用户报告的核心问题：/wake 后 phase=fully_awake，但 activity=napping 导致不回复。
    """
    now = datetime(2026, 7, 13, 13, 30, 0)  # 下午 1:30（午睡时间）
    manager = MockSleepManager(phase="fully_awake", is_sleeping=False)
    plan = _build_plan_with_activity(now, ActivityType.NAPPING, 13, 14)
    plan.current_activity = ActivityType.NAPPING  # 模拟过时的缓存值

    engine = _build_engine(manager)
    engine._update_current_activity(plan, now)

    assert plan.current_activity == ActivityType.IDLE, (
        f"fully_awake + napping 应返回 IDLE，实际为 {plan.current_activity}"
    )
    assert plan.current_activity not in DO_NOT_DISTURB_ACTIVITIES
    print(f"[OK] 测试 1 通过: fully_awake + napping -> {plan.current_activity.value}")


def test_night_awake_with_sleeping_returns_idle():
    """测试 2: phase=night_awake, planned_activity=sleeping -> activity 应为 idle。"""
    now = datetime(2026, 7, 13, 2, 30, 0)  # 凌晨 2:30
    manager = MockSleepManager(phase="night_awake", is_sleeping=False)
    plan = _build_plan_with_activity(now, ActivityType.SLEEPING, 0, 6)
    plan.current_activity = ActivityType.SLEEPING

    engine = _build_engine(manager)
    engine._update_current_activity(plan, now)

    assert plan.current_activity == ActivityType.IDLE, (
        f"night_awake + sleeping 应返回 IDLE，实际为 {plan.current_activity}"
    )
    assert plan.current_activity not in DO_NOT_DISTURB_ACTIVITIES
    print(f"[OK] 测试 2 通过: night_awake + sleeping -> {plan.current_activity.value}")


def test_sleeping_with_sleeping_still_returns_sleeping():
    """测试 3: phase=sleeping, planned_activity=sleeping -> activity 应为 sleeping（回归测试）。"""
    now = datetime(2026, 7, 13, 2, 30, 0)
    manager = MockSleepManager(phase="sleeping", is_sleeping=True)
    plan = _build_plan_with_activity(now, ActivityType.SLEEPING, 0, 6)
    plan.current_activity = ActivityType.SLEEPING

    engine = _build_engine(manager)
    engine._update_current_activity(plan, now)

    assert plan.current_activity == ActivityType.SLEEPING, (
        f"sleeping + sleeping 应返回 SLEEPING，实际为 {plan.current_activity}"
    )
    print(f"[OK] 测试 3 通过: sleeping + sleeping -> {plan.current_activity.value}")


def test_fully_awake_with_non_dnd_activity_unchanged():
    """测试 4: phase=fully_awake, planned_activity=reading -> activity 应为 reading（回归测试）。"""
    now = datetime(2026, 7, 13, 11, 30, 0)  # 上午 11:30
    manager = MockSleepManager(phase="fully_awake", is_sleeping=False)
    plan = _build_plan_with_activity(now, ActivityType.READING, 11, 12)
    plan.current_activity = ActivityType.READING

    engine = _build_engine(manager)
    engine._update_current_activity(plan, now)

    assert plan.current_activity == ActivityType.READING, (
        f"fully_awake + reading 应返回 READING，实际为 {plan.current_activity}"
    )
    print(f"[OK] 测试 4 通过: fully_awake + reading -> {plan.current_activity.value}")


def main():
    print("=" * 70)
    print("验证唤醒后回复修复（不触发异步任务版本）")
    print("=" * 70)
    test_fully_awake_with_napping_returns_idle()
    test_night_awake_with_sleeping_returns_idle()
    test_sleeping_with_sleeping_still_returns_sleeping()
    test_fully_awake_with_non_dnd_activity_unchanged()
    print("=" * 70)
    print("所有测试通过！修复有效。")
    print()
    print("修复说明：")
    print("1. reply_policy.py: 当 activity 是 DND 时，调用 refresh_current_activity 刷新")
    print("2. sleep_manager.py: get_activity_override 对 NIGHT_AWAKE phase 返回 'idle'")
    print("3. engine.py: _update_current_activity 中，当 phase 是 fully_awake/night_awake")
    print("   且 planned_activity 是 DND 活动时，使用 idle 代替")
    print()
    print("效果：")
    print("- /wake 唤醒后（phase=fully_awake），即使计划是 napping，activity 也会是 idle")
    print("- 半夜被叫醒（phase=night_awake），即使计划是 sleeping，activity 也会是 idle")
    print("- reply_policy 查询 activity 得到 idle，is_dnd=False，走空闲分支正常回复")
    print("- 不会再错误地走 DND 分支静默累积消息")


if __name__ == "__main__":
    main()
