#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源管理器主模块
整合监控、模型管理、清理策略和GPU管理功能
"""

from core.utils.logger import get_logger
import asyncio

import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.contracts import ResourceType, ResourceSeverity
from core.resource_components import ResourcePriority, ModelResource

from .config import ResourceConfig
from .monitor import ResourceMonitor
from .model_manager import ModelManager
from .cleanup import CleanupStrategy
from .gpu import GPUManager
from core.utils.async_locks import LazyAsyncLock

logger = get_logger(__name__)

ResourceState = ResourceSeverity


class ResourceManager:
    """资源管理器"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        # 配置
        self._config = ResourceConfig.from_dict(config)
        
        # 子模块
        self.monitor = ResourceMonitor()
        self._model_manager = ModelManager()
        self._cleanup_strategy = CleanupStrategy()
        self._gpu_manager = GPUManager(
            get_gpu_free_mb_func=self._get_gpu_free_mb_async,
            get_vram_reserve_mb_func=self._get_vram_reserve_mb,
        )
        
        # 同步配置
        self._sync_config()
        
        # 状态
        self._is_running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        
        # 缓存统计
        self._cache_stats = {"hits": 0, "misses": 0, "size": 0}
        
        # 初始化模型
        self._register_initial_models()
    
    def _sync_config(self):
        """同步配置到子模块"""
        # 设置模型管理器的典型显存占用
        self._model_manager.set_typical_vram_usage(self._config.typical_vram_usage)
        self._gpu_manager.set_typical_vram_usage(self._config.typical_vram_usage)
        
        # 设置清理策略的冷却时间
        for level, seconds in self._config.cleanup_cooldown.items():
            self._cleanup_strategy.set_cooldown(level, seconds)
        
        # 设置监控阈值
        max_memory_percent = self._config.max_memory_usage_percent
        emergency_threshold = min(max_memory_percent, 95.0)
        from core.resource_components import ResourceThreshold
        self.monitor.set_threshold(
            ResourceType.MEMORY,
            ResourceThreshold(
                emergency_threshold * 0.8,
                emergency_threshold * 0.9,
                emergency_threshold,
            ),
        )
    
    def _register_initial_models(self):
        """预注册核心模型"""
        initial_models = [
            ("llm_engine", "llm", ResourcePriority.HIGH, 250, self._config.typical_vram_usage.get("llm_engine", 0)),
            ("image_gen_module", "image_gen", ResourcePriority.MEDIUM, 800, self._config.typical_vram_usage.get("image_gen_module", 0)),
            ("vision_module", "vision", ResourcePriority.MEDIUM, 400, self._config.typical_vram_usage.get("vision_module", 0)),
            ("tts_engine", "tts", ResourcePriority.MEDIUM, 150, self._config.typical_vram_usage.get("tts_engine", 0)),
            ("stt_engine", "stt", ResourcePriority.MEDIUM, 120, self._config.typical_vram_usage.get("stt_engine", 0)),
        ]
        
        for mid, mtype, prio, mem, vram in initial_models:
            if mid not in self._model_manager.models:
                self._model_manager.register_model(
                    model_id=mid,
                    model_type=mtype,
                    priority=prio,
                    load_func=None,
                    unload_func=None,
                    memory_usage_mb=mem,
                    vram_usage_mb=vram,
                )
                # 标记为未加载
                model = self._model_manager.get_model(mid)
                if model:
                    model.is_loaded = False
    
    # ==================== 属性访问 ====================
    
    @property
    def config(self) -> ResourceConfig:
        """获取配置"""
        return self._config
    
    @property
    def models(self) -> Dict[str, ModelResource]:
        """获取所有已注册的模型"""
        return self._model_manager.models
    
    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._is_running
    
    # ==================== 生命周期管理 ====================
    
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
                
                # 取消所有恢复任务
                self._model_manager.cancel_restore_tasks()
                
                logger.info("资源管理器已停止")
    
    # ==================== 模型管理接口 ====================
    
    def register_model(self, **kwargs):
        """注册模型资源"""
        self._model_manager.register_model(**kwargs)
    
    def unregister_model(self, model_id: str):
        """注销模型资源"""
        self._model_manager.unregister_model(model_id)
    
    def get_model(self, model_id: str) -> Optional[ModelResource]:
        """获取模型资源信息"""
        return self._model_manager.get_model(model_id)
    
    def mark_model_loaded(self, model_id: str, loaded: bool):
        """标记模型加载状态"""
        self._model_manager.mark_model_loaded(
            model_id, loaded, self._gpu_manager.determine_model_device
        )
        
        # 触发异步更新指标
        if self._is_running:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._update_model_resource_metrics())
            except Exception:
                pass
    
    async def unload_model(self, model_id: str):
        """异步卸载模型"""
        await self._model_manager.unload_model(model_id)
    
    def register_resource_handler(self, resource_type: str, priority: ResourcePriority, handler: Callable):
        """注册资源处理器"""
        self._cleanup_strategy.register_resource_handler(resource_type, priority, handler)
    
    def register_memory_cleanup_callback(self, callback: Callable):
        """注册内存清理回调"""
        self._cleanup_strategy.register_memory_cleanup_callback(callback)
    
    # ==================== 资源状态查询 ====================
    
    def is_memory_critical(self) -> bool:
        """检查内存是否处于临界状态"""
        return self.monitor.get_memory_usage() >= 90.0
    
    async def get_gpu_free_mb(self) -> Optional[int]:
        """获取GPU可用显存"""
        return await self._get_gpu_free_mb_async()
    
    async def _get_gpu_free_mb_async(self) -> Optional[int]:
        """异步获取GPU可用显存"""
        gpu_info = await self.monitor.get_gpu_memory_usage_async()
        if not gpu_info:
            return None
        used, total = gpu_info
        try:
            free = int(total) - int(used)
            return max(0, int(free))
        except Exception:
            return None
    
    def _get_vram_reserve_mb(self) -> int:
        """获取显存保留量"""
        try:
            from config.integrated_config import get_settings
            settings = get_settings()
            model_settings = getattr(settings, "model", None)
            if model_settings is not None:
                return int(getattr(model_settings, "vram_reserve_mb", 0) or 0)
        except Exception:
            return 0
        return 0
    
    # ==================== 资源准备和清理 ====================
    
    async def prepare_for_heavy_task(self, task_type: str = "llm"):
        """为重负载任务准备资源"""
        started_at = time.time()
        logger.info(f"Preparing resources for heavy task: {task_type}")
        
        task_priority = {
            "llm": ResourcePriority.HIGH,
            "image_gen": ResourcePriority.HIGH,
            "vision": ResourcePriority.MEDIUM,
            "tts": ResourcePriority.MEDIUM,
            "stt": ResourcePriority.MEDIUM,
        }.get(task_type.lower(), ResourcePriority.HIGH)
        
        # 演示日志
        try:
            from core.utils.demo_utils import add_demo_log
            add_demo_log(
                f"Scheduler: Prioritizing {task_type.upper()} task. Checking resource availability...",
                "info",
            )
        except Exception:
            pass
        
        # 判定是否需要清理
        gpu_free_mb = await self._get_gpu_free_mb_async()
        should_skip_cleanup = False
        task_type_lower = task_type.lower()
        reserve_mb = self._get_vram_reserve_mb()
        min_free_mb = max(1500, int(reserve_mb))
        
        # LLM已加载时跳过清理
        if task_type_lower == "llm":
            llm_model = self._model_manager.get_model("llm_engine")
            if llm_model and llm_model.is_loaded and llm_model.device != "CPU":
                should_skip_cleanup = True
                logger.info("LLM already loaded on GPU, skipping cleanup for LLM task")
        
        # 显存充足时跳过清理
        if gpu_free_mb is not None and gpu_free_mb > min_free_mb and task_type_lower != "image_gen":
            should_skip_cleanup = True
            logger.info(f"VRAM is sufficient ({gpu_free_mb}MB), skipping aggressive cleanup for {task_type}")
        
        # 释放低优先级资源
        if not should_skip_cleanup:
            await self._cleanup_strategy.release_low_priority_resources(task_priority)
        
        # 确定冲突模型
        conflicts = self._get_conflict_models(task_type_lower)
        
        # 并行卸载冲突模型
        if conflicts and not should_skip_cleanup:
            logger.info(f"Task {task_type} starting, parallel offloading conflict models: {conflicts}")
            await self._offload_conflict_models(conflicts, task_type_lower)
        elif conflicts and should_skip_cleanup:
            # 更新使用时间
            for model_id in conflicts:
                m = self._model_manager.get_model(model_id)
                if m:
                    m.update_usage()
        
        # 清理缓存
        import sys
        _torch = sys.modules.get("torch")
        has_torch_cuda = bool(_torch and _torch.cuda.is_available())
        if has_torch_cuda and not should_skip_cleanup:
            self._gpu_manager.clear_torch_cache()
        
        # 更新指标
        try:
            await self._update_model_resource_metrics()
        except Exception:
            pass
        
        # 演示日志
        try:
            from core.utils.demo_utils import add_demo_log
            add_demo_log(
                f"Scheduler: Resource ready for {task_type.upper()}. Resource Matrix updated.",
                "success",
            )
        except Exception:
            pass
        
        logger.info(
            "Resource preparation done for %s in %.2fs",
            task_type,
            time.time() - started_at,
        )
    
    def _get_conflict_models(self, task_type: str) -> List[str]:
        """获取冲突模型列表"""
        if task_type == "llm":
            return ["vision_module", "image_gen_module", "stt_engine", "tts_engine"]
        elif task_type == "vision":
            return ["llm_engine", "image_gen_module", "stt_engine", "tts_engine"]
        elif task_type == "image_gen":
            return ["vision_module", "llm_engine", "stt_engine", "tts_engine"]
        return []
    
    async def _offload_conflict_models(self, conflicts: List[str], reason: str):
        """并行卸载冲突模型"""
        offload_tasks = []
        for model_id in conflicts:
            model = self._model_manager.get_model(model_id)
            if model:
                offload_tasks.append(
                    self._gpu_manager.try_offload_model_to_cpu(model, reason=reason)
                )
        
        if offload_tasks:
            results = await asyncio.gather(*offload_tasks, return_exceptions=True)
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    logger.error(f"Failed to offload {conflicts[i]} during {reason} preparation: {res}")
    
    async def emergency_cleanup(self):
        """紧急资源清理"""
        logger.warning("!!! 执行紧急资源清理 !!!")
        
        await self._cleanup_strategy.emergency_cleanup(
            unload_all_func=self._model_manager.emergency_unload_all,
            offload_voice_func=lambda: self._gpu_manager.offload_voice_services(self._model_manager.models),
        )
        
        # 清理缓存
        self._cache_stats["size"] = 0
        
        logger.info("紧急资源清理完成")
    
    async def optimize_resources(self):
        """手动触发资源优化"""
        memory_state = self.monitor.get_resource_state(ResourceType.MEMORY)
        gpu_state = await self._get_gpu_state()
        
        if memory_state == ResourceState.EMERGENCY or gpu_state == ResourceState.EMERGENCY:
            await self._cleanup_strategy.emergency_cleanup(
                unload_all_func=self._model_manager.emergency_unload_all,
                offload_voice_func=lambda: self._gpu_manager.offload_voice_services(self._model_manager.models),
            )
        elif memory_state == ResourceState.CRITICAL or gpu_state == ResourceState.CRITICAL:
            await self._cleanup_strategy.critical_cleanup(
                unload_medium_func=lambda: self._model_manager.unload_models_by_priority(ResourcePriority.MEDIUM),
                offload_voice_func=lambda: self._gpu_manager.offload_voice_services(self._model_manager.models),
            )
        else:
            await self._cleanup_strategy.regular_cleanup()
        
        try:
            await self._auto_recover_gpu_models()
        except Exception:
            pass
    
    async def _get_gpu_state(self) -> ResourceState:
        """获取GPU状态"""
        gpu_usage = await self.monitor.get_gpu_memory_usage_async()
        if not gpu_usage:
            return ResourceState.NORMAL
        
        used, total = gpu_usage
        percent = (used / total) * 100 if total > 0 else 0
        threshold = self.monitor.thresholds.get(ResourceType.GPU_MEMORY)
        
        if threshold is None:
            return ResourceState.NORMAL
        
        if percent >= threshold.emergency:
            return ResourceState.EMERGENCY
        elif percent >= threshold.critical:
            return ResourceState.CRITICAL
        elif percent >= threshold.warning:
            return ResourceState.WARNING
        
        return ResourceState.NORMAL
    
    # ==================== 资源监控 ====================
    
    async def _monitor_resources(self):
        """资源监控任务"""
        try:
            while self._is_running:
                await asyncio.sleep(self._config.monitor_interval)
                
                # 检查资源状态
                memory_state = self.monitor.get_resource_state(ResourceType.MEMORY)
                gpu_state = await self._get_gpu_state()
                
                # 记录资源使用情况
                logger.debug(
                    f"资源使用情况 - 内存: {self.monitor.get_memory_usage():.1f}%, "
                    f"进程内存: {self.monitor.get_process_memory_usage()}MB, "
                    f"CPU: {self.monitor.get_cpu_usage():.1f}%"
                )
                
                # 根据资源状态执行清理
                if self._cleanup_strategy.can_cleanup("emergency"):
                    if memory_state == ResourceState.EMERGENCY or gpu_state == ResourceState.EMERGENCY:
                        await self._cleanup_strategy.emergency_cleanup(
                            unload_all_func=self._model_manager.emergency_unload_all,
                            offload_voice_func=lambda: self._gpu_manager.offload_voice_services(self._model_manager.models),
                        )
                        self._cleanup_strategy.record_cleanup("emergency")
                
                if self._cleanup_strategy.can_cleanup("critical"):
                    if memory_state == ResourceState.CRITICAL or gpu_state == ResourceState.CRITICAL:
                        await self._cleanup_strategy.critical_cleanup(
                            unload_medium_func=lambda: self._model_manager.unload_models_by_priority(ResourcePriority.MEDIUM),
                            offload_voice_func=lambda: self._gpu_manager.offload_voice_services(self._model_manager.models),
                        )
                        self._cleanup_strategy.record_cleanup("critical")
                
                if self._cleanup_strategy.can_cleanup("regular"):
                    if memory_state == ResourceState.WARNING or gpu_state == ResourceState.WARNING:
                        await self._cleanup_strategy.regular_cleanup()
                
                # 更新模型资源状态
                await self._update_model_resource_metrics()
                
                # 发布资源更新事件
                try:
                    from core.core_engine.event_bus import get_event_bus
                    await get_event_bus().publish(
                        "resource.metrics_updated", **self.get_resource_stats()
                    )
                except Exception:
                    pass
                
                # 清理超时未使用的模型
                await self._model_manager.cleanup_unused_models(self._config.model_unload_timeout)
                
                # 清理缓存
                await self._cleanup_cache()
                
                # 自动恢复GPU模型
                try:
                    await self._auto_recover_gpu_models()
                except Exception:
                    pass
        
        except Exception as e:
            logger.error(f"资源监控任务异常: {str(e)}")
    
    async def _update_model_resource_metrics(self, gpu_info: Optional[Tuple[int, int]] = None):
        """更新所有已注册模型的实时资源指标"""
        async with self._model_manager.lock:
            if gpu_info is None:
                gpu_info = await self.monitor.get_gpu_memory_usage_async()
            
            global_used = int(gpu_info[0]) if gpu_info else 0
            global_total = int(gpu_info[1]) if gpu_info else 0
            
            # 重置未加载模型的显存
            for model in self._model_manager.models.values():
                if not model.is_loaded:
                    model.vram_usage_mb = 0
                if model.is_offloaded or model.device != "GPU":
                    model.vram_usage_mb = 0
            
            active_gpu_models = self._model_manager.get_gpu_models()
            
            if not active_gpu_models:
                return
            
            if not gpu_info or global_total <= 0:
                for m in active_gpu_models:
                    if int(m.vram_usage_mb or 0) <= 0:
                        m.vram_usage_mb = int(self._config.typical_vram_usage.get(m.model_id, 0) or 0)
                return
            
            if global_used <= 0:
                return
            
            # 计算基础显存使用
            estimated_base = int(max(700, min(1500, global_total * 0.08)))
            
            pid_usage = await self.monitor.get_gpu_compute_process_usage_async()
            compute_total = 0
            if isinstance(pid_usage, dict):
                try:
                    compute_total = sum(int(v or 0) for v in pid_usage.values())
                except Exception:
                    compute_total = 0
            
            base_used = estimated_base
            if compute_total > 0:
                base_used = max(0, int(global_used) - int(compute_total))
            base_used = max(0, min(int(base_used), int(global_used)))
            
            # 获取当前进程显存使用
            inproc_used = self.monitor.get_current_process_gpu_used_mb(pid_usage=pid_usage)
            if inproc_used is None:
                inproc_used = 0
            if int(inproc_used) <= 0:
                if compute_total > 0:
                    inproc_used = max(0, int(global_used) - int(base_used))
                else:
                    inproc_used = max(0, int(global_used) - int(estimated_base))
            inproc_used = max(0, min(int(inproc_used), int(global_used)))
            
            if int(inproc_used) <= 0:
                for m in active_gpu_models:
                    if int(m.vram_usage_mb or 0) <= 0:
                        m.vram_usage_mb = int(self._config.typical_vram_usage.get(m.model_id, 0) or 0)
                return
            
            # 按权重分配显存
            weights: Dict[str, int] = {}
            sum_weights = 0
            for m in active_gpu_models:
                w = int(self._config.typical_vram_usage.get(m.model_id, 0) or m.vram_usage_mb or 1)
                w = max(1, w)
                weights[m.model_id] = w
                sum_weights += w
            
            if sum_weights <= 0:
                return
            
            if len(active_gpu_models) == 1:
                m = active_gpu_models[0]
                m.vram_usage_mb = int(inproc_used)
                return
            
            for m in active_gpu_models:
                desired = int(inproc_used * (weights.get(m.model_id, 1) / sum_weights))
                desired = max(10, desired) if inproc_used > 0 else 0
                m.vram_usage_mb = desired
    
    async def _cleanup_cache(self):
        """清理缓存"""
        if self._cache_stats["size"] > self._config.cache_size_limit_mb:
            target_size = int(self._config.cache_size_limit_mb * 0.8)
            logger.info(f"清理缓存: 从 {self._cache_stats['size']}MB 到 {target_size}MB")
            self._cache_stats["size"] = target_size
    
    async def _auto_recover_gpu_models(self):
        """自动恢复GPU模型"""
        gpu_usage = await self.monitor.get_gpu_memory_usage_async()
        if not gpu_usage:
            return
        
        used, total = gpu_usage
        percent = (used / total) * 100 if total > 0 else 0
        threshold = self.monitor.thresholds.get(ResourceType.GPU_MEMORY)
        
        if threshold is None or percent >= threshold.warning:
            return
        
        # 图像生成模块加载时不恢复
        image = self._model_manager.get_model("image_gen_module")
        if image and image.is_loaded:
            return
        
        gpu_free_mb = await self._get_gpu_free_mb_async()
        if gpu_free_mb is None:
            return
        
        targets = ["llm_engine", "vision_module", "tts_engine", "stt_engine"]
        
        for model_id in targets:
            model = self._model_manager.get_model(model_id)
            if not model or not model.is_loaded:
                continue
            if str(model.device).upper() == "GPU":
                continue
            
            # 尝试恢复到GPU
            try:
                await self._gpu_manager.try_restore_model_to_gpu(model, gpu_free_mb)
            except Exception as e:
                logger.error(f"恢复模型 {model_id} 到GPU失败: {e}")
    
    # ==================== 统计和状态 ====================
    
    def update_cache_stats(self, is_hit: bool, size_change: int = 0):
        """更新缓存统计"""
        if is_hit:
            self._cache_stats["hits"] += 1
        else:
            self._cache_stats["misses"] += 1
        self._cache_stats["size"] += size_change
    
    def get_resource_stats(self, gpu_info: Optional[Tuple[int, int]] = None) -> Dict[str, Any]:
        """获取资源统计信息"""
        gpu = gpu_info if gpu_info is not None else self.monitor.get_gpu_memory_usage()
        used_mb = int(gpu[0]) if gpu else 0
        total_mb = int(gpu[1]) if gpu else 0
        percent = (used_mb / total_mb * 100.0) if total_mb > 0 else 0.0
        
        payload = {
            "memory_usage_percent": self.monitor.get_memory_usage(),
            "process_memory_mb": self.monitor.get_process_memory_usage(),
            "cpu_usage_percent": self.monitor.get_cpu_usage(),
            "gpu_memory_used_mb": used_mb,
            "gpu_memory_total_mb": total_mb,
            "gpu_memory_percent": percent,
            "gpu_memory_usage_percent": percent,
            "loaded_models": sum(1 for model in self._model_manager.models.values() if model.is_loaded),
            "total_models": len(self._model_manager.models),
            "cache_stats": self._cache_stats,
        }
        
        # 添加快照信息
        try:
            resources = {}
            for rtype in (ResourceType.MEMORY, ResourceType.CPU, ResourceType.GPU_MEMORY):
                try:
                    st = self.monitor.get_resource_state(rtype)
                except Exception:
                    st = ResourceState.NORMAL
                
                entry = {"state": st.value}
                if rtype == ResourceType.MEMORY:
                    entry["usage_percent"] = float(payload["memory_usage_percent"] or 0.0)
                elif rtype == ResourceType.CPU:
                    entry["usage_percent"] = float(payload["cpu_usage_percent"] or 0.0)
                elif rtype == ResourceType.GPU_MEMORY:
                    entry["usage_percent"] = float(payload["gpu_memory_usage_percent"] or 0.0)
                    entry["used_mb"] = int(used_mb)
                    entry["total_mb"] = int(total_mb)
                resources[rtype.value] = entry
            
            models = {mid: m.to_contract_dict() for mid, m in self._model_manager.models.items()}
            
            payload["snapshot"] = {
                "resources": resources,
                "models": models,
                "timestamp": time.time(),
            }
        except Exception:
            pass
        
        return payload
    
    def get_optimal_precision(self) -> str:
        """获取最佳精度级别"""
        if not self._config.auto_precision_adjust:
            return "fp16"
        
        gpu_state = self.monitor.get_resource_state(ResourceType.GPU_MEMORY)
        return self._cleanup_strategy.get_optimal_precision(gpu_state)
    
    def should_use_low_memory_mode(self) -> bool:
        """判断是否应使用低内存模式"""
        memory_state = self.monitor.get_resource_state(ResourceType.MEMORY)
        gpu_memory_state = self.monitor.get_resource_state(ResourceType.GPU_MEMORY)
        
        return self._cleanup_strategy.should_use_low_memory_mode(
            memory_state, gpu_memory_state, self._config.low_memory_mode
        )


# ==================== 全局单例 ====================

_resource_manager_instance: Optional[ResourceManager] = None
_resource_manager_lock = asyncio.Lock()


def get_resource_manager() -> ResourceManager:
    """获取全局资源管理器实例 (同步)"""
    global _resource_manager_instance
    if _resource_manager_instance is None:
        _resource_manager_instance = ResourceManager()
        # 尝试自动启动监控
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(_resource_manager_instance.start())
        except RuntimeError:
            pass
    return _resource_manager_instance


async def get_global_resource_manager() -> ResourceManager:
    """获取全局资源管理器实例 (异步)"""
    global _resource_manager_instance
    async with _resource_manager_lock:
        if _resource_manager_instance is None:
            _resource_manager_instance = ResourceManager()
            await _resource_manager_instance.start()
    return _resource_manager_instance


async def shutdown_global_resource_manager():
    """关闭全局资源管理器"""
    global _resource_manager_instance
    async with _resource_manager_lock:
        if _resource_manager_instance:
            await _resource_manager_instance.stop()
            _resource_manager_instance = None


# 便捷函数
def get_current_memory_usage() -> int:
    """获取当前进程内存使用（MB）"""
    import psutil
    return psutil.Process().memory_info().rss // (1024 * 1024)


def cleanup_memory():
    """清理内存"""
    import sys
    _torch = sys.modules.get("torch")
    if _torch and _torch.cuda.is_available():
        _torch.cuda.empty_cache()
        if hasattr(_torch.cuda, "ipc_collect"):
            _torch.cuda.ipc_collect()


async def is_system_under_memory_pressure() -> bool:
    """检查系统是否处于内存压力下"""
    manager = await get_global_resource_manager()
    return manager.monitor.is_resource_pressure(ResourceType.MEMORY)


# 模块版本
__version__ = "2.0.0"
