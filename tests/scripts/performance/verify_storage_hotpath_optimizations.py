"""验证 P0-P2 存储/检索热路径优化。

运行：
    venv_core\Scripts\python.exe tests/scripts/performance/verify_storage_hotpath_optimizations.py

脚本复用标准 pytest 回归，避免 tests/scripts 与 tests/unit 维护两份断言。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEST_FILE = PROJECT_ROOT / "tests" / "unit" / "test_storage_hotpath_optimizations.py"


def main() -> int:
    command = [sys.executable, "-m", "pytest", "-q", str(TEST_FILE)]
    completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
