"""P0-1 验证脚本：确认聊天入口中已无 exec() 调试代码。

验证内容：
1. 文件中不再出现 `exec(` 调用
2. 文件中不再出现 `urllib.request` 导入
3. 文件中不再出现 `#region debug-point` / `#endregion` 标记
4. 文件可正常解析（无语法错误）
5. 拆分后的 Active Care 处理器仍保留关键模式分流逻辑

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\security_p0\\verify_p0_01_no_exec_debug.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HANDLER_DIR = PROJECT_ROOT / "core" / "interfaces" / "websocket" / "adapters" / "handlers"
SECURITY_TARGET = HANDLER_DIR / "chat_handlers.py"
ACTIVE_CARE_TARGET = HANDLER_DIR / "chat" / "active_care.py"

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


def check_no_forbidden_patterns(content: str) -> list[str]:
    """检查是否包含禁止的模式。"""
    issues = []
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in content:
            issues.append(f"发现禁止的模式: {pattern!r}")
    return issues


def check_syntax_valid(file_path: Path) -> tuple[bool, str]:
    """检查文件是否能被 Python AST 解析。"""
    try:
        ast.parse(file_path.read_text(encoding="utf-8"))
        return True, ""
    except SyntaxError as e:
        return False, f"语法错误: {e}"


def check_logic_preserved(content: str) -> list[str]:
    """检查关键功能逻辑是否还在。"""
    issues = []
    # enter_reduced 分支必须保留
    if 'intent.get("action") == "enter_reduced"' not in content:
        issues.append("缺失 enter_reduced 分支处理逻辑")
    # exit_reduced 分支必须保留
    if 'intent.get("action") == "exit_reduced"' not in content:
        issues.append("缺失 exit_reduced 分支处理逻辑")
    # set_sleep_mode 调用必须保留
    if "set_sleep_mode" not in content:
        issues.append("缺失 set_sleep_mode 调用")
    return issues


def main() -> int:
    targets = (SECURITY_TARGET, ACTIVE_CARE_TARGET)
    missing = [path for path in targets if not path.exists()]
    if missing:
        print(f"[FAIL] 目标文件不存在: {missing}")
        return 2

    active_care_content = ACTIVE_CARE_TARGET.read_text(encoding="utf-8")

    failures: list[str] = []

    # 1. 检查禁止模式
    for path in targets:
        content = path.read_text(encoding="utf-8")
        failures.extend(
            f"[{path.relative_to(PROJECT_ROOT)}] {issue}"
            for issue in check_no_forbidden_patterns(content)
        )

    # 2. 语法检查
    for path in targets:
        ok, err = check_syntax_valid(path)
        if not ok:
            failures.append(f"[{path.relative_to(PROJECT_ROOT)}] {err}")

    # 3. 逻辑保留检查
    failures.extend(check_logic_preserved(active_care_content))

    if failures:
        print("[FAIL] P0-1 验证未通过:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("[OK] P0-1 验证通过:")
    print(f"  - 文件 {SECURITY_TARGET.relative_to(PROJECT_ROOT)} 已无 exec() 调试代码")
    print(f"  - 文件 {ACTIVE_CARE_TARGET.relative_to(PROJECT_ROOT)} 已无 exec() 调试代码")
    print("  - 无 urllib.request 调用")
    print("  - 无 debug-point 标记")
    print("  - 语法检查通过")
    print("  - enter_reduced/exit_reduced 分支逻辑保留")
    return 0


if __name__ == "__main__":
    sys.exit(main())
