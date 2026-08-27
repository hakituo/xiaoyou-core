#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-2 验证：修复 fire-and-forget 任务引用管理

验证目标：
1. 关键 fire-and-forget 调用点已保存任务引用（避免被 GC 后异常被事件循环静默吞掉）
2. done_callback 已正确清理引用并记录异常
3. 已弃用的 asyncio.ensure_future(..., loop=loop) 写法已替换

涉及修改的文件：
- core/voice/engines/qwen3_tts_engine.py
- core/utils/log_sanitizer.py
- core/utils/logger.py
- core/services/scheduler/inference/python_llm_handler.py
- core/lifecycle/lifespan.py
- core/core_engine/service_singletons.py
- core/llm/cloud_router.py
- core/interfaces/websocket/connection_management.py
- core/services/active_care/goodnight_proactive.py
- core/services/active_care/good_morning_proactive.py
- core/services/active_care/peer_chat/peer_chat_scheduler.py
- core/services/active_care/core/service.py
- core/services/life_simulation/meal_chat.py
"""

import ast
import asyncio
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


def _read(path: str) -> str:
    return Path(PROJECT_ROOT / path).read_text(encoding="utf-8")


def _grep(pattern: str, content: str) -> list:
    return re.findall(pattern, content)


# ============================================================
# 场景 1：检查关键文件已添加任务集合变量与回调
# ============================================================

def test_1_qwen3_tts():
    """qwen3_tts_engine.py: 批处理任务集合 + _spawn_batch_task"""
    src = _read("core/voice/engines/qwen3_tts_engine.py")
    issues = []
    if "_batch_tasks: set = set()" not in src:
        issues.append("缺少 _batch_tasks 集合变量")
    if "_spawn_batch_task" not in src:
        issues.append("缺少 _spawn_batch_task 方法")
    if "self._batch_tasks.add(task)" not in src:
        issues.append("未将批处理任务加入集合")
    if "self._batch_tasks.discard(t)" not in src:
        issues.append("done_callback 未清理集合")
    # 不再直接 asyncio.create_task(self._process_batch())
    if "asyncio.create_task(self._process_batch())" in src:
        issues.append("仍存在未包装的 asyncio.create_task(self._process_batch())")
    return issues


def test_2_log_sanitizer():
    """log_sanitizer.py: 错误上报 tracker"""
    src = _read("core/utils/log_sanitizer.py")
    issues = []
    if "_pending_report_tasks: set = set()" not in src:
        issues.append("缺少 _pending_report_tasks 集合")
    if "_spawn_error_report" not in src:
        issues.append("缺少 _spawn_error_report 函数")
    # 旧的未引用 create_task 应被替换
    if "asyncio.create_task(ErrorReporter.report_error(e, context=context))" in src:
        issues.append("仍存在未引用的 create_task 调用")
    return issues


def test_3_logger():
    """logger.py: 复用 log_sanitizer 的 tracker"""
    src = _read("core/utils/logger.py")
    issues = []
    if "_spawn_error_report" not in src:
        issues.append("未引入 _spawn_error_report")
    # 旧的 return asyncio.create_task 应被替换
    if "return asyncio.create_task(\n                    ErrorReporter.report_error" in src:
        issues.append("仍存在 return asyncio.create_task 写法")
    return issues


def test_4_python_llm_handler():
    """python_llm_handler.py: 推理监控 tracker"""
    src = _read("core/services/scheduler/inference/python_llm_handler.py")
    issues = []
    if "_monitor_tasks: set = set()" not in src:
        issues.append("缺少 _monitor_tasks 集合")
    if "_spawn_monitor_task" not in src:
        issues.append("缺少 _spawn_monitor_task 函数")
    # 旧的未引用 create_task 应被替换
    if "asyncio.create_task(monitor_inference(future, inference_start_time))" in src:
        issues.append("仍存在未引用的 create_task 调用")
    return issues


def test_5_lifespan():
    """lifespan.py: 后台任务 tracker"""
    src = _read("core/lifecycle/lifespan.py")
    issues = []
    if "_pending_bg_tasks: set = set()" not in src:
        issues.append("缺少 _pending_bg_tasks 集合")
    if "_spawn_bg_task" not in src:
        issues.append("缺少 _spawn_bg_task 函数")
    # 旧的未引用 create_task 应被替换
    for old_pattern in [
        "asyncio.create_task(backfill_last_month_if_missing())",
        'asyncio.create_task(event_bus.publish("app.startup_completed"))',
        "asyncio.create_task(_do_shutdown())",
    ]:
        if old_pattern in src:
            issues.append(f"仍存在未引用的: {old_pattern}")
    return issues


def test_6_service_singletons():
    """service_singletons.py: 后台初始化 tracker"""
    src = _read("core/core_engine/service_singletons.py")
    issues = []
    if "_pending_bg_init_tasks: set = set()" not in src:
        issues.append("缺少 _pending_bg_init_tasks 集合")
    if "_spawn_bg_init_task" not in src:
        issues.append("缺少 _spawn_bg_init_task 函数")
    if "asyncio.create_task(_bg_init())" in src:
        issues.append("仍存在未引用的 asyncio.create_task(_bg_init())")
    return issues


def test_7_cloud_router():
    """cloud_router.py: 客户端初始化 tracker"""
    src = _read("core/llm/cloud_router.py")
    issues = []
    if "_pending_init_tasks: set = set()" not in src:
        issues.append("缺少 _pending_init_tasks 集合")
    # 旧的未引用 create_task 应被替换（区分赋值给 task 的形式）
    # 匹配不在 "task = " 之后的 asyncio.create_task(client.initialize())
    unassigned = re.findall(
        r"(?<!task = )asyncio\.create_task\(client\.initialize\(\)\)",
        src,
    )
    if unassigned:
        issues.append(f"仍存在未引用的 create_task(client.initialize()): {len(unassigned)} 处")
    return issues


def test_8_connection_management():
    """connection_management.py: 离线消息推送 tracker"""
    src = _read("core/interfaces/websocket/connection_management.py")
    issues = []
    if "_pending_offline_flush_tasks: set = set()" not in src:
        issues.append("缺少 _pending_offline_flush_tasks 集合")
    if "_spawn_offline_flush_task" not in src:
        issues.append("缺少 _spawn_offline_flush_task 方法")
    if "asyncio.create_task(self._flush_offline_messages(user_id, websocket))" in src:
        issues.append("仍存在未引用的 create_task 调用")
    return issues


def test_9_goodnight_proactive():
    """goodnight_proactive.py: 已弃用 loop= 参数已替换"""
    src = _read("core/services/active_care/goodnight_proactive.py")
    issues = []
    if "_pending_goodnight_tasks: set = set()" not in src:
        issues.append("缺少 _pending_goodnight_tasks 集合")
    if "_spawn_goodnight_task" not in src:
        issues.append("缺少 _spawn_goodnight_task 函数")
    # 已弃用的 ensure_future(..., loop=loop) 写法应被替换
    if "asyncio.ensure_future(\n        trigger_character_goodnight" in src:
        issues.append("仍存在 ensure_future(..., loop=loop) 写法")
    if "loop=loop," in src:
        issues.append("仍存在 loop=loop 参数")
    return issues


def test_10_good_morning_proactive():
    """good_morning_proactive.py: 已弃用 loop= 参数已替换"""
    src = _read("core/services/active_care/good_morning_proactive.py")
    issues = []
    if "_pending_good_morning_tasks: set = set()" not in src:
        issues.append("缺少 _pending_good_morning_tasks 集合")
    if "_spawn_good_morning_task" not in src:
        issues.append("缺少 _spawn_good_morning_task 函数")
    if "asyncio.ensure_future(\n        trigger_character_good_morning" in src:
        issues.append("仍存在 ensure_future(..., loop=loop) 写法")
    if "loop=loop," in src:
        issues.append("仍存在 loop=loop 参数")
    return issues


def test_11_peer_chat_scheduler():
    """peer_chat_scheduler.py: 持久化任务 tracker"""
    src = _read("core/services/active_care/peer_chat/peer_chat_scheduler.py")
    issues = []
    if "_pending_persist_tasks: set = set()" not in src:
        issues.append("缺少 _pending_persist_tasks 集合")
    # 旧的未引用 ensure_future 应被替换（区分赋值给 task 的形式）
    # 匹配不在 "task = " 之后的 asyncio.ensure_future(self._persist_user_activity())
    unassigned = re.findall(
        r"(?<!task = )asyncio\.ensure_future\(self\._persist_user_activity\(\)\)",
        src,
    )
    if unassigned:
        issues.append(f"仍存在未引用的 ensure_future(self._persist_user_activity()): {len(unassigned)} 处")
    return issues


def test_12_active_care_service():
    """active_care/core/service.py: ProactiveChecker 延迟初始化 tracker"""
    src = _read("core/services/active_care/core/service.py")
    issues = []
    if "_pending_init_tasks: set = set()" not in src:
        issues.append("缺少 _pending_init_tasks 集合")
    # 旧的未引用 ensure_future 应被替换
    if "asyncio.ensure_future(_active_care_service.checker.initialize())" in src:
        # 排除被赋值的情况
        if "_task = asyncio.ensure_future(_active_care_service.checker.initialize())" not in src:
            issues.append("仍存在未引用的 ensure_future 调用")
    return issues


def test_13_meal_chat():
    """meal_chat.py: 边吃边聊触发 tracker"""
    src = _read("core/services/life_simulation/meal_chat.py")
    issues = []
    # 旧的未引用 ensure_future 应被替换
    if "asyncio.ensure_future(scheduler.run_single_check())" in src:
        # 排除被赋值的情况
        if "task = asyncio.ensure_future(scheduler.run_single_check())" not in src:
            issues.append("仍存在未引用的 ensure_future 调用")
    return issues


# ============================================================
# 场景 2：模块导入测试
# ============================================================

def test_14_module_imports():
    """所有修改后的模块可以正常导入"""
    issues = []
    modules_to_test = [
        "core.voice.engines.qwen3_tts_engine",
        "core.utils.log_sanitizer",
        "core.utils.logger",
        "core.services.scheduler.inference.python_llm_handler",
        "core.lifecycle.lifespan",
        "core.core_engine.service_singletons",
        "core.llm.cloud_router",
        "core.interfaces.websocket.connection_management",
        "core.services.active_care.goodnight_proactive",
        "core.services.active_care.good_morning_proactive",
        "core.services.active_care.peer_chat.peer_chat_scheduler",
        "core.services.active_care.core.service",
        "core.services.life_simulation.meal_chat",
    ]
    for mod in modules_to_test:
        try:
            __import__(mod)
        except Exception as e:
            issues.append(f"{mod}: {e!r}")
    return issues


# ============================================================
# 场景 3：运行时验证 - tracker 行为正确
# ============================================================

async def _test_tracker_runtime():
    """验证 tracker 模式：保存引用、自动清理、异常被记录"""
    issues = []

    # 模拟一个 tracker
    pending: set = set()
    errors_logged: list = []

    def spawn(coro):
        task = asyncio.create_task(coro)
        pending.add(task)

        def on_done(t):
            pending.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                errors_logged.append(exc)

        task.add_done_callback(on_done)

    # 1. 正常完成的任务应被自动清理
    async def normal():
        await asyncio.sleep(0.05)
        return 42

    spawn(normal())
    await asyncio.sleep(0.15)
    if pending:
        issues.append(f"正常完成的任务未被清理: {len(pending)} 个残留")
    if errors_logged:
        issues.append(f"正常完成的任务不应记录异常: {errors_logged}")

    # 2. 抛异常的任务应被记录
    async def boom():
        await asyncio.sleep(0.05)
        raise ValueError("test error")

    spawn(boom())
    await asyncio.sleep(0.15)
    if pending:
        issues.append(f"异常任务未被清理: {len(pending)} 个残留")
    if not errors_logged:
        issues.append("异常任务的异常未被记录")

    return issues


def test_15_runtime():
    """运行时验证 tracker 行为"""
    return asyncio.run(_test_tracker_runtime())


# ============================================================
# 场景 4：ruff 检查（关键文件）
# ============================================================

def test_16_ruff():
    """ruff 检查修改后的关键文件（仅 F401 未使用导入，因本次修改涉及导入调整）"""
    import subprocess
    files = [
        "core/voice/engines/qwen3_tts_engine.py",
        "core/utils/log_sanitizer.py",
        "core/utils/logger.py",
        "core/services/scheduler/inference/python_llm_handler.py",
        "core/lifecycle/lifespan.py",
        "core/core_engine/service_singletons.py",
        "core/llm/cloud_router.py",
        "core/interfaces/websocket/connection_management.py",
        "core/services/active_care/goodnight_proactive.py",
        "core/services/active_care/good_morning_proactive.py",
        "core/services/active_care/peer_chat/peer_chat_scheduler.py",
        "core/services/active_care/core/service.py",
        "core/services/life_simulation/meal_chat.py",
    ]
    issues = []
    for f in files:
        r = subprocess.run(
            [str(Path(PROJECT_ROOT / "venv_core/Scripts/python.exe")),
             "-m", "ruff", "check", "--select=F401", str(PROJECT_ROOT / f)],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        if r.returncode != 0:
            issues.append(f"{f}: {r.stdout.strip()[:200]}")
    return issues


# ============================================================
# 主入口
# ============================================================

def main():
    print("=" * 72)
    print("P1-2 验证：修复 fire-and-forget 任务引用管理")
    print("=" * 72)

    tests = [
        ("[1/16] qwen3_tts_engine.py 任务集合", test_1_qwen3_tts),
        ("[2/16] log_sanitizer.py 错误上报 tracker", test_2_log_sanitizer),
        ("[3/16] logger.py 复用 tracker", test_3_logger),
        ("[4/16] python_llm_handler.py 监控 tracker", test_4_python_llm_handler),
        ("[5/16] lifespan.py 后台任务 tracker", test_5_lifespan),
        ("[6/16] service_singletons.py 初始化 tracker", test_6_service_singletons),
        ("[7/16] cloud_router.py 客户端 tracker", test_7_cloud_router),
        ("[8/16] connection_management.py 离线消息 tracker", test_8_connection_management),
        ("[9/16] goodnight_proactive.py 弃用 loop= 替换", test_9_goodnight_proactive),
        ("[10/16] good_morning_proactive.py 弃用 loop= 替换", test_10_good_morning_proactive),
        ("[11/16] peer_chat_scheduler.py 持久化 tracker", test_11_peer_chat_scheduler),
        ("[12/16] active_care/core/service.py 初始化 tracker", test_12_active_care_service),
        ("[13/16] meal_chat.py 边吃边聊 tracker", test_13_meal_chat),
        ("[14/16] 模块导入测试", test_14_module_imports),
        ("[15/16] 运行时 tracker 行为", test_15_runtime),
        ("[16/16] ruff F 检查", test_16_ruff),
    ]

    total_issues = 0
    for name, fn in tests:
        try:
            issues = fn()
        except Exception as e:
            issues = [f"测试本身异常: {e!r}"]
        if not issues:
            print(f"  {name}: ✅ 通过")
        else:
            print(f"  {name}: ❌ 失败 ({len(issues)} 个问题)")
            for iss in issues:
                print(f"    - {iss}")
            total_issues += len(issues)

    print()
    if total_issues == 0:
        print("✅ 所有验证通过！P1-2 修复有效。")
        return 0
    else:
        print(f"❌ 共 {total_issues} 个问题未通过。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
