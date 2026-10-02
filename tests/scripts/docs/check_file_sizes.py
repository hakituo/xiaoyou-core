#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按语言分档的单文件行数审计（报告模式 + 存量基线）。

分档口径（与 `.trae/rules/RULES.md` §2 一致；**本文件的 `LIMITS` 是这些数字的唯一定义处**）：

| 语言 | 单文件上限 | 依据 |
| --- | --- | --- |
| Python（含 `core/`、`tests/` 等） | 300 | 项目既有拆分口径：职责子模块目标 ≤260、薄壳门面 ≤300 |
| Kotlin / Java | 400 | 注解与参数一行一个，样板密度高 |
| C / C++ | 400 | 头文件声明与实现分家（`verify_*_decomposition.py` 系列同源） |
| TypeScript / Vue / Swift | 350 | 类型与视图样板 |
| Markdown 文档 | 500 | 排除逐日追加的日志归档（`docs/updates/`、`.trae/memory/YYYY-MM-DD.md`） |

`tests/` 目录下的 Python 由 `tests/scripts/audit_tests.py` 按**同一个 300** 检查，
本脚本不重复扫它；两个数字的一致性由 `check_rules_consistency.py` 强制校验。

存量超限文件登记在 `tests/scripts/docs/file_size_baseline.txt`，命中基线的文件跳过、只报新增项：
这是技术债看板的 ratchet —— 条目数应随拆分递减，新增超限文件应当场拆掉而不是往基线里加。

运行：
    venv_core\\Scripts\\python.exe tests\\scripts\\docs\\check_file_sizes.py
    venv_core\\Scripts\\python.exe tests\\scripts\\docs\\check_file_sizes.py --strict
    venv_core\\Scripts\\python.exe tests\\scripts\\docs\\check_file_sizes.py --update-baseline
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]

# 单文件行数上限：扩展名 → 行数（唯一定义处，改这里就要同步 RULES.md §2）
# 不纳入审计的扩展名及原因：
#   .js  —— aveline-web 下的 .js 全是 dist/ 构建产物（dist 已在 SKIP_DIRS 中排除）
#   .xml —— Android 资源（res/drawable 矢量图、values 等）属资产而非代码
#   .kts —— Gradle 构建脚本，由构建侧约束
#   .sh / .bat / .ps1 —— 启动与运维脚本，通常只有几十行
LIMITS: dict[str, int] = {
    ".py": 300,
    ".kt": 400,
    ".java": 400,
    ".cpp": 400,
    ".cc": 400,
    ".c": 400,
    ".h": 400,
    ".hpp": 400,
    ".ts": 350,
    ".tsx": 350,
    ".vue": 350,
    ".swift": 350,
    ".md": 500,
}

# 语言名（用于报告；同档语言合并展示）
LANGUAGE_NAMES: dict[str, str] = {
    ".py": "Python",
    ".kt": "Kotlin",
    ".java": "Java",
    ".cpp": "C/C++",
    ".cc": "C/C++",
    ".c": "C/C++",
    ".h": "C/C++",
    ".hpp": "C/C++",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
    ".swift": "Swift",
    ".md": "Markdown",
}

# 代码根目录（tests/ 交给 audit_tests.py，不在这里重复扫）
CODE_ROOTS = [
    "core",
    "services",
    "routers",
    "config",
    "scripts",
    "memory",
    "clients",
    "cpp_modules",
    "multimodal",
    "tools",
]
DOC_ROOTS = [".trae", "docs"]

# 第三方依赖 / 构建产物 / 历史遗留，一律不参与行数审计
SKIP_DIRS = {
    "venv_core",
    "venv_cpu",
    "node_modules",
    ".git",
    "build",
    "build_vs18",
    "dist",
    "__pycache__",
    ".gradle",
    "gradle",
    "intermediates",
    "external",
    "legacy",
    "output",
    "models",
    "paper",
    ".idea",
    ".vs",
    "site-packages",
    ".pytest_cache",
}

BASELINE_PATH = ROOT / "tests" / "scripts" / "docs" / "file_size_baseline.txt"


def _rel(path: pathlib.Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def is_doc_archive(path: pathlib.Path) -> bool:
    """逐日追加的日志归档不做行数限制（文档口径的明确例外）。"""
    posix = _rel(path)
    if posix.startswith("docs/updates/"):
        return True
    return posix.startswith(".trae/memory/") and path.name[:2].isdigit()


def _iter_dir(root: pathlib.Path):
    try:
        candidates = list(root.rglob("*"))
    except OSError:
        return
    for path in candidates:
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def collect_files() -> list[pathlib.Path]:
    """收集参与审计的文件（代码根全部 + 文档根去掉日志归档）。"""
    files: list[pathlib.Path] = []
    for name in CODE_ROOTS:
        base = ROOT / name
        if base.exists():
            files.extend(_iter_dir(base))
    for name in DOC_ROOTS:
        base = ROOT / name
        if base.exists():
            files.extend(path for path in _iter_dir(base) if not is_doc_archive(path))
    return files


def scan() -> list[tuple[str, int, int]]:
    """返回 (仓库相对路径, 行数, 该扩展名的上限)，按超出程度降序。"""
    entries: list[tuple[str, int, int]] = []
    for path in collect_files():
        limit = LIMITS.get(path.suffix.lower())
        if limit is None:
            continue
        try:
            count = sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        if count > limit:
            entries.append((_rel(path), count, limit))
    return sorted(entries, key=lambda item: item[1], reverse=True)


def load_baseline() -> set[str]:
    """读取存量超限清单（每行一个仓库相对路径，`#` 之后是注释）。"""
    if not BASELINE_PATH.exists():
        return set()
    entries = set()
    for line in BASELINE_PATH.read_text(encoding="utf-8").splitlines():
        path = line.split("#", 1)[0].strip()
        if path:
            entries.add(path)
    return entries


def update_baseline(entries: list[tuple[str, int, int]], verbose: bool = False) -> int:
    """按当前扫描结果重建存量清单（拆分后条目数应递减）。"""
    lines = [
        f"# 单文件超限存量清单（{len(entries)} 项）—— 技术债看板，只减不增",
        "# 由 `check_file_sizes.py --update-baseline` 生成；新增超限文件请直接拆分，不要往这里加",
        "# 分档口径见 `.trae/rules/RULES.md` §2；tests/ 的 Python 见 audit_tests.py 的 large_file_baseline.txt",
    ]
    lines.extend(f"{rel}  # {count} 行 > {limit}" for rel, count, limit in entries)
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已写入 {_rel(BASELINE_PATH)}（{len(entries)} 项）")
    return 0


def group_by_language(entries: list[tuple[str, int, int]]) -> dict[str, int]:
    groups: dict[str, int] = {}
    for rel, _count, _limit in entries:
        name = LANGUAGE_NAMES.get(pathlib.PurePosixPath(rel).suffix.lower(), "其它")
        groups[name] = groups.get(name, 0) + 1
    return groups


def main() -> int:
    parser = argparse.ArgumentParser(description="按语言分档的单文件行数审计")
    parser.add_argument("--strict", action="store_true", help="有新增超限文件时返回非零")
    parser.add_argument(
        "--update-baseline", action="store_true", help="按当前扫描结果重建存量清单后退出"
    )
    parser.add_argument("--verbose", action="store_true", help="打印分档口径与全部新增项")
    args = parser.parse_args()

    entries = scan()

    if args.update_baseline:
        return update_baseline(entries, args.verbose)

    baseline = load_baseline()
    live = {rel for rel, _count, _limit in entries}
    new_items = [item for item in entries if item[0] not in baseline]
    removable = sorted(baseline - live)

    print("=" * 60)
    print("单文件行数审计（按语言分档）")
    print("=" * 60)

    if args.verbose:
        print("\n[分档口径]")
        for ext in sorted(LIMITS, key=lambda item: LIMITS[item]):
            print(f"  {LANGUAGE_NAMES.get(ext, ext):11s} {ext:6s} ≤ {LIMITS[ext]} 行")
        print("  例外：docs/updates/ 与 .trae/memory/YYYY-MM-DD.md 逐日日志不受限")

    print(f"\n[存量] 超限 {len(entries)} 项（已登记 {len(live & baseline)} 项）")
    if entries:
        for name, count in sorted(group_by_language(entries).items(), key=lambda item: -item[1]):
            print(f"  {name:11s} {count:4d} 项")

    if new_items:
        print(f"\n[新增超限] {len(new_items)} 项（应当场拆分，而不是登记进基线）")
        for rel, count, limit in new_items[:20]:
            print(f"  FAIL {count} 行 > {limit}: {rel}")
        if len(new_items) > 20:
            print(f"  ... 另有 {len(new_items) - 20} 项")
    else:
        print("\n[新增超限] 无")

    if removable:
        print(f"\n[基线可移除] {len(removable)} 项已降到上限内，可跑 --update-baseline 收缩")
        for rel in removable[:10]:
            print(f"  INFO {rel}")
        if len(removable) > 10:
            print(f"  ... 另有 {len(removable) - 10} 项")

    print("\n" + "=" * 60)
    if not new_items:
        print("单文件行数审计通过（无新增超限）✓")
        return 0
    print(f"共 {len(new_items)} 个新增超限文件")
    return 1 if args.strict else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
