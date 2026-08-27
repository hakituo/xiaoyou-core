#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
立即执行蒸馏测试脚本

用法：
    python tests/test_distillation_now.py              # 蒸馏所有角色
    python tests/test_distillation_now.py --user aveline  # 只蒸馏 aveline
    python tests/test_distillation_now.py --user ling     # 只蒸馏 ling
    python tests/test_distillation_now.py --dry-run       # 只查看待蒸馏记忆，不实际执行
"""

import os
import sys
import time
import asyncio
import argparse

# 添加项目根目录到 path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from memory.weighted_memory_manager import get_weighted_memory_manager
from memory.nightly_processor import NightlyProcessor, DEFAULT_NIGHTLY_CONFIG


def count_undistilled_memories(user_id: str) -> tuple:
    """统计用户的未蒸馏记忆数量"""
    manager = get_weighted_memory_manager(user_id)
    undistilled = []
    total = 0

    with manager.lock:
        total = len(manager.weighted_memories)
        for mid, msg in manager.weighted_memories.items():
            if not msg.get("is_distilled"):
                undistilled.append({
                    "id": mid,
                    "content": msg.get("content", "")[:80] + "..." if len(msg.get("content", "")) > 80 else msg.get("content", ""),
                    "timestamp": msg.get("timestamp", 0),
                    "age_hours": (time.time() - msg.get("timestamp", 0)) / 3600
                })

    return total, undistilled


async def distill_user(user_id: str, dry_run: bool = False):
    """对单个用户执行蒸馏"""
    print(f"\n{'='*60}")
    print(f"用户: {user_id}")
    print(f"{'='*60}")

    # 统计待蒸馏记忆
    total, undistilled = count_undistilled_memories(user_id)
    print(f"加权记忆总数: {total}")
    print(f"待蒸馏记忆数: {len(undistilled)}")

    if not undistilled:
        print("✓ 没有待蒸馏的记忆")
        return

    # 显示待蒸馏记忆
    print(f"\n待蒸馏记忆列表 (前10条):")
    for i, mem in enumerate(undistilled[:10]):
        print(f"  {i+1}. [{mem['id']}] ({mem['age_hours']:.1f}小时前)")
        print(f"     {mem['content']}")

    if dry_run:
        print(f"\n[DRY RUN] 不实际执行蒸馏")
        return

    # 执行蒸馏
    print(f"\n开始蒸馏...")
    manager = get_weighted_memory_manager(user_id)

    # 创建 NightlyProcessor 实例
    config = DEFAULT_NIGHTLY_CONFIG.copy()
    config["auto_run"] = False
    config["distillation_threshold_hours"] = 0  # 蒸馏所有未蒸馏的记忆
    config["max_distill_per_night"] = 20  # 限制数量，避免测试时间太长

    processor = NightlyProcessor(config=config)

    try:
        distilled_count = await processor._distill_memories_async(user_id, manager)
        print(f"\n✓ 蒸馏完成！成功蒸馏 {distilled_count} 条记忆")

        # 再次统计
        total_after, undistilled_after = count_undistilled_memories(user_id)
        print(f"蒸馏后待蒸馏记忆数: {len(undistilled_after)}")

        # 显示蒸馏结果示例
        if distilled_count > 0:
            print(f"\n蒸馏结果示例:")
            with manager.lock:
                count = 0
                for mid, msg in manager.weighted_memories.items():
                    if msg.get("is_distilled") and count < 3:
                        print(f"  ID: {mid}")
                        print(f"  梗概: {msg.get('distilled_summary', 'N/A')}")
                        print(f"  关键词: {msg.get('distilled_keywords', [])}")
                        print()
                        count += 1

    except Exception as e:
        print(f"\n✗ 蒸馏失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        processor.stop()


async def main():
    parser = argparse.ArgumentParser(description="立即执行蒸馏测试")
    parser.add_argument("--user", type=str, choices=["aveline", "ling", "all"], default="all",
                       help="指定用户 (aveline/ling/all)")
    parser.add_argument("--dry-run", action="store_true", help="只查看待蒸馏记忆，不实际执行")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("蒸馏测试脚本")
    print("="*60)
    print(f"模式: {'DRY RUN (只查看)' if args.dry_run else '实际执行蒸馏'}")

    users = []
    if args.user == "all":
        users = ["aveline", "ling"]
    else:
        users = [args.user]

    for user_id in users:
        await distill_user(user_id, dry_run=args.dry_run)

    print("\n" + "="*60)
    print("测试完成")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
