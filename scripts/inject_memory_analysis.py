# -*- coding: utf-8 -*-
"""
注入式内存分析脚本
通过在主进程中执行代码来分析内存泄漏
"""

import gc
import sys
from collections import defaultdict
from datetime import datetime


def analyze_list_sources():
    """分析list对象的来源"""
    print("\n" + "="*80)
    print("List 对象来源分析")
    print("="*80)
    
    gc.collect()
    
    # 统计大型list的持有者
    list_holders = defaultdict(lambda: {'count': 0, 'total_elements': 0, 'examples': []})
    
    for obj in gc.get_objects():
        if isinstance(obj, list) and len(obj) > 50:
            referrers = gc.get_referrers(obj)
            for ref in referrers[:1]:
                holder_type = type(ref).__name__
                list_holders[holder_type]['count'] += 1
                list_holders[holder_type]['total_elements'] += len(obj)
                
                # 记录示例
                if len(list_holders[holder_type]['examples']) < 3:
                    # 追踪更上层来源
                    parents = gc.get_referrers(ref)
                    parent_types = [type(p).__name__ for p in parents[:2]]
                    
                    list_holders[holder_type]['examples'].append({
                        'size': len(obj),
                        'repr': str(ref)[:100],
                        'parents': parent_types
                    })
    
    # 按持有元素总数排序
    sorted_holders = sorted(list_holders.items(), key=lambda x: x[1]['total_elements'], reverse=True)
    
    print("\n按持有元素总数排序:")
    print("-"*80)
    for holder_type, info in sorted_holders[:15]:
        print(f"\n{holder_type}:")
        print(f"  持有list数: {info['count']}")
        print(f"  总元素数: {info['total_elements']}")
        if info['examples']:
            print(f"  示例:")
            for i, ex in enumerate(info['examples'][:2]):
                print(f"    [{i+1}] size={ex['size']}, repr={ex['repr'][:60]}...")
                print(f"        parents: {ex['parents']}")
    
    return list_holders


def analyze_dict_sources():
    """分析dict对象的来源"""
    print("\n" + "="*80)
    print("Dict 对象来源分析")
    print("="*80)
    
    gc.collect()
    
    # 统计大型dict的持有者
    dict_holders = defaultdict(lambda: {'count': 0, 'total_keys': 0, 'examples': []})
    
    for obj in gc.get_objects():
        if isinstance(obj, dict) and len(obj) > 100:
            referrers = gc.get_referrers(obj)
            for ref in referrers[:1]:
                holder_type = type(ref).__name__
                dict_holders[holder_type]['count'] += 1
                dict_holders[holder_type]['total_keys'] += len(obj)
                
                # 记录示例
                if len(dict_holders[holder_type]['examples']) < 3:
                    dict_holders[holder_type]['examples'].append({
                        'size': len(obj),
                        'repr': str(ref)[:100],
                        'keys_sample': list(obj.keys())[:5]
                    })
    
    # 按持有键总数排序
    sorted_holders = sorted(dict_holders.items(), key=lambda x: x[1]['total_keys'], reverse=True)
    
    print("\n按持有键总数排序:")
    print("-"*80)
    for holder_type, info in sorted_holders[:15]:
        print(f"\n{holder_type}:")
        print(f"  持有dict数: {info['count']}")
        print(f"  总键数: {info['total_keys']}")
        if info['examples']:
            print(f"  示例:")
            for i, ex in enumerate(info['examples'][:2]):
                print(f"    [{i+1}] size={ex['size']}, keys_sample={ex['keys_sample']}")
    
    return dict_holders


def trace_specific_object(target_type='list', min_size=1000):
    """追踪特定类型的大型对象"""
    print(f"\n" + "="*80)
    print(f"追踪大型 {target_type} 对象 (size > {min_size})")
    print("="*80)
    
    gc.collect()
    
    found = 0
    for obj in gc.get_objects():
        if isinstance(obj, list) and target_type == 'list' and len(obj) > min_size:
            found += 1
            if found > 5:
                break
                
            print(f"\n--- Large list (size={len(obj)}) ---")
            
            # 获取直接引用者
            referrers = gc.get_referrers(obj)
            print(f"直接引用者: {len(referrers)}")
            
            for i, ref in enumerate(referrers[:3]):
                ref_type = type(ref).__name__
                print(f"  [{i+1}] {ref_type}: {str(ref)[:80]}")
                
                # 追踪上层
                parents = gc.get_referrers(ref)
                for j, parent in enumerate(parents[:2]):
                    print(f"       <- {type(parent).__name__}: {str(parent)[:60]}")
        
        elif isinstance(obj, dict) and target_type == 'dict' and len(obj) > min_size:
            found += 1
            if found > 5:
                break
                
            print(f"\n--- Large dict (size={len(obj)}) ---")
            
            # 获取直接引用者
            referrers = gc.get_referrers(obj)
            print(f"直接引用者: {len(referrers)}")
            
            for i, ref in enumerate(referrers[:3]):
                ref_type = type(ref).__name__
                print(f"  [{i+1}] {ref_type}: {str(ref)[:80]}")


def find_accumulation_pattern():
    """找出累积模式"""
    print("\n" + "="*80)
    print("对象累积模式分析")
    print("="*80)
    
    gc.collect()
    
    # 分析哪些类型的对象持有最多的子对象
    container_stats = defaultdict(lambda: {'child_count': 0, 'instance_count': 0})
    
    for obj in gc.get_objects():
        if isinstance(obj, (list, dict, set, tuple)):
            children = 0
            if isinstance(obj, (list, tuple)):
                children = len(obj)
            elif isinstance(obj, (dict, set)):
                children = len(obj)
            
            if children > 0:
                type_name = type(obj).__name__
                container_stats[type_name]['child_count'] += children
                container_stats[type_name]['instance_count'] += 1
    
    print("\n容器类型统计:")
    print("-"*60)
    for type_name, stats in sorted(container_stats.items(), key=lambda x: x[1]['child_count'], reverse=True):
        avg = stats['child_count'] / stats['instance_count'] if stats['instance_count'] > 0 else 0
        print(f"{type_name:15s}: instances={stats['instance_count']:>8d}, total_children={stats['child_count']:>10d}, avg={avg:.1f}")


if __name__ == "__main__":
    print("内存泄漏深度分析 (注入模式)")
    print("="*80)
    print(f"分析时间: {datetime.now()}")
    print(f"Python版本: {sys.version}")
    print(f"GC对象总数: {len(gc.get_objects())}")
    
    # 1. 分析list来源
    list_holders = analyze_list_sources()
    
    # 2. 分析dict来源
    dict_holders = analyze_dict_sources()
    
    # 3. 追踪大型list
    trace_specific_object('list', 1000)
    
    # 4. 追踪大型dict
    trace_specific_object('dict', 2000)
    
    # 5. 分析累积模式
    find_accumulation_pattern()
    
    print("\n" + "="*80)
    print("分析完成")
    print("="*80)
