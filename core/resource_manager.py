#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源管理器
负责统一管理系统中的内存、CPU等资源使用
提供自动优化、监控和回收功能
"""

import os
import time
import psutil
import torch
import asyncio
import logging
from typing import Dict, Optional, List, Callable, Any
from dataclasses import dataclass
from enum import Enum, auto

logger = logging.getLogger(__name__)


class ResourceType(Enum):
    """资源类型枚举"""
    MEMORY = auto()
    CPU = auto()
    GPU_MEMORY = auto()
    DISK = auto()


class ResourcePriority(Enum):
    """资源优先级枚举"""
    HIGH = 100
    MEDIUM = 50
    LOW = 10
    IDLE = 1


class ResourceState(Enum):
    """资源状态枚举"""
    NORMAL = auto()
    WARNING = auto()
    CRITICAL = auto()
    EMERGENCY = auto()


@dataclass
class ResourceThreshold:
    """资源阈值配置"""
    warning: float  # 警告阈值
    critical: float  # 临界阈值
    emergency: float  # 紧急阈值


class ResourceMonitor:
    """资源监控器"""
    
    def __init__(self):
        self._thresholds = {
            ResourceType.MEMORY: ResourceThreshold(70.0, 85.0, 95.0),
            ResourceType.CPU: ResourceThreshold(70.0, 85.0, 95.0),
            ResourceType.GPU_MEMORY: ResourceThreshold(70.0, 85.0, 95.0),
            ResourceType.DISK: ResourceThreshold(70.0, 85.0, 95.0)
        }
        self._process = psutil.Process()
        self._last_check_time = 0
        self._check_interval = 1.0  # 检查间隔（秒）
        
    def set_threshold(self, resource_type: ResourceType, threshold: ResourceThreshold):
        """设置资源阈值"""
        self._thresholds[resource_type] = threshold
    
    def get_memory_usage(self) -> float:
        """获取系统内存使用率（百分比）"""
        return psutil.virtual_memory().percent
    
    def get_process_memory_usage(self) -> int:
        """获取当前进程内存使用（MB）"""
        return self._process.memory_info().rss // (1024 * 1024)
    
    def get_cpu_usage(self) -> float:
        """获取系统CPU使用率（百分比）"""
        return psutil.cpu_percent(interval=0.1)
    
    def get_gpu_memory_usage(self) -> Optional[float]:
        """获取GPU内存使用率（百分比）"""
        if torch.cuda.is_available():
            try:
                allocated = torch.cuda.memory_allocated()
                total = torch.cuda.get_device_properties(0).total_memory
                return (allocated / total) * 100
            except Exception as e:
                logger.warning(f"获取GPU内存使用率失败: {str(e)}")
        return None
    
    def get_disk_usage(self) -> float:
        """获取磁盘使用率（百分比）"""
        return psutil.disk_usage('/').percent
    
    def get_resource_state(self, resource_type: ResourceType) -> ResourceState:
        """获取资源状态"""
        current_time = time.time()
        
        # 实现检查频率限制
        if current_time - self._last_check_time < self._check_interval:
            return ResourceState.NORMAL
        
        self._last_check_time = current_time
        
        threshold = self._thresholds[resource_type]
        
        if resource_type == ResourceType.MEMORY:
            usage = self.get_memory_usage()
        elif resource_type == ResourceType.CPU:
            usage = self.get_cpu_usage()
        elif resource_type == ResourceType.GPU_MEMORY:
            usage = self.get_gpu_memory_usage()
            if usage is None:
                return ResourceState.NORMAL
        elif resource_type == ResourceType.DISK:
            usage = self.get_disk_usage()
        else:
            return ResourceState.NORMAL
        
        if usage >= threshold.emergency:
            return ResourceState.EMERGENCY
        elif usage >= threshold.critical:
            return ResourceState.CRITICAL
        elif usage >= threshold.warning:
            return ResourceState.WARNING
        else:
            return ResourceState.NORMAL
    
    def is_resource_pressure(self, resource_type: ResourceType) -> bool:
        """检查资源是否有压力"""
        state = self.get_resource_state(resource_type)
        return state in [ResourceState.WARNING, ResourceState.CRITICAL, ResourceState.EMERGENCY]


class ModelResource:
    """模型资源类"""
    
    def __init__(self, model_id: str, model_type: str, priority: ResourcePriority, 
                 load_func: Callable, unload_func: Callable, memory_usage_mb: int = 0):
        self.model_id = model_id
        self.model_type = model_type
        self.priority = priority
        self.load_func = load_func
        self.unload_func = unload_func
        self.memory_usage_mb = memory_usage_mb
        self.is_loaded = False
        self.last_used_time = time.time()
        self.usage_count = 0
    
    def update_usage(self):
        """更新使用信息"""
        self.last_used_time = time.time()
        self.usage_count += 1


class ResourceManager:
    """资源管理器"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        # 默认配置
        default_config = {
            'auto_optimization': True,
            'max_memory_usage_percent': 95,  # 提高内存使用率阈值，避免频繁触发紧急清理
            'max_cpu_usage_percent': 90,
            'max_gpu_memory_usage_percent': 90,
            'min_free_memory_mb': 512,  # 减少最小空闲内存要求
            'model_unload_timeout': 300,  # 模型空闲卸载超时时间（秒）
            'aggressive_cleanup_threshold': 95,  # 激进清理阈值
            'monitor_interval': 10.0,  # 增加监控间隔，减少检查频率
            'cache_size_limit_mb': 512,  # 缓存大小限制
            'auto_precision_adjust': True,  # 自动精度调整
            'low_memory_mode': False,  # 低内存模式
        }
        
        self.config = {**default_config, **(config or {})}
        self.monitor = ResourceMonitor()
        self._models: Dict[str, ModelResource] = {}
        self._lock = asyncio.Lock()
        self._is_running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._memory_cleanup_callbacks: List[Callable] = []
        self._cache_stats = {
            'hits': 0,
            'misses': 0,
            'size': 0
        }
        
        # 调整监控阈值
        self.monitor.set_threshold(
            ResourceType.MEMORY,
            ResourceThreshold(
                self.config['max_memory_usage_percent'] * 0.8,
                self.config['max_memory_usage_percent'] * 0.9,
                self.config['max_memory_usage_percent']
            )
        )
    
    async def start(self):
        """启动资源管理器"""
        async with self._lock:
            if not self._is_running:
                self._is_running = True
                self._monitor_task = asyncio.create_task(self._monitor_resources())
                logger.info("资源管理器已启动")
    
    async def stop(self):
        """停止资源管理器"""
        async with self._lock:
            if self._is_running:
                self._is_running = False
                if self._monitor_task:
                    self._monitor_task.cancel()
                    try:
                        await self._monitor_task
                    except asyncio.CancelledError:
                        pass
                logger.info("资源管理器已停止")
    
    def register_model(self, model_id: str, model_type: str, priority: ResourcePriority,
                       load_func: Callable, unload_func: Callable, memory_usage_mb: int = 0):
        """注册模型资源"""
        model = ModelResource(
            model_id=model_id,
            model_type=model_type,
            priority=priority,
            load_func=load_func,
            unload_func=unload_func,
            memory_usage_mb=memory_usage_mb
        )
        self._models[model_id] = model
        logger.info(f"模型已注册: {model_id}, 类型: {model_type}, 优先级: {priority.name}")
    
    def unregister_model(self, model_id: str):
        """注销模型资源"""
        if model_id in self._models:
            del self._models[model_id]
            logger.info(f"模型已注销: {model_id}")
    
    def register_memory_cleanup_callback(self, callback: Callable):
        """注册内存清理回调"""
        self._memory_cleanup_callbacks.append(callback)
    
    async def _monitor_resources(self):
        """资源监控任务"""
        try:
            while self._is_running:
                await asyncio.sleep(self.config['monitor_interval'])
                
                # 检查内存压力
                memory_state = self.monitor.get_resource_state(ResourceType.MEMORY)
                gpu_memory_state = self.monitor.get_resource_state(ResourceType.GPU_MEMORY)
                
                # 记录资源使用情况
                logger.debug(f"资源使用情况 - 内存: {self.monitor.get_memory_usage():.1f}%, "
                           f"进程内存: {self.monitor.get_process_memory_usage()}MB, "
                           f"CPU: {self.monitor.get_cpu_usage():.1f}%")
                
                # 根据资源状态执行不同级别的优化
                if memory_state == ResourceState.EMERGENCY or gpu_memory_state == ResourceState.EMERGENCY:
                    await self._emergency_cleanup()
                elif memory_state == ResourceState.CRITICAL or gpu_memory_state == ResourceState.CRITICAL:
                    await self._critical_cleanup()
                elif memory_state == ResourceState.WARNING or gpu_memory_state == ResourceState.WARNING:
                    await self._regular_cleanup()
                
                # 清理超时未使用的模型
                await self._cleanup_unused_models()
                
                # 清理缓存
                await self._cleanup_cache()
                
        except Exception as e:
            logger.error(f"资源监控任务异常: {str(e)}")
    
    async def _emergency_cleanup(self):
        """紧急清理模式"""
        logger.warning("进入紧急清理模式")
        
        # 1. 执行所有内存清理回调
        for callback in self._memory_cleanup_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error(f"执行内存清理回调失败: {str(e)}")
        
        # 2. 强制卸载所有非高优先级模型
        await self._unload_models_by_priority(ResourcePriority.HIGH)
        
        # 3. 清理PyTorch缓存
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, 'ipc_collect'):
                torch.cuda.ipc_collect()
        
        # 4. 清理缓存到最小
        self._cache_stats['size'] = 0
        logger.warning("紧急清理完成")
    
    async def _critical_cleanup(self):
        """临界清理模式"""
        logger.warning("进入临界清理模式")
        
        # 1. 执行内存清理回调
        for callback in self._memory_cleanup_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error(f"执行内存清理回调失败: {str(e)}")
        
        # 2. 卸载中等优先级及以下的模型
        await self._unload_models_by_priority(ResourcePriority.MEDIUM)
        
        # 3. 清理PyTorch缓存
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    
    async def _regular_cleanup(self):
        """常规清理模式"""
        logger.info("执行常规资源清理")
        
        # 1. 清理PyTorch缓存
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    
    async def _unload_models_by_priority(self, min_priority: ResourcePriority):
        """按优先级卸载模型"""
        async with self._lock:
            # 按优先级和使用时间排序，先卸载优先级低且长时间未使用的模型
            models_to_unload = sorted(
                [(model_id, model) for model_id, model in self._models.items() 
                 if model.is_loaded and model.priority.value < min_priority.value],
                key=lambda x: (x[1].priority.value, x[1].last_used_time)
            )
            
            for model_id, model in models_to_unload:
                try:
                    logger.info(f"卸载模型: {model_id} (优先级: {model.priority.name})")
                    if asyncio.iscoroutinefunction(model.unload_func):
                        await model.unload_func()
                    else:
                        model.unload_func()
                    model.is_loaded = False
                except Exception as e:
                    logger.error(f"卸载模型 {model_id} 失败: {str(e)}")
    
    async def _cleanup_unused_models(self):
        """清理未使用的模型"""
        current_time = time.time()
        timeout = self.config['model_unload_timeout']
        
        async with self._lock:
            for model_id, model in self._models.items():
                # 跳过高优先级模型
                if model.priority == ResourcePriority.HIGH:
                    continue
                    
                # 检查是否超时未使用
                if model.is_loaded and (current_time - model.last_used_time) > timeout:
                    try:
                        logger.info(f"卸载超时未使用的模型: {model_id} (闲置时间: {current_time - model.last_used_time:.0f}秒)")
                        if asyncio.iscoroutinefunction(model.unload_func):
                            await model.unload_func()
                        else:
                            model.unload_func()
                        model.is_loaded = False
                    except Exception as e:
                        logger.error(f"卸载模型 {model_id} 失败: {str(e)}")
    
    async def _cleanup_cache(self):
        """清理缓存"""
        if self._cache_stats['size'] > self.config['cache_size_limit_mb']:
            # 这里可以实现具体的缓存清理逻辑
            # 例如将缓存大小减少到限制的80%
            target_size = int(self.config['cache_size_limit_mb'] * 0.8)
            logger.info(f"清理缓存: 从 {self._cache_stats['size']}MB 到 {target_size}MB")
            self._cache_stats['size'] = target_size
    
    async def optimize_resources(self):
        """手动触发资源优化"""
        memory_state = self.monitor.get_resource_state(ResourceType.MEMORY)
        
        if memory_state == ResourceState.EMERGENCY:
            await self._emergency_cleanup()
        elif memory_state == ResourceState.CRITICAL:
            await self._critical_cleanup()
        else:
            await self._regular_cleanup()
    
    def get_optimal_precision(self) -> str:
        """获取最佳精度级别"""
        if not self.config['auto_precision_adjust']:
            return 'fp16'
        
        if torch.cuda.is_available():
            try:
                gpu_memory_state = self.monitor.get_resource_state(ResourceType.GPU_MEMORY)
                
                if gpu_memory_state == ResourceState.EMERGENCY:
                    return 'fp4'
                elif gpu_memory_state == ResourceState.CRITICAL:
                    return 'fp8'
                elif gpu_memory_state == ResourceState.WARNING:
                    return 'fp16'
                else:
                    # 检查可用显存大小来决定
                    allocated = torch.cuda.memory_allocated()
                    total = torch.cuda.get_device_properties(0).total_memory
                    available = total - allocated
                    available_gb = available / (1024 * 1024 * 1024)
                    
                    if available_gb < 4.0:
                        return 'fp8'
                    elif available_gb < 6.0:
                        return 'fp16'
                    else:
                        return 'fp16'  # 即使有足够显存，默认也使用fp16以保持一致性
            except Exception:
                pass
        
        return 'fp16'
    
    def should_use_low_memory_mode(self) -> bool:
        """判断是否应该使用低内存模式"""
        if self.config['low_memory_mode']:
            return True
        
        memory_state = self.monitor.get_resource_state(ResourceType.MEMORY)
        gpu_memory_state = self.monitor.get_resource_state(ResourceType.GPU_MEMORY)
        
        return memory_state in [ResourceState.CRITICAL, ResourceState.EMERGENCY] or \
               gpu_memory_state in [ResourceState.CRITICAL, ResourceState.EMERGENCY]
    
    def update_cache_stats(self, is_hit: bool, size_change: int = 0):
        """更新缓存统计信息"""
        if is_hit:
            self._cache_stats['hits'] += 1
        else:
            self._cache_stats['misses'] += 1
        
        self._cache_stats['size'] += size_change
    
    def get_resource_stats(self) -> Dict[str, Any]:
        """获取资源统计信息"""
        return {
            'memory_usage_percent': self.monitor.get_memory_usage(),
            'process_memory_mb': self.monitor.get_process_memory_usage(),
            'cpu_usage_percent': self.monitor.get_cpu_usage(),
            'gpu_memory_usage_percent': self.monitor.get_gpu_memory_usage(),
            'loaded_models': sum(1 for model in self._models.values() if model.is_loaded),
            'total_models': len(self._models),
            'cache_stats': self._cache_stats
        }


# 全局资源管理器实例
_resource_manager_instance = None
_resource_manager_lock = asyncio.Lock()


async def get_global_resource_manager() -> ResourceManager:
    """
    获取全局资源管理器实例
    """
    global _resource_manager_instance
    async with _resource_manager_lock:
        if _resource_manager_instance is None:
            _resource_manager_instance = ResourceManager()
            await _resource_manager_instance.start()
    return _resource_manager_instance


async def shutdown_global_resource_manager():
    """
    关闭全局资源管理器
    """
    global _resource_manager_instance
    async with _resource_manager_lock:
        if _resource_manager_instance:
            await _resource_manager_instance.stop()
            _resource_manager_instance = None


# 便捷函数
def get_current_memory_usage() -> int:
    """
    获取当前进程内存使用（MB）
    """
    return psutil.Process().memory_info().rss // (1024 * 1024)


def cleanup_memory():
    """
    清理内存
    """
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        if hasattr(torch.cuda, 'ipc_collect'):
            torch.cuda.ipc_collect()


async def is_system_under_memory_pressure() -> bool:
    """
    检查系统是否处于内存压力下
    """
    manager = await get_global_resource_manager()
    return manager.monitor.is_resource_pressure(ResourceType.MEMORY)


# 模块版本
__version__ = "1.0.0"