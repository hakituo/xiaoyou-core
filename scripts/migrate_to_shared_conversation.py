#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨平台聊天历史/记忆数据迁移脚本

将旧的"按 user_id 隔离"格式数据合并到"按 persona 共享"路径下：
  旧格式 conversation_id: {session_id}__persona__{slug}  (如 private_12345__persona__aveline)
  旧格式 memory user_id:   {session_id}__scope__{slug}    (如 private_12345__scope__aveline)
  新格式 conversation_id: shared__persona__{slug}         (如 shared__persona__aveline)
  新格式 memory user_id:   shared__scope__{slug}         (如 shared__scope__aveline)

迁移目标：
- 让所有平台（QQ/Telegram/websocket/Android）同一 persona 共享一份聊天历史和记忆池
- 同一 persona 下旧数据按时间戳合并（不丢消息）

使用方法：
  cd D:\AI\xiaoyou-core
  python scripts/migrate_to_shared_conversation.py --dry-run   # 预演，不实际改动
  python scripts/migrate_to_shared_conversation.py             # 实际迁移
  python scripts/migrate_to_shared_conversation.py --rollback  # 回滚（如果出问题）

注意：
- 迁移前请停止后端服务，避免数据竞争
- --dry-run 模式只打印将要做什么，不实际改动文件
- 自动备份被覆盖的目标文件到 .bak 目录
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

# 把项目根目录加到 sys.path，让 import 能解析
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _parse_persona_slug_from_filename(filename: str) -> str:
    """从 persona_filename 提取 slug（与 data_paths.build_shared_persona_conversation_id 一致）"""
    raw = str(filename or "").strip()
    if not raw:
        return ""
    normalized = raw.replace("\\", "/").strip("/")
    stem = normalized.rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    safe = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff]+", "_", stem).strip("_").lower()
    if not safe:
        import hashlib
        digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:8]
        safe = f"persona_{digest}"
    return safe


def _find_legacy_persona_dirs(base: Path) -> list[tuple[Path, str, str]]:
    """扫描 base 下所有 chat_history 目录，找出旧格式 user_id__persona__slug 子目录

    返回 [(legacy_dir, slug, base_user_id), ...]
    """
    results: list[tuple[Path, str, str]] = []
    if not base.exists():
        return results
    # 遍历所有 *_data/chat_history/ 子目录
    for chat_root in base.rglob("chat_history"):
        if not chat_root.is_dir():
            continue
        for entry in chat_root.iterdir():
            if not entry.is_dir():
                continue
            name = entry.name
            # 匹配 user_id__persona__slug 格式
            m = re.match(r"^(.+?)__persona__(.+)$", name)
            if m:
                base_user_id = m.group(1).rstrip("_")
                slug = m.group(2).strip("_")
                if base_user_id.lower() == "shared":
                    continue  # 已经是新格式，跳过
                results.append((entry, slug, base_user_id))
    return results


def _merge_jsonl(src: Path, dst: Path, dry_run: bool) -> int:
    """合并两个 JSONL 文件，按 timestamp 去重后写入 dst

    返回新增的消息条数
    """
    if not src.exists():
        return 0
    import json
    seen_keys: set[str] = set()
    existing_lines: list[str] = []
    if dst.exists():
        with dst.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    # 用 timestamp + role + content 前 80 字做去重 key
                    key = f"{obj.get('timestamp', '')}|{obj.get('role', '')}|{str(obj.get('content', ''))[:80]}"
                    seen_keys.add(key)
                    existing_lines.append(line)
                except Exception:
                    existing_lines.append(line)  # 解析失败的行保留
    new_count = 0
    new_lines: list[str] = []
    with src.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                key = f"{obj.get('timestamp', '')}|{obj.get('role', '')}|{str(obj.get('content', ''))[:80]}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                new_lines.append(line)
                new_count += 1
            except Exception:
                continue
    if not dry_run and new_lines:
        dst.parent.mkdir(parents=True, exist_ok=True)
        # 备份目标
        if dst.exists():
            bak = dst.with_suffix(dst.suffix + ".bak")
            shutil.copy2(dst, bak)
        with dst.open("a", encoding="utf-8") as f:
            for line in new_lines:
                f.write(line)
    return new_count


def _migrate_chat_history(base: Path, dry_run: bool) -> int:
    """迁移 chat_history 目录下的旧格式子目录到 shared__persona__{slug}"""
    legacy_entries = _find_legacy_persona_dirs(base)
    if not legacy_entries:
        print(f"  [{base}] 无旧格式数据需要迁移")
        return 0
    migrated = 0
    for legacy_dir, slug, base_user_id in legacy_entries:
        # 找该 persona 所属的 scope 目录（如 aveline_data, ling_data）
        # legacy_dir 的父父目录是 {scope}_data
        scope_data_dir = legacy_dir.parent.parent
        new_cid_dirname = f"shared__persona__{slug}"
        new_dir = legacy_dir.parent / new_cid_dirname
        print(f"  迁移: {legacy_dir.name} -> {new_cid_dirname}  (scope_data={scope_data_dir.name})")
        if dry_run:
            print(f"    [DRY-RUN] 将合并 {legacy_dir} -> {new_dir}")
            continue
        # 实际迁移：合并目录下所有 jsonl 文件
        new_dir.mkdir(parents=True, exist_ok=True)
        for src_file in legacy_dir.glob("*.jsonl"):
            dst_file = new_dir / src_file.name
            added = _merge_jsonl(src_file, dst_file, dry_run=False)
            print(f"    {src_file.name}: 新增 {added} 条")
        # 旧目录保留（不删，方便回滚），改名加 .legacy 后缀避免再次扫描
        legacy_bak = legacy_dir.parent / f"{legacy_dir.name}.legacy"
        if not legacy_bak.exists():
            shutil.move(str(legacy_dir), str(legacy_bak))
        migrated += 1
    return migrated


def _migrate_memory_pool(base: Path, dry_run: bool) -> int:
    """迁移 memory_pool 目录下的 user_id__scope__slug 子目录到 shared__scope__slug"""
    if not base.exists():
        return 0
    migrated = 0
    for mem_root in base.rglob("memory_pool"):
        if not mem_root.is_dir():
            continue
        for entry in mem_root.iterdir():
            if not entry.is_dir():
                continue
            name = entry.name
            m = re.match(r"^(.+?)__scope__(.+)$", name)
            if not m:
                continue
            base_user_id = m.group(1).rstrip("_")
            scope = m.group(2).strip("_")
            if base_user_id.lower() == "shared":
                continue
            new_name = f"shared__scope__{scope}"
            new_dir = mem_root / new_name
            print(f"  迁移记忆池: {entry.name} -> {new_name}")
            if dry_run:
                print(f"    [DRY-RUN] 将合并 {entry} -> {new_dir}")
                continue
            new_dir.mkdir(parents=True, exist_ok=True)
            # 记忆池通常是 .json 文件（按类型分），合并覆盖
            for src_file in entry.iterdir():
                if not src_file.is_file():
                    continue
                dst_file = new_dir / src_file.name
                if dst_file.exists():
                    # 备份并覆盖（记忆池以最新为准，不简单合并）
                    bak = dst_file.with_suffix(dst_file.suffix + ".bak")
                    shutil.copy2(dst_file, bak)
                shutil.copy2(src_file, dst_file)
                print(f"    {src_file.name}: 已复制")
            # 旧目录改名加 .legacy
            legacy_bak = mem_root / f"{entry.name}.legacy"
            if not legacy_bak.exists():
                shutil.move(str(entry), str(legacy_bak))
            migrated += 1
    return migrated


def main():
    parser = argparse.ArgumentParser(
        description="跨平台聊天历史/记忆数据迁移到 shared__persona__{slug} 格式"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="预演模式：只打印将做什么，不实际改动"
    )
    parser.add_argument(
        "--rollback", action="store_true", help="回滚：把 .legacy 目录改回原名"
    )
    parser.add_argument(
        "--data-root",
        default=str(_PROJECT_ROOT / "generated_data"),
        help="数据根目录（默认 generated_data）",
    )
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve()
    if not data_root.exists():
        print(f"数据根目录不存在: {data_root}")
        sys.exit(1)

    if args.rollback:
        print("=== 回滚模式：恢复 .legacy 目录 ===")
        restored = 0
        for legacy_bak in data_root.rglob("*.legacy"):
            original = legacy_bak.with_name(legacy_bak.name[:-7])  # 去掉 .legacy
            if original.exists():
                print(f"  跳过（目标已存在）: {legacy_bak}")
                continue
            shutil.move(str(legacy_bak), str(original))
            print(f"  恢复: {legacy_bak.name} -> {original.name}")
            restored += 1
        print(f"回滚完成，恢复了 {restored} 个目录")
        return

    print(f"=== {'DRY-RUN' if args.dry_run else '实际迁移'} ===")
    print(f"数据根目录: {data_root}")

    print("\n[1/2] 迁移 chat_history...")
    chat_count = _migrate_chat_history(data_root, args.dry_run)
    print(f"  共迁移 {chat_count} 个 chat_history 旧格式目录")

    print("\n[2/2] 迁移 memory_pool...")
    mem_count = _migrate_memory_pool(data_root, args.dry_run)
    print(f"  共迁移 {mem_count} 个 memory_pool 旧格式目录")

    print("\n=== 完成 ===")
    if args.dry_run:
        print("（DRY-RUN 模式，未实际改动）")
    else:
        print("实际迁移已完成。旧目录已改名为 .legacy，可用 --rollback 回滚。")
        print("建议：检查无问题后重启后端服务，验证历史和记忆可正常加载。")


if __name__ == "__main__":
    main()
