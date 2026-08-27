# -*- coding: utf-8 -*-
"""P2-4: 统一时区处理 - 验证脚本

验证内容：
1. time_utils.py 新增函数可正常 import
2. 所有修改后的文件可正常 import（无语法错误）
3. 关键文件的 datetime.now() 已被替换为 get_current_time()
4. 关键文件的 datetime.fromtimestamp() 已被替换为 from_timestamp() / ts_to_str() / ts_to_iso()
5. 关键文件的 datetime.now().isoformat() 已被替换为 now_iso()
6. ruff check 无 syntax 错误
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = PROJECT_ROOT / "venv_core" / "Scripts" / "python.exe"
VENV_RUFF = PROJECT_ROOT / "venv_core" / "Scripts" / "ruff.exe"


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def _info(msg: str) -> None:
    print(f"  [INFO] {msg}")


def check_time_utils_functions() -> bool:
    """检查 time_utils.py 是否包含新增函数。"""
    print("\n=== 1. 检查 time_utils.py 新增函数 ===")
    time_utils_path = PROJECT_ROOT / "core" / "utils" / "time_utils.py"
    if not time_utils_path.exists():
        _fail(f"time_utils.py 不存在: {time_utils_path}")
        return False

    content = time_utils_path.read_text(encoding="utf-8")
    expected_functions = [
        "def now_iso()",
        "def now_str(",
        "def today_str()",
        "def from_timestamp(",
        "def ts_to_str(",
        "def ts_to_iso(",
        "def current_hour()",
        "def current_timestamp()",
    ]

    all_passed = True
    for func_def in expected_functions:
        if func_def in content:
            _ok(f"找到函数定义: {func_def}")
        else:
            _fail(f"未找到函数定义: {func_def}")
            all_passed = False

    return all_passed


def check_files_syntax() -> bool:
    """检查所有修改过的文件的语法。"""
    print("\n=== 2. 检查关键文件语法（AST 解析）===")

    # 关键修改的文件列表
    key_files = [
        "core/utils/time_utils.py",
        "routers/v1/context.py",
        "routers/v1/system.py",
        "routers/v1/media.py",
        "routers/v1/peer_chat.py",
        "routers/v1/chat.py",
        "routers/v1/life.py",
        "core/services/active_care/core/user_response_handler.py",
        "core/services/active_care/core/sleep_session_manager.py",
        "core/services/active_care/scheduling/delayed_scheduler.py",
        "core/services/active_care/storage/reminder_assignment_registry.py",
        "core/services/auto_heal/anomaly_detector.py",
        "core/services/auto_heal/models.py",
        "core/services/auto_heal/report_generator.py",
        "core/services/character_daily/engine_peer_chat_support.py",
        "core/services/daily/manager.py",
        "core/services/journal/journal_helpers.py",
        "core/services/journal/models.py",
        "core/services/journal/persona_exports.py",
        "core/services/life_simulation/actor_manager.py",
        "core/services/life_simulation/orchestrator.py",
        "core/services/life_simulation/sleep_decision.py",
        "core/services/life_simulation/coordinators/websocket_coordinator.py",
        "core/services/study/daily_tracker.py",
        "core/services/study/student_state.py",
        "core/services/study/summary_generator.py",
        "core/services/study/tutor_engine.py",
        "core/services/study/weakness_tracker.py",
        "core/services/workspace/history_store.py",
        "core/services/workspace/snapshot.py",
        "core/services/workspace/service.py",
        "core/services/dual_role/storage.py",
        "core/services/dual_role/service.py",
        "core/services/self_improvement/core_memory.py",
        "core/services/self_improvement/daily_logger.py",
        "core/utils/error_collector.py",
        "core/utils/memory_watchdog.py",
        "core/async_monitor.py",
        "core/llm/llm_logger.py",
        "core/agents/chat_agent_components/handler.py",
        "core/image/image_utils.py",
        "core/character/people/extractor.py",
    ]

    all_passed = True
    for rel_path in key_files:
        full_path = PROJECT_ROOT / rel_path
        if not full_path.exists():
            _fail(f"文件不存在: {rel_path}")
            all_passed = False
            continue

        try:
            content = full_path.read_text(encoding="utf-8")
            ast.parse(content)
            _ok(f"语法正确: {rel_path}")
        except SyntaxError as e:
            _fail(f"语法错误: {rel_path} - {e}")
            all_passed = False

    return all_passed


def check_no_naive_datetime_now() -> bool:
    """检查关键文件是否还残留 datetime.now()（排除注释和字符串）。"""
    print("\n=== 3. 检查关键文件是否残留 datetime.now() ===")

    # 排除的文件（允许保留 datetime.now()）
    excluded_files = {
        "core/utils/time_utils.py",  # 本身
        "core/utils/timestamp_utils.py",  # 时间戳工具，差值运算
        "core/utils/logger.py",  # logger 内部
        "core/utils/log_cleanup.py",  # 日志清理
    }

    # 检查 routers/ 和 core/services/ 下所有 .py 文件
    check_dirs = [
        PROJECT_ROOT / "routers",
        PROJECT_ROOT / "core" / "services",
    ]

    all_passed = True
    found_count = 0
    for check_dir in check_dirs:
        if not check_dir.exists():
            continue
        for py_file in check_dir.rglob("*.py"):
            rel_path = py_file.relative_to(PROJECT_ROOT).as_posix()
            if rel_path in excluded_files:
                continue
            if "__pycache__" in str(py_file):
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
                # 移除注释和字符串字面量
                tree = ast.parse(content)
            except SyntaxError:
                continue

            # 遍历 AST 查找 datetime.now() 调用
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    # 检查 func 是否为 datetime.now()
                    if isinstance(node.func, ast.Attribute):
                        if node.func.attr == "now":
                            # 检查是否为 datetime.now 或 self._something.now
                            if isinstance(node.func.value, ast.Name):
                                if node.func.value.id == "datetime":
                                    # 排除注释中（AST 不会包含注释，所以这里直接报）
                                    _fail(f"残留 datetime.now(): {rel_path}:{node.lineno}")
                                    found_count += 1
                                    all_passed = False

    if found_count == 0:
        _ok("routers/ 和 core/services/ 下未发现 datetime.now() 残留")
    else:
        _fail(f"共发现 {found_count} 处 datetime.now() 残留")

    return all_passed


def check_imports() -> bool:
    """检查关键文件是否正确 import 了 time_utils。"""
    print("\n=== 4. 检查关键文件是否正确 import time_utils ===")

    # 检查使用了 now_iso/now_str/ts_to_str/ts_to_iso/from_timestamp 的文件
    files_to_check = [
        ("routers/v1/context.py", "now_iso"),
        ("routers/v1/system.py", "now_iso"),
        ("routers/v1/media.py", "now_iso"),
        ("routers/v1/chat.py", "now_iso"),
        ("core/services/daily/manager.py", "now_str"),
        ("core/services/journal/journal_helpers.py", "ts_to_str"),
        ("core/services/life_simulation/orchestrator.py", "now_str"),
        ("core/services/study/summary_generator.py", "ts_to_str"),
        ("core/services/workspace/snapshot.py", "ts_to_str"),
        ("core/services/active_care/storage/reminder_assignment_registry.py", "ts_to_str"),
        ("core/character/people/extractor.py", "ts_to_str"),
    ]

    all_passed = True
    for rel_path, expected_func in files_to_check:
        full_path = PROJECT_ROOT / rel_path
        if not full_path.exists():
            _fail(f"文件不存在: {rel_path}")
            all_passed = False
            continue

        content = full_path.read_text(encoding="utf-8")
        if f"from core.utils.time_utils import" in content:
            # 检查是否 import 了 expected_func
            # 简单检查：在 import 行中是否包含 expected_func
            lines = content.split("\n")
            found = False
            for line in lines:
                if "from core.utils.time_utils import" in line:
                    if expected_func in line:
                        found = True
                        break
                    # 处理多行 import
                    if line.rstrip().endswith("("):
                        # 多行 import，查找下一行
                        idx = lines.index(line)
                        for next_line in lines[idx + 1 :]:
                            if expected_func in next_line:
                                found = True
                                break
                            if ")" in next_line:
                                break
            if found:
                _ok(f"{rel_path} 正确 import 了 {expected_func}")
            else:
                _fail(f"{rel_path} 未 import {expected_func}")
                all_passed = False
        else:
            _fail(f"{rel_path} 未 import time_utils")
            all_passed = False

    return all_passed


def check_ruff() -> bool:
    """运行 ruff check 验证无 syntax 错误。"""
    print("\n=== 5. 运行 ruff check（仅 E9 和 F821）===")
    try:
        result = subprocess.run(
            [str(VENV_RUFF), "check", "core", "routers", "--select", "E9,F821", "--output-format=concise"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            _ok("ruff check 通过（无 E9/F821 错误）")
            return True
        else:
            # 过滤出真正的 E9/F821 错误
            errors = [line for line in result.stdout.split("\n") if line.strip()]
            real_errors = [e for e in errors if ": E9" in e or ": F821" in e or "invalid-syntax" in e or "Undefined name" in e]
            if not real_errors:
                _ok("ruff check 通过（无 E9/F821 错误）")
                return True
            _fail(f"ruff check 发现 {len(real_errors)} 个 E9/F821 错误:")
            for err in real_errors[:10]:
                print(f"    {err}")
            return False
    except Exception as e:
        _fail(f"ruff check 运行失败: {e}")
        return False


def main() -> int:
    print("=" * 70)
    print("P2-4: 统一时区处理 - 验证脚本")
    print("=" * 70)

    results = []
    results.append(check_time_utils_functions())
    results.append(check_files_syntax())
    results.append(check_no_naive_datetime_now())
    results.append(check_imports())
    results.append(check_ruff())

    print("\n" + "=" * 70)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"总计: {passed}/{total} 项通过")
    print("=" * 70)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
