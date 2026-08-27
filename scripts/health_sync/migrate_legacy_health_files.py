# -*- coding: utf-8 -*-
"""把旧的逐次快照文件迁移到新的 latest.json + 事件流结构。

背景
----
旧实现每次同步写一个 ``YYYY-MM-DD_HH-MM-SS.json``，手机端 1 分钟同步一次
就是一天 1440 个文件。新结构见 ``core.services.health_sync.store``。

本脚本做三件事：
1. 按时间顺序回放所有旧快照，重建 latest.json 与事件流
2. 把旧文件移动到 ``health_sync/legacy/`` 归档（不删除，保留可回溯）
3. 打印迁移统计

用法::

    venv_core/Scripts/python.exe scripts/health_sync/migrate_legacy_health_files.py
    venv_core/Scripts/python.exe scripts/health_sync/migrate_legacy_health_files.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.services.health_sync.store import ingest_snapshot  # noqa: E402
from core.utils.data_paths import get_companion_data_dir  # noqa: E402

# 旧文件名格式：2026-08-06_12-59-32.json
LEGACY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.json$")

# 旧文件里由后端补写、不属于设备上报的字段，回放时剔除
NON_DEVICE_KEYS = {"server_timestamp"}


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移旧健康快照文件")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不改动文件")
    args = parser.parse_args()

    base = get_companion_data_dir() / "health_sync"
    if not base.exists():
        print("health_sync 目录不存在，无需迁移")
        return 0

    legacy_files = sorted(
        p for p in base.iterdir()
        if p.is_file() and LEGACY_PATTERN.match(p.name)
    )
    if not legacy_files:
        print("没有需要迁移的旧文件")
        return 0

    print(f"发现 {len(legacy_files)} 个旧快照文件")
    if args.dry_run:
        print("dry-run 模式，以下文件将被回放并归档到 health_sync/legacy/：")
        for p in legacy_files[:10]:
            print(f"  {p.name}")
        if len(legacy_files) > 10:
            print(f"  ... 另外 {len(legacy_files) - 10} 个")
        return 0

    archive = base / "legacy"
    archive.mkdir(parents=True, exist_ok=True)

    replayed = 0
    total_events = 0
    skipped = 0

    for path in legacy_files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            print(f"  [跳过] {path.name} 解析失败: {e}")
            skipped += 1
            continue

        # 旧文件用 exclude_none=False 保存，满是 null，回放时要滤掉
        cleaned = {
            k: v for k, v in payload.items()
            if v is not None and k not in NON_DEVICE_KEYS
        }
        if not cleaned:
            skipped += 1
        else:
            result = ingest_snapshot(cleaned)
            total_events += len(result.events)
            replayed += 1

        shutil.move(str(path), str(archive / path.name))

    print(f"\n迁移完成：")
    print(f"  回放快照 {replayed} 个（跳过空文件 {skipped} 个）")
    print(f"  生成事件 {total_events} 条")
    print(f"  旧文件已归档到 {archive}")
    print(f"  当前快照 {base / 'latest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
