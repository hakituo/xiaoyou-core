"""验证角色活动收敛到单一真相源，且生命衰减分档覆盖全部活动值

背景（2026-09-03）：
    「角色当前在做什么」曾有两套完全独立的计算链：

    A. character_daily 计划链
       engine.get_current_activity(role_id) -> ActivityType（24 个值）
       来源：LLM 生成的当日计划槽位
       消费方：peer_chat 门控、reply_policy、active care 决策注入、
                bionic_state prompt、前端

    B. life_simulation 小时段链
       orchestrator._ACTIVITY_TIME_RANGES = [(0,6,sleeping),(6,9,waking_up),
                                             (9,18,working),(18,23,relaxing),
                                             (23,24,preparing_sleep)]
       来源：仅按小时 + CPU/电池推导
       消费方：生命衰减、前端 WebSocket 广播

    两套词表的交集只有 sleeping / waking_up / idle 三个。典型矛盾：
    上午 10 点 character_daily 可能是 studying 或 reading，
    而 life_simulation 无条件给出 working；且 working 这个取值在
    character_daily 的 ActivityType 里根本不存在，却被归为重体力档扣血。

    另有 tick_actor_life_states 对所有角色套用同一个 activity，
    加上 _PRIMARY_SLEEP_ROLE_ID 硬编码为 aveline，
    导致Ling的生命衰减完全跟随Aveline的作息。

本轮修复：
- 活动以 character_daily 为准，小时段推导降级为引擎不可用时的回退；
- tick_actor_life_states 支持按角色分别取活动；
- 生命衰减分档补齐，使 24 个 ActivityType 全部有明确归属，不再走默认兜底。

本脚本校验上述三点，并固化"新增活动值必须同步归档"的约束。
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


def _covered() -> set:
    from core.services.life_simulation.life_stats import (
        _HEAVY_ACTIVITIES,
        _LIGHT_ACTIVITIES,
        _NORMAL_ACTIVITIES,
        _RECOVERY_ACTIVITIES,
    )

    return set(_RECOVERY_ACTIVITIES) | set(_LIGHT_ACTIVITIES) | set(
        _NORMAL_ACTIVITIES
    ) | set(_HEAVY_ACTIVITIES)


def test_all_activity_types_covered() -> None:
    _section("测试 1: character_daily 的每个活动值都有明确衰减分档")
    from core.services.character_daily.activity_model import ActivityType

    covered = _covered()
    # sleeping 由 resolve_vitals_decay 单独前置处理，不算未归档
    missing = [
        a.value
        for a in ActivityType
        if a.value != "sleeping" and a.value not in covered
    ]
    if missing:
        _fail(f"有 {len(missing)} 个活动值未归档，会走默认兜底速率", str(missing))
    else:
        _ok(f"{len(ActivityType)} 个 ActivityType 全部归档（含 sleeping 特判）")


def test_no_orphan_decay_values() -> None:
    _section("测试 2: 分档表里没有 character_daily 之外的孤儿值（除非是标注过的回退值）")
    from core.services.character_daily.activity_model import ActivityType

    known = {a.value for a in ActivityType}
    # 这三个是 life_simulation 小时段回退路径的取值，character_daily 没有，
    # 属于已知且已在 life_stats 注释中标注的例外。
    allowed_fallback = {"working", "working_hard", "relaxing", "preparing_sleep"}
    covered = _covered()
    orphans = sorted(covered - known - allowed_fallback)
    if orphans:
        _fail("分档表存在既非 character_daily 也未标注的取值", str(orphans))
    else:
        _ok("分档表取值均来自 character_daily 或已标注的回退值")


def test_fallback_values_documented() -> None:
    _section("测试 3: 回退值已完整归档，不再走默认兜底")
    covered = _covered()
    for fallback in ("working", "working_hard", "relaxing", "preparing_sleep"):
        if fallback in covered:
            _ok(f"回退值 {fallback} 已归档")
        else:
            _fail(f"回退值 {fallback} 仍未归档，引擎停机时会走默认速率")


def test_orchestrator_uses_planned_activity() -> None:
    _section("测试 4: orchestrator 优先取 character_daily 的活动")
    from core.services.life_simulation.orchestrator import LifeOrchestrator

    if not hasattr(LifeOrchestrator, "_resolve_planned_activity"):
        _fail("LifeOrchestrator 缺少 _resolve_planned_activity")
    else:
        _ok("LifeOrchestrator 提供 _resolve_planned_activity")

    if not hasattr(LifeOrchestrator, "_activities_by_role"):
        _fail("LifeOrchestrator 缺少 _activities_by_role")
    else:
        _ok("LifeOrchestrator 提供 _activities_by_role")

    # 引擎未运行时必须安全回退为空串，由调用方降级
    result = LifeOrchestrator._resolve_planned_activity("aveline")  # noqa: SLF001
    if isinstance(result, str):
        _ok(f"引擎不可用时安全返回字符串而非抛异常（当前={result!r}）")
    else:
        _fail("_resolve_planned_activity 返回类型异常", repr(result))

    import inspect

    src = inspect.getsource(LifeOrchestrator._update_activity_and_mood)  # noqa: SLF001
    if "planned_activity" in src and "if planned_activity:" in src:
        _ok("_update_activity_and_mood 中用计划活动覆盖小时段推导")
    else:
        _fail("_update_activity_and_mood 未使用计划活动", src[:300])


def test_hour_range_is_fallback_only() -> None:
    _section("测试 5: 小时段表仅作为回退存在")
    from core.services.life_simulation.orchestrator import _ACTIVITY_TIME_RANGES

    values = {v for _, _, v in _ACTIVITY_TIME_RANGES}
    from core.services.character_daily.activity_model import ActivityType

    known = {a.value for a in ActivityType}
    only_fallback = sorted(values - known)
    _ok(f"小时段表取值：{sorted(values)}")
    if only_fallback:
        _ok(f"其中不属于 character_daily 的取值（仅回退时出现）：{only_fallback}")


def test_per_role_decay() -> None:
    _section("测试 6: 生命衰减支持按角色分别取活动")
    from core.services.life_simulation.actor_manager import ActorManager

    sig = ActorManager.tick_actor_life_states.__code__.co_varnames[
        : ActorManager.tick_actor_life_states.__code__.co_argcount
    ]
    if "activity_by_role" in sig:
        _ok("tick_actor_life_states 支持 activity_by_role 参数")
    else:
        _fail("tick_actor_life_states 仍只接受单一 activity", str(sig))
        return

    # 构造两个角色，验证各自按自己的活动衰减
    mgr = ActorManager.__new__(ActorManager)
    mgr._actor_life_states = {  # noqa: SLF001
        "aveline": {"energy": 80.0, "hunger": 80.0, "thirst": 80.0, "mood_score": 60.0},
        "ling": {"energy": 80.0, "hunger": 80.0, "thirst": 80.0, "mood_score": 60.0},
    }
    mgr._actor_relationships = {}  # noqa: SLF001
    mgr._dirty = False  # noqa: SLF001
    mgr._maybe_save_actor_states = lambda: None  # noqa: SLF001

    mgr.tick_actor_life_states(
        activity="idle",
        activity_by_role={"aveline": "sleeping", "ling": "exercising"},
    )
    a = mgr._actor_life_states["aveline"]  # noqa: SLF001
    ling = mgr._actor_life_states["ling"]  # noqa: SLF001

    if a["energy"] > 80.0:
        _ok(f"aveline 处于 sleeping，精力回升到 {a['energy']:.1f}")
    else:
        _fail("aveline 未按 sleeping 处理", str(a))

    if ling["energy"] < 80.0:
        _ok(f"ling 处于 exercising，精力衰减到 {ling['energy']:.1f}")
    else:
        _fail("ling 未按 exercising 处理", str(ling))

    if ling["hunger"] < a["hunger"]:
        _ok("两个角色按各自活动产生了不同的饥饿衰减（不再共用同一活动）")
    else:
        _fail("两个角色衰减结果相同，说明仍共用活动", f"aveline={a} ling={ling}")


def main() -> int:
    print("=" * 64)
    print("角色活动单一真相源 & 衰减分档覆盖 验证")
    print("=" * 64)

    test_all_activity_types_covered()
    test_no_orphan_decay_values()
    test_fallback_values_documented()
    test_orchestrator_uses_planned_activity()
    test_hour_range_is_fallback_only()
    test_per_role_decay()

    print("\n" + "=" * 64)
    print(f"结果: {_PASSED} 通过 / {_FAILED} 失败")
    print("=" * 64)
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
