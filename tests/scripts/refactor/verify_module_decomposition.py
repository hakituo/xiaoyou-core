# -*- coding: utf-8 -*-
r"""验证「薄壳门面 + 业务子包」解耦约定。

背景（2026-09-25）：五个超长 Python 入口（weighted_memory_manager、
websocket adapter、auto_commit_push、active_care prompt_builder、
ye_runtime_state）拆分时，第一版把实现文件以相同前缀平铺在原目录
（如 prompt_section_filter.py、auto_commit_network.py），可读性差。
已改为按业务命名的子包集中存放；本脚本把该约定固化为可执行判据：
1. 门面文件不得超过 RULES.md §2 的 Python 上限（300 行）；
2. 每个门面对应的实现子包存在，且包含预期的职责文件；
3. 旧的"同前缀平铺实现文件"不得复活；
4. 拆分前的存量基线（file_size_baseline.txt）不得再登记这五个入口。

运行：
    venv_core\Scripts\python.exe tests\scripts\refactor\verify_module_decomposition.py
"""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PYTHON_LINE_LIMIT = 300

# 门面 -> (实现子包, 子包内必备职责文件, 禁止复活的历史平铺文件名)
DECOMPOSITIONS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "memory/weighted_memory_manager.py": (
        "memory/weighted_manager",
        ("initialization.py", "lifecycle.py", "writing.py", "queries.py", "preferences.py", "support.py"),
        (
            "memory/weighted_manager_init.py",
            "memory/weighted_manager_lifecycle.py",
            "memory/weighted_manager_write.py",
            "memory/weighted_manager_query.py",
            "memory/weighted_manager_preferences.py",
            "memory/weighted_manager_support.py",
        ),
    ),
    "core/interfaces/websocket/adapters/adapter.py": (
        "core/interfaces/websocket/adapters/fastapi",
        ("connection.py", "routing.py", "demo.py", "image_generation.py", "resource_broadcast.py"),
        (
            "core/interfaces/websocket/adapters/connection_flow.py",
            "core/interfaces/websocket/adapters/message_router.py",
            "core/interfaces/websocket/adapters/demo_flow.py",
            "core/interfaces/websocket/adapters/image_generation.py",
            "core/interfaces/websocket/adapters/resource_broadcast.py",
        ),
    ),
    "scripts/git/auto_commit_push.py": (
        "scripts/git/auto_commit",
        ("process.py", "network.py", "changes.py", "sensitive_scan.py", "repo_guard.py", "workflow.py"),
        (
            "scripts/git/auto_commit_process.py",
            "scripts/git/auto_commit_network.py",
            "scripts/git/auto_commit_changes.py",
            "scripts/git/auto_commit_scan.py",
            "scripts/git/auto_commit_repo_guard.py",
            "scripts/git/auto_commit_workflow.py",
        ),
    ),
    "core/services/active_care/prompt/prompt_builder.py": (
        "core/services/active_care/prompt/sections",
        ("models.py", "filtering.py", "constraints.py", "tasks.py", "composer.py", "assembly.py", "persona_reminders.py"),
        (
            "core/services/active_care/prompt/prompt_sections.py",
            "core/services/active_care/prompt/prompt_section_filter.py",
            "core/services/active_care/prompt/prompt_section_composer.py",
            "core/services/active_care/prompt/prompt_constraints.py",
            "core/services/active_care/prompt/prompt_task_blocks.py",
            "core/services/active_care/prompt/prompt_assembly.py",
            "core/services/active_care/prompt/persona_reminders.py",
        ),
    ),
    "core/services/data_ops/ye_runtime_state.py": (
        "core/services/data_ops/ye_runtime",
        ("document.py", "rule_extractor.py", "uie.py", "merge.py", "expiry.py"),
        (
            "core/services/data_ops/ye_state_document.py",
            "core/services/data_ops/ye_state_rule_extractor.py",
            "core/services/data_ops/ye_state_uie.py",
            "core/services/data_ops/ye_state_merge.py",
            "core/services/data_ops/ye_state_expiry.py",
        ),
    ),
}

_FAILED: list[str] = []


def _ok(message: str) -> None:
    print(f"  [OK] {message}")


def _fail(message: str) -> None:
    print(f"  [FAIL] {message}")
    _FAILED.append(message)


def check_facade_lines(facade: str) -> None:
    path = PROJECT_ROOT / facade
    lines = len(path.read_text(encoding="utf-8").splitlines())
    if lines <= PYTHON_LINE_LIMIT:
        _ok(f"{facade} = {lines} 行 (<= {PYTHON_LINE_LIMIT})")
    else:
        _fail(f"{facade} = {lines} 行，超过门面上限 {PYTHON_LINE_LIMIT}")


def check_subpackage(facade: str, subpackage: str, required: tuple[str, ...]) -> None:
    package_dir = PROJECT_ROOT / subpackage
    if not package_dir.is_dir():
        _fail(f"实现子包不存在: {subpackage}")
        return
    missing = [name for name in required if not (package_dir / name).is_file()]
    if missing:
        _fail(f"{subpackage} 缺少职责文件: {missing}")
    else:
        _ok(f"{subpackage} 包含全部 {len(required)} 个职责文件")


def check_flat_files_not_revived(facade: str, legacy_files: tuple[str, ...]) -> None:
    revived = [name for name in legacy_files if (PROJECT_ROOT / name).exists()]
    if revived:
        _fail(f"{facade} 的同前缀平铺实现文件复活: {revived}")
    else:
        _ok(f"{facade} 无同前缀平铺实现文件")


def check_baseline_clean() -> None:
    baseline = PROJECT_ROOT / "tests" / "scripts" / "docs" / "file_size_baseline.txt"
    text = baseline.read_text(encoding="utf-8", errors="replace")
    still_listed = [facade for facade in DECOMPOSITIONS if facade in text]
    if still_listed:
        _fail(f"已拆分入口仍登记在存量超限基线: {still_listed}")
    else:
        _ok("存量超限基线不再登记本次拆分的五个入口")


def main() -> int:
    print("=" * 64)
    print("模块解耦约定验证（薄壳门面 + 业务子包）")
    print("=" * 64)
    for facade, (subpackage, required, legacy) in DECOMPOSITIONS.items():
        print(f"\n--- {facade} ---")
        check_facade_lines(facade)
        check_subpackage(facade, subpackage, required)
        check_flat_files_not_revived(facade, legacy)
    print("\n--- 存量基线 ---")
    check_baseline_clean()
    print("=" * 64)
    if _FAILED:
        print(f"失败 {len(_FAILED)} 项")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    raise SystemExit(main())
