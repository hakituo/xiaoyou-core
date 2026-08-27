#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析当前进程的内存使用情况"""

import gc
import sys
from collections import Counter

def analyze():
    print("=== 内存对象分析 ===\n")
    
    # 触发GC
    print("触发垃圾回收...")
    collected = gc.collect()
    print(f"GC回收了 {collected} 个对象\n")
    
    # 统计对象类型
    print("统计对象类型...")
    type_counts = Counter()
    type_sizes = Counter()
    
    for obj in gc.get_objects():
        type_name = type(obj).__name__
        type_counts[type_name] += 1
        try:
            size = sys.getsizeof(obj)
            type_sizes[type_name] += size
        except:
            pass
    
    # 按数量排序输出前30
    print("\n=== 按数量排序 (Top 30) ===")
    print(f"{'类型':<30} {'数量':>10} {'大小(MB)':>10}")
    print("-" * 55)
    for type_name, count in type_counts.most_common(30):
        size_mb = type_sizes.get(type_name, 0) / (1024 * 1024)
        print(f"{type_name:<30} {count:>10} {size_mb:>10.1f}")
    
    # 按大小排序输出前20
    print("\n=== 按大小排序 (Top 20) ===")
    print(f"{'类型':<30} {'数量':>10} {'大小(MB)':>10}")
    print("-" * 55)
    for type_name, size in type_sizes.most_common(20):
        count = type_counts.get(type_name, 0)
        size_mb = size / (1024 * 1024)
        print(f"{type_name:<30} {count:>10} {size_mb:>10.1f}")
    
    # 总结
    total_objects = sum(type_counts.values())
    total_size_mb = sum(type_sizes.values()) / (1024 * 1024)
    print(f"\n=== 总计 ===")
    print(f"对象总数: {total_objects:,}")
    print(f"总大小: {total_size_mb:.1f} MB")

if __name__ == "__main__":
    analyze()
