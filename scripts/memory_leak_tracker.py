# -*- coding: utf-8 -*-
"""
内存泄漏追踪器
在内存增长时自动抓取调用栈，定位泄漏源头
"""

import gc
import sys
import time
import tracemalloc
import threading
from collections import defaultdict
from datetime import datetime


class MemoryLeakTracker:
    """内存泄漏追踪器"""
    
    def __init__(self):
        self.snapshots = []
        self.growth_points = []
        self.tracking = False
        self._lock = threading.Lock()
        
    def start(self, top_n=25):
        """开始追踪"""
        tracemalloc.start(top_n)
        self.tracking = True
        self._last_snapshot = tracemalloc.take_snapshot()
        self._last_rss = self._get_rss_mb()
        self._last_time = time.time()
        print(f"[MemoryLeakTracker] 开始追踪，top_n={top_n}")
        
    def stop(self):
        """停止追踪"""
        self.tracking = False
        tracemalloc.stop()
        print("[MemoryLeakTracker] 停止追踪")
        
    def _get_rss_mb(self):
        """获取当前RSS内存"""
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    
    def check_growth(self, threshold_mb=10):
        """检查内存增长，如果超过阈值则记录调用栈"""
        if not self.tracking:
            return None
            
        current_snapshot = tracemalloc.take_snapshot()
        current_rss = self._get_rss_mb()
        current_time = time.time()
        
        delta_mb = current_rss - self._last_rss
        delta_time = current_time - self._last_time
        
        if delta_mb > threshold_mb:
            # 计算差异
            stats = current_snapshot.compare_to(self._last_snapshot, 'lineno')
            
            growth_info = {
                'timestamp': datetime.now().isoformat(),
                'delta_mb': round(delta_mb, 2),
                'current_rss_mb': round(current_rss, 2),
                'delta_time_sec': round(delta_time, 1),
                'top_allocations': []
            }
            
            # 记录增长最多的分配点
            for stat in stats[:10]:
                if stat.size_diff > 0:
                    growth_info['top_allocations'].append({
                        'file': stat.traceback[0].filename if stat.traceback else 'unknown',
                        'line': stat.traceback[0].lineno if stat.traceback else 0,
                        'size_diff_kb': round(stat.size_diff / 1024, 2),
                        'count_diff': stat.count_diff,
                        'frame': str(stat.traceback[0]) if stat.traceback else 'unknown'
                    })
            
            self.growth_points.append(growth_info)
            
            print(f"\n{'='*80}")
            print(f"[{growth_info['timestamp']}] 内存增长检测: +{delta_mb:.2f} MB")
            print(f"{'='*80}")
            print(f"当前RSS: {current_rss:.2f} MB")
            print(f"\nTop 内存分配增长点:")
            for alloc in growth_info['top_allocations'][:5]:
                print(f"  {alloc['file']}:{alloc['line']}")
                print(f"    增长: +{alloc['size_diff_kb']:.2f} KB ({alloc['count_diff']} objects)")
            print(f"{'='*80}\n")
            
            # 更新基准
            self._last_snapshot = current_snapshot
            self._last_rss = current_rss
            self._last_time = current_time
            
            return growth_info
        
        return None
    
    def get_report(self):
        """获取报告"""
        return {
            'growth_points_count': len(self.growth_points),
            'growth_points': self.growth_points[-20:]  # 最近20次
        }


def analyze_gc_objects():
    """分析GC对象类型分布"""
    print("\n" + "="*80)
    print("GC 对象分析")
    print("="*80)
    
    gc.collect()
    
    # 统计对象类型
    type_counts = defaultdict(int)
    type_sizes = defaultdict(int)
    
    for obj in gc.get_objects():
        type_name = type(obj).__name__
        type_counts[type_name] += 1
        try:
            type_sizes[type_name] += sys.getsizeof(obj, 0)
        except:
            pass
    
    # 按数量排序
    print("\n按数量排序 (Top 20):")
    print("-"*60)
    for type_name, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:20]:
        size_mb = type_sizes[type_name] / (1024*1024)
        print(f"  {type_name:30s} {count:>10d} {size_mb:>10.2f} MB")
    
    # 按大小排序
    print("\n按大小排序 (Top 20):")
    print("-"*60)
    for type_name, size in sorted(type_sizes.items(), key=lambda x: x[1], reverse=True)[:20]:
        count = type_counts[type_name]
        size_mb = size / (1024*1024)
        print(f"  {type_name:30s} {count:>10d} {size_mb:>10.2f} MB")
    
    return type_counts, type_sizes


def find_list_accumulators():
    """查找累积大量list的对象"""
    print("\n" + "="*80)
    print("查找累积大量 list 的容器对象")
    print("="*80)
    
    gc.collect()
    
    # 找出所有包含大量list的容器
    large_containers = []
    
    for obj in gc.get_objects():
        if isinstance(obj, (list, dict, set)):
            if isinstance(obj, list) and len(obj) > 1000:
                large_containers.append({
                    'type': 'list',
                    'size': len(obj),
                    'id': id(obj),
                    'referrers': len(gc.get_referrers(obj))
                })
            elif isinstance(obj, dict) and len(obj) > 1000:
                large_containers.append({
                    'type': 'dict',
                    'size': len(obj),
                    'id': id(obj),
                    'referrers': len(gc.get_referrers(obj))
                })
    
    # 按大小排序
    large_containers.sort(key=lambda x: x['size'], reverse=True)
    
    print(f"\n找到 {len(large_containers)} 个大型容器 (>1000元素)")
    print("-"*60)
    for item in large_containers[:20]:
        print(f"  {item['type']:6s} size={item['size']:>8d} referrers={item['referrers']}")
    
    # 追踪这些容器的来源
    print("\n追踪大型list的来源...")
    print("-"*60)
    
    for obj in gc.get_objects():
        if isinstance(obj, list) and len(obj) > 5000:
            referrers = gc.get_referrers(obj)
            if referrers:
                print(f"\nlist size={len(obj)}, referrers={len(referrers)}")
                for ref in referrers[:3]:
                    print(f"  <- {type(ref).__name__}: {str(ref)[:100]}")
                    # 再追踪一层
                    ref2_list = gc.get_referrers(ref)
                    for ref2 in ref2_list[:2]:
                        print(f"    <- {type(ref2).__name__}: {str(ref2)[:80]}")


def snapshot_all_lists():
    """快照所有list对象的调用栈"""
    print("\n" + "="*80)
    print("List 对象调用栈快照")
    print("="*80)
    
    # 使用tracemalloc获取list分配的调用栈
    snapshot = tracemalloc.take_snapshot()
    
    # 过滤出list相关的分配
    list_stats = []
    for stat in snapshot.statistics('traceback'):
        # 检查调用栈中是否有list相关操作
        for frame in stat.traceback:
            if 'list' in str(frame).lower() or 'append' in str(frame).lower():
                list_stats.append(stat)
                break
    
    print(f"\n找到 {len(list_stats)} 个list相关分配点")
    print("-"*60)
    
    for stat in list_stats[:15]:
        print(f"\n总大小: {stat.size / 1024:.2f} KB, 数量: {stat.count}")
        for frame in stat.traceback[:5]:
            print(f"  {frame}")


if __name__ == "__main__":
    print("内存泄漏深度分析")
    print("="*80)
    
    # 1. 分析GC对象
    type_counts, type_sizes = analyze_gc_objects()
    
    # 2. 查找累积大量list的对象
    find_list_accumulators()
    
    # 3. 如果命令行参数指定，启动追踪器
    if "--track" in sys.argv:
        tracker = MemoryLeakTracker()
        tracker.start()
        
        print("\n追踪器已启动，等待内存增长...")
        print("按 Ctrl+C 停止")
        
        try:
            while True:
                tracker.check_growth(threshold_mb=50)
                time.sleep(10)
        except KeyboardInterrupt:
            tracker.stop()
            report = tracker.get_report()
            print(f"\n追踪报告: 检测到 {report['growth_points_count']} 次增长")
