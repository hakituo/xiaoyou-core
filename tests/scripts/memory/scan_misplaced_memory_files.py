#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描并（可选）迁移「放错角色目录」的记忆文件。

背景
----
修复 scope 解析前，客户端 cid（``web_core_ling.json`` 等）匹配不到 persona slug，
全部塌进 ``aveline_data/memories``，导致 ling / ye 的记忆文件混在 aveline 目录里。
修复解析后这些文件变成孤儿：对应角色读不到自己的历史记忆，aveline 目录也被污染。

本脚本按文件名里的 conversation_id 重新判定归属角色，与目标目录不一致的即为「放错」。

用法
----
    # 只扫描，不动任何文件（默认）
    venv_core/Scripts/python.exe tests/scripts/memory/scan_misplaced_memory_files.py

    # 实际迁移（会先把目标同名文件备份为 .bak-<时间戳>）
    venv_core/Scripts/python.exe tests/scripts/memory/scan_misplaced_memory_files.py --apply
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.data.scope_registry import (  # noqa: E402
    get_registered_role_scopes,
    resolve_data_scope_from_conversation_id,
)

COMPANION_DIR = PROJECT_ROOT / "companion_data"

# 记忆文件的固定命名形态：persistent_states_<cid>.json / <cid>_short.json /
# <cid>_weighted.json / <cid>_long_term.json。
# 必须严格匹配，否则 sessions.json 这类目录级索引会被误判成需要迁移。
_MEMORY_FILE_PATTERN = re.compile(
    r"^(?:persistent_states_(?P<cid1>.+)\.json"
    r"|(?P<cid2>.+)_(?:short|weighted|long_term)\.json)$",
    re.IGNORECASE,
)
# 纯噪音/测试会话，不做迁移判定
_NOISE_PREFIXES = ("test_", "u1", "u2", "group_", "mem_style_", "obsidian_")


def _extract_cid(file_name: str) -> str:
    """从记忆文件名反解 conversation_id；非记忆文件返回空串。"""
    match = _MEMORY_FILE_PATTERN.match(file_name)
    if not match:
        return ""
    return match.group("cid1") or match.group("cid2") or ""


def _is_noise(cid: str) -> bool:
    return cid.startswith(_NOISE_PREFIXES)


def _target_scope(cid: str, valid_scopes: set[str]) -> str:
    """判定该文件应归属的角色 scope；无法判定时返回空串。"""
    if not cid or _is_noise(cid):
        return ""
    scope = resolve_data_scope_from_conversation_id(cid)
    return scope if scope in valid_scopes else ""


def _relocate_target(path: Path, current_scope: str, target_scope: str) -> Path:
    """把 <current>_data/... 路径改写为 <target>_data/... 路径。"""
    parts = list(path.relative_to(PROJECT_ROOT).parts)
    parts[1] = f"{target_scope}_data"
    return PROJECT_ROOT.joinpath(*parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际执行迁移；默认只打印清单（dry-run）",
    )
    args = parser.parse_args()

    valid_scopes = get_registered_role_scopes()
    misplaced: list[tuple[Path, Path, str, str]] = []

    for scope_dir in sorted(COMPANION_DIR.glob("*_data")):
        current_scope = scope_dir.name[: -len("_data")]
        memories_dir = scope_dir / "memories"
        if not memories_dir.exists():
            continue
        for path in sorted(memories_dir.rglob("*")):
            if not path.is_file():
                continue
            cid = _extract_cid(path.name)
            target_scope = _target_scope(cid, valid_scopes)
            if not target_scope or target_scope == current_scope:
                continue
            misplaced.append((path, _relocate_target(path, current_scope, target_scope), current_scope, target_scope))

    if not misplaced:
        print("未发现放错角色目录的记忆文件。")
        return 0

    print(f"发现 {len(misplaced)} 个放错角色目录的记忆文件：\n")
    for src, dst, cur, tgt in misplaced:
        print(f"  {src.relative_to(PROJECT_ROOT)}")
        print(f"    -> {dst.relative_to(PROJECT_ROOT)}   [{cur} -> {tgt}]")

    if not args.apply:
        print("\n[dry-run] 未修改任何文件。确认无误后加 --apply 执行迁移。")
        return 0

    moved = 0
    for src, dst, cur, tgt in misplaced:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            backup = dst.with_suffix(dst.suffix + f".bak-{datetime.now():%Y%m%d%H%M%S}")
            shutil.move(str(dst), str(backup))
            print(f"  目标已存在，先备份: {backup.name}")
        shutil.move(str(src), str(dst))
        moved += 1
        print(f"  已迁移 [{cur} -> {tgt}]: {dst.relative_to(PROJECT_ROOT)}")

    print(f"\n迁移完成，共 {moved} 个文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
