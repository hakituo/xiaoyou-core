#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模型管理模块
负责模型的注册、加载、卸载和状态管理
"""

from core.utils.logger import get_logger
import asyncio

import time
from typing import Any, Callable, Dict, List, Optional

from core.resource_components import ResourcePriority, ModelResource
from core.resource.config import ResourceConfig
from core.utils.async_locks import LazyAsyncLock

logger = get_logger(__name__)


class ModelManager:
    """模型管理器"""
    
    def __init__(self):
        self._models: Dict[str, ModelResource] = {}
        self._lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._restore_tasks: Dict[str, asyncio.Task] = {}
        self._restore_lock = LazyAsyncLock()
        
        # 从统一配置读取典型显存占用映射 (MB)
        self._typical_vram_usage: Dict[str, int] = ResourceConfig().typical_vram_usage
    
    @property
    def models(self) -> Dict[str, ModelResource]:
        """获取所有已注册的模型"""
        return self._models
    
    @property
    def lock(self) -> asyncio.Lock:
        """获取模型锁"""
        return self._lock
    
    def set_typical_vram_usage(self, usage: Dict[str, int]):
        """设置典型显存占用"""
        self._typical_vram_usage = usage
    
    def register_model(
        self,
        model_id: str,
        model_type: str,
        priority: ResourcePriority,
        load_func: Callable,
        unload_func: Callable,
        memory_usage_mb: int = 0,
        vram_usage_mb: int = 0,
        offload_func: Optional[Callable] = None,
        instance: Any = None,
    ):
        """注册模型资源"""
        # 如果未显式提供 instance，尝试从 load_func 中提取
        if instance is None and hasattr(load_func, "__self__"):
            instance = load_func.__self__
        
        # 如果未提供显存占用，尝试从典型值中获取
        if vram_usage_mb == 0:
            vram_usage_mb = self._typical_vram_usage.get(model_id, 0)
        
        model = ModelResource(
            model_id=model_id,
            model_type=model_type,
            priority=priority,
            load_func=load_func,
            unload_func=unload_func,
            memory_usage_mb=memory_usage_mb,
            vram_usage_mb=vram_usage_mb,
            offload_func=offload_func,
            instance=instance,
        )
        self._models[model_id] = model
        logger.info(f"模型已注册: {model_id}, 类型: {model_type}, 优先级: {priority.name}")
    
    def unregister_model(self, model_id: str):
        """注销模型资源"""
        if model_id in self._models:
            del self._models[model_id]
            logger.info(f"模型已注销: {model_id}")
    
    def get_model(self, model_id: str) -> Optional[ModelResource]:
        """获取模型资源信息"""
        return self._models.get(model_id)
    
    def mark_model_loaded(self, model_id: str, loaded: bool, determine_device_func: Optional[Callable] = None):
        """标记模型加载状态并更新设备信息"""
        model = self._models.get(model_id)
        if not model:
            return
        
        model.is_loaded = bool(loaded)
        if loaded:
            model.update_usage()
            # 确保有显存占用初始值
            if model.vram_usage_mb == 0:
                model.vram_usage_mb = self._typical_vram_usage.get(model_id, 0)
            
            # 判定设备
            if determine_device_func:
                model.device = determine_device_func(model)
        else:
            model.device = "CPU"
            model.is_offloaded = False
            model.vram_usage_mb = 0
    
    async def unload_model(self, model_id: str):
        """异步卸载模型并释放资源"""
        model = self._models.get(model_id)
        if not model or not model.is_loaded:
            return
        
        if model.unload_func:
            try:
                logger.info(f"正在执行模型卸载: {model_id}")
                if asyncio.iscoroutinefunction(model.unload_func):
                    await model.unload_func()
                else:
                    model.unload_func()
            except Exception as e:
                logger.error(f"卸载模型 {model_id} 失败: {e}")
        
        model.is_loaded = False
        model.device = "CPU"
        model.is_offloaded = False
        model.vram_usage_mb = 0
        
        # 卸载后立即执行一次垃圾回收
        import gc
        gc.collect()
    
    async def unload_models_by_priority(self, min_priority: ResourcePriority):
        """按优先级卸载模型"""
        async with self._lock:
            # 按优先级和使用时间排序
            models_to_unload = sorted(
                [
                    (model_id, model)
                    for model_id, model in self._models.items()
                    if model.is_loaded and model.priority.value < min_priority.value
                ],
                key=lambda x: (x[1].priority.value, x[1].last_used_time),
            )
            
            for model_id, model in models_to_unload:
                try:
                    logger.info(f"卸载模型: {model_id} (优先级: {model.priority.name})")
                    if asyncio.iscoroutinefunction(model.unload_func):
                        await model.unload_func()
                    else:
                        model.unload_func()
                    model.is_loaded = False
                    model.vram_usage_mb = 0
                except Exception as e:
                    logger.error(f"卸载模型 {model_id} 失败: {str(e)}")
    
    async def cleanup_unused_models(self, timeout: int = 300):
        """清理未使用的模型"""
        current_time = time.time()
        
        async with self._lock:
            for model_id, model in self._models.items():
                # 跳过高优先级模型
                if model.priority == ResourcePriority.HIGH:
                    continue
                
                # 检查是否超时未使用
                if model.is_loaded and (current_time - model.last_used_time) > timeout:
                    try:
                        logger.info(
                            f"卸载超时未使用的模型: {model_id} (闲置时间: {current_time - model.last_used_time:.0f}秒)"
                        )
                        if asyncio.iscoroutinefunction(model.unload_func):
                            await model.unload_func()
                        else:
                            model.unload_func()
                        model.is_loaded = False
                        model.vram_usage_mb = 0
                    except Exception as e:
                        logger.error(f"卸载模型 {model_id} 失败: {str(e)}")
    
    def get_loaded_models(self) -> List[str]:
        """获取所有已加载的模型ID"""
        return [model_id for model_id, model in self._models.items() if model.is_loaded]
    
    def get_gpu_models(self) -> List[ModelResource]:
        """获取所有在GPU上运行的模型"""
        return [
            model for model in self._models.values()
            if model.is_loaded and not model.is_offloaded and model.device == "GPU"
        ]
    
    def get_model_stats(self) -> Dict[str, Any]:
        """获取模型统计信息"""
        loaded_count = sum(1 for m in self._models.values() if m.is_loaded)
        total_vram = sum(m.vram_usage_mb for m in self._models.values() if m.is_loaded and not m.is_offloaded)
        
        return {
            "total_models": len(self._models),
            "loaded_models": loaded_count,
            "total_vram_usage_mb": total_vram,
            "models": {mid: m.to_contract_dict() for mid, m in self._models.items()},
        }
    
    async def emergency_unload_all(self, timeout: float = 3.0):
        """紧急卸载所有模型"""
        unload_tasks = []
        for model_id, model in self._models.items():
            if model.is_loaded:
                unload_tasks.append(self.unload_model(model_id))
        
        if unload_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*unload_tasks, return_exceptions=True),
                    timeout=timeout,
                )
            except Exception:
                pass
    
    def cancel_restore_tasks(self):
        """取消所有恢复任务"""
        for task in self._restore_tasks.values():
            if not task.done():
                task.cancel()
        self._restore_tasks.clear()
