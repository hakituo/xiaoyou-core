#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
图像管理器
负责管理图像模型的生命周期和图像生成处理
"""

import asyncio
import logging
import os
import uuid
import tempfile
from datetime import datetime
from typing import Dict, Any, Optional, Union
from pathlib import Path

# 导入必要的机器学习库
import torch
from diffusers import FluxPipeline # 用于类型检查

# 导入新的模型加载器模块
from core.image.model_loader import ModelLoader, ModelDiscovery, SD15_LOCAL_PATH, SDXL_LOCAL_PATH
from config.integrated_config import get_settings

# Constants
SD15_BASE_DIR = "d:\\AI\\xiaoyou-core\\models\\img\\sd1.5"
SD15_CHECKPOINT_DIR = os.path.join(SD15_BASE_DIR, "check_point")
SD15_LORA_DIR = os.path.join(SD15_BASE_DIR, "lora")

SDXL_BASE_DIR = "d:\\AI\\xiaoyou-core\\models\\img\\sdxl"
SDXL_CHECKPOINT_DIR = os.path.join(SDXL_BASE_DIR, "checkpoints")
SDXL_LORA_DIR = os.path.join(SDXL_BASE_DIR, "lora")

# 导入项目模块
# 注意：确保这些模块的路径在 sys.path 中
try:
    from core.utils.logger import get_logger
    from core.services.scheduler.task_scheduler import get_global_scheduler, TaskPriority
    from core.model_registry import global_model_registry
    from core.core_engine.config_manager import get_config_manager
    from core.image.prompt_processor import get_global_prompt_processor, process_image_prompt
    from core.resource_manager import (
        get_global_resource_manager, 
        ResourcePriority, 
        get_current_memory_usage,
        cleanup_memory
    )
except ImportError as e:
    print(f"CRITICAL: Failed to import core modules: {e}")
    # 提供一个备用的 get_logger
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("IMAGE_MANAGER_FALLBACK")
    print("Using fallback logger.")
    
    # 定义备用函数和类，以允许文件至少能被解析
    def get_global_resource_manager(): return None
    def get_global_prompt_processor(): return None
    def process_image_prompt(prompt, **kwargs): return {**kwargs, "prompt": prompt, "negative_prompt": ""}
    
    class MockGlobalModelRegistry:
        def register(self, *args, **kwargs): pass
        def unload(self, *args, **kwargs): pass
    global_model_registry = MockGlobalModelRegistry()

    class MockResourceManager:
        def optimize_resources(self): pass
        def get_optimal_precision(self): return "fp16"
        def should_use_low_memory_mode(self): return True
        def register_memory_cleanup_callback(self, *args, **kwargs): pass
        def unregister_memory_cleanup_callback(self, *args, **kwargs): pass
        def register_model(self, *args, **kwargs): pass
        def unregister_model(self, *args, **kwargs): pass
        def is_memory_pressure_high(self): return False
        def record_resource_usage(self, *args, **kwargs): pass
    
    original_get_global_resource_manager = get_global_resource_manager
    async def get_global_resource_manager():
        return MockResourceManager()

    logger.warning("Core modules import failed. Using mock objects.")


logger = get_logger("IMAGE_MANAGER")

# 图像输出目录
# DEFAULT_IMAGE_OUTPUT_DIR = Path("d:\\AI\\xiaoyou-core") / "output" / "image"  # Deprecated

class ImageGenerationConfig:
    """
    图像生成配置类
    """
    def __init__(self,
                 width: Optional[int] = None,
                 height: Optional[int] = None,
                 num_inference_steps: Optional[int] = None,
                 guidance_scale: float = 7.5,
                 seed: Optional[int] = None,
                 negative_prompt: Optional[str] = None,
                 lora_path: Optional[str] = None,
                 lora_weight: float = 0.7,
                 **kwargs):
        settings = get_settings()
        self.width = width if width is not None else settings.model.image_gen_width
        self.height = height if height is not None else settings.model.image_gen_height
        self.num_inference_steps = num_inference_steps if num_inference_steps is not None else settings.model.image_gen_steps
        self.guidance_scale = guidance_scale
        self.seed = seed
        self.negative_prompt = negative_prompt
        self.lora_path = lora_path
        self.lora_weight = lora_weight
        self.additional_params = kwargs

class ImageManager:
    """
    图像管理器类
    负责图像模型的初始化、图像生成和资源管理
    """
    def __init__(self):
        self._models: Dict[str, Any] = {}
        self._default_model_id: Optional[str] = None
        self._is_initialized = False
        self._lock = asyncio.Lock()
        
        settings = get_settings()
        self._output_dir = Path(settings.model.image_output_dir)
        if not self._output_dir.is_absolute():
            self._output_dir = Path.cwd() / self._output_dir
        
        # 确保输出目录存在
        self._ensure_output_dir()
        
        # 资源管理器
        self._resource_manager = None
        
        # 性能统计
        self._performance_stats = {
            'total_generations': 0,
            'total_time': 0,
            'avg_time': 0,
            'peak_memory': 0
        }
        
        logger.info("图像管理器已初始化")
    
    def _ensure_output_dir(self):
        """
        确保输出目录存在
        """
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"图像输出目录: {self._output_dir}")
        except Exception as e:
            logger.error(f"创建图像输出目录失败: {e}")
    
    async def initialize(self) -> bool:
        """
        初始化图像管理器
        """
        if self._is_initialized:
            return True
        
        try:
            # 加载配置
            settings = get_settings()
            default_model = settings.model.default_image_model
            
            # 设置输出目录（如果配置中有）
            # if "output_dir" in image_config:
            #    self._output_dir = Path(image_config["output_dir"])
            #    self._ensure_output_dir()
            
            # 尝试获取资源管理器
            try:
                self._resource_manager = await get_global_resource_manager()
                if self._resource_manager:
                    self._resource_manager.register_memory_cleanup_callback(self._cleanup_memory)
            except Exception as resource_err:
                logger.warning(f"获取资源管理器失败: {resource_err}，将在无资源管理器的情况下继续")
                self._resource_manager = None
            
            # 初始化默认模型
            if default_model:
                try:
                    await self.load_model(
                        default_model,
                        model_type="diffusion"
                    )
                except Exception as model_err:
                    logger.warning(f"初始化默认模型失败: {model_err}，将继续初始化")
            
            self._is_initialized = True
            logger.info("图像管理器初始化完成")
            return True
        except Exception as e:
            logger.error(f"图像管理器初始化失败: {e}")
            self._is_initialized = True # 即使失败也标记，避免重复尝试
            return False # 返回 False
    
    async def load_model(self, model_id: str, model_type: str = "diffusion", config: Optional[Dict[str, Any]] = None) -> bool:
        """
        加载图像模型
        """
        async with self._lock:
            try:
                if model_id in self._models:
                    logger.info(f"模型 {model_id} 已加载")
                    return True
                
                # 资源优化准备
                low_cpu_mem_usage = True
                if self._resource_manager:
                    await self._resource_manager.optimize_resources()
                    if config is None: config = {}
                    config['generation'] = config.get('generation', {})
                    low_cpu_mem_usage = self._resource_manager.should_use_low_memory_mode()
                
                logger.info(f"正在加载真实图像模型: {model_id} (类型: {model_type})")
                
                # 1. 解析模型路径
                resolved_path = ModelDiscovery.resolve_model_path(model_id)
                if not resolved_path:
                    # 如果解析失败，但它是HugginFace格式，可能ModelDiscovery没判断对，但ModelLoader会尝试
                    # 这里我们相信ModelDiscovery的判断，如果它返回None且是本地路径，那就是不存在
                    # 但为了兼容，我们还是用传入的 model_id 试一试，或者抛出错误
                    if os.path.exists(model_id):
                        resolved_path = model_id
                    elif '/' in model_id: # 在线模型
                        resolved_path = model_id
                    else:
                        logger.error(f"无法解析模型路径: {model_id}")
                        raise FileNotFoundError(f"模型路径不存在: {model_id}")
                
                logger.info(f"使用模型路径: {resolved_path}")
                
                # 2. 加载模型
                try:
                    real_model = await asyncio.to_thread(
                        ModelLoader.load_pipeline,
                        resolved_path,
                        model_type,
                        low_cpu_mem_usage
                    )
                except Exception as load_err:
                    logger.error(f"Diffusers 加载失败: {load_err}")
                    import traceback
                    traceback.print_exc()
                    raise load_err

                model_instance = {
                    "model_id": model_id,
                    "model_type": model_type,
                    "config": config,
                    "model": real_model,
                    "loaded_at": asyncio.get_event_loop().time()
                }
                
                # 3. 注册模型
                try:
                    self._models[model_id] = model_instance
                    logger.info(f"模型 {model_id} 已添加到模型字典，字典长度: {len(self._models)}")
                except Exception as dict_err:
                    logger.error(f"将模型添加到字典失败: {dict_err}")
                    raise
                
                try:
                    global_model_registry.register_model(f"image_{model_id}", model_instance)
                except Exception as registry_err:
                    logger.warning(f"注册模型到全局注册表失败 (将继续使用): {registry_err}")
                
                if self._resource_manager:
                    try:
                        self._resource_manager.register_model(model_id=model_id, model_type='image_gen', priority=ResourcePriority.MEDIUM, load_func=lambda: True, unload_func=lambda: True, memory_usage_mb=500)
                    except Exception as resource_err:
                        logger.warning(f"注册模型到资源管理器失败 (将继续使用): {resource_err}")
                
                # 设置默认模型
                try:
                    self._default_model_id = model_id
                    logger.info(f"已设置默认图像模型ID: {self._default_model_id}")
                except Exception as default_err:
                    logger.error(f"设置默认模型失败: {default_err}")
                
                logger.info(f"图像模型加载成功: {model_id}")
                return True
            
            except Exception as e:
                logger.error(f"加载图像模型失败 {model_id}: {e}")
                import traceback
                traceback.print_exc()
                return False
    
    async def unload_model(self, model_id: Optional[str] = None) -> bool:
        """
        卸载图像模型
        """
        async with self._lock:
            try:
                if model_id is None:
                    model_id = self._default_model_id
                
                if model_id is None or model_id not in self._models:
                    logger.error(f"模型不存在: {model_id}")
                    return False
                
                logger.info(f"正在卸载图像模型: {model_id}")
                
                try:
                    global_model_registry.unregister_model(f"image_{model_id}")
                except Exception as e:
                    logger.error(f"从模型注册表移除失败: {e}")
                
                if self._resource_manager:
                    self._resource_manager.unregister_model(model_id)
                
                # 显式删除模型对象以帮助释放 VRAM
                if "model" in self._models[model_id]:
                    del self._models[model_id]["model"]
                    
                del self._models[model_id]
                
                # 垃圾回收
                import gc
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                
                if self._default_model_id == model_id:
                    if self._models:
                        self._default_model_id = next(iter(self._models.keys()))
                        logger.info(f"设置新的默认图像模型: {self._default_model_id}")
                    else:
                        self._default_model_id = None
                
                logger.info(f"图像模型卸载成功: {model_id}")
                return True
            except Exception as e:
                logger.error(f"卸载图像模型失败 {model_id}: {e}")
                return False
    
    async def list_models(self) -> Dict[str, Any]:
        """
        List available models on disk (SD1.5 checkpoints, LoRAs, and SDXL)
        """
        models = {
            "sd15": {
                "checkpoints": [],
                "loras": []
            },
            "sdxl": {
                "models": [],
                "loras": []
            }
        }

        # Scan SD1.5 Checkpoints
        if os.path.exists(SD15_CHECKPOINT_DIR):
            for f in os.listdir(SD15_CHECKPOINT_DIR):
                if f.endswith('.safetensors') or f.endswith('.ckpt'):
                    models["sd15"]["checkpoints"].append({
                        "name": f,
                        "path": os.path.join(SD15_CHECKPOINT_DIR, f)
                    })
        
        # Scan SD1.5 LoRAs
        if os.path.exists(SD15_LORA_DIR):
            for f in os.listdir(SD15_LORA_DIR):
                if f.endswith('.safetensors') or f.endswith('.pt'):
                     models["sd15"]["loras"].append({
                        "name": f,
                        "path": os.path.join(SD15_LORA_DIR, f)
                    })

        # Scan SDXL Checkpoints
        if os.path.exists(SDXL_CHECKPOINT_DIR):
            for f in os.listdir(SDXL_CHECKPOINT_DIR):
                if f.endswith('.safetensors') or f.endswith('.ckpt'):
                    models["sdxl"]["models"].append({
                        "name": f,
                        "path": os.path.join(SDXL_CHECKPOINT_DIR, f)
                    })

        # Scan SDXL LoRAs
        if os.path.exists(SDXL_LORA_DIR):
            for f in os.listdir(SDXL_LORA_DIR):
                if f.endswith('.safetensors') or f.endswith('.pt'):
                     models["sdxl"]["loras"].append({
                        "name": f,
                        "path": os.path.join(SDXL_LORA_DIR, f)
                    })

        # Add default SDXL model if local path exists and list is empty
        if os.path.exists(SDXL_LOCAL_PATH) and not models["sdxl"]["models"]:
             models["sdxl"]["models"].append({
                "name": "SDXL Base 1.0 (Default)",
                "path": SDXL_LOCAL_PATH,
                "type": "sdxl"
            })
            
        return models

    async def generate_image(self,
                           prompt: str,
                           config: Optional[ImageGenerationConfig] = None,
                           model_id: Optional[str] = None,
                           save_to_file: bool = True) -> Dict[str, Any]:
        """
        生成图像
        """
        logger.info(f"[图像生成请求] 提示词: {prompt[:30]}...")
        
        if not prompt or not prompt.strip():
            logger.error("[图像生成请求] 空提示词")
            return {"success": False, "error": "空提示词", "error_code": "EMPTY_PROMPT"}
        
        if not self._is_initialized:
            logger.info("[图像生成请求] 图像管理器未初始化，正在初始化...")
            await self.initialize()
        
        # ==========================================================
        # 自动加载逻辑 (使用 ModelDiscovery 简化)
        # ==========================================================
        
        use_model_id = model_id or self._default_model_id
        
        # 检查模型是否已加载
        if use_model_id is None or use_model_id not in self._models:
            logger.info(f"[图像生成请求] 模型 {use_model_id} 未加载，尝试自动查找并加载...")
            
            # 查找最佳匹配模型
            found_model_path = ModelDiscovery.find_best_match_model(use_model_id)
            
            if found_model_path:
                logger.info(f"[图像生成请求] 找到模型文件: {found_model_path}")
                load_success = await self.load_model(found_model_path)
                if load_success:
                    use_model_id = found_model_path
                    self._default_model_id = found_model_path
                else:
                    logger.error(f"[图像生成请求] 加载模型失败: {found_model_path}")
            else:
                logger.error(f"[图像生成请求] 未找到任何可用模型 (目标: {use_model_id})")
                return {
                    "success": False,
                    "error": f"模型 {use_model_id} 不可用，自动加载失败",
                    "error_code": "MODEL_NOT_AVAILABLE"
                }
        
        # 最终确认
        if use_model_id is None or use_model_id not in self._models:
             return {
                "success": False,
                "error": f"模型 {use_model_id} 最终不可用",
                "error_code": "MODEL_NOT_AVAILABLE"
            }
            
        if config is None:
            config = ImageGenerationConfig()

        # [SDXL Compatibility]
        # Check if current model is SDXL (by path or name)
        is_sdxl = False
        if "sdxl" in str(use_model_id).lower() or "stable-diffusion-xl" in str(use_model_id).lower():
            is_sdxl = True
            logger.info(f"[图像生成] 检测到 SDXL 模型: {use_model_id}")
            # SDXL LoRA Support enabled
            if config.lora_path:
                logger.info(f"[图像生成] SDXL 模式下加载 LoRA: {config.lora_path}")

        
        # 直接执行图像生成
        try:
            result = await self._generate_image_impl(
                prompt=prompt,
                config=config,
                model_id=use_model_id,
                save_to_file=save_to_file
            )
            logger.info(f"[图像生成请求] 图像生成完成，结果: {'成功' if result.get('success', False) else '失败'}")
            return result
        except Exception as e:
            logger.error(f"[图像生成请求] 图像生成过程发生异常: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": f"图像生成过程发生异常: {str(e)}",
                "error_code": "UNKNOWN_ERROR",
                "prompt": prompt[:50] + "..."
            }
    
    async def _generate_image_impl(self,
                                 prompt: str,
                                 config: ImageGenerationConfig,
                                 model_id: str,
                                 save_to_file: bool = True) -> Dict[str, Any]:
        """
        实际的图像生成实现
        """
        import traceback
        from PIL import Image, ImageDraw
        
        start_time = asyncio.get_event_loop().time()
        generation_id = str(uuid.uuid4())
        start_memory = get_current_memory_usage() if self._resource_manager else 0
        
        logger.info(f"[图像生成-{generation_id}] 开始 - 模型: {model_id}")
        
        try:
            # 1. 处理提示词
            try:
                processed_input = await process_image_prompt(
                    prompt=prompt, width=config.width, height=config.height,
                    num_inference_steps=config.num_inference_steps, guidance_scale=config.guidance_scale,
                    seed=config.seed, custom_negative=config.negative_prompt
                )
            except Exception as prompt_error:
                logger.error(f"[图像生成-{generation_id}] 提示词处理失败: {prompt_error}")
                processed_input = {"prompt": prompt, "negative_prompt": config.negative_prompt or "", "width": config.width, "height": config.height, "num_inference_steps": config.num_inference_steps, "guidance_scale": config.guidance_scale, "seed": config.seed}
            
            processed_prompt = processed_input["prompt"]
            width = processed_input["width"]
            height = processed_input["height"]
            num_inference_steps = processed_input["num_inference_steps"]
            guidance_scale = processed_input["guidance_scale"]
            seed = processed_input.get("seed")
            
            # 2. 资源检查
            if self._resource_manager:
                try:
                    if self._resource_manager.is_memory_pressure_high():
                        logger.warning(f"[图像生成-{generation_id}] 检测到高内存压力，执行内存清理")
                        await self._cleanup_memory()
                except AttributeError:
                    pass
            
            # 3. 准备文件路径
            image_id = str(uuid.uuid4())[:8]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_filename = f"image_{timestamp}_{image_id}.png"
            image_path = str(self._output_dir / image_filename)
            
            try:
                await asyncio.to_thread(os.makedirs, self._output_dir, exist_ok=True)
            except Exception:
                image_path = str(Path(tempfile.gettempdir()) / image_filename)
            
            # 4. 生成图像
            model_info = self._models.get(model_id)
            if not model_info or "model" not in model_info:
                raise ValueError(f"模型 {model_id} 未加载或无效")
            
            model = model_info["model"]
            
            # 确定生成器
            generator = None
            if seed:
                generator = torch.Generator(device="cuda" if torch.cuda.is_available() else "cpu").manual_seed(seed)

            # 执行生成
            if isinstance(model, FluxPipeline):
                logger.info(f"[图像生成-{generation_id}] 调用 Flux Pipeline...")
                pipeline_output = await asyncio.to_thread(
                    model,
                    prompt=processed_prompt,
                    width=width, height=height,
                    num_inference_steps=num_inference_steps,
                    guidance_scale=guidance_scale,
                    generator=generator,
                    output_type="pil"
                )
                image_result = pipeline_output.images[0]
            else:
                # 通用 SD/SDXL 调用
                logger.info(f"[图像生成-{generation_id}] 调用通用 Pipeline...")
                gen_kwargs = {
                    "prompt": processed_prompt,
                    "width": width, "height": height,
                    "num_inference_steps": num_inference_steps,
                    "guidance_scale": guidance_scale,
                    "generator": generator,
                    "output_type": "pil"
                }
                
                # LoRA 处理 (简化版)
                # 检查是否为 SDXL 模型，如果是则跳过 LoRA 加载
                is_sdxl = False
                if model_id and ("sdxl" in model_id.lower() or "xl" in model_id.lower()):
                     is_sdxl = True
                
                # Check actual model class
                if "StableDiffusionXLPipeline" in str(type(model)):
                    is_sdxl = True

                if not is_sdxl:
                    try:
                        if hasattr(config, 'lora_path') and config.lora_path:
                            lora_path = config.lora_path
                            # 尝试解析 LoRA 路径
                            if not os.path.isabs(lora_path):
                                # 尝试在 SD1.5 LoRA 目录查找
                                potential_path = os.path.join(SD15_LORA_DIR, lora_path)
                                if os.path.exists(potential_path):
                                    lora_path = potential_path
                                else:
                                    # 尝试直接作为文件名查找
                                    found = False
                                    if os.path.exists(SD15_LORA_DIR):
                                        for f in os.listdir(SD15_LORA_DIR):
                                            if f == lora_path or f.startswith(lora_path):
                                                lora_path = os.path.join(SD15_LORA_DIR, f)
                                                found = True
                                                break
                                    if not found:
                                        logger.warning(f"LoRA文件未找到: {config.lora_path}")

                            if hasattr(model, 'load_lora_weights'):
                                logger.info(f"加载 LoRA: {lora_path} (权重: {getattr(config, 'lora_weight', 0.7)})")
                                model.load_lora_weights(lora_path)
                                if hasattr(model, 'fuse_lora'):
                                    try:
                                        model.fuse_lora(lora_scale=float(getattr(config, 'lora_weight', 0.7)))
                                    except Exception: pass
                    except Exception as lora_err:
                        logger.warning(f"LoRA应用失败: {lora_err}")
                else:
                    if hasattr(config, 'lora_path') and config.lora_path:
                        logger.info(f"SDXL模型检测到 LoRA 请求 ({config.lora_path})，但已跳过 (防止后端崩溃)")

                pipeline_output = await asyncio.to_thread(model, **gen_kwargs)
                image_result = pipeline_output.images[0]
            
            # 5. 保存图像
            await asyncio.to_thread(image_result.save, image_path, 'PNG')
            file_size = await asyncio.to_thread(os.path.getsize, image_path)
            file_size = file_size / 1024
            logger.info(f"[图像生成-{generation_id}] 保存成功: {image_path} ({file_size:.2f}KB)")
            
            # 6. 构建结果
            generation_time = asyncio.get_event_loop().time() - start_time
            memory_used = (get_current_memory_usage() if self._resource_manager else 0) - start_memory
            
            self._update_performance_stats(generation_time)
            
            return {
                "success": True,
                "image_id": image_id,
                "generation_id": generation_id,
                "prompt": processed_prompt,
                "model_id": model_id,
                "generation_time": generation_time,
                "image_path": image_path if save_to_file else None,
                "metadata": { "timestamp": timestamp, "memory_used_mb": memory_used }
            }
            
        except Exception as e:
            logger.error(f"[图像生成-{generation_id}] 失败: {e}")
            return {
                "success": False, 
                "error": str(e),
                "error_code": "IMAGE_GENERATION_FAILED",
                "prompt": prompt
            }

    async def get_available_models(self) -> Dict[str, Dict[str, Any]]:
        return {model_id: {
            "model_id": model_info["model_id"],
            "model_type": model_info["model_type"],
            "loaded_at": model_info["loaded_at"],
            "is_default": model_id == self._default_model_id
        } for model_id, model_info in self._models.items()}
    
    async def shutdown(self):
        logger.info("正在关闭图像管理器...")
        for model_id in list(self._models.keys()):
            await self.unload_model(model_id)
        if self._resource_manager:
            self._resource_manager.unregister_memory_cleanup_callback(self._cleanup_memory)
        self._is_initialized = False
        logger.info("图像管理器已关闭")
    
    async def _cleanup_memory(self):
        logger.info("执行内存清理...")
        try:
            if len(self._models) > 1:
                for model_id in list(self._models.keys()):
                    if model_id != self._default_model_id:
                        await self.unload_model(model_id)
            import gc
            gc.collect()
            return True
        except Exception as e:
            logger.error(f"内存清理失败: {str(e)}")
            return False
    
    def _update_performance_stats(self, execution_time: float):
        try:
            self._performance_stats['total_generations'] += 1
            self._performance_stats['total_time'] += execution_time
            self._performance_stats['avg_time'] = (self._performance_stats['total_time'] / self._performance_stats['total_generations'])
            current_memory = get_current_memory_usage()
            if current_memory > self._performance_stats['peak_memory']:
                self._performance_stats['peak_memory'] = current_memory
        except Exception:
            pass


# Global Image Manager Instance
global_image_manager = None

async def get_image_manager() -> ImageManager:
    """
    Get the global ImageManager instance
    """
    global global_image_manager
    if global_image_manager is None:
        global_image_manager = ImageManager()
        await global_image_manager.initialize()
    return global_image_manager
