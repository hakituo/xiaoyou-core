#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查找所有已蒸馏的记忆"""
import json
import os
import glob

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
weighted_dir = os.path.join(ROOT_DIR, 'companion_data', 'aveline_data', 'memories', 'weighted')

distilled_count = 0
total_count = 0

# 遍历所有加权记忆文件
for filepath in glob.glob(os.path.join(weighted_dir, '**', '*.json'), recursive=True):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 处理不同的数据格式
        items = []
        if isinstance(data, dict):
            items = list(data.values())
        elif isinstance(data, list):
            items = data
        
        for item in items:
            if not isinstance(item, dict):
                continue
            total_count += 1
            # 检查 is_distilled 字段
            if item.get('is_distilled'):
                distilled_count += 1
                if distilled_count <= 3:  # 只显示前3个
                    print(f"\n找到已蒸馏记忆:")
                    print(f"  文件: {os.path.relpath(filepath, ROOT_DIR)}")
                    print(f"  ID: {item.get('id', 'N/A')[:16]}...")
                    # 使用正确的字段名
                    print(f"  梗概: {item.get('summary', 'N/A')}")
                    print(f"  关键词: {item.get('keywords', [])}")
                    print(f"  原文: {item.get('content', '')[:60]}...")
    except Exception as e:
        pass

print(f"\n{'='*60}")
print(f"统计结果:")
print(f"  总记忆数: {total_count}")
print(f"  已蒸馏数: {distilled_count}")
print(f"{'='*60}")
