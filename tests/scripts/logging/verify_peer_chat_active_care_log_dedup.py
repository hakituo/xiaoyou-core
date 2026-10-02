#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证：peer chat 关闭后不再刷日志、Active Care 静默模式降噪生效

背景
----
1. peer chat 总开关读的是不存在的配置路径：get_active_care_config("peer_chat_enabled")
   内部强制拼 life_simulation. 前缀，而该字段只定义在 DualRoleSettings
   （yaml 的 dual_role 段），读取永远回落到 default=True，关掉开关后互聊照常调度。
2. CharacterDaily / peer_chat_gate 每个 tick 无条件打印拦截与诊断日志。
3. Active Care 主循环与决策流程的常规 INFO 在静默模式下照常每轮输出。

验证项
------
A. is_peer_chat_enabled() 正确读到 dual_role.peer_chat_enabled（并复现旧路径恒 True）
B. 开关关闭时 PeerChatScheduler 单周期静默返回，且提示只打一次
C. CharacterDaily 引擎源码中 peer chat 检查受总开关保护
D. peer_chat_gate 拦截日志默认不落盘，debug.peer_chat 打开后才输出
E. 主循环调度日志：静默时降级 debug、非静默时 info 且 60s 节流

运行：
    venv_core\\Scripts\\python.exe tests\\scripts\\logging\\verify_peer_chat_active_care_log_dedup.py
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class _Capture(logging.Handler):
    """收集指定 logger 上的所有记录"""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def messages(self, level=None):
        if level is None:
            return [r.getMessage() for r in self.records]
        return [r.getMessage() for r in self.records if r.levelno == level]


def _attach(logger_name):
    from core.utils.logger import get_logger

    lg = get_logger(logger_name)
    lg.setLevel(logging.DEBUG)
    cap = _Capture()
    lg.addHandler(cap)
    return lg, cap


def _detach(lg, cap):
    lg.removeHandler(cap)


def check_a():
    """A. 开关读取路径修复"""
    from core.services.character_daily.peer_chat_gate import is_peer_chat_enabled
    from core.utils.config_accessor import get_active_care_config
    from config.integrated_config import get_settings

    expected = bool(get_settings().dual_role.peer_chat_enabled)
    actual = is_peer_chat_enabled()
    assert actual == expected, "开关读取结果应等于 dual_role.peer_chat_enabled"
    print("  [A1] dual_role.peer_chat_enabled=%s, is_peer_chat_enabled()=%s OK" % (expected, actual))

    if not expected:
        legacy = bool(get_active_care_config("peer_chat_enabled", default=True))
        assert legacy is True, "预期旧路径恒为 True，实际 False，请复核本用例"
        print("  [A2] 旧路径 get_active_care_config 仍恒为 True（已不再使用）OK")
    else:
        print("  [A2] dual_role.peer_chat_enabled=true，跳过旧路径对比")


def check_b():
    """B. 开关关闭时 PeerChatScheduler 单周期静默，提示只打一次"""
    from core.services.active_care.peer_chat.peer_chat_scheduler import PeerChatScheduler
    from config.integrated_config import get_settings

    enabled = bool(get_settings().dual_role.peer_chat_enabled)
    lg, cap = _attach("PEER_CHAT_SCHEDULER")
    try:
        sched = PeerChatScheduler.__new__(PeerChatScheduler)
        sched._settings = get_settings()
        sched._disabled_flag_logged = ""
        sched._total_runs = 0
        sched._last_run_ts = 0.0
        sched._consecutive_failures = 0

        for _ in range(3):
            asyncio.run(sched._run_single_cycle())

        infos = cap.messages(logging.INFO)
        if not enabled:
            assert len(infos) == 1, "关闭态 3 个周期应只 1 条提示，实际 %d 条: %s" % (len(infos), infos)
            assert "已禁用" in infos[0], "关闭提示文案异常: %s" % infos[0]
            assert sched._total_runs == 0, "关闭态不应推进 _total_runs（提前返回未生效）"
            print("  [B1] 关闭态 3 周期仅 1 条提示、_total_runs=0 OK")
        else:
            print("  [B1] dual_role.peer_chat_enabled=true，跳过关闭态断言")
    finally:
        _detach(lg, cap)


def check_c():
    """C. CharacterDaily 引擎源码：peer chat 检查受总开关保护"""
    from core.services.character_daily import engine

    src = inspect.getsource(engine.CharacterDailyEngine._tick)
    assert "is_peer_chat_enabled()" in src, "_tick 应使用 is_peer_chat_enabled() 做总开关判断"

    gate_idx = src.index("_maybe_trigger_peer_chat(now)")
    switch_idx = src.rindex("is_peer_chat_enabled()", 0, gate_idx)
    assert switch_idx < gate_idx, "开关判断必须早于 _maybe_trigger_peer_chat 调用"
    print("  [C1] _tick 中总开关判断位于 peer chat 检查之前 OK")

    assert "if self._peer_chat_scheduler and is_peer_chat_enabled():" in src, (
        "提醒分工协商检查也应受总开关保护"
    )
    print("  [C2] 提醒分工协商检查受总开关保护 OK")


def check_d():
    """D. peer_chat_gate 拦截日志默认不落盘"""
    from core.services.character_daily import peer_chat_gate
    from core.services.character_daily.activity_model import ActivityType, DailyPlan
    from core.services.character_daily.config import CharacterDailyConfig
    from config.debug_config import get_debug_settings

    plan_a = DailyPlan(role_id="aveline", date="2026-09-15")
    plan_l = DailyPlan(role_id="ling", date="2026-09-15")
    # 双方都在不可打扰活动，命中条件4-双DND 拦截分支
    plan_a.current_activity = ActivityType.SLEEPING
    plan_l.current_activity = ActivityType.SLEEPING

    cfg = CharacterDailyConfig()
    now = datetime(2026, 9, 15, 12, 0)

    lg, cap = _attach("PEER_CHAT")
    debug_settings = get_debug_settings()
    original = debug_settings.peer_chat
    try:
        debug_settings.peer_chat = False
        cap.records.clear()
        result = peer_chat_gate.should_trigger_peer_chat(now, plan_a, plan_l, cfg)
        assert result == (False, None), "双 DND 应被拦截"
        assert cap.messages(logging.INFO) == [], "debug 关闭时不应输出拦截日志"
        print("  [D1] debug.peer_chat=false 时拦截日志 0 条 OK")

        debug_settings.peer_chat = True
        cap.records.clear()
        peer_chat_gate.should_trigger_peer_chat(now, plan_a, plan_l, cfg)
        assert len(cap.messages(logging.INFO)) >= 1, "debug 打开时应输出拦截日志"
        print("  [D2] debug.peer_chat=true 时拦截日志正常输出 OK")
    finally:
        debug_settings.peer_chat = original
        _detach(lg, cap)


def check_e():
    """E. 主循环调度日志：静默降级 debug、非静默 info 且 60s 节流"""
    from core.services.active_care.core.proactive_loop import ProactiveLoopRunner

    class _Service:
        def __init__(self):
            self._last_schedule_log_ts = 0.0
            self.checker = None

    lg, cap = _attach("ACTIVE_CARE")
    try:
        runner = ProactiveLoopRunner(_Service())

        cap.records.clear()
        runner.log_schedule_status(300, 1, quiet_mode=True)
        assert cap.messages(logging.INFO) == [], "静默模式不应输出 INFO 调度日志"
        assert len(cap.messages(logging.DEBUG)) == 1, "静默模式应输出 1 条 debug"
        print("  [E1] 静默模式调度日志降级为 debug OK")

        # 重置节流窗口，保证本用例不受上一条 debug 调用的时间戳影响
        runner._service._last_schedule_log_ts = 0.0
        cap.records.clear()
        runner.log_schedule_status(300, 2, quiet_mode=False)
        assert len(cap.messages(logging.INFO)) == 1, "非静默首轮应输出 1 条 info"
        print("  [E2] 非静默模式输出 info 调度日志 OK")

        cap.records.clear()
        runner.log_schedule_status(300, 3, quiet_mode=False)
        assert cap.messages(logging.INFO) == [], "60s 内重复调用应被节流"
        print("  [E3] 60s 节流生效（重复调用无输出）OK")

        runner._service._last_schedule_log_ts = 0.0
        cap.records.clear()
        runner.log_schedule_status(300, 4, quiet_mode=False)
        assert len(cap.messages(logging.INFO)) == 1, "超过节流窗口后应重新输出"
        assert "loop=4" in cap.messages(logging.INFO)[0], "调度日志应带 loop 轮次"
        print("  [E4] 节流窗口过后恢复输出且带 loop 轮次 OK")
    finally:
        _detach(lg, cap)


def check_f():
    """F. 幽灵配置项已补齐：字段声明存在、YAML 值能读到"""
    from core.utils.config_accessor import get_config, get_dual_role_config
    from config.debug_config import get_debug_settings, is_debug_enabled
    from config.integrated_config import get_settings

    settings = get_settings()

    # F1: debug.character_daily 字段此前未声明，is_debug_enabled 恒 False
    debug_settings = get_debug_settings()
    assert hasattr(debug_settings, "character_daily"), "DebugSettings 缺少 character_daily 字段"
    original = debug_settings.character_daily
    try:
        debug_settings.character_daily = True
        assert is_debug_enabled("character_daily") is True, "打开后 is_debug_enabled 应为 True"
    finally:
        debug_settings.character_daily = original
    print("  [F1] debug.character_daily 开关可用（不再恒 False）OK")

    # F2: active_care_quiet_hours 此前未声明，YAML 配了也恒为 {}
    quiet = get_config("life_simulation.active_care_quiet_hours", default=None)
    assert isinstance(quiet, dict) and quiet, "active_care_quiet_hours 应能读到 YAML 配置"
    print("  [F2] active_care_quiet_hours 读到 %d 个键（allow_goodnight_probe 可生效）OK" % len(quiet))

    # F3: peer_chat 阈值走 dual_role 段
    expected_limit = int(settings.dual_role.peer_chat_daily_limit)
    actual_limit = int(get_dual_role_config("peer_chat_daily_limit", default=-1))
    assert actual_limit == expected_limit, "peer_chat_daily_limit 应等于 dual_role 段配置"
    print("  [F3] get_dual_role_config 读到 peer_chat_daily_limit=%d OK" % actual_limit)

    # F4: primary_role_id 字段已声明（orchestrator 此前读的是不存在的 settings.life）
    assert hasattr(settings.life_simulation, "primary_role_id"), (
        "LifeSimulationSettings 缺少 primary_role_id"
    )
    assert not hasattr(settings, "life"), "AppSettings 不应有 life 段（正确段名是 life_simulation）"
    print("  [F4] life_simulation.primary_role_id 字段已声明 OK")


def main() -> int:
    checks = (
        ("A 开关读取路径", check_a),
        ("B 调度器关闭态静默", check_b),
        ("C 引擎源码开关保护", check_c),
        ("D 门控拦截日志降噪", check_d),
        ("E 主循环调度日志", check_e),
        ("F 幽灵配置项补齐", check_f),
    )
    failed = []
    for name, fn in checks:
        print("[%s]" % name)
        try:
            fn()
        except AssertionError as exc:
            failed.append(name)
            print("  FAIL: %s" % exc)
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            print("  ERROR: %s: %s" % (type(exc).__name__, exc))

    print("")
    if failed:
        print("验证失败: %s" % "、".join(failed))
        return 1
    print("全部验证通过：peer chat 关闭后静默、静默模式日志已降噪")
    return 0


if __name__ == "__main__":
    sys.exit(main())
