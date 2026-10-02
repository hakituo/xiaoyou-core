"""验证 Git diff 美化与提交前敏感扫描配置。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def run_git_config(*args: str) -> str:
    result = subprocess.run(
        ["git", "config", "--local", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def record(name: str, passed: bool, detail: str) -> bool:
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}: {detail}")
    return passed


def verify_hook_files() -> bool:
    hook_path = ROOT / ".githooks" / "pre-commit"
    script_path = ROOT / "scripts" / "git" / "run_pre_commit_scan.py"
    passed = hook_path.is_file() and script_path.is_file()
    detail = "钩子与扫描脚本都存在" if passed else "缺少钩子文件或扫描脚本"
    return record("钩子文件", passed, detail)


def verify_git_config() -> bool:
    checks = [
        ("core.pager", "delta"),
        ("interactive.diffFilter", "delta --color-only"),
        ("core.hooksPath", ".githooks"),
    ]
    failed: list[str] = []
    for key, expected in checks:
        value = run_git_config("--get", key)
        if value != expected:
            failed.append(f"{key}={value or '<empty>'}")
    detail = "配置符合预期" if not failed else "；".join(failed)
    return record("Git 配置", not failed, detail)


def verify_scan_script() -> bool:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "git" / "run_pre_commit_scan.py"), "--check-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    passed = result.returncode == 0
    detail = result.stdout.strip() or result.stderr.strip() or "无输出"
    return record("扫描脚本", passed, detail)


def main() -> int:
    checks = [
        verify_hook_files(),
        verify_git_config(),
        verify_scan_script(),
    ]
    passed = sum(checks)
    total = len(checks)
    print(f"=== 结果: {passed}/{total} 项通过 ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
