"""合并同角色的重复数据目录：Frost_data → rushuang_data。

Frost角色只有一个，scope 为 "rushuang"。历史上由于 persona slug 用中文文件名
("Frost") 解析时未匹配回 scope，导致同一角色的记忆被拆到两个目录：
  - rushuang_data/  (按 scope 名 rushuang 落盘，规范正确)
  - Frost_data/      (按中文 slug "Frost" 落盘，历史遗留)

修复了 core/utils/data_paths.py 的 _resolve_scope_from_persona_slug 后，
新数据都会落到 rushuang_data/。本脚本负责把遗留的 Frost_data/ 内容合并进来，
并删除空壳目录。

用法：
    python scripts/merge_rushuang_data_dirs.py
    python scripts/merge_rushuang_data_dirs.py --dry-run   # 只打印不实际移动
"""

import argparse
import shutil
import sys
from pathlib import Path

# 允许以脚本方式直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.utils.data_paths import _move_path_merge, get_project_root  # noqa: E402


def merge_rushuang_dirs(dry_run: bool = False) -> int:
    base = get_project_root() / "companion_data"
    src = base / "Frost_data"
    dst = base / "rushuang_data"

    if not src.exists():
        print(f"[skip] 源目录不存在：{src}")
        return 0
    if not dst.exists():
        dst.mkdir(parents=True, exist_ok=True)
        print(f"[info] 目标目录不存在，已创建：{dst}")

    moved = 0

    def _count(path: Path) -> int:
        return sum(1 for _ in path.rglob("*"))

    if dry_run:
        items = list(src.iterdir())
        total = _count(src)
        print(f"[dry-run] 将把 {src} 下的 {len(items)} 个顶层条目 "
              f"({total} 个文件/子项) 合并到 {dst}")
        for child in items:
            print(f"    - {child.name} ({'dir' if child.is_dir() else 'file'})")
        return 0

    for child in list(src.iterdir()):
        target = dst / child.name
        _move_path_merge(child, target)
        moved += 1
        print(f"[move] {child.name} -> {target}")

    # 删除空壳源目录
    try:
        if not any(src.iterdir()):
            src.rmdir()
            print(f"[done] 已删除空目录：{src}")
        else:
            print(f"[warn] {src} 仍有残留内容，未删除：")
            for leftover in src.iterdir():
                print(f"    - {leftover.name}")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 删除 {src} 失败：{exc}")

    print(f"[done] 合并完成，移动顶层条目 {moved} 个 -> {dst}")
    return moved


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="合并Frost_data 到 rushuang_data")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不实际移动")
    args = parser.parse_args()
    merge_rushuang_dirs(dry_run=args.dry_run)
