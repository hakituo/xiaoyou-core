"""验证 tests/ 目录清理优化是否成功。

覆盖：
1. tests/diagnostics/ 下不再有 verify_*.py 一次性验证脚本
2. tests/ 下不再有 verification/、auto_heal/、life_simulation/、self_improvement/、prototypes/、experiments/ 等废弃目录
3. tests/scripts/ 下不再有失效的 .ps1/.bat 启动脚本
4. tests/scripts/ 下不再有一次性 verify_*.py（除 doc_records/ 与 git/ 长期配套）
5. tests/ 根目录下不再有散落的 .py 文件（除 conftest.py）
6. tests/ 下没有引用已删除 context_budget 模块的测试
7. tests/unit/ 下测试文件数量在合理范围（≥ 80，≤ 200）
8. tests/diagnostics/ 下保留的都是长期诊断工具（无 verify_*.py）
9. tests/ 下没有 __pycache__ 残留

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\verify_tests_cleanup.py
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
TESTS_DIR = ROOT / "tests"

# tests/scripts/ 顶层允许保留的 verify_*.py（长期工具）
ALLOWED_SCRIPTS_VERIFY = {
    "verify_qwen3_tts_gpu_optimization.py",
    "verify_tests_cleanup.py",
}


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    return 1


def _ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def check_no_verify_in_diagnostics() -> int:
    """diagnostics/ 下不应再有 verify_*.py。"""
    print("\n[1] 检查 tests/diagnostics/ 下无 verify_*.py")
    matches = list((TESTS_DIR / "diagnostics").glob("verify_*.py"))
    if matches:
        _fail(f"仍存在 {len(matches)} 个 verify_*.py: {[m.name for m in matches[:5]]}")
        return 1
    _ok("diagnostics/ 下无 verify_*.py")
    return 0


def check_obsolete_dirs_removed() -> int:
    """废弃目录应已删除。"""
    print("\n[2] 检查废弃目录已删除")
    obsolete = [
        "verification",
        "auto_heal",
        "life_simulation",
        "self_improvement",
        "prototypes",
        "experiments",
        "_meta_commit_v2",
        "_meta_resolve_v2",
    ]
    rc = 0
    for d in obsolete:
        p = TESTS_DIR / d
        if p.exists():
            _fail(f"目录仍存在: {d}/")
            rc = 1
        else:
            _ok(f"目录已删除: {d}/")
    return rc


def check_no_legacy_ps1_bat() -> int:
    """tests/scripts/ 下不应有失效的 .ps1/.bat 启动脚本。"""
    print("\n[3] 检查 tests/scripts/ 下无失效 .ps1/.bat")
    rc = 0
    for ext in ("*.ps1", "*.bat", "*.lnk"):
        matches = list((TESTS_DIR / "scripts").glob(ext))
        if matches:
            _fail(f"仍存在 {ext}: {[m.name for m in matches]}")
            rc = 1
    if rc == 0:
        _ok("tests/scripts/ 下无 .ps1/.bat/.lnk")
    return rc


def check_no_oneshot_verify_in_scripts() -> int:
    """tests/scripts/ 顶层不应有一次性 verify_*.py（白名单内长期工具除外）。"""
    print("\n[4] 检查 tests/scripts/ 顶层无一次性 verify_*.py")
    matches = [
        p
        for p in (TESTS_DIR / "scripts").glob("verify_*.py")
        if p.name not in ALLOWED_SCRIPTS_VERIFY
    ]
    if matches:
        _fail(f"仍存在 {len(matches)} 个 verify_*.py: {[m.name for m in matches]}")
        return 1
    _ok("tests/scripts/ 顶层无一次性 verify_*.py（白名单内长期工具保留）")
    return 0


def check_no_root_loose_py() -> int:
    """tests/ 根目录下除 conftest.py 外不应有散落 .py 文件。"""
    print("\n[5] 检查 tests/ 根目录无散落 .py（除 conftest.py）")
    loose = [p for p in TESTS_DIR.glob("*.py") if p.name != "conftest.py"]
    if loose:
        _fail(f"仍存在 {len(loose)} 个散落 .py: {[p.name for p in loose[:5]]}")
        return 1
    _ok("tests/ 根目录无散落 .py（仅 conftest.py）")
    return 0


def check_no_context_budget_refs() -> int:
    """不应有 import 已删除 context_budget 模块的测试（用 ast 解析 import 语句）。"""
    print("\n[6] 检查 tests/ 下无 import context_budget 的测试")
    rc = 0
    for p in TESTS_DIR.rglob("*.py"):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        try:
            tree = ast.parse(text, filename=str(p))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "context_budget" in node.module:
                    _fail(f"{p.relative_to(TESTS_DIR)} import {node.module}")
                    rc = 1
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "context_budget" in alias.name:
                        _fail(f"{p.relative_to(TESTS_DIR)} import {alias.name}")
                        rc = 1
    if rc == 0:
        _ok("tests/ 下无 import context_budget")
    return rc


def check_unit_count_in_range() -> int:
    """tests/unit/ 下测试文件数量应在 80-200 之间。"""
    print("\n[7] 检查 tests/unit/ 测试文件数量")
    count = len(list((TESTS_DIR / "unit").glob("test_*.py")))
    if count < 80:
        _fail(f"unit/ 下仅 {count} 个测试，预期 ≥ 80")
        return 1
    if count > 200:
        _fail(f"unit/ 下 {count} 个测试，预期 ≤ 200（可能又开始膨胀）")
        return 1
    _ok(f"unit/ 下 {count} 个测试，在合理范围 [80, 200]")
    return 0


def check_diagnostics_only_longterm() -> int:
    """tests/diagnostics/ 下应只有长期诊断工具（无 verify_*.py、无 test_*_refactor.py）。"""
    print("\n[8] 检查 tests/diagnostics/ 仅含长期诊断工具")
    rc = 0
    bad_patterns = ["verify_", "_refactor", "_reorganization", "_fix_history"]
    for p in (TESTS_DIR / "diagnostics").glob("*.py"):
        for bad in bad_patterns:
            if bad in p.name:
                _fail(f"仍存在一次性脚本: {p.name}")
                rc = 1
    if rc == 0:
        _ok("diagnostics/ 下均为长期诊断工具")
    return rc


def check_no_pycache() -> int:
    """tests/ 下不应有 __pycache__ 残留。"""
    print("\n[9] 检查 tests/ 下无 __pycache__ 残留")
    matches = list(TESTS_DIR.rglob("__pycache__"))
    if matches:
        _fail(f"仍存在 {len(matches)} 个 __pycache__: {[str(m.relative_to(TESTS_DIR)) for m in matches[:3]]}")
        return 1
    _ok("tests/ 下无 __pycache__ 残留")
    return 0


def main() -> int:
    print("=" * 60)
    print("tests/ 目录清理优化验证")
    print("=" * 60)

    checks = [
        check_no_verify_in_diagnostics,
        check_obsolete_dirs_removed,
        check_no_legacy_ps1_bat,
        check_no_oneshot_verify_in_scripts,
        check_no_root_loose_py,
        check_no_context_budget_refs,
        check_unit_count_in_range,
        check_diagnostics_only_longterm,
        check_no_pycache,
    ]

    rc = 0
    for chk in checks:
        rc |= chk()

    print("\n" + "=" * 60)
    if rc == 0:
        print("✓ 所有检查通过，tests/ 目录清理优化成功")
    else:
        print("✗ 部分检查未通过，请查看上方 [FAIL] 项")
    print("=" * 60)
    return rc


if __name__ == "__main__":
    sys.exit(main())
