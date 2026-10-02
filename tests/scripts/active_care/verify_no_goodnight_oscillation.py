#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证「角色跟着作息表反复睡觉 / 催用户睡觉」的震荡循环已被打断。

背景（2026-09-22）：
用户凌晨还在正常聊天，角色却每 1~2 分钟发一条"我先睡了"的告别消息，
并反复在 sleeping / 被叫醒之间横跳。日志实证：

    04:31:29  ReplyPolicy: 睡觉中，静默累积消息 (count=3, will_process_on_wake)
    04:31:29  ReplyPolicy: 不可打扰但被强制唤醒（prob=1.00），延迟 0.1s 回复
    04:31:29  RoleWakeCtx: DND 累积计数已重置（成功唤醒）
    04:31:30  角色 aveline 进入 SLEEPING（prev=fully_awake），已异步触发晚安主动消息
    04:31:31  角色 aveline 进入 WAKING_UP（prev=night_awake），已异步触发起床问候消息
    04:31:31  角色 aveline 进入 SLEEPING（prev=fully_awake），已异步触发晚安主动消息

闭环：角色按作息表入睡（sleeping=DND）→ 用户发消息被判"静默累积" →
因为用户身份被强制唤醒回复 → 唤醒后 DND 计数重置 → 下一轮又判"在睡"。
每一轮"进入 SLEEPING"都触发一次 goodnight_proactive，其 prompt 模板
硬塞"现在是深夜 / 你要睡了 / 说句告别"，于是用户在正常聊天时被反复催睡。

另有一个独立的学习污染：MDP 把"用户回复"一律当 +1.0 奖励，导致
late_night|sleep|replied::goodnight_proactive 的 Q 值虚高到 0.863
（执行过 51 次），深夜越发越勤。

本脚本验证四项修复：
  A. 睡眠窗口里"用户在聊天"时不再把活动覆盖成 sleeping
  B. 用户正在聊天时不触发晚安主动消息（两道防线）
  C. 深夜睡眠题材的回复不再计入 MDP/Bandit 正反馈
  D. 新增阈值均可通过配置调整（用户要求：不许写死）

运行：
    venv_core/Scripts/python.exe tests/scripts/active_care/verify_no_goodnight_oscillation.py
"""
from __future__ import annotations

import inspect
import sys
from datetime import datetime
from pathlib import Path

# 允许从仓库根目录直接运行
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_PASSED = 0
_FAILED = 0
_FAILURES: list[str] = []


def check(group: str, name: str, condition: bool, detail: str = "") -> None:
    """记录一条断言。"""
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  [PASS] {name}")
    else:
        _FAILED += 1
        _FAILURES.append(f"{group} :: {name} {detail}")
        print(f"  [FAIL] {name} {detail}")


# ============================================================
# A. get_activity_override：用户在聊天时不覆盖成 sleeping
# ============================================================
def test_activity_override() -> None:
    print("\n[A] 睡眠窗口里用户在聊天时不再覆盖成 sleeping")
    from core.services.life_simulation.sleep_manager import SleepManager
    from core.services.life_simulation.sleep_models import SleepPhase

    src = inspect.getsource(SleepManager.get_activity_override)
    check(
        "A",
        "get_activity_override 调用了 _is_user_chatting_with_role",
        "_is_user_chatting_with_role" in src,
    )

    helper_src = inspect.getsource(SleepManager._is_user_chatting_with_role)
    check(
        "A",
        "_is_user_chatting_with_role 走按角色过滤的 is_active_for_scope",
        "is_active_for_scope" in helper_src,
        "（必须按角色过滤，不能全局口径）",
    )
    check(
        "A",
        "_is_user_chatting_with_role 读可配置的宽限期",
        "role_awake_while_user_chatting_grace_seconds" in helper_src,
    )
    check(
        "A",
        "_is_user_chatting_with_role 异常时保守返回 False",
        "return False" in helper_src,
    )

    # 行为验证：SLEEPING + 用户在聊天 -> 不返回 sleeping
    class _State:
        phase = SleepPhase.SLEEPING
        actual_wakeup_ts = 0.0
        sleep_inertia_score = 0.0
        stay_up_activity = "idle"
        sleep_later_until_ts = 0.0

    class _Mgr(SleepManager):
        def __init__(self):  # 绕过真实构造，只测 override 分支
            pass

        def get_state(self, role_id, now=None):
            return _State()

    mgr = _Mgr()
    mgr.get_activity_override.__func__  # noqa: B018 - 保留引用便于阅读

    # 用 monkeypatch 风格直接替换实例方法
    chat_flags = {"chatting": True}
    mgr._is_user_chatting_with_role = lambda role_id: chat_flags["chatting"]  # type: ignore[method-assign]

    result_chatting = SleepManager.get_activity_override(
        mgr, "aveline", now=datetime(2026, 9, 22, 4, 30)
    )
    check(
        "A",
        "SLEEPING + 用户正在聊天 -> 不返回 sleeping",
        result_chatting != "sleeping",
        f"(实际 {result_chatting!r})",
    )

    chat_flags["chatting"] = False
    result_idle = SleepManager.get_activity_override(
        mgr, "aveline", now=datetime(2026, 9, 22, 4, 30)
    )
    check(
        "A",
        "SLEEPING + 用户没在聊天 -> 恢复返回 sleeping",
        result_idle == "sleeping",
        f"(实际 {result_idle!r})",
    )


# ============================================================
# B. 深夜免打扰：用户聊天时不触发晚安主动消息
# ============================================================
def test_goodnight_suppressed() -> None:
    print("\n[B] 用户正在聊天时不发晚安主动消息（两道防线）")
    from core.services.life_simulation.sleep_manager import SleepManager
    from core.services.active_care import goodnight_proactive as gp

    entering_src = inspect.getsource(SleepManager._on_enter_sleeping)
    check(
        "B",
        "第一道防线：_on_enter_sleeping 在用户聊天时提前 return",
        "_is_user_chatting_with_role" in entering_src
        and "跳过" in entering_src,
    )

    trigger_src = inspect.getsource(gp.trigger_character_goodnight)
    check(
        "B",
        "第二道防线：trigger_character_goodnight 在用户聊天时提前 return",
        "_is_user_in_conversation" in trigger_src,
    )

    # 关键：不再"换个 instruction 继续发"，而是直接不发
    check(
        "B",
        "不再使用'聊天中入睡告别 instruction'继续发消息",
        "build_sleep_during_chat_farewell_instruction" not in trigger_src,
        "（那样仍会打扰对话）",
    )


# ============================================================
# C. MDP 奖励：深夜睡眠题材不计正反馈
# ============================================================
def test_mdp_reward_guard() -> None:
    print("\n[C] 深夜睡眠题材的回复不再计入正反馈")
    from core.services.active_care.core.user_response_handler import (
        UserResponseHandler,
        _SLEEP_INTENT_NAMES,
    )

    handler_src = inspect.getsource(UserResponseHandler._reward_last_action)
    check(
        "C",
        "_reward_last_action 有深夜睡眠题材守卫",
        "_is_late_night_sleep_topic" in handler_src,
    )
    check(
        "C",
        "守卫只拦正奖励，负奖励（用户忽略）仍保留",
        "reward > 0" in handler_src,
    )

    check(
        "C",
        "睡眠 intent 名单含 goodnight_proactive",
        "goodnight_proactive" in _SLEEP_INTENT_NAMES,
    )
    check(
        "C",
        "睡眠 intent 名单含 sleep_again_proactive",
        "sleep_again_proactive" in _SLEEP_INTENT_NAMES,
    )

    # 时段判定：需要冻结时间才能确定性验证
    is_late = UserResponseHandler._is_late_night_sleep_topic
    from core.services.active_care.core import user_response_handler as urh

    class _FrozenNow:
        def __init__(self, h):
            self._h = h

        def __call__(self):
            return datetime(2026, 9, 22, self._h, 30)

    import core.utils.time_utils as time_utils

    original = time_utils.get_current_time
    try:
        # 深夜：晚安类题材 -> True
        time_utils.get_current_time = _FrozenNow(4)
        check(
            "C",
            "凌晨 04:30 + goodnight_proactive:sleep -> 判定为深夜睡眠题材",
            is_late("goodnight_proactive:sleep") is True,
        )
        check(
            "C",
            "凌晨 04:30 + sleep_again_proactive:sleep -> 判定为深夜睡眠题材",
            is_late("sleep_again_proactive:sleep") is True,
        )
        check(
            "C",
            "凌晨 04:30 + share_thought:sleep -> 不算（普通聊天不误伤）",
            is_late("share_thought:sleep") is False,
        )

        # 白天：同一题材不再拦截
        time_utils.get_current_time = _FrozenNow(14)
        check(
            "C",
            "下午 14:30 + goodnight_proactive:sleep -> 不算（白天不拦）",
            is_late("goodnight_proactive:sleep") is False,
        )

        # 边界：23:00 恰好在深夜区间内
        time_utils.get_current_time = _FrozenNow(23)
        check(
            "C",
            "23:30 + goodnight_proactive:sleep -> 算（深夜区间含 23 点）",
            is_late("goodnight_proactive:sleep") is True,
        )
        # 边界：06:00 起不算深夜
        time_utils.get_current_time = _FrozenNow(6)
        check(
            "C",
            "06:30 + goodnight_proactive:sleep -> 不算（深夜区间到 5 点止）",
            is_late("goodnight_proactive:sleep") is False,
        )
    finally:
        time_utils.get_current_time = original

    check(
        "C",
        "空题材安全返回 False",
        is_late("") is False,
    )


# ============================================================
# D. 阈值可配（用户明确要求）
# ============================================================
def test_configurable() -> None:
    print("\n[D] 新增阈值均可通过配置调整")
    from core.utils.config_accessor import get_config
    from config.integrated_config import get_settings

    value = get_config(
        "life_simulation.role_awake_while_user_chatting_grace_seconds",
        default=None,
    )
    check(
        "D",
        "role_awake_while_user_chatting_grace_seconds 已在 app.yaml 可读",
        value is not None,
        f"(实际 {value!r})",
    )
    check(
        "D",
        "宽带期默认值为 600 秒",
        float(value) == 600.0,
        f"(实际 {value!r})",
    )

    # 关键：yaml 里写了的键，必须在 pydantic 设置类里也显式声明，
    # 否则 get_settings() 的对象根本拿不到该属性，yaml 改了也没用
    # （extra="allow" 只在构造时传入才生效）。这是上一轮的真实漏网之鱼。
    ls = get_settings().life_simulation
    for attr in (
        "active_care_bert_wakeup_exit_threshold",
        "active_care_daytime_exit_activity_seconds",
        "role_awake_while_user_chatting_grace_seconds",
        "study_mode",
    ):
        check(
            "D",
            f"LifeSimulationSettings 已声明字段 {attr}",
            hasattr(ls, attr),
            "（只改 yaml 不改设置类 = 配置无效）",
        )

    study_mode = getattr(ls, "study_mode", None)
    if study_mode is not None:
        for sub in (
            "study_mode_session_ttl_seconds",
            "study_mode_max_turns",
            "study_mode_idle_turns",
            "study_mode_idle_seconds",
        ):
            check(
                "D",
                f"StudyModeSettings 已声明字段 {sub}",
                hasattr(study_mode, sub),
            )
    else:
        check("D", "study_mode 子配置存在", False)

    # 回归：上一轮新增的配置项仍在，不能被本次改动碰坏
    for key, expect in (
        ("life_simulation.active_care_bert_wakeup_exit_threshold", 0.70),
        ("life_simulation.active_care_daytime_exit_activity_seconds", 1800),
        ("life_simulation.study_mode.study_mode_session_ttl_seconds", 10800),
    ):
        got = get_config(key, default=None)
        check(
            "D",
            f"{key.split('.')[-1]} 仍可读且值正确",
            got is not None and float(got) == float(expect),
            f"(实际 {got!r})",
        )

    # 学习模式读取路径必须带 study_mode. 子前缀（曾经漏掉导致配置失效）
    from core.tools.study_mode_tool import get_study_session_limits

    limits = get_study_session_limits()
    check(
        "D",
        "get_study_session_limits 能读到 yaml 的值（路径含 study_mode. 子前缀）",
        float(limits["ttl_seconds"]) == 10800.0
        and int(limits["max_turns"]) == 60,
        f"(实际 {limits})",
    )


# ============================================================
# E. MDP 历史数据：深夜催睡组合已清理
# ============================================================
def test_mdp_table_cleaned() -> None:
    print("\n[E] MDP 表中深夜催睡的高 Q 组合已清理")
    import json

    path = _ROOT / "companion_data" / "aveline_data" / "active_care" / "active_care_mdp.json"
    if not path.exists():
        check("E", "MDP Q 表存在", False, f"({path} 不存在)")
        return

    with path.open(encoding="utf-8") as f:
        table = json.load(f)

    late_night_sleep = [k for k in table if k.startswith("late_night|sleep|")]
    check(
        "E",
        "已无 late_night|sleep| 条目（虚高 Q 值已清理）",
        not late_night_sleep,
        f"(残留 {late_night_sleep})",
    )

    bad = [
        k for k in table
        if k == "late_night|sleep|replied::goodnight_proactive"
    ]
    check(
        "E",
        "曾经 Q=0.863 / count=51 的催睡组合已移除",
        not bad,
    )

    # 白天晚安属于正常场景，不应被误删
    daytime = [
        k for k in table
        if k == "day|sleep|replied::goodnight_proactive"
    ]
    check(
        "E",
        "白天的晚安学习数据保留（不误删正常场景）",
        bool(daytime),
    )


def main() -> int:
    print("=" * 64)
    print("验证：打断「角色反复睡觉 / 催用户睡觉」的震荡循环")
    print("=" * 64)

    test_activity_override()
    test_goodnight_suppressed()
    test_mdp_reward_guard()
    test_configurable()
    test_mdp_table_cleaned()

    print("\n" + "=" * 64)
    print(f"结果：{_PASSED} passed, {_FAILED} failed")
    if _FAILURES:
        print("失败项：")
        for item in _FAILURES:
            print(f"  - {item}")
    print("=" * 64)
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
