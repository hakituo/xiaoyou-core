"""
PeerChat 睡眠门禁验证脚本

验证内容（QR-20260718-PEER-CHAT-SLEEP-GUARD）：
1. 任一角色 SLEEPING 时，_try_negotiation_peer_chat 被门禁拦截（return False，不进入 _collect_today_reminders）
2. 双方都不是 SLEEPING 时，门禁放行（流程继续走到 _collect_today_reminders）
3. NIGHT_AWAKE 不被拦截（被叫醒后的清醒状态，可参与协商）
4. 睡眠门禁检查抛异常时不中断主流程（继续走协商流程）

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\active_care\\verify_peer_chat_sleep_guard.py
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ==================== 测试工具 ====================

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def ok(self, name: str):
        self.passed += 1
        print(f"  [PASS] {name}")

    def fail(self, name: str, reason: str = ""):
        self.failed += 1
        msg = f"  [FAIL] {name}" + (f": {reason}" if reason else "")
        self.errors.append(msg)
        print(msg)

    def summary(self) -> bool:
        total = self.passed + self.failed
        print("\n========== 验证结果 ==========")
        print(f"通过: {self.passed}/{total}")
        print(f"失败: {self.failed}/{total}")
        if self.failed == 0:
            print("全部通过！")
        else:
            print("有失败项，请检查")
        return self.failed == 0


result = TestResult()


# ==================== Mock 构造工具 ====================

def _make_state(phase):
    """构造一个带 phase 属性的 mock SleepRuntimeState"""
    state = MagicMock()
    state.phase = phase
    return state


def _make_scheduler():
    """构造一个 PeerChatScheduler 实例（依赖全部用 Mock 注入）"""
    from core.services.active_care.peer_chat.peer_chat_scheduler import PeerChatScheduler
    return PeerChatScheduler(
        storage=MagicMock(),
        context=MagicMock(),
        decision=MagicMock(),
        executor=MagicMock(),
        settings=MagicMock(),
    )


def _build_patches(mock_registry, mock_sleep_manager):
    """构造 patch 上下文管理器（统一处理两个 get_xxx 单例）"""
    return (
        patch(
            "core.services.active_care.storage.reminder_assignment_registry."
            "get_reminder_assignment_registry",
            return_value=mock_registry,
        ),
        patch(
            "core.services.life_simulation.get_sleep_manager",
            return_value=mock_sleep_manager,
        ),
    )


async def _run_negotiation_with_sleep_phases(a_phase, l_phase, sleep_state_error=None):
    """模拟 _try_negotiation_peer_chat 调用，控制两个角色的睡眠 phase

    Args:
        a_phase: aveline 的 SleepPhase（None 表示让 get_state 抛异常）
        l_phase: ling 的 SleepPhase
        sleep_state_error: 若不为 None，让 sleep_manager.get_state 抛此异常

    Returns:
        (return_value, collect_called)
        - return_value: _try_negotiation_peer_chat 的返回值
        - collect_called: _collect_today_reminders 是否被调用
          True = 流程穿过门禁；False = 被门禁拦截
    """
    scheduler = _make_scheduler()

    # registry.needs_negotiation -> True，让流程走到睡眠门禁
    mock_registry = MagicMock()
    mock_registry.needs_negotiation = AsyncMock(return_value=True)
    mock_registry.mark_negotiation_status = AsyncMock()
    mock_registry.set_pending_reminders = AsyncMock()

    # sleep_manager.get_state 根据 role_id 返回不同 phase 的 state
    mock_sleep_manager = MagicMock()
    if sleep_state_error is not None:
        mock_sleep_manager.get_state = MagicMock(side_effect=sleep_state_error)
    else:
        def _get_state(role_id, **kwargs):
            phase = a_phase if role_id == "aveline" else l_phase
            return _make_state(phase)
        mock_sleep_manager.get_state = MagicMock(side_effect=_get_state)

    # 追踪 _collect_today_reminders 是否被调用；返回空列表让方法安全 return False
    collect_called = False

    async def _mock_collect():
        nonlocal collect_called
        collect_called = True
        return []

    scheduler._collect_today_reminders = _mock_collect

    connections = [
        {"role_id": "aveline", "persona_filename": "core_aveline.json"},
        {"role_id": "ling", "persona_filename": "core_ling.json"},
    ]

    p1, p2 = _build_patches(mock_registry, mock_sleep_manager)
    with p1, p2:
        ret = await scheduler._try_negotiation_peer_chat(connections)

    return ret, collect_called


# ==================== 测试用例 ====================

async def test_sleep_guard_blocks_when_aveline_sleeping():
    """场景 A: aveline SLEEPING + ling FULLY_AWAKE → 门禁拦截"""
    print("\n--- 测试1: aveline=SLEEPING 应被门禁拦截 ---")
    from core.services.life_simulation.sleep_models import SleepPhase
    ret, collect_called = await _run_negotiation_with_sleep_phases(
        SleepPhase.SLEEPING, SleepPhase.FULLY_AWAKE
    )
    if ret is False and not collect_called:
        result.ok(
            "aveline=SLEEPING, ling=FULLY_AWAKE -> 拦截"
            "（return False, 未进入 _collect_today_reminders）"
        )
    else:
        result.fail(
            "aveline=SLEEPING 拦截",
            f"ret={ret}, collect_called={collect_called} (期望 False, False)"
        )


async def test_sleep_guard_blocks_when_ling_sleeping():
    """场景 B: aveline FULLY_AWAKE + ling SLEEPING → 门禁拦截"""
    print("\n--- 测试2: ling=SLEEPING 应被门禁拦截 ---")
    from core.services.life_simulation.sleep_models import SleepPhase
    ret, collect_called = await _run_negotiation_with_sleep_phases(
        SleepPhase.FULLY_AWAKE, SleepPhase.SLEEPING
    )
    if ret is False and not collect_called:
        result.ok(
            "aveline=FULLY_AWAKE, ling=SLEEPING -> 拦截"
            "（return False, 未进入 _collect_today_reminders）"
        )
    else:
        result.fail(
            "ling=SLEEPING 拦截",
            f"ret={ret}, collect_called={collect_called} (期望 False, False)"
        )


async def test_sleep_guard_blocks_when_both_sleeping():
    """场景 C: 双方 SLEEPING → 门禁拦截"""
    print("\n--- 测试3: 双方 SLEEPING 应被门禁拦截 ---")
    from core.services.life_simulation.sleep_models import SleepPhase
    ret, collect_called = await _run_negotiation_with_sleep_phases(
        SleepPhase.SLEEPING, SleepPhase.SLEEPING
    )
    if ret is False and not collect_called:
        result.ok(
            "双方 SLEEPING -> 拦截"
            "（return False, 未进入 _collect_today_reminders）"
        )
    else:
        result.fail(
            "双方 SLEEPING 拦截",
            f"ret={ret}, collect_called={collect_called} (期望 False, False)"
        )


async def test_sleep_guard_passes_when_both_fully_awake():
    """场景 D: 双方 FULLY_AWAKE → 门禁放行，流程继续"""
    print("\n--- 测试4: 双方 FULLY_AWAKE 应穿过门禁 ---")
    from core.services.life_simulation.sleep_models import SleepPhase
    ret, collect_called = await _run_negotiation_with_sleep_phases(
        SleepPhase.FULLY_AWAKE, SleepPhase.FULLY_AWAKE
    )
    if collect_called:
        result.ok(
            "双方 FULLY_AWAKE -> 穿过门禁（_collect_today_reminders 被调用）"
        )
    else:
        result.fail(
            "双方 FULLY_AWAKE 穿过门禁",
            f"collect_called={collect_called} (期望 True)"
        )


async def test_sleep_guard_passes_when_both_night_awake():
    """场景 E: 双方 NIGHT_AWAKE → 门禁放行（NIGHT_AWAKE 是被叫醒后的清醒状态）"""
    print("\n--- 测试5: 双方 NIGHT_AWAKE 应穿过门禁 ---")
    from core.services.life_simulation.sleep_models import SleepPhase
    ret, collect_called = await _run_negotiation_with_sleep_phases(
        SleepPhase.NIGHT_AWAKE, SleepPhase.NIGHT_AWAKE
    )
    if collect_called:
        result.ok(
            "双方 NIGHT_AWAKE -> 穿过门禁"
            "（NIGHT_AWAKE 不是 SLEEPING，可参与协商）"
        )
    else:
        result.fail(
            "双方 NIGHT_AWAKE 穿过门禁",
            f"collect_called={collect_called} (期望 True)"
        )


async def test_sleep_guard_passes_when_preparing_sleep():
    """场景 F: 双方 PREPARING_SLEEP → 门禁放行（PREPARING_SLEEP 是睡前准备阶段，尚未入睡）"""
    print("\n--- 测试6: 双方 PREPARING_SLEEP 应穿过门禁 ---")
    from core.services.life_simulation.sleep_models import SleepPhase
    ret, collect_called = await _run_negotiation_with_sleep_phases(
        SleepPhase.PREPARING_SLEEP, SleepPhase.PREPARING_SLEEP
    )
    if collect_called:
        result.ok(
            "双方 PREPARING_SLEEP -> 穿过门禁"
            "（PREPARING_SLEEP 是睡前准备阶段，尚未真正入睡）"
        )
    else:
        result.fail(
            "双方 PREPARING_SLEEP 穿过门禁",
            f"collect_called={collect_called} (期望 True)"
        )


async def test_sleep_guard_exception_does_not_break_flow():
    """场景 G: 睡眠门禁检查抛异常 → 不中断主流程，继续协商"""
    print("\n--- 测试7: 睡眠门禁异常不应中断流程 ---")
    ret, collect_called = await _run_negotiation_with_sleep_phases(
        None, None, sleep_state_error=RuntimeError("mock sleep state error")
    )
    if collect_called:
        result.ok(
            "睡眠门禁异常 -> 流程继续（_collect_today_reminders 被调用）"
        )
    else:
        result.fail(
            "睡眠门禁异常不中断流程",
            f"collect_called={collect_called} (期望 True)"
        )


# ==================== 主入口 ====================

async def main():
    print("=" * 60)
    print("PeerChat 睡眠门禁验证 (QR-20260718-PEER-CHAT-SLEEP-GUARD)")
    print("=" * 60)

    await test_sleep_guard_blocks_when_aveline_sleeping()
    await test_sleep_guard_blocks_when_ling_sleeping()
    await test_sleep_guard_blocks_when_both_sleeping()
    await test_sleep_guard_passes_when_both_fully_awake()
    await test_sleep_guard_passes_when_both_night_awake()
    await test_sleep_guard_passes_when_preparing_sleep()
    await test_sleep_guard_exception_does_not_break_flow()

    return result.summary()


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)