"""验证「学习模式误触发/无法退出」与「醒来后卡在晚安模式」两个修复（2026-09-21）

背景（来自真实日志 logs/2026/9/21/xiaoyou_main.log）：

问题 1 —— 莫名进入学习模式且退不出来：
    [23:05:47] [Native Tool] Executing: enter_study_mode
    [23:05:47] [Tools.StudyMode] 用户 web_role_aveline 进入学习模式 subject=物理 topic=费米能级
用户只是在聊安卓开发/软硬件，模型自行脑补出学科「物理」、主题「费米能级」；
且 _study_sessions 只在内存、无过期机制，进去后除非模型主动调用 exit 否则永久锁定。

问题 2 —— 醒来后系统一直卡在晚安模式：
    [22:24:20] [MODE_STATE] 忽略缺少明确起床陈述的 BERT WAKEUP_NOW: conf=0.80 text=才醒
    [22:39:22] [MODE_STATE] 忽略缺少明确起床陈述的 BERT WAKEUP_NOW: conf=0.60 text=...我睡觉的时候也被她吵醒了...
    Active Care: 仍在晚安模式，无法退出 (...)  ← 从 16:51 一直打到 22:24
用户确实是那个点睡的，22 点也确实是起来说了「我醒了」，但 BERT 的高置信
苏醒信号被 mode_state 无条件丢弃，退出闸门一路落空。

修复内容：
A) core/tools/study_mode_tool.py
   - 收紧 enter_study_mode 描述（禁止闲聊/随口提专业名词时调用）
   - subject/topic 反脑补：只接受用户原话里出现过的词
   - 新增 tick_study_session：轮次上限 / TTL / 空闲轮次 / 空闲时长 四重自动退出
B) core/agents/.../dynamic_injections.py
   - _study_mode 每轮调用 tick_study_session 推进会话心跳
C) core/services/active_care/state/mode_state.py
   - is_direct_awake_statement 放宽（允许「才醒」这类带上下文的起床自述）
   - BERT WAKEUP_NOW 不再无条件丢弃；置信度 >= 可配置阈值时允许退出低打扰
D) core/services/active_care/core/sleep_session_manager.py
   - 新增白天兜底退出：晚安后持续活跃满阈值即退出，不依赖单句意图

运行：
    D:\\AI\\xiaoyou-core\\venv_core\\Scripts\\python.exe -m tests.scripts.prompt.verify_study_mode_and_awake_exit
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Dict

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  [PASS] {name}")
    else:
        _FAILED += 1
        print(f"  [FAIL] {name}" + (f" -- {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# 问题 1：学习模式
# ---------------------------------------------------------------------------

def test_study_tool_description_is_tightened():
    """验证 enter_study_mode 描述明确禁止闲聊/随口提专业名词时调用。"""
    print("\n[1] 学习模式工具描述收紧")
    from core.tools.study_mode_tool import EnterStudyModeTool

    desc = EnterStudyModeTool.description
    _check("描述包含『明确要求』限定", "明确要求" in desc)
    _check("描述显式禁止闲聊场景", "禁止调用" in desc)
    _check("描述禁止随口提到专业名词", "半导体" in desc or "变频器" in desc)
    _check("描述要求 subject/topic 来自用户原话", "用户原话" in desc)


def test_study_subject_topic_anti_hallucination():
    """验证模型脑补的 subject/topic 会被清洗掉。"""
    print("\n[2] subject/topic 反脑补")
    from core.tools.study_mode_tool import _sanitize_subject_topic

    # 用户原话里没有「物理」「费米能级」→ 应被清空
    subj, topic = _sanitize_subject_topic(
        "物理", "费米能级", "我那个安卓输入法的发送键逻辑有点问题"
    )
    _check("脑补的学科被清空", subj == "", f"got={subj!r}")
    _check("脑补的主题被清空", topic == "", f"got={topic!r}")

    # 用户原话里真的有 → 应保留
    subj2, topic2 = _sanitize_subject_topic(
        "佛学", "般若心经", "我准备学佛学，从般若心经开始吧"
    )
    _check("原话提及的学科保留", subj2 == "佛学", f"got={subj2!r}")
    _check("原话提及的主题保留", topic2 == "般若心经", f"got={topic2!r}")

    # 拿不到用户原话 → 保守清空
    subj3, topic3 = _sanitize_subject_topic("物理", "费米能级", "")
    _check("无用户原话时保守清空", subj3 == "" and topic3 == "", f"got={subj3!r}/{topic3!r}")


def test_study_session_auto_expire():
    """验证学习会话四重自动退出。"""
    print("\n[3] 学习会话自动过期")
    from core.tools import study_mode_tool as smt

    smt.reset_study_sessions()
    uid = "verify_study_user"

    # 3.1 空闲轮次：连续多轮无学习信号 → 自动退出
    smt._set_study_state(uid, True, "佛学", "般若心经")
    _check("初始处于学习模式", smt.is_study_mode_active(uid))
    exited = None
    for _ in range(10):
        exited = smt.tick_study_session(uid, has_learning_signal=False)
        if exited:
            break
    _check("连续无学习信号后自动退出", bool(exited), f"exited={exited}")
    _check(
        "退出原因含『无学习信号』",
        bool(exited and "无学习信号" in str(exited.get("exit_reason"))),
        f"reason={exited.get('exit_reason') if exited else None}",
    )
    _check("退出后状态为未激活", not smt.is_study_mode_active(uid))

    # 3.2 有学习信号则不退出
    smt.reset_study_sessions()
    smt._set_study_state(uid, True, "佛学", "般若心经")
    still_active = True
    for _ in range(10):
        if smt.tick_study_session(uid, has_learning_signal=True):
            still_active = False
            break
    _check("持续有学习信号时保持激活", still_active and smt.is_study_mode_active(uid))

    # 3.3 轮次上限
    smt.reset_study_sessions()
    smt._set_study_state(uid, True, "佛学", "般若心经")
    limits = smt.get_study_session_limits()
    max_turns = int(limits["max_turns"])
    hit_turn_limit = None
    for _ in range(max_turns + 5):
        r = smt.tick_study_session(uid, has_learning_signal=True)
        if r:
            hit_turn_limit = r
            break
    _check("达到轮次上限自动退出", bool(hit_turn_limit), f"limits={limits}")
    _check(
        "退出原因含『轮次上限』",
        bool(hit_turn_limit and "轮次上限" in str(hit_turn_limit.get("exit_reason"))),
        f"reason={hit_turn_limit.get('exit_reason') if hit_turn_limit else None}",
    )

    # 3.4 TTL（直接篡改 entered_at 模拟长时间会话）
    smt.reset_study_sessions()
    smt._set_study_state(uid, True, "佛学", "般若心经")
    session = smt.get_study_session(uid)
    ttl = float(limits["ttl_seconds"])
    session["entered_at"] = time.time() - (ttl + 60)
    session["last_signal_at"] = time.time()
    r_ttl = smt.tick_study_session(uid, has_learning_signal=True)
    _check("超过 TTL 自动退出", bool(r_ttl), f"ttl={ttl}")
    _check(
        "退出原因含『超过会话时长』",
        bool(r_ttl and "超过会话时长" in str(r_ttl.get("exit_reason"))),
        f"reason={r_ttl.get('exit_reason') if r_ttl else None}",
    )

    smt.reset_study_sessions()


def test_study_limits_are_configurable():
    """验证学习模式阈值来自可配置项。"""
    print("\n[4] 学习模式阈值可配置")
    from core.tools.study_mode_tool import get_study_session_limits

    limits = get_study_session_limits()
    _check("包含 ttl_seconds", "ttl_seconds" in limits, f"limits={limits}")
    _check("包含 max_turns", "max_turns" in limits, f"limits={limits}")
    _check("包含 idle_turns", "idle_turns" in limits, f"limits={limits}")
    _check("包含 idle_seconds", "idle_seconds" in limits, f"limits={limits}")
    _check(
        "阈值均为有效正数",
        all(float(limits[k]) > 0 for k in ("ttl_seconds", "max_turns", "idle_turns", "idle_seconds")),
        f"limits={limits}",
    )


# ---------------------------------------------------------------------------
# 问题 2：醒来后卡在晚安模式
# ---------------------------------------------------------------------------

def test_direct_awake_statement_recognizes_real_utterances():
    """验证真实起床陈述能被识别（含用户日志中的原话）。"""
    print("\n[5] 起床陈述识别放宽")
    from core.services.active_care.state.mode_state import is_direct_awake_statement

    # 日志中真实出现、但旧实现漏判的原话
    for text in ["才醒", "我醒了", "我刚醒", "我睡觉的时候也被她吵醒了，气死我", "刚起来", "早安"]:
        _check(f"识别起床陈述: {text[:20]}", is_direct_awake_statement(text))

    # 讨论语境不应误判
    for text in ["你起床了吗", "几点醒的", "我明天几点起来比较好"]:
        _check(f"不误判讨论语境: {text}", not is_direct_awake_statement(text))


def test_bert_wakeup_no_longer_unconditionally_discarded():
    """验证 BERT WAKEUP_NOW 在晚安低打扰中不再被无条件丢弃。"""
    print("\n[6] BERT 苏醒信号不再被无条件丢弃")
    from core.services.active_care.state.mode_state import ModeStateManager
    import inspect

    src = inspect.getsource(ModeStateManager.detect_transition_intent)
    _check(
        "旧的无条件丢弃分支已移除",
        "忽略缺少明确起床陈述的 BERT WAKEUP_NOW" not in src,
        "仍存在旧的 return none 分支",
    )
    _check("存在阈值判断", "_bert_wakeup_exit_threshold" in src)

    mgr = ModeStateManager(storage=None)
    thr = mgr._bert_wakeup_exit_threshold()
    _check("阈值可读取且为正数", float(thr) > 0, f"threshold={thr}")
    _check("默认阈值为 0.70", abs(float(thr) - 0.70) < 1e-9, f"threshold={thr}")


def test_awake_statement_exits_goodnight_mode():
    """端到端：用户说「才醒」应让 detect_transition_intent 给出退出意图。"""
    print("\n[7] 醒来陈述触发退出低打扰（端到端）")
    from core.services.active_care.state.mode_state import ModeStateManager

    mgr = ModeStateManager(storage=None)
    intent = asyncio.run(mgr.detect_transition_intent("才醒"))
    _check("action 为 exit_reduced", intent.get("action") == "exit_reduced", f"intent={intent}")
    _check("reason 为 morning", intent.get("reason") == "morning", f"intent={intent}")
    _check("label 为 wake", intent.get("label") == "wake", f"intent={intent}")

    intent2 = asyncio.run(mgr.detect_transition_intent("我醒了"))
    _check("『我醒了』同样退出", intent2.get("action") == "exit_reduced", f"intent={intent2}")


def test_daytime_backstop_helper():
    """验证白天兜底退出判定逻辑。"""
    print("\n[8] 白天兜底退出逻辑")
    from core.services.active_care.core.sleep_session_manager import SleepSessionManager

    mgr = SleepSessionManager(
        intent_detector=None,
        sleep_policy=None,
        storage=None,
        get_config_value=lambda k, d: d,
        checker=None,
    )
    threshold = mgr._sustained_activity_after_goodnight_seconds()
    _check("兜底阈值可读取且为正数", float(threshold) > 0, f"threshold={threshold}")
    _check("默认阈值为 1800s", abs(float(threshold) - 1800.0) < 1e-9, f"threshold={threshold}")

    now = time.time()
    goodnight_ts = now - 10000.0

    # 晚安后 2000s（>1800s 阈值）有信号 → 应判定为持续活跃
    signal_fresh = now - 2000.0
    _check(
        "晚安后持续活跃超阈值 → 判定为已清醒",
        mgr._has_sustained_activity_after_goodnight({}, signal_fresh, goodnight_ts, now),
    )

    # 刚刚才在晚安后有信号（距今不足阈值）→ 不应兜底退出
    signal_just = now - 10.0
    _check(
        "晚安后刚有信号（未满阈值）→ 不兜底退出",
        not mgr._has_sustained_activity_after_goodnight({}, signal_just, goodnight_ts, now),
    )

    # 信号早于晚安（旧消息重放）→ 不应退出
    signal_before = goodnight_ts - 100.0
    _check(
        "信号早于晚安（旧消息重放）→ 不退出",
        not mgr._has_sustained_activity_after_goodnight({}, signal_before, goodnight_ts, now),
    )


def test_config_entries_present():
    """验证新增配置项都在 app.yaml 里可改。"""
    print("\n[9] 新增配置项可修改")
    import yaml

    root = Path(__file__).resolve().parents[3]
    cfg_path = root / "config" / "yaml" / "app.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    ls = data.get("life_simulation", {})

    for key in (
        "active_care_bert_wakeup_exit_threshold",
        "active_care_daytime_exit_activity_seconds",
    ):
        _check(f"app.yaml 含 {key}", key in ls, f"keys={sorted(ls.keys())[:10]}...")

    study = ls.get("study_mode") or {}
    for key in (
        "study_mode_session_ttl_seconds",
        "study_mode_max_turns",
        "study_mode_idle_turns",
        "study_mode_idle_seconds",
    ):
        _check(f"app.yaml 含 study_mode.{key}", key in study, f"study_mode={study}")


def main():
    print("=" * 78)
    print("验证：学习模式误触发/无法退出 + 醒来后卡在晚安模式（2026-09-21）")
    print("=" * 78)

    test_study_tool_description_is_tightened()
    test_study_subject_topic_anti_hallucination()
    test_study_session_auto_expire()
    test_study_limits_are_configurable()
    test_direct_awake_statement_recognizes_real_utterances()
    test_bert_wakeup_no_longer_unconditionally_discarded()
    test_awake_statement_exits_goodnight_mode()
    test_daytime_backstop_helper()
    test_config_entries_present()

    print("\n" + "=" * 78)
    print(f"结果：{_PASSED} passed, {_FAILED} failed")
    print("=" * 78)
    return 1 if _FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
