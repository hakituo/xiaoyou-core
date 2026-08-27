#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查蒸馏结果"""
import json
import sys
import os

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# 读取一个加权记忆文件
filepath = os.path.join(ROOT_DIR, 'companion_data', 'aveline_data', 'memories', 'weighted', 'diary', 'aveline_weighted.json')

with open(filepath, 'r', encoding='utf-8') as f:
    data = json.load(f)

# 找到已蒸馏的记忆
if isinstance(data, dict):
    items = data.values()
else:
    items = data

distilled = [m for m in items if isinstance(m, dict) and m.get('is_distilled')]
print(f"总记忆数: {len(data)}")
print(f"已蒸馏数: {len(distilled)}")

if distilled:
    print("\n蒸馏结果示例:")
    for m in distilled[:2]:
        mid = m.get("id", "N/A")
        summary = m.get("distilled_summary", "N/A")
        keywords = m.get("distilled_keywords", [])
        content = m.get("content", "")[:50]
        print(f"  ID: {mid[:16]}...")
        print(f"  梗概: {summary}")
        print(f"  关键词: {keywords}")
        print(f"  原文前50字: {content}...")
        print()
else:
    print("没有找到已蒸馏的记忆")
