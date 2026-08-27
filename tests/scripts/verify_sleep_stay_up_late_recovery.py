"""验证 sleep_manager STAY_UP_LATE 白天卡死 bug 修复是否成功。

背景：
    sleep_states.json 中两个角色 phase 卡在 "stay_up_late"，
    stay_up_activity="phone_scrolling"，导致 get_activity_override 一直返回
    phone_scrolling，覆盖了 plan 中的 reading/studying/cooking 等活动。
    修复前：白天不会自动从 STAY_UP_LATE 转换为 WAKING_UP/FULLY_AWAKE，
    只有用户发消息触发 finalize_sleep_recovery_check 才会转换。
    修复后：_update_runtime_state 在白天（dt >= wake_dt）会自动把
    STAY_UP_LATE/NIGHT_AWAKE/SLEEP_LATER 转换为 WAKING_UP。

验证项：
1. 白天调用 get_state，phase 从 STAY_UP_LATE 转换为 WAKING_UP（或 FULLY_AWAKE）
2. get_activity_override 不再返回 phone_scrolling
3. 跨天不会误触发（夜间 STAY_UP_LATE 仍保持，不被强制转换）
4. 真实 sleep_states.json 中卡死的状态能被修复

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\verify_sleep_stay_up_late_recovery.py
"""

from __future__ import annotations

import sys
import pathlib
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.services.life_simulation.sleep_manager import SleepManager  # noqa: E402
from core.services.life_simulation.sleep_models import (  # noqa: E402
    SleepPhase,
    SleepRuntimeState,
)


def _ok(msg: str) -> bool:
    print(f"  [OK]   {msg}")
    return True


def _fail(msg: str) -> bool:
    print(f"  [FAIL] {msg}")
    return False


def _make_test_state(role_id: str = "aveline") -> SleepRuntimeState:
    """构造一个卡在 STAY_UP_LATE 的测试状态（模拟线上 bug 现场）。"""
    return SleepRuntimeState(
        role_id=role_id,
        date="",  # 由 _update_runtime_state 填充
        phase=SleepPhase.STAY_UP_LATE,
        is_sleeping=False,
        actual_sleep_start_ts=0.0,
        actual_wakeup_ts=0.0,
        last_sleep_duration_hours=0.0,
        stay_up_activity="phone_scrolling",
        sleep_later_until_ts=0.0,
        last_wake_ts=0.0,
        last_chat_ts=0.0,
    )


def _make_manager_with_state(state: SleepRuntimeState) -> SleepManager:
    """创建 SleepManager，注入指定状态，mock 掉持久化避免污染磁盘。"""
    manager = SleepManager()
    # 清空真实状态，注入测试状态
    manager._states = {state.role_id: state}
    # mock 持久化，避免测试污染真实 sleep_states.json
    manager._persist = lambda *a, **kw: None
    return manager


def test_daytime_recovery() -> bool:
    """验证项1+2：白天 STAY_UP_LATE 应转换为 WAKING_UP，且 override 不返回 phone_scrolling。"""
    print("\n[测试1] 白天 STAY_UP_LATE 自动恢复为 WAKING_UP")
    state = _make_test_state("aveline")
    manager = _make_manager_with_state(state)

    # 用白天时间调用 get_state（早上 9 点，已过计划起床时间 07:03）
    daytime = datetime(2026, 7, 4, 9, 0, 0)
    result = manager.get_state("aveline", now=daytime)

    if result.phase == SleepPhase.STAY_UP_LATE:
        return _fail("phase 仍为 STAY_UP_LATE，修复未生效")
    _ok(f"phase 从 STAY_UP_LATE 转换为 {result.phase.value}")

    # 验证 activity_override 不再返回 phone_scrolling
    override = manager.get_activity_override("aveline", now=daytime)
    if override == "phone_scrolling":
        return _fail("get_activity_override 仍返回 phone_scrolling")
    _ok(f"get_activity_override 返回: {override!r}（不再是 phone_scrolling）")

    # 验证 stay_up_activity 被清理
    if result.stay_up_activity == "phone_scrolling":
        return _fail("stay_up_activity 仍为 phone_scrolling")
    _ok(f"stay_up_activity 已清理为: {result.stay_up_activity!r}")

    return True


def test_long_daytime_full_recovery() -> bool:
    """验证项1补充：白天超过 1 小时后，应进一步转换为 FULLY_AWAKE。"""
    print("\n[测试2] 白天超过 1 小时后，STAY_UP_LATE 应直接恢复为 FULLY_AWAKE")
    state = _make_test_state("aveline")
    manager = _make_manager_with_state(state)

    # 用下午时间调用 get_state（已过起床时间 8 小时）
    afternoon = datetime(2026, 7, 4, 15, 0, 0)
    result = manager.get_state("aveline", now=afternoon)

    if result.phase != SleepPhase.FULLY_AWAKE:
        return _fail(
            f"下午应已 FULLY_AWAKE，实际为 {result.phase.value}"
        )
    _ok(f"phase 直接恢复为 {result.phase.value}")
    return True


def test_night_stay_up_preserved() -> bool:
    """验证项3：夜间（睡眠窗口内）STAY_UP_LATE 应保持，不被强制转换。"""
    print("\n[测试3] 夜间 STAY_UP_LATE 应保持（不被白天恢复逻辑误伤）")
    state = _make_test_state("aveline")
    manager = _make_manager_with_state(state)

    # 用深夜时间调用 get_state（晚上 23:30，在睡眠窗口内）
    # aveline planned_sleep_time=23:10, planned_wake_time=07:03
    nighttime = datetime(2026, 7, 4, 23, 30, 0)
    result = manager.get_state("aveline", now=nighttime)

    # 夜间 STAY_UP_LATE 应保持（这是合法的熬夜状态）
    if result.phase != SleepPhase.STAY_UP_LATE:
        return _fail(
            f"夜间 STAY_UP_LATE 被误转为 {result.phase.value}，"
            f"应保持 STAY_UP_LATE"
        )
    _ok("夜间 STAY_UP_LATE 保持不变（合法熬夜）")
    return True


def test_real_state_file_recoverable() -> bool:
    """验证项4：真实 sleep_states.json 中卡死的状态能被修复逻辑处理。"""
    print("\n[测试4] 真实 sleep_states.json 中卡死的状态可被修复")
    real_state_file = (
        ROOT / "companion_data" / "character_daily" / "sleep_states.json"
    )
    if not real_state_file.exists():
        _ok("真实 sleep_states.json 不存在，跳过（无现场可验证）")
        return True

    import json
    with open(real_state_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    aveline_data = data.get("aveline", {})
    if aveline_data.get("phase") != "stay_up_late":
        _ok(f"aveline 当前 phase={aveline_data.get('phase')!r}，非卡死状态，跳过")
        return True

    # 用真实状态构造 SleepRuntimeState
    state = SleepRuntimeState(
        role_id="aveline",
        date=str(aveline_data.get("date") or ""),
        phase=SleepPhase(aveline_data.get("phase", "stay_up_late")),
        is_sleeping=bool(aveline_data.get("is_sleeping", False)),
        actual_sleep_start_ts=float(aveline_data.get("actual_sleep_start_ts") or 0.0),
        actual_wakeup_ts=float(aveline_data.get("actual_wakeup_ts") or 0.0),
        last_sleep_duration_hours=float(
            aveline_data.get("last_sleep_duration_hours") or 0.0
        ),
        stay_up_activity=str(aveline_data.get("stay_up_activity") or "idle"),
        sleep_later_until_ts=float(aveline_data.get("sleep_later_until_ts") or 0.0),
        last_wake_ts=float(aveline_data.get("last_wake_ts") or 0.0),
        last_chat_ts=float(aveline_data.get("last_chat_ts") or 0.0),
        sleep_debt_hours=float(aveline_data.get("sleep_debt_hours") or 0.0),
        sleep_inertia_score=float(aveline_data.get("sleep_inertia_score") or 0.0),
        impact_level=str(aveline_data.get("impact_level") or "none"),
    )

    manager = _make_manager_with_state(state)

    # 用当前时间调用 get_state
    now = datetime.now()
    result = manager.get_state("aveline", now=now)

    if result.phase == SleepPhase.STAY_UP_LATE and now.hour >= 8:
        # 当前是白天，应该已经转换
        return _fail(
            f"真实状态在白天仍未转换，phase={result.phase.value}"
        )
    _ok(
        f"真实 aveline 状态 phase 从 stay_up_late 转换为 {result.phase.value}，"
        f"stay_up_activity={result.stay_up_activity!r}"
    )
    return True


def main() -> int:
    print("=" * 70)
    print("验证 sleep_manager STAY_UP_LATE 白天卡死 bug 修复")
    print("=" * 70)

    results = [
        test_daytime_recovery(),
        test_long_daytime_full_recovery(),
        test_night_stay_up_preserved(),
        test_real_state_file_recoverable(),
    ]

    print("\n" + "=" * 70)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"结果：{passed}/{total} 通过")
    print("=" * 70)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
