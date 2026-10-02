"""tests/ 目录健康审计工具（长期维护）。

共 10 项检查（外加可选的死引用检查）：
1. 废弃目录复活：已删除的 verification/、auto_heal/ 等目录重新出现
2. 根目录散落 .py：tests/ 根目录出现除 conftest.py 外的 .py 文件
3. 一次性脚本蔓延：tests/diagnostics/ 或 tests/scripts/ 顶层出现 verify_*.py
4. tests/scripts/ 顶层出现白名单外的 .py
5. Git 跟踪了 __pycache__
6. 重复文件名：unit/ 与其他子目录存在同名 test_*.py
7. 超大文件：单文件超过 LINE_LIMIT 行（默认 300，即 `.trae/rules/RULES.md` §2 的 Python 档）；
   存量超限文件登记在 `tests/scripts/docs/large_file_baseline.txt`，只对**新增**超限文件告警
8. 无 assert 的 test_*.py：用 print 而不是断言，pytest 会收集但不实际验证
9. test 函数返回值：pytest 忽略返回值，等同于没有断言
10. 硬编码本机绝对路径：换机即失效，且可能写入真实数据
可选：死引用（test_*.py import 已不存在的项目内模块），`--no-dead-imports` 可跳过（较慢）

行数口径：Python 单文件 300 行（与 `tests/scripts/docs/check_file_sizes.py` 的 `.py` 档同值，
见 `.trae/rules/RULES.md` §2）。阈值可用 `--threshold` 临时放宽；
拆分完存量文件后用 `--update-baseline` 重建基线。

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\audit_tests.py
    venv_core\\Scripts\\python.exe tests\\scripts\\audit_tests.py --strict          # 任意 WARN 都返回非零
    venv_core\\Scripts\\python.exe tests\\scripts\\audit_tests.py --threshold 1000  # 临时放宽阈值
    venv_core\\Scripts\\python.exe tests\\scripts\\audit_tests.py --update-baseline # 重建存量基线
"""

from __future__ import annotations

import argparse
import ast
import functools
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
TESTS_DIR = ROOT / "tests"
PROJECT_ROOT = ROOT

# 单文件行数上限（口径见 `.trae/rules/RULES.md` §2）。
# 必须与 check_file_sizes.LIMITS[".py"] 保持一致，由 check_rules_consistency.py 强制校验。
LINE_LIMIT = 300
# 存量超限文件基线（避免历史债务长期刷屏；新增超限文件仍会告警）
BASELINE_PATH = ROOT / "tests" / "scripts" / "docs" / "large_file_baseline.txt"

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


def _iter_own_returns(node) -> list[ast.Return]:
    """收集测试函数自身的 return 语句（跳过嵌套函数/类里的 return）。"""
    returns: list[ast.Return] = []
    stack = list(node.body)
    while stack:
        current = stack.pop()
        if isinstance(
            current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        if isinstance(current, ast.Return):
            returns.append(current)
            continue
        stack.extend(ast.iter_child_nodes(current))
    return returns


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
    """检查被 Git 跟踪的 __pycache__；忽略正常运行产生的本地缓存。"""
    result = subprocess.run(
        ["git", "ls-files", "--", "tests"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ["无法读取 Git 跟踪文件，__pycache__ 检查未完成"]
    tracked_cache_dirs = {
        pathlib.PurePosixPath(line).parent
        for line in result.stdout.splitlines()
        if "__pycache__" in pathlib.PurePosixPath(line).parts
    }
    return [
        f"Git 跟踪了 __pycache__: {path}"
        for path in sorted(tracked_cache_dirs, key=str)
    ]


def _has_parent_compat_binding(module_name: str) -> bool:
    """父包显式把旧模块名注册到 sys.modules 时，不判为死引用。"""
    parts = module_name.split(".")
    for parent_size in range(len(parts) - 1, 0, -1):
        init_path = PROJECT_ROOT.joinpath(*parts[:parent_size], "__init__.py")
        if not init_path.is_file():
            continue
        try:
            init_text = init_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if f'"{module_name}"' in init_text or f"'{module_name}'" in init_text:
            return True
    return False


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


def _large_file_entries(threshold: int) -> list[tuple[str, int]]:
    """返回超过 threshold 行的文件（tests/ 相对 POSIX 路径, 行数），按路径排序。"""
    entries: list[tuple[str, int]] = []
    for p in _walk_py_files(TESTS_DIR):
        try:
            line_count = sum(1 for _ in p.open(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if line_count > threshold:
            entries.append((p.relative_to(TESTS_DIR).as_posix(), line_count))
    return sorted(entries)


def _load_large_file_baseline() -> set[str]:
    """读取存量超限文件基线（每行一个 tests/ 相对路径，`#` 之后是注释）。"""
    if not BASELINE_PATH.exists():
        return set()
    entries = set()
    for line in BASELINE_PATH.read_text(encoding="utf-8").splitlines():
        path = line.split("#", 1)[0].strip()
        if path:
            entries.add(path)
    return entries


def audit_large_files(threshold: int = LINE_LIMIT) -> list[str]:
    """检查超大测试文件（> threshold 行，默认 LINE_LIMIT=300，口径见 `.trae/rules/RULES.md` §2）。

    存量超限文件（拆分前的历史债务）登记在 `tests/scripts/docs/large_file_baseline.txt`，
    命中基线的文件跳过、只报新增项，避免几十条常态 WARN 淹没真正的问题；
    存量文件拆到阈值内后用 `--update-baseline` 重建基线。
    """
    baseline = _load_large_file_baseline()
    entries = _large_file_entries(threshold)
    live = {rel for rel, _ in entries}
    issues = [
        f"超大文件 {line_count} 行: {rel}（阈值 {threshold}，建议按职责拆分；确需保留请说明原因）"
        for rel, line_count in entries
        if rel not in baseline
    ]
    for rel in sorted(baseline - live):
        print(f"  INFO 基线可移除（已不超限）: {rel}")
    return issues


def update_large_file_baseline(threshold: int = LINE_LIMIT) -> int:
    """按当前扫描结果重建存量基线（新增超限文件应拆分，而不是往基线里加）。"""
    entries = _large_file_entries(threshold)
    lines = [
        f"# tests/ 单文件超过 {threshold} 行的存量清单（{len(entries)} 项）",
        "# 由 `audit_tests.py --update-baseline` 生成；新增超限文件应拆分，而不是往这里加",
    ]
    lines.extend(f"{rel}  # {line_count} 行" for rel, line_count in entries)
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已写入 {BASELINE_PATH.relative_to(ROOT)}（{len(entries)} 项）")
    return 0


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
                if _has_parent_compat_binding(node.module):
                    continue
                # 跳过已知动态加载模块（带 try/except ImportError 的）
                # 简单启发：检查文件中是否有 try: import ... except ImportError
                if "try:\n" in text and "except ImportError" in text:
                    continue
                issues.append(
                    f"死引用 {p.relative_to(TESTS_DIR)}: import {node.module}"
                )
    return issues


def audit_hardcoded_project_paths() -> list[str]:
    """检查 test_*.py 是否硬编码了本机绝对路径（换机即失效、且可能写入真实数据）。"""
    import re

    issues = []
    patterns = [
        re.compile(r"[dD]:[\\/]+AI[\\/]+xiaoyou-core", re.IGNORECASE),
        re.compile(r"[dD]:[\\/]+AI[\\/]+xiaoyou-public", re.IGNORECASE),
    ]
    for p in _walk_py_files(TESTS_DIR):
        if not p.name.startswith("test_"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if any(pat.search(line) for pat in patterns):
                issues.append(
                    f"硬编码本机路径 {p.relative_to(TESTS_DIR)}:{line_no}"
                    "（应使用 tmp_path / 项目相对路径）"
                )
    return issues


def audit_test_returning_value() -> list[str]:
    """检查 test_* 函数是否 return 了值（pytest 忽略返回值，等同于没有断言）。"""
    issues = []
    for p in _walk_py_files(TESTS_DIR):
        if not p.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            for child in _iter_own_returns(node):
                if child.value is None:
                    continue
                issues.append(
                    f"test 函数返回值 {p.relative_to(TESTS_DIR)}::{node.name}"
                    f":{child.lineno}（pytest 忽略返回值，应改为 assert）"
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
    parser.add_argument(
        "--threshold",
        type=int,
        default=LINE_LIMIT,
        help=f"超大文件行数阈值（默认 {LINE_LIMIT}，口径见 .trae/rules/RULES.md §2）",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="按当前扫描结果重建超大文件存量基线后退出",
    )
    args = parser.parse_args()

    if args.update_baseline:
        return update_large_file_baseline(args.threshold)

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
        (f"超大文件（>{args.threshold} 行）", functools.partial(audit_large_files, args.threshold)),
        ("无 assert 的 test_*.py", audit_test_without_assert),
        ("test 函数返回值", audit_test_returning_value),
        ("硬编码本机路径", audit_hardcoded_project_paths),
    ]
    if not args.no_dead_imports:
        checks.append(("死引用", audit_dead_imports))

    total_issues = 0
    for name, fn in checks:
        print(f"\n[{name}]")
        issues = fn()
        if not issues:
            print("  OK  无问题")
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
