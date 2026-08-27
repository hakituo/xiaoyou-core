"""验证：未接入 active_care 的角色（xiaolu/yeye 等）不再触发主动消息。

背景：2026-08-01 发现 xiaolu 进入 SLEEPING/WAKING_UP 时，
sleep_manager 无条件调用 trigger_character_goodnight_async / trigger_character_good_morning_async，
而 goodnight_proactive / good_morning_proactive 的 _resolve_persona_filename
对未知 role_id fallback 到 qq/Aveline_QQ_Master.json，
导致 xiaolu 的晚安/起床消息以"七濑澪"名义发出，污染 aveline 会话历史。

修复后验证点：
1. sleep_manager 有白名单 _ACTIVE_CARE_ENABLED_ROLES = {"aveline", "ling"}
2. _on_enter_sleeping / _on_enter_waking_up 对非白名单角色跳过（不触发主动消息）
3. goodnight_proactive._resolve_persona_filename 对未知角色返回 None
4. good_morning_proactive._resolve_persona_filename 对未知角色返回 None
5. activity_return.instruction.resolve_persona_filename 对未知角色返回 None
6. trigger_character_goodnight / trigger_character_good_morning 对未知角色返回 False

运行：D:\\AI\\xiaoyou-core\\venv_cpu\\Scripts\\python.exe tests\\scripts\\active_care\\verify_unknown_role_no_fallback.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def test_sleep_manager_whitelist() -> None:
    """验证 sleep_manager 白名单存在且只含 aveline/ling。"""
    _section("1. sleep_manager 白名单")
    from core.services.life_simulation.sleep_manager import _ACTIVE_CARE_ENABLED_ROLES

    assert _ACTIVE_CARE_ENABLED_ROLES == frozenset({"aveline", "ling"}), (
        f"白名单不正确: {_ACTIVE_CARE_ENABLED_ROLES}"
    )
    print(f"  PASS: _ACTIVE_CARE_ENABLED_ROLES = {set(_ACTIVE_CARE_ENABLED_ROLES)}")

    # 非白名单角色
    for role in ("xiaolu", "yeye", "rushuang", "mianmian"):
        assert role not in _ACTIVE_CARE_ENABLED_ROLES, f"{role} 不应在白名单中"
        print(f"  PASS: {role} 不在白名单中（不会触发主动消息）")


def test_sleep_manager_skips_unknown_role() -> None:
    """验证 _on_enter_sleeping / _on_enter_waking_up 对非白名单角色不触发。"""
    _section("2. sleep_manager 对非白名单角色跳过触发")
    from core.services.life_simulation.sleep_manager import SleepManager
    from core.services.life_simulation.sleep_models import SleepPhase

    mgr = SleepManager.__new__(SleepManager)

    # mock trigger 函数，如果被调用说明白名单没生效
    with patch(
        "core.services.active_care.goodnight_proactive.trigger_character_goodnight_async"
    ) as mock_gn, patch(
        "core.services.active_care.good_morning_proactive.trigger_character_good_morning_async"
    ) as mock_gm:
        from datetime import datetime

        now = datetime(2026, 8, 1, 0, 0, 0)

        # 对每个非白名单角色，模拟进入 SLEEPING
        for role in ("xiaolu", "yeye", "rushuang", "mianmian"):
            mgr._on_enter_sleeping(role, SleepPhase.FULLY_AWAKE, now)
            assert not mock_gn.called, (
                f"{role} 不在白名单但 _on_enter_sleeping 仍然触发了 trigger_character_goodnight_async"
            )
            print(f"  PASS: {role} 进入 SLEEPING 未触发晚安消息")

        # 对每个非白名单角色，模拟进入 WAKING_UP
        for role in ("xiaolu", "yeye", "rushuang", "mianmian"):
            mgr._on_enter_waking_up(
                role, SleepPhase.SLEEPING, now, now, is_stay_up_recovery=False
            )
            assert not mock_gm.called, (
                f"{role} 不在白名单但 _on_enter_waking_up 仍然触发了 trigger_character_good_morning_async"
            )
            print(f"  PASS: {role} 进入 WAKING_UP 未触发起床问候消息")

    # 白名单角色应该正常触发
    with patch(
        "core.services.active_care.goodnight_proactive.trigger_character_goodnight_async"
    ) as mock_gn:
        mgr._on_enter_sleeping("aveline", SleepPhase.FULLY_AWAKE, now)
        assert mock_gn.called, "aveline 在白名单中但未触发 trigger_character_goodnight_async"
        print("  PASS: aveline 进入 SLEEPING 正常触发晚安消息")


def test_resolve_persona_no_fallback() -> None:
    """验证三个 resolve_persona_filename 对未知角色返回 None。"""
    _section("3. _resolve_persona_filename 不再 fallback 到 aveline")

    from core.services.active_care.goodnight_proactive import (
        _resolve_persona_filename as resolve_gn,
    )
    from core.services.active_care.good_morning_proactive import (
        _resolve_persona_filename as resolve_gm,
    )
    from core.services.character_daily.activity_return.instruction import (
        resolve_persona_filename as resolve_ar,
    )

    # 已知角色应返回正确 persona
    assert resolve_gn("aveline") == "qq/Aveline_QQ_Master.json"
    assert resolve_gm("aveline") == "qq/Aveline_QQ_Master.json"
    assert resolve_ar("aveline") == "qq/Aveline_QQ_Master.json"
    print("  PASS: aveline → 正确 persona 文件")

    assert resolve_gn("ling") == "qq/Ling_QQ_Master.json"
    assert resolve_gm("ling") == "qq/Ling_QQ_Master.json"
    assert resolve_ar("ling") == "qq/Ling_QQ_Master.json"
    print("  PASS: ling → 正确 persona 文件")

    # 未知角色应返回 None（不再 fallback 到 aveline）
    for role in ("xiaolu", "yeye", "rushuang", "mianmian", "unknown_role", ""):
        assert resolve_gn(role) is None, (
            f"goodnight_proactive: {role!r} 应返回 None，实际返回 {resolve_gn(role)!r}"
        )
        assert resolve_gm(role) is None, (
            f"good_morning_proactive: {role!r} 应返回 None，实际返回 {resolve_gm(role)!r}"
        )
        assert resolve_ar(role) is None, (
            f"activity_return: {role!r} 应返回 None，实际返回 {resolve_ar(role)!r}"
        )
        print(f"  PASS: {role!r} → None（三个模块均不再 fallback）")


def test_trigger_skips_unknown_role() -> None:
    """验证 trigger_character_goodnight/good_morning 对未知角色返回 False。"""
    _section("4. trigger 函数对未知角色返回 False（不发送）")

    from core.services.active_care.goodnight_proactive import (
        trigger_character_goodnight,
    )
    from core.services.active_care.good_morning_proactive import (
        trigger_character_good_morning,
    )

    # mock get_active_care_service 返回一个假的 service，
    # 如果 trigger 没有在 persona_filename 检查处提前返回，
    # 就会走到 trigger_message 调用 → 我们能检测到
    fake_executor = type("FakeExecutor", (), {"trigger_message": None})()
    fake_service = type("FakeService", (), {"executor": fake_executor})()

    trigger_called = []

    async def fake_trigger(**kwargs):
        trigger_called.append(kwargs)
        return True

    fake_executor.trigger_message = fake_trigger

    with patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=fake_service,
    ):
        # 未知角色应返回 False 且不调用 trigger_message
        for role in ("xiaolu", "yeye", "rushuang", "mianmian"):
            trigger_called.clear()

            result_gn = asyncio.run(trigger_character_goodnight(role))
            assert result_gn is False, (
                f"trigger_character_goodnight({role!r}) 应返回 False，实际 {result_gn}"
            )
            assert not trigger_called, (
                f"trigger_character_goodnight({role!r}) 不应调用 trigger_message"
            )
            print(f"  PASS: trigger_character_goodnight({role!r}) → False，未发送")

            trigger_called.clear()

            result_gm = asyncio.run(trigger_character_good_morning(role))
            assert result_gm is False, (
                f"trigger_character_good_morning({role!r}) 应返回 False，实际 {result_gm}"
            )
            assert not trigger_called, (
                f"trigger_character_good_morning({role!r}) 不应调用 trigger_message"
            )
            print(f"  PASS: trigger_character_good_morning({role!r}) → False，未发送")


def main() -> int:
    print("验证：未接入 active_care 的角色不再触发主动消息")
    print(f"项目根目录: {PROJECT_ROOT}")

    tests = [
        test_sleep_manager_whitelist,
        test_sleep_manager_skips_unknown_role,
        test_resolve_persona_no_fallback,
        test_trigger_skips_unknown_role,
    ]

    failed = 0
    for test in tests:
        try:
            test()
        except Exception as e:
            failed += 1
            print(f"\n  FAIL: {test.__name__}: {e}")
            import traceback

            traceback.print_exc()

    _section("总结")
    if failed == 0:
        print(f"  全部通过（{len(tests)} 项验证）")
        return 0
    print(f"  失败 {failed}/{len(tests)} 项")
    return 1


if __name__ == "__main__":
    sys.exit(main())
