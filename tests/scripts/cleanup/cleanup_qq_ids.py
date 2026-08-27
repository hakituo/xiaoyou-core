# -*- coding: utf-8 -*-
"""一次性清理脚本：把代码和文档中硬编码的 QQ 号替换为占位符。

策略：
- 只扫描 git 跟踪的文件（git ls-files），自动跳过 .gitignore 的文件
  这样 .env / config.json / companion_data 等本地运行时数据完全不会被碰
- 核心代码文件（config.py / settings.py / obsidian.py）已改为环境变量读取，跳过
- 其余所有文件中的 123456789 → 10001（QQ 系统号段，明显占位符）

用法：
    venv_core\\Scripts\\python.exe tests\\scripts\\cleanup\\cleanup_qq_ids.py --dry-run
    venv_core\\Scripts\\python.exe tests\\scripts\\cleanup\\cleanup_qq_ids.py
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

# 真实 QQ 号从环境变量读取（避免硬编码泄露），占位符替换
REAL_QQ = os.getenv("XIAOYOU_QQ_MASTER_ID", "").strip()
PLACEHOLDER_QQ = "10001"

# 项目根目录
REPO_ROOT = Path(__file__).resolve().parents[3]

# 已改为环境变量读取的核心文件，跳过
SKIP_FILES = {
    "clients/bots/qq/config.py",
    "clients/bots/qq/settings.py",
    "routers/obsidian.py",
}


def get_tracked_files() -> list[Path]:
    """获取 git 跟踪的所有文件列表，自动排除 .gitignore 中的文件。"""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    files = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        p = REPO_ROOT / line
        if p.is_file():
            files.append(p)
    return files


def should_skip(path: Path) -> bool:
    """判断文件是否应该跳过。"""
    rel = path.relative_to(REPO_ROOT).as_posix()

    # 跳过已改为环境变量的核心文件
    if rel in SKIP_FILES:
        return True

    # 跳过本清理脚本自身
    if rel == "tests/scripts/cleanup/cleanup_qq_ids.py":
        return True

    return False


def scan_and_replace(dry_run: bool = False) -> int:
    """扫描并替换所有 git 跟踪文件中的 QQ 号。返回修改的文件数。"""
    changed_files: list[str] = []

    tracked = get_tracked_files()
    print(f"git 跟踪文件总数: {len(tracked)}")

    for path in tracked:
        if should_skip(path):
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError, OSError):
            continue

        if REAL_QQ not in content:
            continue

        count = content.count(REAL_QQ)
        rel = path.relative_to(REPO_ROOT).as_posix()

        if dry_run:
            print(f"[DRY-RUN] {rel}: {count} 处")
            changed_files.append(rel)
        else:
            new_content = content.replace(REAL_QQ, PLACEHOLDER_QQ)
            path.write_text(new_content, encoding="utf-8")
            print(f"[OK] {rel}: 替换 {count} 处")
            changed_files.append(rel)

    return len(changed_files)


def main() -> int:
    parser = argparse.ArgumentParser(description="批量清理硬编码 QQ 号（仅 git 跟踪文件）")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只扫描不修改，打印将要替换的文件",
    )
    args = parser.parse_args()

    print(f"项目根目录: {REPO_ROOT}")
    print(f"替换规则: {REAL_QQ} → {PLACEHOLDER_QQ}")
    print(f"模式: {'DRY-RUN' if args.dry_run else '实际替换'}")
    print("-" * 60)

    total = scan_and_replace(dry_run=args.dry_run)

    print("-" * 60)
    print(f"共处理 {total} 个文件")
    if total == 0:
        print("未发现需要清理的 QQ 号")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
