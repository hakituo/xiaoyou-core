#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0-02 验证脚本: active_care 模块 exec() 调试代码彻底清除

验证项：
1. active_care 子模块下所有 .py 文件不含禁止模式：
   - exec(
   - urllib.request
   - #region debug-point / #endregion
   - DEBUG_SERVER_URL / DEBUG_SESSION_ID
   - active-care-sleep.env
   - 7777/event
2. 关键功能逻辑保留：
   - service.py: set_sleep_mode / 晚安低打扰进入与退出逻辑
   - proactive_checker.py: set_next_decision_ts 委托
   - checker_event_handler.py: sleep_recovery_guard 调用与 set_next_decision_ts 调用
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ACTIVE_CARE_DIR = ROOT / "core" / "services" / "active_care"

FORBIDDEN_PATTERNS = [
    "exec(",
    "urllib.request",
    "#region debug-point",
    "#endregion",
    "DEBUG_SERVER_URL",
    "DEBUG_SESSION_ID",
    "active-care-sleep.env",
    "7777/event",
]


def check_no_forbidden_patterns(content: str, file_path: Path) -> list[str]:
    """检查文件是否包含禁止模式。"""
    issues = []
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in content:
            issues.append(f"[{file_path}] 发现禁止的模式: {pattern!r}")
    return issues


def check_logic_preserved(content: str, file_path: Path) -> list[str]:
    """检查关键功能逻辑是否保留。"""
    issues = []
    name = file_path.name

    if name == "service.py":
        # set_sleep_mode 必须保留
        if "def set_sleep_mode" not in content and "set_sleep_mode" not in content:
            issues.append(f"[{file_path}] 缺失 set_sleep_mode 方法/调用")
        # 聊天只切换低打扰状态，不能覆盖 Samsung Health 的真实睡眠时间。
        if "enter_low_disturbance_mode" not in content:
            issues.append(f"[{file_path}] 缺失 enter_low_disturbance_mode 调用")
        if "exit_low_disturbance_mode" not in content:
            issues.append(f"[{file_path}] 缺失 exit_low_disturbance_mode 调用")

    elif name == "proactive_checker.py":
        # set_next_decision_ts 委托必须保留
        if "async def set_next_decision_ts" not in content:
            issues.append(f"[{file_path}] 缺失 async def set_next_decision_ts")
        if "self._init_state.set_next_decision_ts" not in content:
            issues.append(f"[{file_path}] 缺失对 _init_state.set_next_decision_ts 的委托调用")

    elif name == "checker_event_handler.py":
        # sleep_recovery_guard 调用必须保留
        if "build_sleep_recovery_guard" not in content:
            issues.append(f"[{file_path}] 缺失 build_sleep_recovery_guard 调用")
        if "set_next_decision_ts" not in content:
            issues.append(f"[{file_path}] 缺失 set_next_decision_ts 调用")
        # 睡眠恢复保护期逻辑必须保留
        if "sleep_recovery_guard" not in content:
            issues.append(f"[{file_path}] 缺失 sleep_recovery_guard 引用")

    return issues


def main() -> int:
    if not ACTIVE_CARE_DIR.exists():
        print(f"[ERROR] active_care 目录不存在: {ACTIVE_CARE_DIR}")
        return 2

    py_files = sorted(ACTIVE_CARE_DIR.rglob("*.py"))
    if not py_files:
        print("[ERROR] active_care 目录下未找到 .py 文件")
        return 2

    all_issues: list[str] = []

    for py_file in py_files:
        try:
            content = py_file.read_text(encoding="utf-8")
        except Exception as exc:
            all_issues.append(f"[{py_file}] 读取失败: {exc}")
            continue

        all_issues.extend(check_no_forbidden_patterns(content, py_file))
        all_issues.extend(check_logic_preserved(content, py_file))

    # 全局再扫一次（确保没有任何文件漏网）
    for py_file in py_files:
        try:
            content = py_file.read_text(encoding="utf-8")
            for pattern in FORBIDDEN_PATTERNS:
                if pattern in content:
                    msg = f"[{py_file}] 全局复查发现禁止模式: {pattern!r}"
                    if msg not in all_issues:
                        all_issues.append(msg)
        except Exception:
            pass

    if all_issues:
        print(f"[FAIL] 共发现 {len(all_issues)} 个问题:")
        for issue in all_issues:
            print(f"  - {issue}")
        return 1

    print(f"[OK] 已扫描 {len(py_files)} 个文件，未发现禁止模式且关键逻辑保留完整")
    print("  - exec() 调试代码已彻底清除")
    print("  - urllib.request 非授权 HTTP 请求已彻底清除")
    print("  - debug-point 标记已彻底清除")
    print("  - set_sleep_mode / set_next_decision_ts / sleep_recovery_guard 关键逻辑保留")
    return 0


if __name__ == "__main__":
    sys.exit(main())
