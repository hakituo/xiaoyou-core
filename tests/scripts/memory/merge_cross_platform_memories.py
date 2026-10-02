#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把同一角色分散在各平台的记忆合并成一份，实现记忆全平台通用。

背景
----
修复前，同一角色的记忆按 conversation_id 分成多份：
QQ 私聊一份、网页一份、安卓 App 一份（``web_core_ling.json``、``mobile_user`` 等）。
结果同一个角色在每个平台都只记得一部分。

``resolve_memory_user_id`` 现在会把同一角色的会话统一归一到
``shared__scope__<scope>``，但**历史上已经写下的多份文件不会自动合并**，
需要本脚本搬一次：把能归一到同一主体的文件合并去重，写进那个主体的文件。

合并规则
--------
- 短期记忆（list）：按 id 去重，按时间戳排序，保留最近 ``SHORT_TERM_LIMIT`` 条
- 加权记忆（dict）：``weighted_memories`` 按 id 去重；``topic_weights`` /
  ``emotion_memory_map`` 同键取较大值；``last_updated`` 取最新
- 群聊 / 双角色互聊 / 外部平台 / 解析不出角色的会话**不参与合并**，保持独立

用法
----
    # 只显示合并计划，不动任何文件（默认）
    venv_core/Scripts/python.exe tests/scripts/memory/merge_cross_platform_memories.py

    # 实际合并（合并前会把参与合并的原文件备份到 companion_data/backups/）
    venv_core/Scripts/python.exe tests/scripts/memory/merge_cross_platform_memories.py --apply
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.utils.data.scope_registry import resolve_memory_user_id  # noqa: E402

COMPANION_DIR = PROJECT_ROOT / "companion_data"
# 短期记忆容量上限，与记忆系统默认保持一致，避免合并后无限膨胀
SHORT_TERM_LIMIT = 60

# 记忆文件的形态：<uid>_short.json / <uid>_weighted.json
_SUFFIX_RE = re.compile(r"_(short|weighted|long_term)\.json$", re.IGNORECASE)


def _extract_uid(path: Path) -> str:
    """从记忆文件名反解出记忆主体 ID（即 uid）。"""
    stem = _SUFFIX_RE.sub("", path.name)
    if stem.endswith(".json"):
        stem = stem[: -len(".json")]
    return stem


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _entry_key(item: Any) -> str:
    """记忆条目的去重键：优先 id，回退 内容+时间戳。"""
    if not isinstance(item, dict):
        return json.dumps(item, ensure_ascii=False, sort_keys=True)
    ident = str(item.get("id") or "").strip()
    if ident:
        return ident
    return f"{item.get('content', '')}|{item.get('timestamp', '')}"


def _ts(item: Any) -> float:
    if isinstance(item, dict):
        for key in ("timestamp", "created_at", "last_access_time"):
            value = item.get(key)
            if isinstance(value, (int, float)):
                return float(value)
    return 0.0


def _merge_short_term(groups: list[Path]) -> list:
    merged: dict[str, dict] = {}
    for path in groups:
        data = _load(path)
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            key = _entry_key(item)
            old = merged.get(key)
            # 同键保留时间戳较新的那条
            if old is None or _ts(item) >= _ts(old):
                merged[key] = item
    result = sorted(merged.values(), key=_ts)
    return result[-SHORT_TERM_LIMIT:]


def _merge_weighted(groups: list[Path]) -> dict:
    memories: dict[str, dict] = {}
    topic_weights: dict[str, float] = {}
    emotion_map: dict[str, Any] = {}
    last_updated = 0.0
    for path in groups:
        data = _load(path)
        if not isinstance(data, dict):
            continue
        for item in data.get("weighted_memories") or []:
            if not isinstance(item, dict):
                continue
            key = _entry_key(item)
            old = memories.get(key)
            if old is None or float(item.get("weight") or 0) >= float(old.get("weight") or 0):
                memories[key] = item
        for topic, weight in (data.get("topic_weights") or {}).items():
            if isinstance(weight, (int, float)):
                topic_weights[topic] = max(topic_weights.get(topic, 0.0), float(weight))
        for emotion, payload in (data.get("emotion_memory_map") or {}).items():
            emotion_map.setdefault(str(emotion), payload)
        updated = data.get("last_updated")
        if isinstance(updated, (int, float)):
            last_updated = max(last_updated, float(updated))
    return {
        "weighted_memories": sorted(memories.values(), key=_ts),
        "topic_weights": topic_weights,
        "emotion_memory_map": emotion_map,
        "last_updated": last_updated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="实际执行合并；默认只显示计划")
    args = parser.parse_args()

    # 1) 收集所有记忆文件，按「归一后的目标主体」分组
    #    key = (目标文件所在目录, 目标 uid, 类型 short/weighted)
    buckets: dict[tuple[Path, str, str], list[Path]] = {}
    for role_dir in sorted(COMPANION_DIR.glob("*_data")):
        memories_dir = role_dir / "memories"
        if not memories_dir.exists():
            continue
        for path in sorted(memories_dir.rglob("*")):
            if not path.is_file():
                continue
            match = _SUFFIX_RE.search(path.name)
            if not match:
                continue
            kind = match.group(1).lower()
            if kind not in {"short", "weighted"}:
                continue
            uid = _extract_uid(path)
            if not uid:
                continue
            target_uid = resolve_memory_user_id(uid)
            if target_uid == uid:
                continue  # 不需要合并（已是目标主体，或不应参与合并）
            buckets.setdefault((path.parent, target_uid, kind), []).append(path)

    # 已经存在目标文件时，也要把它作为合并输入之一
    for (parent, target_uid, kind), sources in list(buckets.items()):
        target = parent / f"{target_uid}_{kind}.json"
        if target.exists() and target not in sources:
            sources.append(target)

    if not buckets:
        print("没有需要合并的记忆文件（各平台记忆主体已统一）。")
        return 0

    print(f"合并计划：{len(buckets)} 个目标主体\n")
    for (parent, target_uid, kind), sources in sorted(buckets.items(), key=lambda kv: str(kv[0][0])):
        print(f"  -> {target_uid}_{kind}.json  （{parent.relative_to(PROJECT_ROOT)}）")
        for src in sources:
            print(f"       + {src.name}")

    if not args.apply:
        print("\n[dry-run] 未修改任何文件。确认无误后加 --apply 执行（会自动备份原文件）。")
        return 0

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = COMPANION_DIR / "backups" / f"pre_merge_{stamp}"
    merged_count = 0
    for (parent, target_uid, kind), sources in buckets.items():
        target = parent / f"{target_uid}_{kind}.json"
        for src in sources:
            rel = src.relative_to(COMPANION_DIR)
            dest = backup_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                shutil.copy2(str(src), str(dest))
        payload = _merge_short_term(sources) if kind == "short" else _merge_weighted(sources)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        merged_count += 1
        # 备份完成后再删除被合并掉的历史文件
        for src in sources:
            if src.exists() and src != target:
                src.unlink()
        print(f"  已合并 {len(sources)} 份 -> {target.relative_to(PROJECT_ROOT)}")

    print(f"\n完成：{merged_count} 个记忆主体已合并。原文件备份于 {backup_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
