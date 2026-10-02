"""验证「用户是否在睡觉」的两个语义被拆开，且与 Active Care 官方口径一致

背景（2026-09-03）：
    life_simulation 的 read_active_care_sleep_state() 与 Active Care 官方的
    SleepStateManager.is_sleep_session_active_from_state() 回答的是同一个问题
    「用户睡着了吗」，但判定逻辑不同：

        官方：  last_goodnight_ts > 0 且 last_goodmorning_ts < last_goodnight_ts
        life_sim：上面那条 + （reduced_mode_active 且 reason ∈ goodnight/sleep_hint）

    多出来的那个分支把「说了晚安但还没睡着」也算成已睡着。于是同一时刻：
    - life_simulation 认为用户睡了 → 把角色活动推导成 sleeping、按睡眠档衰减；
    - Active Care 认为没睡 → 照常判断该不该发消息。
    两侧互相矛盾，且共用"用户在睡觉"这个说法，排查时极易误导。

    这不是简单的"合并成一套"，因为两者关心的东西本就不同：
    - 「已确认睡着」——决定要不要发消息；
    - 「已进入睡眠相关低打扰」——决定角色要不要安静。
    正确做法是拆成两个语义清晰的函数，而不是共用一个含糊的布尔值。

本脚本校验：
- 严格口径与 Active Care 官方判定逐例一致；
- 宽松口径 = 严格口径 ∪ 晚安低打扰；
- 拆分后 read_active_care_sleep_state 行为不变（等价于宽松口径）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

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


# 与 Active Care 官方 is_sleep_session_active_from_state 完全一致的参考实现
def _official(goodnight: float, goodmorning: float) -> bool:
    return goodnight > 0 and goodmorning < goodnight


def _with_state(state: Dict[str, Any], fn):
    """用临时 state 文件驱动被测函数。"""
    import tempfile

    from core.services.life_simulation import service_state_helpers as helpers

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "user_sleep_state.json"
        import json

        target.write_text(json.dumps(state), encoding="utf-8")
        original = helpers.get_active_care_dir

        def _fake_dir(scope=None):
            return Path(tmp)

        helpers.get_active_care_dir = _fake_dir
        try:
            return fn()
        finally:
            helpers.get_active_care_dir = original


def test_strict_matches_official() -> None:
    _section("测试 1: 严格口径与 Active Care 官方判定逐例一致")
    from core.services.life_simulation.service_state_helpers import (
        is_user_confirmed_sleeping,
    )

    cases = [
        ({}, False, "无记录"),
        ({"last_goodnight_ts": 0.0, "last_goodmorning_ts": 0.0}, False, "两个时间戳都为 0"),
        ({"last_goodnight_ts": 1000.0, "last_goodmorning_ts": 500.0}, True, "晚安在早安之后"),
        ({"last_goodnight_ts": 1000.0, "last_goodmorning_ts": 1500.0}, False, "已说早安"),
        ({"last_goodnight_ts": 1000.0, "last_goodmorning_ts": 0.0}, True, "未说早安且已晚安"),
        # 只有晚安低打扰、没有 goodnight 时间戳 → 官方口径认为没睡着
        ({"reduced_mode_active": True, "reduced_mode_reason": "goodnight"}, False,
         "仅晚安低打扰无时间戳（关键分歧点）"),
    ]
    for state, expected, desc in cases:
        got = _with_state(state, is_user_confirmed_sleeping)
        official = _official(
            float(state.get("last_goodnight_ts") or 0.0),
            float(state.get("last_goodmorning_ts") or 0.0),
        )
        if got != expected:
            _fail(f"{desc}: 期望 {expected}，实际 {got}")
        elif got != official:
            _fail(f"{desc}: 与官方口径不一致（官方={official}，本函数={got}）")
        else:
            _ok(f"{desc} → {got}（与官方一致）")


def test_loose_superset() -> None:
    _section("测试 2: 宽松口径 = 严格口径 ∪ 晚安低打扰")
    from core.services.life_simulation.service_state_helpers import (
        is_user_confirmed_sleeping,
        is_user_in_sleep_quiet,
    )

    # 已确认睡着 → 宽松必为真
    state = {"last_goodnight_ts": 1000.0, "last_goodmorning_ts": 500.0}
    if _with_state(state, is_user_in_sleep_quiet) and _with_state(
        state, is_user_confirmed_sleeping
    ):
        _ok("已确认睡着时，宽松与严格同时为真")
    else:
        _fail("已确认睡着时宽松口径应为真")

    # 仅晚安低打扰 → 严格为假、宽松为真
    state = {"reduced_mode_active": True, "reduced_mode_reason": "goodnight"}
    strict = _with_state(state, is_user_confirmed_sleeping)
    loose = _with_state(state, is_user_in_sleep_quiet)
    if not strict and loose:
        _ok("仅晚安低打扰时：严格=False、宽松=True（语义已分离）")
    else:
        _fail("语义未分离", f"strict={strict} loose={loose}")

    # focus 低打扰不应被算作睡眠相关
    state = {"reduced_mode_active": True, "reduced_mode_reason": "focus"}
    if not _with_state(state, is_user_in_sleep_quiet):
        _ok("focus 低打扰不算睡眠相关（避免学习低打扰被误判成睡觉）")
    else:
        _fail("focus 低打扰被误判为睡眠相关")


def test_legacy_wrapper_unchanged() -> None:
    _section("测试 3: read_active_care_sleep_state 行为不变（等价于宽松口径）")
    from core.services.life_simulation.service_state_helpers import (
        is_user_in_sleep_quiet,
        read_active_care_sleep_state,
    )

    cases = [
        {},
        {"last_goodnight_ts": 1000.0, "last_goodmorning_ts": 500.0},
        {"last_goodnight_ts": 1000.0, "last_goodmorning_ts": 1500.0},
        {"reduced_mode_active": True, "reduced_mode_reason": "goodnight"},
        {"reduced_mode_active": True, "reduced_mode_reason": "sleep_hint"},
        {"reduced_mode_active": True, "reduced_mode_reason": "focus"},
        {"reduced_mode_active": False, "reduced_mode_reason": "goodnight"},
    ]
    mismatch = []
    for state in cases:
        legacy = _with_state(state, read_active_care_sleep_state)
        loose = _with_state(state, is_user_in_sleep_quiet)
        if legacy != loose:
            mismatch.append((state, legacy, loose))
    if mismatch:
        _fail("read_active_care_sleep_state 与宽松口径不一致", str(mismatch[:3]))
    else:
        _ok(f"{len(cases)} 个用例下 read_active_care_sleep_state 与宽松口径一致（行为未变）")


def main() -> int:
    print("=" * 64)
    print("用户睡眠状态：严格/宽松两个语义拆分 验证")
    print("=" * 64)

    test_strict_matches_official()
    test_loose_superset()
    test_legacy_wrapper_unchanged()

    print("\n" + "=" * 64)
    print(f"结果: {_PASSED} 通过 / {_FAILED} 失败")
    print("=" * 64)
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
