#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
夜间异步任务超时与错误日志修复验证脚本

验证 memory/nightly/task_runner.py 的修复：
1. NIGHTLY_TASK_TIMEOUT_SECONDS 应为 1800（此前 600s 会在人物档案提取慢时误杀后续步骤）
2. 应显式 import concurrent.futures 并单独捕获 concurrent.futures.TimeoutError
   （Python 3.10 下 concurrent.futures.TimeoutError 与内置 TimeoutError 不是同一个类，
   若不显式捕获会落入通用 except Exception 分支，难以与真实业务异常区分）
3. 两个 except 分支的 logger.error 都必须带 exc_info=True
   （否则 error_collector._schedule_report 会合成 RuntimeError(record.getMessage()) 上报，
   导致 error_code 误报为 RuntimeError、traceback 为空，无法定位真实异常）
4. 错误消息必须包含 exc_type 与 user_id，便于排查
5. 运行时验证：超时后函数返回 {}，且日志 record 携带真实 exc_info（不被合成 RuntimeError）
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import re
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Tuple

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

TARGET_FILE = PROJECT_ROOT / "memory" / "nightly" / "task_runner.py"


def read_target_file() -> str:
    """读取目标文件内容"""
    if not TARGET_FILE.exists():
        print(f"❌ 文件不存在: {TARGET_FILE}")
        sys.exit(1)
    return TARGET_FILE.read_text(encoding="utf-8")


def check_timeout_constant(content: str) -> bool:
    """检查 1：NIGHTLY_TASK_TIMEOUT_SECONDS 应为 1800"""
    match = re.search(
        r"NIGHTLY_TASK_TIMEOUT_SECONDS\s*[:=]\s*(?:int\s*=\s*)?(\d+)", content
    )
    if not match:
        print("❌ 未找到 NIGHTLY_TASK_TIMEOUT_SECONDS 常量定义")
        return False
    value = int(match.group(1))
    if value != 1800:
        print(f"❌ NIGHTLY_TASK_TIMEOUT_SECONDS={value}，预期 1800")
        return False
    print(f"✅ 检查 1 通过：NIGHTLY_TASK_TIMEOUT_SECONDS={value}")
    return True


def check_concurrent_futures_import(content: str) -> bool:
    """检查 2：应显式 import concurrent.futures"""
    if not re.search(r"^\s*import\s+concurrent\.futures\s*$", content, re.MULTILINE):
        print("❌ 未找到 `import concurrent.futures`")
        return False
    print("✅ 检查 2 通过：已显式 import concurrent.futures")
    return True


def _extract_run_nightly_async_tasks_body(content: str) -> str:
    """提取 run_nightly_async_tasks 函数体（到下一个同级 def/class 为止）"""
    func_match = re.search(
        r"def\s+run_nightly_async_tasks\s*\(.*?\).*?(?=\n    async\s+def\s|\n    @|\Z)",
        content,
        re.DOTALL,
    )
    return func_match.group(0) if func_match else ""


def check_timeout_except_clause(content: str) -> bool:
    """检查 3：应单独捕获 concurrent.futures.TimeoutError，且位于通用 except 之前

    注意 run_nightly_async_tasks 内部还有一个 `except Exception as exc:` 是给
    `get_main_loop()` 用的内层 except，必须用 rfind 找最外层的通用 except 来比较顺序。
    """
    pattern = r"except\s+concurrent\.futures\.TimeoutError\s+as\s+exc\s*:"
    if not re.search(pattern, content):
        print("❌ 未找到 `except concurrent.futures.TimeoutError as exc:` 分支")
        return False
    # 只在 run_nightly_async_tasks 函数体内比较顺序，避免被 execute_async_tasks 干扰
    func_body = _extract_run_nightly_async_tasks_body(content)
    if not func_body:
        print("❌ 未找到 run_nightly_async_tasks 函数")
        return False
    timeout_pos = func_body.find("except concurrent.futures.TimeoutError")
    # 用 rfind 找最后一个 `except Exception as exc:`，跳过内层 get_main_loop 的 except
    exception_pos = func_body.rfind("except Exception as exc:")
    if timeout_pos < 0 or exception_pos < 0:
        print("❌ run_nightly_async_tasks 内找不到完整的 except 分支")
        return False
    if timeout_pos >= exception_pos:
        print("❌ TimeoutError 分支应在通用 Exception 分支之前")
        return False
    print("✅ 检查 3 通过：已单独捕获 concurrent.futures.TimeoutError 且顺序正确")
    return True


def _split_logger_error_calls(func_body: str) -> List[str]:
    """提取 func_body 中所有 logger.error(...) 调用，正确处理嵌套括号"""
    calls: List[str] = []
    search_pos = 0
    while True:
        start = func_body.find("logger.error(", search_pos)
        if start < 0:
            break
        # 从 logger.error( 后开始匹配括号
        depth = 1
        i = start + len("logger.error(")
        while i < len(func_body) and depth > 0:
            ch = func_body[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        if depth == 0:
            calls.append(func_body[start:i])
        search_pos = i if i > start else start + 1
    return calls


def check_exc_info_true(content: str) -> bool:
    """检查 4：两个 logger.error 都必须带 exc_info=True"""
    func_body = _extract_run_nightly_async_tasks_body(content)
    if not func_body:
        print("❌ 未找到 run_nightly_async_tasks 函数")
        return False
    error_calls = _split_logger_error_calls(func_body)
    if len(error_calls) < 2:
        print(f"❌ run_nightly_async_tasks 内 logger.error 调用数 {len(error_calls)}，预期 ≥2")
        return False
    missing = []
    for i, call in enumerate(error_calls, start=1):
        if "exc_info=True" not in call:
            missing.append(i)
    if missing:
        print(f"❌ 第 {missing} 个 logger.error 调用未带 exc_info=True")
        return False
    print(f"✅ 检查 4 通过：{len(error_calls)} 个 logger.error 均带 exc_info=True")
    return True


def check_error_message_fields(content: str) -> bool:
    """检查 5：错误消息应包含 exc_type 与 user_id"""
    func_body = _extract_run_nightly_async_tasks_body(content)
    if not func_body:
        print("❌ 未找到 run_nightly_async_tasks 函数")
        return False
    has_exc_type = "exc_type=" in func_body and "type(exc).__name__" in func_body
    has_user_id = "user_id=" in func_body
    if not has_exc_type:
        print("❌ 错误消息未包含 exc_type=type(exc).__name__")
        return False
    if not has_user_id:
        print("❌ 错误消息未包含 user_id=")
        return False
    print("✅ 检查 5 通过：错误消息包含 exc_type 与 user_id 字段")
    return True


def check_runtime_timeout_handling() -> bool:
    """检查 6：运行时验证超时处理。

    构造一个慢协程（sleep 2s），把 NIGHTLY_TASK_TIMEOUT_SECONDS 临时改成 0.5s，
    在独立线程里跑事件循环，验证：
    - 函数返回可被编排器识别的 _nightly_error，避免误标完成
    - 超时协程被取消，不会与下一轮断点补跑并发
    - 日志 record 携带真实 exc_info（exc_info[1] 是 concurrent.futures.TimeoutError 实例），
      不会被 error_collector 合成 RuntimeError 上报
    """
    from memory.nightly.task_runner import NightlyTaskRunner

    runner = NightlyTaskRunner(config={})
    # 临时调小超时
    original_timeout = NightlyTaskRunner.NIGHTLY_TASK_TIMEOUT_SECONDS
    NightlyTaskRunner.NIGHTLY_TASK_TIMEOUT_SECONDS = 0.5

    # 抓取 logger.error 的 record
    captured_records: List[logging.LogRecord] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured_records.append(record)

    handler = _CaptureHandler(level=logging.ERROR)
    logger_obj = logging.getLogger("memory.nightly.task_runner")
    logger_obj.addHandler(handler)

    # 在独立线程跑事件循环
    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()

    cancellation_observed = threading.Event()

    async def slow_coro(_user_id: str, _manager: Any) -> Dict[str, Any]:
        try:
            await asyncio.sleep(2.0)
            return {"should_not_reach": True}
        except asyncio.CancelledError:
            cancellation_observed.set()
            raise

    # Monkey-patch get_main_loop 返回我们的 loop
    import core.lifecycle.lifespan as lifespan_mod

    original_get_main_loop = lifespan_mod.get_main_loop
    lifespan_mod.get_main_loop = lambda: loop

    try:
        result = runner.run_nightly_async_tasks(
            "test_user", manager=None, execute_async_tasks=slow_coro
        )
        cancellation_observed.wait(timeout=1.0)
    finally:
        # 恢复
        lifespan_mod.get_main_loop = original_get_main_loop
        NightlyTaskRunner.NIGHTLY_TASK_TIMEOUT_SECONDS = original_timeout
        logger_obj.removeHandler(handler)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=2.0)

    if not str(result.get("_nightly_error", "")).startswith("timeout:"):
        print(f"❌ 超时后返回值 {result}，预期 _nightly_error 超时标记")
        return False

    if not cancellation_observed.is_set():
        print("❌ 超时后底层协程未被取消，可能与断点补跑重叠")
        return False

    if not captured_records:
        print("❌ 未捕获到 logger.error 调用")
        return False

    record = captured_records[0]
    if not record.exc_info or record.exc_info[1] is None:
        print("❌ record.exc_info 为空，error_collector 会合成 RuntimeError 上报")
        return False

    exc = record.exc_info[1]
    if not isinstance(exc, concurrent.futures.TimeoutError):
        print(f"❌ exc_info[1] 类型 {type(exc).__name__}，预期 TimeoutError")
        return False

    msg = record.getMessage()
    if "exc_type=" not in msg or "TimeoutError" not in msg:
        print(f"❌ 错误消息未包含 exc_type，msg={msg!r}")
        return False
    if "user_id=test_user" not in msg:
        print(f"❌ 错误消息未包含 user_id=test_user，msg={msg!r}")
        return False

    print(
        f"✅ 检查 6 通过：超时协程已取消并返回 _nightly_error，"
        f"record.exc_info 携带真实 {type(exc).__name__}"
    )
    print(f"    错误消息样例: {msg}")
    return True


def main() -> int:
    print("=" * 72)
    print("夜间异步任务超时与错误日志修复验证")
    print("=" * 72)

    content = read_target_file()

    checks: List[Tuple[str, bool]] = []
    checks.append(("timeout 常量为 1800", check_timeout_constant(content)))
    checks.append(("显式 import concurrent.futures", check_concurrent_futures_import(content)))
    checks.append(("单独捕获 TimeoutError 且顺序正确", check_timeout_except_clause(content)))
    checks.append(("logger.error 均带 exc_info=True", check_exc_info_true(content)))
    checks.append(("错误消息含 exc_type 与 user_id", check_error_message_fields(content)))
    checks.append(("运行时超时返回失败标记且携带真实 exc_info", check_runtime_timeout_handling()))

    print("-" * 72)
    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    for name, ok in checks:
        marker = "✅" if ok else "❌"
        print(f"{marker} {name}")

    print("-" * 72)
    if passed == total:
        print(f"🎉 全部 {total} 项检查通过")
        return 0
    print(f"⚠️ {passed}/{total} 项检查通过，{total - passed} 项失败")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
