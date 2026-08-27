#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPU管理模块
负责GPU显存管理、模型卸载/加载到CPU/GPU
"""

from core.utils.logger import get_logger
import asyncio

import sys
from typing import Any, Callable, Dict, Optional, Tuple

from core.resource_components import ModelResource
from core.resource.config import ResourceConfig

logger = get_logger(__name__)


def _get_torch():
    """延迟导入 torch，避免启动时加载 2~5 秒"""
    return sys.modules.get("torch")


class GPUManager:
    """GPU管理器"""
    
    def __init__(self, get_gpu_free_mb_func: Callable, get_vram_reserve_mb_func: Callable):
        self._get_gpu_free_mb = get_gpu_free_mb_func
        self._get_vram_reserve_mb = get_vram_reserve_mb_func
        
        # 从统一配置读取典型显存占用映射
        self._typical_vram_usage: Dict[str, int] = ResourceConfig().typical_vram_usage
    
    def set_typical_vram_usage(self, usage: Dict[str, int]):
        """设置典型显存占用"""
        self._typical_vram_usage = usage
    
    def determine_model_device(self, model: ModelResource) -> str:
        """判定模型运行设备 (GPU/CPU)"""
        if not model.instance:
            return "GPU" if model.vram_usage_mb > 0 else "CPU"
        
        try:
            # 1. 显式强制 CPU 检查
            if bool(getattr(model.instance, "_python_force_cpu", False)):
                return "CPU"
            
            # 2. 检查提供商 (Provider)
            provider = getattr(model.instance, "provider", None)
            if provider and str(provider).strip().lower() != "local":
                return "CPU"
            
            # 3. 针对不同模型类型的特定逻辑
            if model.model_id == "llm_engine":
                cfg = getattr(model.instance, "config", None) or getattr(
                    model.instance, "_gpu_config", None
                )
                if isinstance(cfg, dict):
                    if int(cfg.get("n_gpu_layers", -1)) == 0:
                        return "CPU"
                return "GPU"
            
            if model.model_id == "vision_module":
                device = getattr(model.instance, "device", None)
                if device and "cpu" in str(device).lower():
                    return "CPU"
                return "GPU"
            
            # 4. 通用 Torch 设备检查
            _torch = _get_torch()
            if _torch and _torch.cuda.is_available():
                device = getattr(model.instance, "device", None)
                if device and "cuda" in str(device).lower():
                    return "GPU"
            
            return "CPU" if model.vram_usage_mb == 0 else "GPU"
        except Exception as e:
            logger.debug(f"Error determining device for {model.model_id}: {e}")
            return "GPU" if model.vram_usage_mb > 0 else "CPU"
    
    async def try_offload_model_to_cpu(
        self, model: ModelResource, reason: str = ""
    ) -> bool:
        """尝试将模型卸载到CPU"""
        if not model.is_loaded:
            return False
        
        is_offloaded = getattr(model, "is_offloaded", False)
        if not isinstance(is_offloaded, bool):
            is_offloaded = False
        
        if is_offloaded or str(model.device).upper() == "CPU":
            return False
        
        # 图像生成模块不卸载
        if model.model_id == "image_gen_module":
            return False
        
        # 非本地模型直接标记
        instance_provider = getattr(model.instance, "provider", None)
        if instance_provider and str(instance_provider).strip().lower() != "local":
            model.device = "CPU"
            model.vram_usage_mb = 0
            model.is_offloaded = True
            return True
        
        instance = model.instance
        
        # LLM引擎特殊处理
        if model.model_id == "llm_engine":
            return await self._offload_llm_engine(model, instance, reason)
        
        # 尝试move_to_cpu方法
        move_to_cpu = getattr(instance, "move_to_cpu", None)
        if callable(move_to_cpu):
            ok = await self._call_maybe_async(move_to_cpu, timeout=12.0)
            if ok:
                model.device = "CPU"
                model.vram_usage_mb = 0
                model.is_offloaded = True
                return True
        
        # 尝试卸载函数
        if model.unload_func:
            try:
                if asyncio.iscoroutinefunction(model.unload_func):
                    await model.unload_func()
                else:
                    model.unload_func()
                model.is_loaded = False
                model.vram_usage_mb = 0
                return True
            except Exception as e:
                logger.error(f"卸载模型 {model.model_id} 失败: {e}")
        
        return False
    
    async def _offload_llm_engine(
        self, model: ModelResource, instance: Any, reason: str
    ) -> bool:
        """卸载LLM引擎"""
        # 快速释放模式（为图像生成）
        quick_release = getattr(instance, "release_llm_vram_for_image_gen", None)
        if callable(quick_release) and reason.lower() == "image_gen":
            ok = False
            try:
                if asyncio.iscoroutinefunction(quick_release):
                    task = asyncio.create_task(quick_release())
                    try:
                        await asyncio.wait_for(asyncio.shield(task), timeout=8.0)
                        ok = True
                    except asyncio.TimeoutError:
                        ok = True
                else:
                    await asyncio.wait_for(
                        asyncio.to_thread(quick_release), timeout=8.0
                    )
                    ok = True
            except Exception:
                ok = False
            
            if ok:
                model.device = "CPU"
                model.vram_usage_mb = 0
                model.is_offloaded = True
                return True
        
        # 标准卸载模式
        if model.offload_func:
            ok = await self._call_maybe_async(model.offload_func, timeout=10.0)
            if ok:
                model.device = "CPU"
                model.vram_usage_mb = 0
                model.is_offloaded = True
                return True
        
        return False
    
    async def try_restore_model_to_gpu(
        self, model: ModelResource, gpu_free_mb: Optional[int] = None
    ) -> bool:
        """尝试将模型恢复到GPU"""
        if not model.is_loaded:
            return False
        
        # 图像生成模块不恢复
        if model.model_id == "image_gen_module":
            return False
        
        # 非本地模型跳过
        instance_provider = getattr(model.instance, "provider", None)
        if instance_provider and str(instance_provider).strip().lower() != "local":
            return False
        
        # 检查显存是否足够
        if gpu_free_mb is not None:
            need = int(self._typical_vram_usage.get(model.model_id, 0) or 0)
            buffer_mb = -256 if model.model_id == "llm_engine" else 128
            reserve_mb = self._get_vram_reserve_mb() if model.model_id != "llm_engine" else 0
            threshold = need + buffer_mb + reserve_mb
            
            if need > 0 and gpu_free_mb < threshold:
                logger.debug(
                    "跳过回迁 %s: 剩余显存 %sMB < 阈值 %sMB (需求 %sMB, buffer=%sMB)",
                    model.model_id, gpu_free_mb, threshold, need, buffer_mb,
                )
                return False
        
        instance = model.instance
        logger.info(f"正在尝试将模型 {model.model_id} 回迁至 GPU...")
        
        # LLM引擎特殊处理
        if model.model_id == "llm_engine":
            return await self._restore_llm_engine(model, instance)
        
        # 尝试move_to_gpu方法
        move_to_gpu = getattr(instance, "move_to_gpu", None)
        if callable(move_to_gpu):
            ok, err, timed_out = await self._call_maybe_async_detail(
                move_to_gpu, timeout=30.0,
            )
            if ok:
                model.device = "GPU"
                model.is_offloaded = False
                logger.info(f"模型 {model.model_id} 已成功搬移至 GPU")
            else:
                detail = ""
                if timed_out:
                    detail = "(搬移超时)"
                elif err:
                    detail = f"(原因: {err})"
                logger.warning("模型 %s 搬移至 GPU 失败 %s", model.model_id, detail)
            return bool(ok)
        
        # 尝试重新加载
        if model.load_func:
            logger.info(f"模型 {model.model_id} 不支持直接搬移，尝试重新加载至 GPU...")
            ok = await self._call_maybe_async(model.load_func, timeout=15.0)
            if ok:
                model.device = "GPU"
                model.is_offloaded = False
                logger.info(f"模型 {model.model_id} 已重新加载至 GPU")
            return bool(ok)
        
        return False
    
    async def _restore_llm_engine(self, model: ModelResource, instance: Any) -> bool:
        """恢复LLM引擎到GPU"""
        restore = getattr(instance, "restore_llm_to_gpu", None)
        if not callable(restore):
            return False
        
        ok, err, timed_out = await self._call_maybe_async_detail(
            restore, timeout=120.0,
        )
        
        if ok:
            model.device = "GPU"
            model.is_offloaded = False
            logger.info("LLM 引擎已成功回迁至 GPU")
        else:
            backend = getattr(instance, "_llm_backend", None)
            last_error = getattr(instance, "_last_llm_load_error", None)
            detail = ""
            if timed_out:
                detail = "(回迁超时，后台可能仍在加载)"
            elif err:
                detail = f"(原因: {err})"
            elif last_error:
                detail = f"(最后错误: {last_error})"
            logger.warning(
                "LLM 引擎回迁至 GPU 失败 backend=%s %s", backend, detail,
            )
        
        return bool(ok)
    
    async def offload_voice_services(self, models: Dict[str, ModelResource]):
        """卸载语音服务到CPU"""
        voice_models = ["tts_engine", "stt_engine", "svc_engine"]
        
        models_to_offload = []
        for mid in voice_models:
            model = models.get(mid)
            if model and model.is_loaded:
                models_to_offload.append((mid, model))
        
        if not models_to_offload:
            return
        
        logger.info("ResourceManager: Offloading voice services to CPU...")
        
        for mid, model in models_to_offload:
            # 尝试offload_func
            if model.offload_func:
                try:
                    if asyncio.iscoroutinefunction(model.offload_func):
                        await model.offload_func("release")
                    else:
                        await asyncio.to_thread(model.offload_func, "release")
                    logger.info(f"Offloaded {mid} via offload_func")
                except Exception as e:
                    logger.warning(f"Failed to offload {mid} via offload_func: {e}")
            
            # 尝试instance的move_to_cpu
            elif model.instance:
                if hasattr(model.instance, "move_to_cpu"):
                    try:
                        if asyncio.iscoroutinefunction(model.instance.move_to_cpu):
                            await model.instance.move_to_cpu()
                        else:
                            await asyncio.to_thread(model.instance.move_to_cpu)
                        logger.info(f"Moved {mid} to CPU via move_to_cpu")
                        model.device = "CPU"
                        model.vram_usage_mb = 0
                    except Exception as e:
                        logger.warning(f"Failed to move {mid} to CPU: {e}")
    
    async def _call_maybe_async(
        self, func: Callable, *args, timeout: float = 10.0, **kwargs
    ) -> bool:
        """调用可能是异步的函数"""
        try:
            if asyncio.iscoroutinefunction(func):
                await asyncio.wait_for(
                    asyncio.shield(func(*args, **kwargs)), timeout=timeout
                )
            else:
                await asyncio.wait_for(
                    asyncio.to_thread(func, *args, **kwargs), timeout=timeout
                )
            return True
        except Exception:
            return False
    
    async def _call_maybe_async_detail(
        self, func: Callable, *args, timeout: float = 10.0, **kwargs
    ) -> Tuple[bool, Optional[str], bool]:
        """调用可能是异步的函数（返回详细信息）"""
        try:
            if asyncio.iscoroutinefunction(func):
                await asyncio.wait_for(
                    asyncio.shield(func(*args, **kwargs)), timeout=timeout
                )
            else:
                await asyncio.wait_for(
                    asyncio.to_thread(func, *args, **kwargs), timeout=timeout
                )
            return True, None, False
        except asyncio.TimeoutError:
            return False, "timeout", True
        except Exception as e:
            return False, str(e), False
    
    def clear_torch_cache(self):
        """清理PyTorch缓存"""
        _torch = _get_torch()
        if _torch and _torch.cuda.is_available():
            try:
                _torch.cuda.empty_cache()
                if hasattr(_torch.cuda, "ipc_collect"):
                    _torch.cuda.ipc_collect()
            except Exception as e:
                logger.debug(f"清理PyTorch缓存失败: {e}")
