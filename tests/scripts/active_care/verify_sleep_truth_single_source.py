"""验证睡眠原因集合收敛为单一真相源，且 SleepTruth 提供唯一权威判定

背景（2026-09-03）：
    「用户到底睡没睡」在 Active Care 内部曾散落在三个字段里：

      - ``active``         = 已确认睡着（晚安/早安时间戳推导）
      - ``reduced_mode_*`` = 低打扰，既可能是晚安也可能是专注学习
      - ``quiet_mode``     = 说了晚安但还没确认睡着

    调用方必须自己知道该看哪一个，于是各模块各取所需：
    life_simulation 曾把「说了晚安但没睡着」当成已睡着，
    而 Active Care 认为没睡，同一时刻两侧结论相反。

    更基础的问题是 reduced_mode_reason 的取值集合有多个副本：
    storage.py 有 _SLEEP_MODE_REASONS，life_simulation 有自己的
    _SLEEP_QUIET_REASONS，mode_state / manager 里还有字面量判断。
    新增或调整 reason 时极易漏改。

本轮修复：
- 原因集合上收到 core/services/active_care/shared/constants.py
  （SLEEP_MODE_REASONS / FOCUS_MODE_REASONS / QUIET_MODE_REASONS）；
- storage.py 改为引用共享常量，不再自带副本；
- 新增纯函数 resolve_sleep_truth() 与 SleepTruth 数据类，
  一次性给出四个语义明确的布尔值，命名与 life_simulation 侧对齐；
- get_current_state() 改走 resolve_sleep_truth，并保留 active 等兼容字段。

本脚本校验上述各点，并固化「focus 不得被当作睡眠」这条历史事故防线。
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_PASSED = 0
_FAILED = 0


def _ok(msg: str) -> None:
    global _PASSED
    _PASSED += 1
    print(f"  [PASS] {msg}")


def _fail(msg: str, detail: str = "") -> None:
    global _FAILED
    _FAILED += 1
    print(f"  [FAIL] {msg}")
    if detail:
        print(f"         {detail}")


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def test_shared_constants_exist() -> None:
    _section("测试 1: 共享常量集合已定义")
    from core.services.active_care.shared.mode_reasons import (
        FOCUS_MODE_REASONS,
        QUIET_MODE_REASONS,
        SLEEP_MODE_REASONS,
    )

    if {"goodnight", "sleep_hint", "sleep"} <= set(SLEEP_MODE_REASONS):
        _ok(f"SLEEP_MODE_REASONS 含睡眠三值: {sorted(SLEEP_MODE_REASONS)}")
    else:
        _fail("SLEEP_MODE_REASONS 取值不全", str(SLEEP_MODE_REASONS))

    if {"focus", "study", "work"} <= set(FOCUS_MODE_REASONS):
        _ok(f"FOCUS_MODE_REASONS 含专注三值: {sorted(FOCUS_MODE_REASONS)}")
    else:
        _fail("FOCUS_MODE_REASONS 取值不全", str(FOCUS_MODE_REASONS))

    if set(QUIET_MODE_REASONS) <= set(SLEEP_MODE_REASONS):
        _ok(f"QUIET_MODE_REASONS 是睡眠集合的子集: {sorted(QUIET_MODE_REASONS)}")
    else:
        _fail("QUIET_MODE_REASONS 与 SLEEP_MODE_REASONS 不一致")

    # 睡眠与专注不得交叉——这是"学习低打扰被写成晚安"的防线
    overlap = set(SLEEP_MODE_REASONS) & set(FOCUS_MODE_REASONS)
    if not overlap:
        _ok("睡眠原因与专注原因无交集（focus 不会被误判为睡眠）")
    else:
        _fail("睡眠与专注原因存在交集", str(overlap))


def test_storage_uses_shared_constant() -> None:
    _section("测试 2: storage 不再自带原因集合副本")
    from core.services.active_care.shared.mode_reasons import SLEEP_MODE_REASONS
    from core.services.active_care.storage.storage import ActiveCareStorage

    if ActiveCareStorage._SLEEP_MODE_REASONS is SLEEP_MODE_REASONS:  # noqa: SLF001
        _ok("ActiveCareStorage._SLEEP_MODE_REASONS 直接引用共享常量")
    else:
        _fail(
            "ActiveCareStorage 仍使用自己的副本",
            f"{ActiveCareStorage._SLEEP_MODE_REASONS} vs {SLEEP_MODE_REASONS}",  # noqa: SLF001
        )


def test_resolve_sleep_truth_semantics() -> None:
    _section("测试 3: resolve_sleep_truth 四种语义判定正确")
    from core.services.active_care.shared.state_keys import StateKeys
    from core.services.active_care.state.sleep_state import resolve_sleep_truth

    def build(goodnight=0.0, goodmorning=0.0, active=False, reason="none"):
        return {
            StateKeys.LAST_GOODNIGHT_TS: goodnight,
            StateKeys.LAST_GOODMORNING_TS: goodmorning,
            StateKeys.REDUCED_MODE_ACTIVE: active,
            StateKeys.REDUCED_MODE_REASON: reason,
        }

    cases = [
        ("无状态", build(), dict(cs=False, quiet=False, focus=False)),
        ("已晚安未早安", build(goodnight=1000.0, goodmorning=500.0),
         dict(cs=True, quiet=True, focus=False)),
        ("已说早安", build(goodnight=1000.0, goodmorning=1500.0),
         dict(cs=False, quiet=False, focus=False)),
        ("仅晚安低打扰未确认睡着", build(active=True, reason="goodnight"),
         dict(cs=False, quiet=True, focus=False)),
        ("sleep_hint 低打扰", build(active=True, reason="sleep_hint"),
         dict(cs=False, quiet=True, focus=False)),
        ("专注学习低打扰", build(active=True, reason="focus"),
         dict(cs=False, quiet=False, focus=True)),
        ("study 低打扰", build(active=True, reason="study"),
         dict(cs=False, quiet=False, focus=True)),
    ]

    for desc, state, expect in cases:
        t = resolve_sleep_truth(state)
        ok = (
            t.confirmed_sleeping == expect["cs"]
            and t.in_sleep_quiet == expect["quiet"]
            and t.focus_active == expect["focus"]
        )
        # quiet_mode 仅在"低打扰但未确认睡着"时为真
        ok = ok and (t.quiet_mode == (t.in_sleep_quiet and not t.confirmed_sleeping))
        if ok:
            _ok(f"{desc}: sleeping={t.confirmed_sleeping} "
                f"quiet={t.in_sleep_quiet} focus={t.focus_active}")
        else:
            _fail(f"{desc} 判定错误",
                  f"sleeping={t.confirmed_sleeping} quiet={t.in_sleep_quiet} "
                  f"quiet_mode={t.quiet_mode} focus={t.focus_active}")


def test_consistent_with_legacy_primitive() -> None:
    _section("测试 4: 与既有判定原语 is_sleep_session_active_from_state 一致")
    from core.services.active_care.shared.state_keys import StateKeys
    from core.services.active_care.state.sleep_state import (
        SleepStateManager,
        resolve_sleep_truth,
    )

    samples = [
        (0.0, 0.0),
        (1000.0, 500.0),
        (1000.0, 1500.0),
        (1000.0, 0.0),
        (0.0, 1000.0),
    ]
    for goodnight, goodmorning in samples:
        state = {
            StateKeys.LAST_GOODNIGHT_TS: goodnight,
            StateKeys.LAST_GOODMORNING_TS: goodmorning,
        }
        legacy = SleepStateManager.is_sleep_session_active_from_state(
            goodnight, goodmorning
        )
        new = resolve_sleep_truth(state).confirmed_sleeping
        if legacy == new:
            _ok(f"goodnight={goodnight} goodmorning={goodmorning} → {new}（一致）")
        else:
            _fail("两套判定不一致", f"legacy={legacy} new={new}")


def test_get_current_state_fields() -> None:
    _section("测试 5: get_current_state 输出语义明确字段且保持兼容")
    import inspect

    from core.services.active_care.state.sleep_state import SleepStateManager

    src = inspect.getsource(SleepStateManager.get_current_state)
    if "resolve_sleep_truth" in src:
        _ok("get_current_state 改走 resolve_sleep_truth（唯一路径）")
    else:
        _fail("get_current_state 未使用 resolve_sleep_truth")

    for field in ("confirmed_sleeping", "in_sleep_quiet", "focus_active", "active"):
        if f'"{field}"' in src:
            _ok(f"输出字段保留/新增: {field}")
        else:
            _fail(f"缺少字段: {field}")

    # active 必须仍等价于 confirmed_sleeping（向后兼容）
    if '"active": truth.confirmed_sleeping' in src:
        _ok("active 等价于 confirmed_sleeping（向后兼容未破坏）")
    else:
        _fail("active 语义已改变，既有调用方会受影响")


def test_life_simulation_reuses_shared_constant() -> None:
    _section("测试 6: life_simulation 复用同一份原因集合")
    from core.services.life_simulation import service_state_helpers as helpers

    try:
        from core.services.active_care.shared.mode_reasons import QUIET_MODE_REASONS

        shared = set(QUIET_MODE_REASONS)
    except Exception:
        _fail("无法导入共享常量")
        return

    resolved = set(helpers._sleep_quiet_reasons())  # noqa: SLF001
    if resolved == shared:
        _ok(f"life_simulation 解析到共享集合: {sorted(resolved)}")
    else:
        _fail("life_simulation 与共享集合不一致", f"{sorted(resolved)} vs {sorted(shared)}")


def main() -> int:
    print("=" * 64)
    print("睡眠原因集合单一真相源 & SleepTruth 权威判定 验证")
    print("=" * 64)

    test_shared_constants_exist()
    test_storage_uses_shared_constant()
    test_resolve_sleep_truth_semantics()
    test_consistent_with_legacy_primitive()
    test_get_current_state_fields()
    test_life_simulation_reuses_shared_constant()

    print("\n" + "=" * 64)
    print(f"结果: {_PASSED} 通过 / {_FAILED} 失败")
    print("=" * 64)
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
