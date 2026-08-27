#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
系统内存管理服务
提供系统内存监控、管理和垃圾回收。
"""

from core.utils.logger import get_logger
import gc

import threading
import time
import psutil
from typing import Dict, Any, Optional

from config.integrated_config import get_settings

logger = get_logger(__name__)


class MemoryMonitor:
    """系统内存和进程内存使用监控器"""

    def __init__(self, interval: float = 5.0):
        """初始化内存监控器

        Args:
            interval: 监控间隔（秒）
        """
        self.interval = interval
        self.process = psutil.Process()
        self.running = False
        self.monitor_thread = None

    def start(self):
        """启动内存监控"""
        if self.running:
            logger.warning("Memory monitor already running")
            return

        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("Memory monitor started")

    def stop(self):
        """停止内存监控"""
        if not self.running:
            logger.warning("Memory monitor not running")
            return

        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1.0)
        logger.info("Memory monitor stopped")

    def _monitor_loop(self):
        """监控循环"""
        while self.running:
            try:
                self.get_memory_info()
                # logger.debug(f"Memory usage: {memory_info}")
                # 可以在此添加阈值检查
            except Exception as e:
                logger.error(f"Memory monitoring error: {e}")
            time.sleep(self.interval)

    def get_memory_info(self) -> Dict[str, Any]:
        """获取当前内存使用信息

        Returns:
            包含内存使用信息的字典
        """
        process_memory = self.process.memory_info()
        system_memory = psutil.virtual_memory()

        return {
            "process_rss_mb": process_memory.rss
            / (1024 * 1024),  # 进程物理内存 (MB)
            "process_vms_mb": process_memory.vms
            / (1024 * 1024),  # 进程虚拟内存 (MB)
            "system_total_mb": system_memory.total
            / (1024 * 1024),  # 系统总内存 (MB)
            "system_available_mb": system_memory.available
            / (1024 * 1024),  # 系统可用内存 (MB)
            "system_used_percent": system_memory.percent,  # 系统内存使用百分比
        }

    def get_memory_usage(self) -> Dict[str, float]:
        """获取内存使用摘要

        Returns:
            包含进程和系统内存使用的字典
        """
        memory_info = self.get_memory_info()
        return {
            "process_usage_mb": memory_info["process_rss_mb"],
            "system_usage_percent": memory_info["system_used_percent"],
        }


class GarbageCollector:
    """自定义垃圾回收器，增强Python默认GC"""

    def __init__(self, auto_collect_interval: float = 60.0, threshold: float = 0.8):
        """初始化垃圾回收器

        Args:
            auto_collect_interval: 自动回收间隔（秒）
            threshold: 触发回收的内存使用阈值 (0.0-1.0)
        """
        self.auto_collect_interval = auto_collect_interval
        self.threshold = threshold
        self.running = False
        self.gc_thread = None
        self.stats = {
            "collect_count": 0,
            "last_collect_time": 0,
            "objects_collected": 0,
        }
        logger.info("Garbage collector initialized")

    def start(self):
        """启动自动垃圾回收"""
        if self.running:
            logger.warning("Garbage collector already running")
            return

        self.running = True
        self.gc_thread = threading.Thread(target=self._gc_loop, daemon=True)
        self.gc_thread.start()
        logger.info("Automatic garbage collection started")

    def stop(self):
        """停止自动垃圾回收"""
        if not self.running:
            logger.warning("Garbage collector not running")
            return

        self.running = False
        if self.gc_thread:
            self.gc_thread.join(timeout=1.0)
        logger.info("Automatic garbage collection stopped")

    def collect(self):
        """立即执行垃圾回收

        Returns:
            回收的对象数量
        """
        logger.info("Executing garbage collection")
        before_count = len(gc.get_objects())

        # 执行完整垃圾回收
        count0 = gc.collect(0)
        count1 = gc.collect(1)
        count2 = gc.collect(2)

        # 如果可用，清理GPU内存
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
                logger.info("GPU memory cache cleared")
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Failed to clear GPU memory: {e}")

        after_count = len(gc.get_objects())
        objects_collected = before_count - after_count

        self.stats["collect_count"] += 1
        self.stats["last_collect_time"] = time.time()
        self.stats["objects_collected"] += objects_collected

        logger.info(
            f"Garbage collection complete: Gen0({count0}), Gen1({count1}), Gen2({count2}), Total collected({objects_collected})"
        )
        return objects_collected

    def _gc_loop(self):
        """垃圾回收循环"""
        while self.running:
            try:
                # 检查内存使用，超过阈值时触发回收
                memory_percent = psutil.virtual_memory().percent / 100
                if memory_percent > self.threshold:
                    logger.warning(
                        f"Memory usage exceeded threshold ({memory_percent:.2%}), triggering GC"
                    )
                    self.collect()
            except Exception as e:
                logger.error(f"Garbage collection loop error: {e}")
            time.sleep(self.auto_collect_interval)

    def get_stats(self) -> Dict[str, Any]:
        """获取GC统计信息

        Returns:
            统计信息字典
        """
        return dict(self.stats)


class SystemMemoryManager:
    """系统内存管理器，负责管理和优化应用内存使用"""

    def __init__(self):
        """初始化系统内存管理器"""
        settings = get_settings()

        # 监控间隔默认5.0秒，可按需配置
        self.monitor = MemoryMonitor(interval=5.0)

        # 使用配置设置GC
        # 将阈值从百分比(0-100)转换为浮点数(0.0-1.0)
        gc_threshold = settings.memory.very_high_memory_threshold / 100.0

        self.gc = GarbageCollector(
            auto_collect_interval=float(settings.memory.gc_interval),
            threshold=gc_threshold,
        )
        self.resource_tracker = {}
        self.lock = threading.RLock()
        logger.info("System Memory Manager initialized")

    def start(self):
        """启动内存管理服务"""
        self.monitor.start()
        self.gc.start()
        logger.info("Memory management service started")

    def stop(self):
        """停止内存管理服务"""
        self.gc.stop()
        self.monitor.stop()
        logger.info("Memory management service stopped")

    def track_resource(
        self, resource_id: str, resource: Any, size_estimate: Optional[int] = None
    ):
        """跟踪资源使用

        Args:
            resource_id: 资源标识符
            resource: 要跟踪的资源对象
            size_estimate: 资源估计大小（字节）
        """
        with self.lock:
            self.resource_tracker[resource_id] = {
                "resource": resource,
                "size_estimate": size_estimate,
                "timestamp": time.time(),
            }
            logger.debug(f"Resource tracked: {resource_id}")

    def untrack_resource(self, resource_id: str):
        """取消跟踪资源

        Args:
            resource_id: 资源标识符
        """
        with self.lock:
            if resource_id in self.resource_tracker:
                del self.resource_tracker[resource_id]
                logger.debug(f"Resource untracked: {resource_id}")

    def get_memory_stats(self) -> Dict[str, Any]:
        """获取内存统计信息

        Returns:
            内存统计信息字典
        """
        with self.lock:
            return {
                "monitor_info": self.monitor.get_memory_info(),
                "tracked_resources": len(self.resource_tracker),
                "gc_stats": self.gc.get_stats(),
            }

    def optimize_memory(self):
        """执行内存优化"""
        logger.info("Executing memory optimization")
        # 执行垃圾回收
        self.gc.collect()


# 全局系统内存管理器实例
_system_memory_manager: Optional[SystemMemoryManager] = None


def initialize_system_memory_manager() -> SystemMemoryManager:
    """初始化全局系统内存管理器

    Returns:
        SystemMemoryManager实例
    """
    global _system_memory_manager

    if _system_memory_manager is None:
        _system_memory_manager = SystemMemoryManager()
        _system_memory_manager.start()
        logger.info("Global System Memory Manager initialized")

    return _system_memory_manager


def get_system_memory_manager() -> Optional[SystemMemoryManager]:
    """获取全局系统内存管理器实例

    Returns:
        SystemMemoryManager实例，如果未初始化则返回None
    """
    global _system_memory_manager

    if _system_memory_manager is None:
        logger.warning("System Memory Manager not initialized")
        return initialize_system_memory_manager()

    return _system_memory_manager


async def shutdown_system_memory_manager():
    """关闭全局系统内存管理器"""
    global _system_memory_manager
    if _system_memory_manager:
        _system_memory_manager.stop()
        _system_memory_manager = None
