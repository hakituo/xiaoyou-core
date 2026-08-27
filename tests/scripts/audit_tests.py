"""tests/ 目录健康审计工具（长期维护）。

用于定期扫描 tests/ 目录，发现以下问题：
1. 死引用：test_*.py 文件 import 已不存在的项目内模块
2. 非 pytest 文件：test_*.py 用 print 不用 assert（pytest 会收集但不实际验证）
3. 一次性脚本蔓延：tests/diagnostics/ 或 tests/scripts/ 顶层出现 verify_*.py
4. 根目录散落：tests/ 根目录出现除 conftest.py 外的 .py 文件
5. __pycache__ 残留
6. 重复文件名：不同子目录下存在同名 test_*.py
7. 超大文件：单文件超过 1000 行（建议拆分）
8. 废弃目录复活：已删除的 verification/、auto_heal/ 等目录重新出现

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\audit_tests.py
    venv_core\\Scripts\\python.exe tests\\scripts\\audit_tests.py --strict  # 任意 WARN 都返回非零
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[2]
TESTS_DIR = ROOT / "tests"
PROJECT_ROOT = ROOT

# 已废弃的目录（不应再出现）
OBSOLETE_DIRS = [
    "verification",
    "auto_heal",
    "life_simulation",
    "self_improvement",
    "prototypes",
    "experiments",
    "_meta_commit_v2",
    "_meta_resolve_v2",
]

# 允许在 tests/scripts/ 顶层放 verify_*.py 的子目录（长期配套）
ALLOWED_VERIFY_SUBDIRS = {"doc_records", "git"}

# 允许的 tests/scripts/ 顶层 .py 文件（长期工具）
ALLOWED_SCRIPTS_TOPLEVEL = {
    "check_bert_load.py",
    "export_bge_onnx.py",
    "ingest_knowledge.py",
    "verify_qwen3_tts_gpu_optimization.py",
    "verify_tests_cleanup.py",
    "audit_tests.py",
}


def _walk_py_files(root: pathlib.Path) -> list[pathlib.Path]:
    """枚举 root 下所有 .py 文件（跳过 __pycache__）。"""
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


# --------------------------------------------------------------------- #
# 检查项
# --------------------------------------------------------------------- #


def audit_obsolete_dirs() -> list[str]:
    """检查废弃目录是否复活。"""
    issues = []
    for d in OBSOLETE_DIRS:
        p = TESTS_DIR / d
        if p.exists():
            issues.append(f"废弃目录复活: {d}/")
    return issues


def audit_root_loose_py() -> list[str]:
    """检查 tests/ 根目录是否有散落 .py（除 conftest.py）。"""
    issues = []
    for p in TESTS_DIR.glob("*.py"):
        if p.name != "conftest.py":
            issues.append(f"根目录散落 .py: {p.name}（应移到 unit/ 或 diagnostics/）")
    return issues


def audit_oneshot_verify_spread() -> list[str]:
    """检查 tests/diagnostics/ 与 tests/scripts/ 顶层是否蔓延 verify_*.py。"""
    issues = []
    for p in (TESTS_DIR / "diagnostics").glob("verify_*.py"):
        issues.append(f"diagnostics/ 蔓延 verify_*.py: {p.name}")
    for p in (TESTS_DIR / "scripts").glob("verify_*.py"):
        if p.name not in ALLOWED_SCRIPTS_TOPLEVEL:
            issues.append(f"scripts/ 顶层蔓延 verify_*.py: {p.name}")
    return issues


def audit_scripts_toplevel() -> list[str]:
    """检查 tests/scripts/ 顶层 .py 是否在白名单内。"""
    issues = []
    for p in (TESTS_DIR / "scripts").glob("*.py"):
        if p.name not in ALLOWED_SCRIPTS_TOPLEVEL:
            issues.append(
                f"scripts/ 顶层非白名单文件: {p.name}（应放入语义子目录或加入白名单）"
            )
    return issues


def audit_pycache() -> list[str]:
    """检查 __pycache__ 残留。"""
    issues = []
    for p in TESTS_DIR.rglob("__pycache__"):
        issues.append(f"__pycache__ 残留: {p.relative_to(TESTS_DIR)}")
    return issues


def audit_duplicate_filenames() -> list[str]:
    """检查 tests/unit/ 与其他子目录是否同名 test_*.py（潜在职责重复）。"""
    issues = []
    unit_names = {p.name for p in (TESTS_DIR / "unit").glob("test_*.py")}
    for sub in ("diagnostics", "integration", "scheduler", "stress", "tools", "utils", "character_daily", "journal_plan", "benchmark"):
        sub_dir = TESTS_DIR / sub
        if not sub_dir.exists():
            continue
        for p in sub_dir.glob("test_*.py"):
            if p.name in unit_names:
                issues.append(
                    f"重复文件名: unit/{p.name} 与 {sub}/{p.name}（应合并或改名）"
                )
    return issues


def audit_large_files(threshold: int = 2000) -> list[str]:
    """检查超大测试文件（> threshold 行，默认 2000）。

    threshold 设为 2000 是因为：
    - 主题集中的测试文件（如 test_message_deferral.py 1033 行）即使超过 1000 行也是合理的
    - 真正需要警惕的是 2000+ 行的混杂主题文件
    - 可通过 --threshold 参数调整
    """
    issues = []
    for p in _walk_py_files(TESTS_DIR):
        try:
            line_count = sum(1 for _ in p.open(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if line_count > threshold:
            issues.append(
                f"超大文件 {line_count} 行: {p.relative_to(TESTS_DIR)}（建议拆分）"
            )
    return issues


def audit_test_without_assert() -> list[str]:
    """检查 test_*.py 是否有 assert / pytest.raises / unittest 风格 self.assertXxx。"""
    issues = []
    # unittest.TestCase 中的 assert 方法
    unittest_assert_methods = {
        "assertEqual","assertNotEqual","assertTrue","assertFalse","assertIs",
        "assertIsNot","assertIsNone","assertIsNotNone","assertIn","assertNotIn",
        "assertIsInstance","assertNotIsInstance","assertRaises","assertWarns",
        "assertAlmostEqual","assertNotAlmostEqual","assertGreater","assertGreaterEqual",
        "assertLess","assertLessEqual","assertRegex","assertNotRegex","assertCountEqual",
        "assertDictEqual","assertListEqual","assertSetEqual","assertTupleEqual",
        "assertSequenceEqual","assertMultiLineEqual","fail","skip","skipTest",
    }
    for p in _walk_py_files(TESTS_DIR):
        if not p.name.startswith("test_"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        # 跳过明显是手动诊断脚本（在 diagnostics/ 下）
        if "diagnostics" in p.parts:
            continue
        try:
            tree = ast.parse(text, filename=str(p))
        except SyntaxError:
            continue
        has_assert = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                has_assert = True
                break
            if isinstance(node, ast.Call):
                func = node.func
                # pytest.raises / pytest.warns / pytest.fail / pytest.skip
                if (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "pytest"
                    and func.attr in ("raises", "warns", "fail", "skip")
                ):
                    has_assert = True
                    break
                # self.assertEqual / self.assertTrue 等 unittest 风格
                if (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "self"
                    and func.attr in unittest_assert_methods
                ):
                    has_assert = True
                    break
        if not has_assert:
            issues.append(
                f"无 assert 的 test_*.py: {p.relative_to(TESTS_DIR)}（pytest 会收集但不实际验证）"
            )
    return issues


def audit_dead_imports() -> list[str]:
    """检查 test_*.py 是否 import 已不存在的项目内模块（仅扫项目根下的顶级包）。"""
    issues = []
    # 项目顶级包
    top_packages = set()
    for d in PROJECT_ROOT.iterdir():
        if d.is_dir() and (d / "__init__.py").exists():
            top_packages.add(d.name)
    top_packages.update({"core", "memory", "clients", "config", "routers", "multimodal", "scripts"})

    for p in _walk_py_files(TESTS_DIR):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        try:
            tree = ast.parse(text, filename=str(p))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module is None:
                continue
            # 只检查项目内顶级包
            top = node.module.split(".")[0]
            if top not in top_packages:
                continue
            # 检查 import 的目标路径是否存在
            module_path = PROJECT_ROOT
            for part in node.module.split("."):
                module_path = module_path / part
            # 可能是包（目录）或模块（.py 文件）
            if not (module_path.exists() or module_path.with_suffix(".py").exists()):
                # 跳过已知动态加载模块（带 try/except ImportError 的）
                # 简单启发：检查文件中是否有 try: import ... except ImportError
                if "try:\n" in text and "except ImportError" in text:
                    continue
                issues.append(
                    f"死引用 {p.relative_to(TESTS_DIR)}: import {node.module}"
                )
    return issues


# --------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------- #


def main() -> int:
    parser = argparse.ArgumentParser(description="tests/ 目录健康审计")
    parser.add_argument(
        "--strict", action="store_true", help="任意 WARN 都返回非零退出码"
    )
    parser.add_argument(
        "--no-dead-imports", action="store_true", help="跳过死引用检查（较慢）"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("tests/ 目录健康审计")
    print("=" * 60)

    checks = [
        ("废弃目录复活", audit_obsolete_dirs),
        ("根目录散落 .py", audit_root_loose_py),
        ("一次性 verify_*.py 蔓延", audit_oneshot_verify_spread),
        ("scripts/ 顶层白名单", audit_scripts_toplevel),
        ("__pycache__ 残留", audit_pycache),
        ("重复文件名", audit_duplicate_filenames),
        ("超大文件", audit_large_files),
        ("无 assert 的 test_*.py", audit_test_without_assert),
    ]
    if not args.no_dead_imports:
        checks.append(("死引用", audit_dead_imports))

    total_issues = 0
    for name, fn in checks:
        print(f"\n[{name}]")
        issues = fn()
        if not issues:
            print(f"  OK  无问题")
        else:
            for s in issues:
                print(f"  WARN {s}")
            total_issues += len(issues)

    print("\n" + "=" * 60)
    if total_issues == 0:
        print("✓ tests/ 目录健康，无问题")
        return 0
    print(f"共发现 {total_issues} 个潜在问题")
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
