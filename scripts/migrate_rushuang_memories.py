# -*- coding: utf-8 -*-
"""一次性迁移脚本：把错误落在 aveline_data/memories 里的自定义人设记忆迁到对应 {slug}_data/memories。

背景：data_paths.py 的 _resolve_scope_from_persona_slug 此前对未注册的自定义人设 slug（如"Frost"）
匹配不上任何 role_id，返回空，最终回退到 aveline scope，导致自定义人设的记忆被错误存到
aveline_data/memories/。修复后 slug 会作为独立 scope，记忆应落到 {slug}_data/memories/。

本脚本扫描 aveline_data/memories 下所有文件名带 __persona__{slug} 的文件，按 slug 迁移到
对应的 {slug}_data/memories 目录，保持相对路径结构。

用法：python scripts/migrate_rushuang_memories.py [--dry-run]
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPANION_DATA = PROJECT_ROOT / "companion_data"
AVELINE_MEMORIES = COMPANION_DATA / "aveline_data" / "memories"

# 匹配文件名里的 __persona__{slug} 后缀（slug 可能含中文）
PERSONA_PATTERN = re.compile(r"__persona__([a-zA-Z0-9_\u4e00-\u9fff]+?)(?:_(?:weighted|short|sessions)\.json$|\.json$)")

# 已注册角色 role_id（这些及其变体 slug 正确落在对应 {role}_data 目录，不迁移）
REGISTERED_ROLE_IDS = {"aveline", "ling", "xiaolu", "yeye"}
# QQ Official 历史 slug（已在 data_paths.py 的 _QQ_OFFICIAL_SLUG_TO_SCOPE 映射，不迁移）
QQ_OFFICIAL_SLUGS = {"qq_official_1", "qq_official_2", "xiaolu", "yeye"}


def is_registered_slug(slug: str) -> bool:
    """判断 slug 是否属于已注册角色（含变体如 aveline_qq_master / core_aveline）。

    与 data_paths.py 的 _resolve_scope_from_persona_slug 逻辑对齐：
    slug 以 role_id 开头（作为独立段）的视为已注册角色变体。
    """
    slug_lower = str(slug or "").strip().lower()
    if not slug_lower:
        return False
    if slug_lower in QQ_OFFICIAL_SLUGS:
        return True
    # core_{role_id} 或 {role_id}_xxx 格式
    parts = slug_lower.split("_")
    for role_id in REGISTERED_ROLE_IDS:
        if slug_lower == role_id:
            return True
        if slug_lower == f"core_{role_id}":
            return True
        if role_id in parts or slug_lower.startswith(role_id):
            return True
    return False


def extract_slug(filename: str) -> str | None:
    """从文件名提取 __persona__ 后面的 slug。"""
    m = PERSONA_PATTERN.search(filename)
    if not m:
        return None
    return m.group(1)


def migrate(dry_run: bool = False) -> None:
    if not AVELINE_MEMORIES.exists():
        print(f"源目录不存在: {AVELINE_MEMORIES}")
        return

    moved = 0
    skipped = 0
    for src_file in AVELINE_MEMORIES.rglob("*.json"):
        if not src_file.is_file():
            continue
        slug = extract_slug(src_file.name)
        if not slug:
            skipped += 1
            continue
        # 已注册角色及其变体的 slug 不迁移（它们本就该在对应 {role}_data 目录）
        if is_registered_slug(slug):
            skipped += 1
            continue

        # 目标目录：companion_data/{slug}_data/memories/{相对路径}
        rel = src_file.relative_to(AVELINE_MEMORIES)
        dst_dir = COMPANION_DATA / f"{slug}_data" / "memories"
        dst_file = dst_dir / rel

        print(f"[{'DRY' if dry_run else 'MOVE'}] {slug}")
        print(f"  src: {src_file}")
        print(f"  dst: {dst_file}")

        if dry_run:
            moved += 1
            continue

        dst_file.parent.mkdir(parents=True, exist_ok=True)
        if dst_file.exists():
            # 目标已存在，合并策略：保留更大的文件
            src_size = src_file.stat().st_size
            dst_size = dst_file.stat().st_size
            if src_size > dst_size:
                dst_file.unlink()
                shutil.move(str(src_file), str(dst_file))
                print(f"  合并：源更大({src_size} > {dst_size})，覆盖目标")
            else:
                src_file.unlink()
                print(f"  合并：目标更大({dst_size} >= {src_size})，删除源")
        else:
            shutil.move(str(src_file), str(dst_file))
        moved += 1

    print(f"\n完成：迁移 {moved} 个文件，跳过 {skipped} 个已注册/无 slug 文件")
    if dry_run:
        print("(dry-run 模式，未实际移动)")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    migrate(dry_run=dry)
