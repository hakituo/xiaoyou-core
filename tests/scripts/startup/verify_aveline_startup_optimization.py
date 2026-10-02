#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 AvelineService 启动路径优化是否仍然生效。"""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SERVICE_PATH = PROJECT_ROOT / "core" / "services" / "aveline" / "service.py"


def main() -> None:
    source = SERVICE_PATH.read_text(encoding="utf-8")
    ast.parse(source, filename=str(SERVICE_PATH))

    checks = {
        "不再固定 sleep 2 秒": "await asyncio.sleep(2)" not in source,
        "不再预创建 default WeightedMemoryManager": "get_weighted_memory_manager" not in source,
        "ChatAgent import/构造位于 worker helper": "def _get_chat_agent_in_worker" in source,
        "ChatAgent 构造通过 asyncio.to_thread": (
            "await asyncio.to_thread(_get_chat_agent_in_worker)" in source
        ),
        "保留 memory_manager 兼容字段": "self.memory_manager = None" in source,
        "后台初始化提供分段计时": all(
            marker in source
            for marker in (
                'stage_times["character_config"]',
                'stage_times["chat_agent_construct"]',
                'stage_times["chat_agent_initialize"]',
            )
        ),
    }

    failed = [name for name, ok in checks.items() if not ok]
    for name, ok in checks.items():
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")

    if failed:
        raise SystemExit("AvelineService 启动优化验证失败: " + ", ".join(failed))

    print("AvelineService 启动优化结构验证通过。")


if __name__ == "__main__":
    main()
