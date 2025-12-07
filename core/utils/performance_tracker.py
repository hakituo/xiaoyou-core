#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
性能统计工具类，用于统一各模块的性能监控
"""
from typing import Dict, Any, Union
import time


class PerformanceTracker:
    """
    性能统计跟踪器，提供统一的性能监控功能
    可用于模型推理、图像处理、语音处理等各模块的性能统计
    """
    
    def __init__(self, name: str = "default"):
        """
        初始化性能统计跟踪器
        
        Args:
            name: 跟踪器名称，用于区分不同模块
        """
        self.name = name
        self._stats = {
            'total_operations': 0,
            'total_time': 0.0,
            'avg_time': 0.0,
            'peak_memory': 0.0,
            'total_errors': 0
        }
        self._start_time = None
    
    def start_tracking(self):
        """
        开始跟踪操作时间
        """
        self._start_time = time.time()
    
    def end_tracking(self, error_occurred: bool = False, memory_used: float = None) -> float:
        """
        结束跟踪，更新性能统计
        
        Args:
            error_occurred: 是否发生错误
            memory_used: 使用的内存（可选）
            
        Returns:
            操作耗时（秒）
        """
        if self._start_time is None:
            return 0.0
        
        execution_time = time.time() - self._start_time
        self._start_time = None
        
        # 更新统计信息
        self._stats['total_operations'] += 1
        self._stats['total_time'] += execution_time
        
        # 计算平均时间
        if self._stats['total_operations'] > 0:
            self._stats['avg_time'] = (
                self._stats['total_time'] / self._stats['total_operations']
            )
        
        # 更新峰值内存
        if memory_used is not None and memory_used > self._stats['peak_memory']:
            self._stats['peak_memory'] = memory_used
        
        # 更新错误计数
        if error_occurred:
            self._stats['total_errors'] += 1
        
        return execution_time
    
    def get_stats(self) -> Dict[str, Union[int, float]]:
        """
        获取当前性能统计数据的副本
        
        Returns:
            包含性能统计信息的字典
        """
        return self._stats.copy()
    
    def reset(self):
        """
        重置性能统计数据
        """
        self._stats = {
            'total_operations': 0,
            'total_time': 0.0,
            'avg_time': 0.0,
            'peak_memory': 0.0,
            'total_errors': 0
        }
        self._start_time = None
    
    def __str__(self) -> str:
        """
        返回性能统计的字符串表示
        """
        stats = self.get_stats()
        return (
            f"PerformanceTracker({self.name}): "
            f"ops={stats['total_operations']}, "
            f"avg_time={stats['avg_time']:.4f}s, "
            f"peak_mem={stats['peak_memory']:.2f}MB, "
            f"errors={stats['total_errors']}"
        )