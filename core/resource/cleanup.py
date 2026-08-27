#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清理策略模块
负责根据不同资源状态执行相应的清理操作
"""

from core.utils.logger import get_logger
import asyncio

import sys
import time
from typing import Callable, Dict, List, Optional

from core.contracts import ResourceSeverity
from core.resource_components import ResourcePriority

logger = get_logger(__name__)

ResourceState = ResourceSeverity


def _get_torch():
    """延迟导入 torch，避免启动时加载 2~5 秒"""
    return sys.modules.get("torch")


class CleanupStrategy:
    """清理策略管理器"""
    
    def __init__(self):
        self._memory_cleanup_callbacks: List[Callable] = []
        self._resource_handlers: List[Dict] = []
        
        # 清理冷却时间
        self._cleanup_cooldown_seconds: Dict[str, float] = {
            "emergency": 12.0,
            "critical": 6.0,
            "regular": 3.0,
        }
        self._last_cleanup_ts: Dict[str, float] = {
            "emergency": 0.0,
            "critical": 0.0,
            "regular": 0.0,
        }
    
    def set_cooldown(self, level: str, seconds: float):
        """设置清理冷却时间"""
        if level in self._cleanup_cooldown_seconds:
            self._cleanup_cooldown_seconds[level] = seconds
    
    def register_memory_cleanup_callback(self, callback: Callable):
        """注册内存清理回调"""
        self._memory_cleanup_callbacks.append(callback)
    
    def register_resource_handler(
        self, resource_type: str, priority: ResourcePriority, handler: Callable
    ):
        """注册资源处理器"""
        self._resource_handlers.append({
            "type": resource_type,
            "priority": priority,
            "handler": handler,
        })
        # 按优先级升序排序
        self._resource_handlers.sort(key=lambda x: x["priority"].value)
        logger.info(f"Registered resource handler for {resource_type} with priority {priority.name}")
    
    def can_cleanup(self, level: str) -> bool:
        """检查是否可以执行清理（考虑冷却时间）"""
        now = time.time()
        last_ts = self._last_cleanup_ts.get(level, 0.0)
        cooldown = self._cleanup_cooldown_seconds.get(level, 3.0)
        return (now - last_ts) >= cooldown
    
    def record_cleanup(self, level: str):
        """记录清理时间"""
        self._last_cleanup_ts[level] = time.time()
    
    async def execute_cleanup_callbacks(self):
        """执行所有内存清理回调"""
        for callback in self._memory_cleanup_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error(f"执行内存清理回调失败: {str(e)}")
    
    async def release_low_priority_resources(self, max_priority: ResourcePriority):
        """释放低优先级资源"""
        for handler_info in self._resource_handlers:
            if handler_info["priority"].value < max_priority.value:
                try:
                    logger.info(f"Releasing {handler_info['type']} (Priority: {handler_info['priority'].name})")
                    func = handler_info["handler"]
                    if asyncio.iscoroutinefunction(func):
                        await func("release")
                    else:
                        func("release")
                except Exception as e:
                    logger.error(f"Error releasing resource: {e}")
    
    async def emergency_cleanup(
        self,
        unload_all_func: Callable,
        offload_voice_func: Optional[Callable] = None,
    ):
        """紧急清理模式"""
        logger.warning("进入紧急清理模式")
        
        # 1. 卸载语音服务
        if offload_voice_func:
            try:
                await asyncio.wait_for(offload_voice_func(), timeout=3.0)
            except asyncio.TimeoutError:
                logger.warning("卸载语音服务超时，跳过")
            except Exception as e:
                logger.warning(f"卸载语音服务失败，跳过: {e}")
        
        # 2. 释放低优先级资源
        await self.release_low_priority_resources(ResourcePriority.HIGH)
        
        # 3. 执行所有内存清理回调
        await self.execute_cleanup_callbacks()
        
        # 4. 卸载所有模型
        await unload_all_func()
        
        # 5. 清理PyTorch缓存
        self._clear_torch_cache()
        
        logger.warning("紧急清理完成")
        self.record_cleanup("emergency")
    
    async def critical_cleanup(
        self,
        unload_medium_func: Callable,
        offload_voice_func: Optional[Callable] = None,
    ):
        """临界清理模式"""
        logger.warning("进入临界清理模式")
        
        # 1. 卸载语音服务
        if offload_voice_func:
            try:
                await asyncio.wait_for(offload_voice_func(), timeout=3.0)
            except asyncio.TimeoutError:
                logger.warning("卸载语音服务超时，跳过")
            except Exception as e:
                logger.warning(f"卸载语音服务失败，跳过: {e}")
        
        # 2. 释放低优先级资源
        await self.release_low_priority_resources(ResourcePriority.HIGH)
        
        # 3. 执行内存清理回调
        await self.execute_cleanup_callbacks()
        
        # 4. 卸载中等优先级及以下的模型
        await unload_medium_func()
        
        # 5. 清理PyTorch缓存
        self._clear_torch_cache()
        
        logger.warning("临界清理完成")
        self.record_cleanup("critical")
    
    async def regular_cleanup(self):
        """常规清理模式"""
        logger.debug("执行常规资源清理")
        self._clear_torch_cache()
        self.record_cleanup("regular")
    
    def _clear_torch_cache(self):
        """清理PyTorch缓存"""
        _torch = _get_torch()
        if _torch and _torch.cuda.is_available():
            try:
                _torch.cuda.empty_cache()
                if hasattr(_torch.cuda, "ipc_collect"):
                    _torch.cuda.ipc_collect()
            except Exception as e:
                logger.debug(f"清理PyTorch缓存失败: {e}")
    
    def get_optimal_precision(self, gpu_state: Optional[ResourceState] = None) -> str:
        """获取最佳精度级别"""
        if gpu_state is None:
            return "fp16"
        
        if gpu_state in [ResourceState.CRITICAL, ResourceState.EMERGENCY]:
            return "int8"
        
        return "fp16"
    
    def should_use_low_memory_mode(
        self,
        memory_state: ResourceState,
        gpu_memory_state: ResourceState,
        config_low_memory_mode: bool = False,
    ) -> bool:
        """判断是否应使用低内存模式"""
        if config_low_memory_mode:
            return True
        
        return (
            memory_state in [ResourceState.CRITICAL, ResourceState.EMERGENCY] or
            gpu_memory_state in [ResourceState.CRITICAL, ResourceState.EMERGENCY]
        )
