"""验证 Telegram 主程序托管与消息可靠性修复。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
VENV_PYTHON = PROJECT_ROOT / "venv_core" / "Scripts" / "python.exe"
VENV_RUFF = PROJECT_ROOT / "venv_core" / "Scripts" / "ruff.exe"


def _run(name: str, command: list[str]) -> bool:
    print(f"\n=== {name} ===")
    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if result.returncode == 0:
        print(f"[OK] {name}")
        return True
    print(f"[FAIL] {name}，退出码 {result.returncode}")
    return False


def main() -> int:
    checks = [
        _run(
            "Telegram 离线专项测试",
            [
                str(VENV_PYTHON),
                "-m",
                "pytest",
                "tests/diagnostics/test_telegram_adapter.py",
                "-q",
            ],
        ),
        _run(
            "Telegram 关键文件 Ruff",
            [
                str(VENV_RUFF),
                "check",
                "config/integrated_config.py",
                "config/settings_adapters.py",
                "clients/bots/telegram/settings.py",
                "clients/bots/telegram/adapter.py",
                "clients/bots/telegram/session.py",
                "core/lifecycle/lifespan.py",
                "tests/diagnostics/test_telegram_adapter.py",
                "tests/scripts/telegram/verify_telegram_adapter_reliability.py",
            ],
        ),
    ]
    passed = sum(checks)
    print(f"\nTelegram 可靠性验证：{passed}/{len(checks)} 项通过")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
