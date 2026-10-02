#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查内存中的蒸馏状态"""
import sys
import os
import time
import asyncio

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from memory.weighted_memory_manager import get_weighted_memory_manager

async def check():
    user_id = 'aveline'
    manager = get_weighted_memory_manager(user_id)
    
    # 等待加载完成
    time.sleep(2)
    
    # 统计
    with manager.lock:
        total = len(manager.weighted_memories)
        distilled = sum(1 for m in manager.weighted_memories.values() if m.get('is_distilled'))
        undistilled = total - distilled
        
        # 找一个已蒸馏的
        found = False
        for mid, msg in manager.weighted_memories.items():
            if msg.get('is_distilled'):
                print(f"找到已蒸馏记忆: {mid[:16]}...")
                summary = msg.get('summary', 'N/A')
                keywords = msg.get('keywords', [])
                content = msg.get('content', '')[:50]
                print(f"  梗概: {summary}")
                print(f"  关键词: {keywords}")
                print(f"  原文: {content}...")
                found = True
                break
        
        if not found:
            print("没有找到已蒸馏的记忆")
    
    print(f"\n内存统计: 总数={total}, 已蒸馏={distilled}, 待蒸馏={undistilled}")

asyncio.run(check())
