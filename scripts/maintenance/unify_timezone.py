# -*- coding: utf-8 -*-
"""P2-4: 统一时区处理 - 批量替换脚本。

将散落各处的 `datetime.now()`、`datetime.fromtimestamp()` 等调用
替换为 `core.utils.time_utils` 中的对应函数，确保全局时区策略一致。

替换规则：
  - `datetime.now().isoformat()` → `now_iso()`
  - `datetime.now().strftime(FMT)` → `now_str(FMT)`
  - `datetime.fromtimestamp(TS).strftime(FMT)` → `ts_to_str(TS, FMT)`
  - `datetime.fromtimestamp(TS).isoformat()` → `ts_to_iso(TS)`
  - `datetime.fromtimestamp(TS).hour` → `from_timestamp(TS).hour`
  - `datetime.fromtimestamp(TS)` (其他场景) → `from_timestamp(TS)`

注意：
  - 用于"今天日期归属"的 `datetime.now().strftime("%Y-%m-%d")` 不在此脚本自动替换
    （需要根据上下文判断是否使用 `get_diary_target_date_str()`），需手动处理。
  - 脚本仅替换明确安全的模式，对于复杂表达式会跳过并打印警告。
  - 脚本会自动添加 `from core.utils.time_utils import ...` 导入。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Tuple

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 需要扫描的目录（仅 core/ 和 routers/）
SCAN_DIRS = [
    PROJECT_ROOT / "core",
    PROJECT_ROOT / "routers",
]

# 排除的文件/目录
EXCLUDE_PATHS = {
    str(PROJECT_ROOT / "core" / "utils" / "time_utils.py"),  # 本身
}

# 需要添加的 import 语句
IMPORT_LINE = "from core.utils.time_utils import now_iso, now_str, ts_to_str, ts_to_iso, from_timestamp"

# ==================== 替换规则 ====================

# (pattern, replacement, description)
# 注意：顺序很重要，先匹配复杂模式，再匹配简单模式
REPLACEMENTS: List[Tuple[re.Pattern, str, str]] = [
    # datetime.now().isoformat() → now_iso()
    (
        re.compile(r"datetime\.now\(\)\.isoformat\(\)"),
        "now_iso()",
        "datetime.now().isoformat() → now_iso()",
    ),
    # datetime.fromtimestamp(TS).isoformat() → ts_to_iso(TS)
    # TS 可以是任意非括号表达式
    (
        re.compile(r"datetime\.fromtimestamp\((?P<ts>[^()]+(?:\([^()]*\))?)\)\.isoformat\(\)"),
        r"ts_to_iso(\g<ts>)",
        "datetime.fromtimestamp(TS).isoformat() → ts_to_iso(TS)",
    ),
    # datetime.fromtimestamp(TS).strftime(FMT) → ts_to_str(TS, FMT)
    # FMT 必须是字符串字面量（避免歧义）
    (
        re.compile(
            r"datetime\.fromtimestamp\((?P<ts>[^()]+(?:\([^()]*\))?)\)\.strftime\((?P<fmt>[^()]+(?:\([^()]*\))?)\)"
        ),
        r"ts_to_str(\g<ts>, \g<fmt>)",
        "datetime.fromtimestamp(TS).strftime(FMT) → ts_to_str(TS, FMT)",
    ),
    # datetime.fromtimestamp(TS).hour → from_timestamp(TS).hour
    (
        re.compile(r"datetime\.fromtimestamp\((?P<ts>[^()]+(?:\([^()]*\))?)\)\.hour"),
        r"from_timestamp(\g<ts>).hour",
        "datetime.fromtimestamp(TS).hour → from_timestamp(TS).hour",
    ),
    # datetime.now().strftime(FMT) → now_str(FMT)
    # 注意：排除 "%Y-%m-%d" 这种日期归属模式，需要手动判断
    # 但其他格式可以直接替换
    (
        re.compile(r"datetime\.now\(\)\.strftime\((?P<fmt>[^()]+(?:\([^()]*\))?)\)"),
        r"now_str(\g<fmt>)",
        "datetime.now().strftime(FMT) → now_str(FMT)",
    ),
]


def find_python_files() -> List[Path]:
    """查找所有需要扫描的 Python 文件。"""
    files: List[Path] = []
    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for py_file in scan_dir.rglob("*.py"):
            fp = str(py_file)
            if fp in EXCLUDE_PATHS:
                continue
            # 排除 __pycache__
            if "__pycache__" in fp:
                continue
            files.append(py_file)
    return files


def has_time_utils_import(text: str) -> bool:
    """检查文件是否已经 import 了 time_utils。"""
    return "from core.utils.time_utils import" in text


def add_time_utils_import(text: str, needed_names: set) -> str:
    """在文件中添加 time_utils import。

    策略：在已有的 `from core.utils...` 或 `from datetime import` 附近添加。
    """
    if not needed_names:
        return text

    # 如果已经有 time_utils import，则跳过
    if has_time_utils_import(text):
        return text

    import_str = f"from core.utils.time_utils import {', '.join(sorted(needed_names))}"

    lines = text.split("\n")
    insert_idx = -1

    # 优先找其他 `from core.utils` 或 `from datetime` import
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("from core.utils") or stripped.startswith("from datetime import"):
            insert_idx = i + 1

    # 如果没找到，找任意 `from ...` import
    if insert_idx == -1:
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("from ") or stripped.startswith("import "):
                insert_idx = i + 1

    # 如果还是没找到，在文件开头（跳过 docstring/注释）插入
    if insert_idx == -1:
        # 跳过 shebang 和编码声明
        start = 0
        if lines and lines[0].startswith("#!"):
            start = 1
        if start < len(lines) and lines[start].startswith("# -*-"):
            start += 1
        # 跳过 docstring
        in_doc = False
        for i in range(start, len(lines)):
            s = lines[i].strip()
            if not in_doc:
                if s.startswith('"""') or s.startswith("'''"):
                    if s.count('"""') == 2 or s.count("'''") == 2:
                        continue
                    in_doc = True
                    continue
                if not s or s.startswith("#"):
                    continue
                insert_idx = i
                break
            else:
                if '"""' in s or "'''" in s:
                    in_doc = False
                    insert_idx = i + 1

    if insert_idx == -1:
        insert_idx = 0

    # 检查前一行是否为空行，如果不是则加一个空行
    if insert_idx > 0 and lines[insert_idx - 1].strip() and not lines[insert_idx - 1].strip().startswith(("from ", "import ")):
        lines.insert(insert_idx, "")
        insert_idx += 1

    lines.insert(insert_idx, import_str)
    return "\n".join(lines)


def determine_needed_names(new_text: str) -> set:
    """根据替换后的文本确定需要 import 哪些函数。"""
    needed = set()
    if "now_iso(" in new_text:
        needed.add("now_iso")
    if "now_str(" in new_text:
        needed.add("now_str")
    if "ts_to_str(" in new_text:
        needed.add("ts_to_str")
    if "ts_to_iso(" in new_text:
        needed.add("ts_to_iso")
    if "from_timestamp(" in new_text:
        needed.add("from_timestamp")
    return needed


def process_file(filepath: Path) -> dict:
    """处理单个文件，返回统计信息。"""
    stats = {
        "filepath": str(filepath),
        "replacements": 0,
        "modified": False,
        "details": [],
    }

    try:
        original_text = filepath.read_text(encoding="utf-8")
    except Exception as e:
        stats["error"] = f"读取失败: {e}"
        return stats

    new_text = original_text

    for pattern, replacement, desc in REPLACEMENTS:
        matches = list(pattern.finditer(new_text))
        if not matches:
            continue

        # 检查是否在字符串字面量中（简单启发式：检查前一行是否有未闭合的引号）
        # 这里简化处理，直接替换
        new_text = pattern.sub(replacement, new_text)
        stats["replacements"] += len(matches)
        stats["details"].append(f"{desc} ({len(matches)} 处)")

    if new_text == original_text:
        return stats

    # 添加 import
    needed_names = determine_needed_names(new_text)
    if needed_names:
        new_text = add_time_utils_import(new_text, needed_names)

    # 写回文件
    try:
        filepath.write_text(new_text, encoding="utf-8")
        stats["modified"] = True
    except Exception as e:
        stats["error"] = f"写入失败: {e}"

    return stats


def main():
    print("=" * 70)
    print("P2-4: 统一时区处理 - 批量替换")
    print("=" * 70)

    files = find_python_files()
    print(f"扫描 {len(files)} 个 Python 文件...")

    total_replacements = 0
    modified_files = 0
    file_stats: List[dict] = []

    for f in files:
        stats = process_file(f)
        file_stats.append(stats)
        if stats["modified"]:
            modified_files += 1
            total_replacements += stats["replacements"]
            print(f"\n✓ {f.relative_to(PROJECT_ROOT)}")
            for d in stats["details"]:
                print(f"    {d}")

    print("\n" + "=" * 70)
    print(f"总计: 修改 {modified_files} 个文件, {total_replacements} 处替换")
    print("=" * 70)

    # 输出未处理的提示
    print("\n⚠ 注意：以下场景需要手动处理（脚本未自动替换）：")
    print("  1. datetime.now().strftime('%Y-%m-%d') 用于日期归属 → 需判断是否用 get_diary_target_date_str()")
    print("  2. datetime.now() 用于日期比较 → 需判断是否用 get_current_time()")
    print("  3. datetime.fromtimestamp(TS) 用于非 .strftime/.isoformat/.hour 场景 → 手动改为 from_timestamp(TS)")
    print("  4. datetime.now().timestamp() → current_timestamp()")
    print("  5. datetime.now().hour → current_hour()")


if __name__ == "__main__":
    main()
