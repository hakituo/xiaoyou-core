"""验证晚安信号不会清空随后生成的计划，且 skipped 不显示为完成。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    test_file = PROJECT_ROOT / "tests" / "journal_plan" / "test_sleep_plan_settlement.py"
    pytest_temp_parent = PROJECT_ROOT / ".tmp"
    pytest_temp_parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(test_file),
            "-q",
            "--basetemp",
            str(pytest_temp_parent / "pytest-sleep-plan"),
        ],
        cwd=PROJECT_ROOT,
        check=False,
    )
    if result.returncode != 0:
        return result.returncode

    codec = (
        PROJECT_ROOT
        / "clients"
        / "frontend"
        / "aveline-android"
        / "android"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "aveline"
        / "ai"
        / "mobile"
        / "domain"
        / "PlanMarkdownCodec.kt"
    ).read_text(encoding="utf-8")
    if 'endsWith("⏭️")' not in codec or "isDone = false" not in codec:
        print("[FAIL] Android codec 未兼容历史 skipped 格式")
        return 1
    print("[OK] 晚安计划结算与 Android skipped 语义验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
