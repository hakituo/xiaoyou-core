# -*- coding: utf-8 -*-
"""
追踪 cell 对象的来源
cell 对象是函数闭包的一部分，持有对外部变量的引用
"""

import gc
import sys
from collections import defaultdict


def trace_cell_sources():
    """追踪 cell 对象的来源函数"""
    print("="*80)
    print("Cell 对象来源追踪")
    print("="*80)
    
    gc.collect()
    
    # 统计 cell 对象引用的函数
    cell_functions = defaultdict(lambda: {'count': 0, 'list_sizes': []})
    
    for obj in gc.get_objects():
        if isinstance(obj, list) and len(obj) > 0:
            # 检查是否被 cell 引用
            referrers = gc.get_referrers(obj)
            for ref in referrers:
                if type(ref).__name__ == 'cell':
                    # 找到引用这个 cell 的函数
                    cell_referrers = gc.get_referrers(ref)
                    for cell_ref in cell_referrers:
                        if callable(cell_ref):
                            func_name = getattr(cell_ref, '__qualname__', str(cell_ref))
                            cell_functions[func_name]['count'] += 1
                            cell_functions[func_name]['list_sizes'].append(len(obj))
                        elif isinstance(cell_ref, (list, tuple)):
                            # 继续追踪
                            nested_referrers = gc.get_referrers(cell_ref)
                            for nested in nested_referrers:
                                if callable(nested):
                                    func_name = getattr(nested, '__qualname__', str(nested))
                                    cell_functions[func_name]['count'] += 1
                                    cell_functions[func_name]['list_sizes'].append(len(obj))
    
    # 按持有 list 数量排序
    sorted_funcs = sorted(cell_functions.items(), key=lambda x: x[1]['count'], reverse=True)
    
    print("\n持有最多 list 的函数闭包:")
    print("-"*80)
    for func_name, info in sorted_funcs[:20]:
        avg_size = sum(info['list_sizes']) / len(info['list_sizes']) if info['list_sizes'] else 0
        total_elements = sum(info['list_sizes'])
        print(f"\n{func_name}:")
        print(f"  闭包数: {info['count']}")
        print(f"  平均 list 大小: {avg_size:.1f}")
        print(f"  总元素数: {total_elements}")
    
    return cell_functions


def trace_large_list_holders():
    """追踪大型 list 的持有者"""
    print("\n" + "="*80)
    print("大型 List 持有者追踪")
    print("="*80)
    
    gc.collect()
    
    large_holders = defaultdict(lambda: {'count': 0, 'total_elements': 0, 'examples': []})
    
    for obj in gc.get_objects():
        if isinstance(obj, list) and len(obj) > 100:
            referrers = gc.get_referrers(obj)
            for ref in referrers[:1]:
                ref_type = type(ref).__name__
                ref_repr = str(ref)[:80]
                
                large_holders[ref_type]['count'] += 1
                large_holders[ref_type]['total_elements'] += len(obj)
                
                if len(large_holders[ref_type]['examples']) < 3:
                    large_holders[ref_type]['examples'].append({
                        'size': len(obj),
                        'repr': ref_repr
                    })
    
    sorted_holders = sorted(large_holders.items(), key=lambda x: x[1]['total_elements'], reverse=True)
    
    print("\n持有大型 list 的对象类型:")
    print("-"*80)
    for holder_type, info in sorted_holders[:15]:
        print(f"\n{holder_type}:")
        print(f"  持有 list 数: {info['count']}")
        print(f"  总元素数: {info['total_elements']}")
        if info['examples']:
            print(f"  示例:")
            for ex in info['examples'][:2]:
                print(f"    size={ex['size']}, repr={ex['repr'][:60]}...")


def analyze_dict_holdings():
    """分析 dict 的持有情况"""
    print("\n" + "="*80)
    print("Dict 持有情况分析")
    print("="*80)
    
    gc.collect()
    
    dict_holders = defaultdict(lambda: {'count': 0, 'total_keys': 0, 'key_patterns': []})
    
    for obj in gc.get_objects():
        if isinstance(obj, dict) and len(obj) > 50:
            referrers = gc.get_referrers(obj)
            for ref in referrers[:1]:
                ref_type = type(ref).__name__
                
                dict_holders[ref_type]['count'] += 1
                dict_holders[ref_type]['total_keys'] += len(obj)
                
                # 记录 key 模式
                keys = list(obj.keys())[:5]
                if len(dict_holders[ref_type]['key_patterns']) < 5:
                    dict_holders[ref_type]['key_patterns'].append(keys)
    
    sorted_holders = sorted(dict_holders.items(), key=lambda x: x[1]['total_keys'], reverse=True)
    
    print("\n持有大型 dict 的对象类型:")
    print("-"*80)
    for holder_type, info in sorted_holders[:15]:
        print(f"\n{holder_type}:")
        print(f"  持有 dict 数: {info['count']}")
        print(f"  总键数: {info['total_keys']}")
        if info['key_patterns']:
            print(f"  Key 示例: {info['key_patterns'][0][:3]}")


def find_specific_patterns():
    """查找特定模式"""
    print("\n" + "="*80)
    print("特定模式查找")
    print("="*80)
    
    gc.collect()
    
    # 查找可能的缓存对象
    cache_candidates = []
    
    for obj in gc.get_objects():
        if isinstance(obj, dict):
            # 检查是否是缓存相关的 dict
            keys = list(obj.keys()) if obj else []
            if any(k in ['cache', '_cache', 'data', '_data', 'history', '_history', 'items', '_items'] for k in keys):
                cache_candidates.append({
                    'type': type(obj).__name__,
                    'size': len(obj),
                    'keys': keys[:5],
                    'referrers': len(gc.get_referrers(obj))
                })
    
    if cache_candidates:
        print("\n可能的缓存对象:")
        print("-"*80)
        for i, candidate in enumerate(cache_candidates[:10]):
            print(f"\n[{i+1}] type={candidate['type']}, size={candidate['size']}, referrers={candidate['referrers']}")
            print(f"    keys: {candidate['keys']}")


if __name__ == "__main__":
    print("内存泄漏深度追踪")
    print("="*80)
    
    # 1. 追踪 cell 对象来源
    cell_functions = trace_cell_sources()
    
    # 2. 追踪大型 list 持有者
    trace_large_list_holders()
    
    # 3. 分析 dict 持有情况
    analyze_dict_holdings()
    
    # 4. 查找特定模式
    find_specific_patterns()
    
    print("\n" + "="*80)
    print("追踪完成")
    print("="*80)
