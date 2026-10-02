from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "core-ci.yml"
SLOW_TEST = ROOT / "tests" / "unit" / "test_sleep_window_fix.py"


def _check(name: str, condition: bool) -> bool:
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    return condition


def main() -> int:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    slow_test = SLOW_TEST.read_text(encoding="utf-8")

    checks = [
        _check("不再由 tests/** 泛触发 Core CI", "- 'tests/**'\n" not in workflow),
        _check("pytest 文件仍会触发", "'tests/**/test_*.py'" in workflow),
        _check("conftest.py 仍会触发", "'tests/conftest.py'" in workflow),
        _check("Core CI 只申请一个 GitHub-hosted runner", workflow.count("runs-on: ubuntu-latest") == 1),
        _check("单个 job 有 10 分钟硬超时", "timeout-minutes: 10" in workflow),
        _check("Ruff 仍在 Core CI", "uv run ruff check" in workflow),
        _check("完整 pytest 命令仍在 Core CI", "uv run pytest \\" in workflow),
        _check(
            "故障回退测试不再真实等待退避",
            'monkeypatch.setattr(atomic_io.time, "sleep"' in slow_test,
        ),
        _check("故障回退仍验证 10 次 replace", "assert len(replace_calls) == 10" in slow_test),
    ]
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
