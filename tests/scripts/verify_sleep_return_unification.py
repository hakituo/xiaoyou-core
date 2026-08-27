"""验证"叫醒睡回 / 打断做事"统一为同一套"交互结束→回原状态"逻辑。

覆盖：
1. 被叫醒（NIGHT_AWAKE）在静默窗口到达后确定性睡回，不再让 LLM 拖延几十分钟；
2. 静默未到（用户还在聊）时不睡回；
3. 打断做事（_decide_work_return_should_defer）在用户最近仍在聊时确定性顺延；
4. 共享判定 is_user_recently_active 在最近有/无用户消息时分别返回 True/False。
"""

import asyncio
import sys
import types
from datetime import datetime

sys.path.insert(0, r"d:\AI\xiaoyou-core")

from core.services.life_simulation.sleep_manager import SleepManager, SleepPhase
from core.services.character_daily.activity_return.core import (
    _decide_work_return_should_defer,
)
import core.services.character_daily.reply_policy_support as rps
import core.services.active_care.core.service as ac_svc


def _fake_active_care(recent_timestamp: float):
    """构造一个返回指定时间戳"最近用户消息"的假 active_care 服务。"""

    class _Ctx:
        def get_recent_user_message(self, cid):
            return {"content": "在吗", "timestamp": recent_timestamp}

    class _Ac:
        executor = types.SimpleNamespace(context=_Ctx())

    svc = _Ac() if recent_timestamp is not None else None

    def _get():
        return svc

    return _get


async def test_wake_sleep_back_deterministic():
    print("== 测试1: 被叫醒后静默到达 → 确定性睡回 ==")
    sm = SleepManager()
    role = "aveline"
    now = datetime(2026, 8, 22, 2, 0, 0)  # 深夜，处于睡眠窗口
    state = sm.get_state(role, now=now)
    state.phase = SleepPhase.NIGHT_AWAKE
    state.is_sleeping = False
    state.last_chat_ts = now.timestamp() - 300  # 300s 前最后一条用户消息（>180s 静默窗口）

    after = await sm.finalize_sleep_recovery_check(role, now=now)
    assert after.phase == SleepPhase.SLEEPING.value, f"期望睡回, 实际 {after.phase}"
    assert after.is_sleeping is True
    print("  PASS: 静默到达后已确定性睡回 (phase=sleeping)")


async def test_wake_not_yet_silent():
    print("== 测试2: 被叫醒但用户还在聊（静默未到）→ 不睡回 ==")
    sm = SleepManager()
    role = "aveline"
    now = datetime(2026, 8, 22, 2, 0, 0)
    state = sm.get_state(role, now=now)
    state.phase = SleepPhase.NIGHT_AWAKE
    state.is_sleeping = False
    state.last_chat_ts = now.timestamp() - 10  # 10s 前还在聊（<180s 静默窗口）

    after = await sm.finalize_sleep_recovery_check(role, now=now)
    assert after.phase == SleepPhase.NIGHT_AWAKE.value, f"期望仍 awake, 实际 {after.phase}"
    print("  PASS: 用户还在聊（静默未到）时未睡回 (phase=night_awake)")


async def test_interrupt_defer_when_recently_active():
    print("== 测试3: 打断做事 + 用户最近还在聊 → 顺延（不回去做事）==")
    now_ts = __import__("time").time()
    ac_svc.get_active_care_service = _fake_active_care(recent_timestamp=now_ts)  # 刚刚有消息
    try:
        dummy_ac = types.SimpleNamespace(executor=None, settings=None)
        deferred = await _decide_work_return_should_defer(
            dummy_ac, "default_user", "aveline", "reading"
        )
        assert deferred is True, f"期望顺延 True, 实际 {deferred}"
        print("  PASS: 用户最近还在聊 → 确定性顺延")
    finally:
        # 还原由 import 缓存的函数（本脚本内联，无需还原全局）
        pass


async def test_is_user_recently_active():
    print("== 测试4: 共享判定 is_user_recently_active ==")
    now_ts = __import__("time").time()
    ac_svc.get_active_care_service = _fake_active_care(recent_timestamp=now_ts)
    assert rps.is_user_recently_active("default_user", lookback_seconds=90) is True
    ac_svc.get_active_care_service = _fake_active_care(
        recent_timestamp=now_ts - 1000
    )  # 很久以前
    assert rps.is_user_recently_active("default_user", lookback_seconds=90) is False
    ac_svc.get_active_care_service = _fake_active_care(None)  # 无缓存
    assert rps.is_user_recently_active("default_user", lookback_seconds=90) is False
    print("  PASS: 最近有消息=True / 久无消息=False / 无缓存=False")


async def main():
    await test_wake_sleep_back_deterministic()
    await test_wake_not_yet_silent()
    await test_interrupt_defer_when_recently_active()
    await test_is_user_recently_active()
    print("\n全部通过：叫醒睡回 与 打断做事 已统一为『交互结束→回原状态』逻辑。")


if __name__ == "__main__":
    asyncio.run(main())
