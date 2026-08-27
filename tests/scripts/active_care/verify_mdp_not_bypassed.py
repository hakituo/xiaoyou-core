"""验证 MDP 不被 must_probe 架空 + activity 挂机检测降级。

修复背景（2026-08-14 诊断）：
1. decision_executor.select_action 的 must_probe 分支原本硬编码 curious_question，
   导致 MDP 的 select_action（动作选择）从未被调用，Q 表白学。
   修复：must_probe 时改为调用 _select_mdp_or_bandit，让 MDP 按状态选动作，
   冷启动/异常回退 bandit。
2. activity_detector 只看前台进程，原神挂机（人离开）时仍判 gaming busy=True，
   触发 activity gate 0.10 软拦截，漏发主动关怀。
   修复：复用 GetLastInputInfo 挂机检测，无键鼠输入超阈值时降级为 idle。

运行：
    venv_core/Scripts/python.exe tests/scripts/active_care/verify_mdp_not_bypassed.py
"""
import asyncio
import inspect
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# 项目根目录加入路径
sys.path.insert(0, ".")

PASS = 0
FAIL = 0


def _ok(name: str, detail: str = "") -> None:
    global PASS
    PASS += 1
    print(f"  [PASS] {name}{(' - ' + detail) if detail else ''}")


def _fail(name: str, detail: str = "") -> None:
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {name}{(' - ' + detail) if detail else ''}")


# ───────────────────────── MDP 修复验证 ─────────────────────────

def test_mdp_source_not_hardcoded_in_must_probe() -> None:
    """静态：select_action 的 must_probe 分支应调用 _select_mdp_or_bandit。"""
    from core.services.active_care.decision.decision_executor import DecisionExecutor

    src = inspect.getsource(DecisionExecutor.select_action)
    # must_probe 分支必须委托给 _select_mdp_or_bandit，而非硬编码 curious_question
    if "_select_mdp_or_bandit" not in src:
        _fail("test_mdp_source_not_hardcoded_in_must_probe", "源码未调用 _select_mdp_or_bandit")
        return
    # 定位 must_probe 分支，确认该分支内有 _select_mdp_or_bandit 调用
    must_probe_idx = src.find('must_probe')
    select_mdp_idx = src.find('_select_mdp_or_bandit', must_probe_idx)
    if select_mdp_idx < 0:
        _fail("test_mdp_source_not_hardcoded_in_must_probe", "must_probe 分支未调用 _select_mdp_or_bandit")
        return
    _ok("test_mdp_source_not_hardcoded_in_must_probe", "must_probe 分支已委托 MDP/bandit")


async def _test_mdp_must_probe_calls_mdp_or_bandit_async() -> None:
    """行为：must_probe=True 且无 urgent_needs 时，应调用 _select_mdp_or_bandit。"""
    from core.services.active_care.decision.decision_executor import DecisionExecutor

    # 用 mock 构造 executor，避免真实 storage/decision 依赖
    executor = DecisionExecutor(
        storage=MagicMock(),
        context=MagicMock(),
        decision=MagicMock(),
        executor=MagicMock(),
        priority_analyzer=MagicMock(),
        intent_detector=MagicMock(),
        sleep_policy=MagicMock(),
    )
    # 必须把 must_probe 触发的动作集限制为"非 do_nothing"
    captured_actions = {}

    async def fake_select(ctx, actions):
        captured_actions["actions"] = list(actions)
        return "share_thought"  # MDP 选了一个非 curious_question 的动作

    with patch.object(executor, "_select_mdp_or_bandit", new=AsyncMock(side_effect=fake_select)):
        priority_focus = {"must_probe": True}
        decision_ctx = {"elapsed_seconds": 1500}
        available_actions = ["do_nothing", "share_thought", "curious_question"]

        chosen = await executor.select_action(
            decision_ctx=decision_ctx,
            available_actions=available_actions,
            priority_analysis={"ranked": []},
            priority_focus=priority_focus,
            urgent_needs=[],
        )

    if chosen != "share_thought":
        _fail("test_mdp_must_probe_calls_mdp_or_bandit", f"chosen={chosen} 应为 MDP 返回的 share_thought")
        return
    # 关键：传给 MDP 的动作集不应包含 do_nothing（must_probe 必须主动探测）
    if "do_nothing" in captured_actions.get("actions", []):
        _fail("test_mdp_must_probe_calls_mdp_or_bandit", "动作集含 do_nothing，破坏 must_probe 语义")
        return
    if "curious_question" not in captured_actions.get("actions", []):
        _fail("test_mdp_must_probe_calls_mdp_or_bandit", "动作集缺 curious_question")
        return
    _ok("test_mdp_must_probe_calls_mdp_or_bandit", f"chosen={chosen}, actions={captured_actions['actions']}")


async def _test_mdp_must_probe_not_hardcoded_curious_async() -> None:
    """行为：must_probe 时不应无条件返回 curious_question（应走 MDP，可返回其他动作）。"""
    from core.services.active_care.decision.decision_executor import DecisionExecutor

    executor = DecisionExecutor(
        storage=MagicMock(),
        context=MagicMock(),
        decision=MagicMock(),
        executor=MagicMock(),
        priority_analyzer=MagicMock(),
        intent_detector=MagicMock(),
        sleep_policy=MagicMock(),
    )

    with patch.object(executor, "_select_mdp_or_bandit", new=AsyncMock(return_value="emotional_support")):
        chosen = await executor.select_action(
            decision_ctx={"elapsed_seconds": 1500},
            available_actions=["do_nothing", "share_thought", "curious_question", "emotional_support"],
            priority_analysis={"ranked": []},
            priority_focus={"must_probe": True},
            urgent_needs=[],
        )
    if chosen == "curious_question":
        _fail("test_mdp_must_probe_not_hardcoded_curious", "仍硬编码返回 curious_question")
        return
    if chosen != "emotional_support":
        _fail("test_mdp_must_probe_not_hardcoded_curious", f"chosen={chosen} 应为 emotional_support")
        return
    _ok("test_mdp_must_probe_not_hardcoded_curious", "MDP 可返回非 curious_question 动作")


# ───────────────────────── activity 挂机检测验证 ─────────────────────────

def test_activity_has_idle_detection() -> None:
    """静态：activity_detector 应有 _get_idle_seconds 方法和 IDLE_THRESHOLD_SECONDS 常量。"""
    from core.services.active_care.detection import activity_detector as mod

    if not hasattr(mod, "IDLE_THRESHOLD_SECONDS"):
        _fail("test_activity_has_idle_detection", "缺 IDLE_THRESHOLD_SECONDS 常量")
        return
    if not hasattr(mod.UserActivityDetector, "_get_idle_seconds"):
        _fail("test_activity_has_idle_detection", "缺 _get_idle_seconds 方法")
        return
    # _detect_sync 源码应含挂机降级逻辑
    src = inspect.getsource(mod.UserActivityDetector._detect_sync)
    if "IDLE_THRESHOLD_SECONDS" not in src or "_get_idle_seconds" not in src:
        _fail("test_activity_has_idle_detection", "_detect_sync 缺挂机降级逻辑")
        return
    _ok("test_activity_has_idle_detection", f"阈值={mod.IDLE_THRESHOLD_SECONDS}s")


async def _test_activity_idle_downgrade_async() -> None:
    """行为：前台原神(gaming/busy)但挂机超阈值时，应降级为 idle/is_busy=False。"""
    from core.services.active_care.detection.activity_detector import (
        UserActivityDetector,
        IDLE_THRESHOLD_SECONDS,
    )
    from core.services.active_care.detection.activity_maps import UserActivityCategory

    detector = UserActivityDetector()
    detector.invalidate_cache()

    with patch.object(detector, "_get_foreground_process_windows", return_value=("yuanshen.exe", "Genshin Impact", 1234)), \
         patch.object(detector, "_get_idle_seconds", return_value=float(IDLE_THRESHOLD_SECONDS + 60)):
        result = await detector.detect()

    if result.category != UserActivityCategory.IDLE:
        _fail("test_activity_idle_downgrade", f"category={result.category} 应为 IDLE")
        return
    if result.is_busy:
        _fail("test_activity_idle_downgrade", f"is_busy={result.is_busy} 应为 False")
        return
    if result.busy_level != 0.0:
        _fail("test_activity_idle_downgrade", f"busy_level={result.busy_level} 应为 0.0")
        return
    _ok("test_activity_idle_downgrade", "挂机时 gaming 正确降级为 idle")


async def _test_activity_no_idle_when_active_async() -> None:
    """行为：前台原神且最近有键鼠输入时，应保持 gaming/busy（不误降级）。"""
    from core.services.active_care.detection.activity_detector import UserActivityDetector
    from core.services.active_care.detection.activity_maps import UserActivityCategory

    detector = UserActivityDetector()
    detector.invalidate_cache()

    with patch.object(detector, "_get_foreground_process_windows", return_value=("yuanshen.exe", "Genshin Impact", 1234)), \
         patch.object(detector, "_get_idle_seconds", return_value=30.0):  # 30s < 300s 阈值
        result = await detector.detect()

    if result.category != UserActivityCategory.GAMING:
        _fail("test_activity_no_idle_when_active", f"category={result.category} 应为 GAMING")
        return
    if not result.is_busy:
        _fail("test_activity_no_idle_when_active", f"is_busy={result.is_busy} 应为 True（正在玩）")
        return
    _ok("test_activity_no_idle_when_active", "活跃玩游戏时保持 busy 不误降级")


# ───────────────────────── 主流程 ─────────────────────────

async def _run_async_tests() -> None:
    await _test_mdp_must_probe_calls_mdp_or_bandit_async()
    await _test_mdp_must_probe_not_hardcoded_curious_async()
    await _test_activity_idle_downgrade_async()
    await _test_activity_no_idle_when_active_async()


def main() -> int:
    global PASS, FAIL
    print("=" * 64)
    print("验证：MDP 不被 must_probe 架空 + activity 挂机检测降级")
    print("=" * 64)

    print("\n[MDP 修复验证]")
    test_mdp_source_not_hardcoded_in_must_probe()
    asyncio.run(_test_mdp_must_probe_calls_mdp_or_bandit_async())
    asyncio.run(_test_mdp_must_probe_not_hardcoded_curious_async())

    print("\n[activity 挂机检测验证]")
    test_activity_has_idle_detection()
    asyncio.run(_test_activity_idle_downgrade_async())
    asyncio.run(_test_activity_no_idle_when_active_async())

    print("\n" + "=" * 64)
    print(f"结果: {PASS} passed, {FAIL} failed")
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
