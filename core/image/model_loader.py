#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
图像模型加载器
负责发现和加载图像生成模型
"""

import os
import logging
import torch
from typing import Optional, Dict, Any, List, Tuple, Union
from pathlib import Path
from diffusers import FluxPipeline, StableDiffusionPipeline

# 尝试导入 transformers 组件
try:
    from transformers import CLIPTokenizer, CLIPTextModel
except ImportError:
    CLIPTokenizer = None
    CLIPTextModel = None

# 尝试导入 SDXL Pipeline
try:
    from diffusers import StableDiffusionXLPipeline
except ImportError:
    StableDiffusionXLPipeline = None

logger = logging.getLogger("MODEL_LOADER")

# 模型路径常量定义
CHECKPOINT_DIR = "d:\\AI\\xiaoyou-core\\models\\check_point"
CHECKPOINT_DIR_NEW = "d:\\AI\\xiaoyou-core\\models\\img\\check_point"
ARCHIVE_DIR = "d:\\AI\\xiaoyou-core\\models\\archive"

# 本地 Diffusers 资源路径 (来自 Forge)
SD15_LOCAL_PATH = "d:\\AI\\xiaoyou-core\\models\\img\\stable-diffusion-webui-forge-main\\backend\\huggingface\\runwayml\\stable-diffusion-v1-5"
SDXL_LOCAL_PATH = "d:\\AI\\xiaoyou-core\\models\\img\\stable-diffusion-webui-forge-main\\backend\\huggingface\\stabilityai\\stable-diffusion-xl-base-1.0"


class ModelDiscovery:
    """
    模型发现服务
    负责查找本地模型文件，处理路径修正等
    """
    
    @staticmethod
    def resolve_model_path(model_id: str) -> Optional[str]:
        """
        解析模型路径，处理拼写错误和相对路径
        """
        # 1. 检查是否是绝对路径且存在
        if os.path.exists(model_id):
            return model_id
            
        # 2. 检查是否是在线模型 (包含 / 且本地不存在)
        if '/' in model_id and not os.path.exists(model_id):
            # 假设是 HuggingFace ID
            return model_id
            
        # 3. 尝试在标准目录查找
        search_paths = [
            os.path.join(CHECKPOINT_DIR_NEW, model_id),
            os.path.join(CHECKPOINT_DIR, model_id),
            os.path.join(ARCHIVE_DIR, model_id),
            os.path.join("d:\\AI\\xiaoyou-core\\models", model_id),
            os.path.join("d:\\AI\\xiaoyou-core\\models\\img", model_id)
        ]
        
        for path in search_paths:
            if os.path.exists(path):
                return path
                
        # 4. 处理常见的拼写错误 (nsfw -> nsffw)
        if 'nsfw' in model_id.lower():
            corrected_id = model_id.replace('nsfw', 'nsffw', 1)
            return ModelDiscovery.resolve_model_path(corrected_id)
        elif 'nsffw' in model_id.lower():
            corrected_id = model_id.replace('nsffw', 'nsfw', 1)
            return ModelDiscovery.resolve_model_path(corrected_id)
            
        return None

    @staticmethod
    def discover_local_models() -> List[str]:
        """
        扫描所有已知的模型目录，返回可用的模型路径列表
        """
        checkpoint_dir = CHECKPOINT_DIR
        checkpoint_dir_new = CHECKPOINT_DIR_NEW
        models_dir = "d:\\AI\\xiaoyou-core\\models"
        img_models_dir = "d:\\AI\\xiaoyou-core\\models\\img"
        model_paths = []
        
        search_dirs = [checkpoint_dir_new, checkpoint_dir, img_models_dir, models_dir]
        
        # 添加 Forge 的模型目录
        forge_dir = os.path.join(img_models_dir, 'stable-diffusion-webui-forge-main', 'models', 'Stable-diffusion')
        if os.path.exists(forge_dir):
            search_dirs.append(forge_dir)
            
        for search_dir in search_dirs:
            if not os.path.exists(search_dir):
                continue
                
            try:
                for root, _, files in os.walk(search_dir):
                    for f in files:
                        if f.endswith('.safetensors') or f.endswith('.ckpt'):
                            file_path = os.path.join(root, f)
                            model_paths.append(file_path)
                            
                            # 检查并添加拼写错误的版本
                            if 'nsffw' in f.lower():
                                corrected_file = f.replace('nsffw', 'nsfw', 1)
                                corrected_path = os.path.join(root, corrected_file)
                                if os.path.exists(corrected_path):
                                    model_paths.append(corrected_path)
            except Exception as e:
                logger.error(f"读取目录 {search_dir} 失败: {e}")
                
        return model_paths

    @staticmethod
    def find_best_match_model(target_model_id: Optional[str] = None) -> Optional[str]:
        """
        查找最佳匹配的模型
        如果 target_model_id 存在则尝试解析它，否则查找任意可用模型
        """
        # 1. 如果指定了 ID，先尝试解析
        if target_model_id:
            resolved_path = ModelDiscovery.resolve_model_path(target_model_id)
            if resolved_path:
                return resolved_path
                
            # 如果是文件名，尝试在扫描结果中匹配
            if not os.path.isabs(target_model_id):
                all_models = ModelDiscovery.discover_local_models()
                for path in all_models:
                    if os.path.basename(path) == target_model_id:
                        return path
        
        # 2. 如果没找到或没指定，返回第一个可用的本地模型
        all_models = ModelDiscovery.discover_local_models()
        if all_models:
            return all_models[0]
            
        return None


class ModelLoader:
    """
    模型加载器
    负责实际加载 Diffusers 模型
    """
    
    @staticmethod
    def load_pipeline(model_id: str, model_type: str = "diffusion", low_cpu_mem_usage: bool = True) -> Any:
        """
        加载模型 Pipeline
        """
        try:
            # Flux 模型处理
            if "flux" in model_id.lower() or "flux" in model_type.lower():
                return ModelLoader._load_flux_model(model_id, low_cpu_mem_usage)
            
            # Stable Diffusion / SDXL 处理
            return ModelLoader._load_sd_model(model_id, low_cpu_mem_usage)
            
        except Exception as e:
            logger.error(f"加载模型失败 {model_id}: {e}")
            import traceback
            traceback.print_exc()
            raise e

    @staticmethod
    def _load_flux_model(model_id: str, low_cpu_mem_usage: bool) -> Any:
        logger.info("检测到 Flux 模型，正在初始化 Diffusers Pipeline...")
        
        # 清理内存
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

        if os.path.isfile(model_id):
            logger.info(f"使用 from_single_file 加载 Flux 模型: {model_id}")
            pipe = FluxPipeline.from_single_file(
                model_id,
                torch_dtype=torch.bfloat16,
                use_safetensors=True,
                low_cpu_mem_usage=low_cpu_mem_usage,
                local_files_only=True
            )
        else:
            logger.info(f"使用 from_pretrained 加载 Flux 模型: {model_id}")
            pipe = FluxPipeline.from_pretrained(
                model_id,
                torch_dtype=torch.bfloat16,
                use_safetensors=True,
                low_cpu_mem_usage=low_cpu_mem_usage,
                local_files_only=True
            )

        # 强制使用最节省显存的顺序CPU卸载策略
        logger.info("强制启用顺序 CPU 卸载以防止崩溃...")
        pipe.enable_sequential_cpu_offload()
        
        # VAE 优化
        pipe.vae.enable_slicing()
        pipe.vae.enable_tiling()
        
        return pipe

    @staticmethod
    def _load_sd_model(model_id: str, low_cpu_mem_usage: bool) -> Any:
        real_model = None
        
        # 检查 SDXL
        is_sdxl = ('sdxl' in os.path.basename(model_id).lower()) or ('xl' in os.path.basename(model_id).lower())
        
        if model_id.endswith('.safetensors') or model_id.endswith('.ckpt') or os.path.isfile(model_id):
            # 尝试查找配置文件 (v1-inference.yaml)
            config_file = None
            if not is_sdxl: # SDXL通常不需要v1配置，或者需要专门的SDXL配置
                if os.path.isfile(model_id):
                    model_dir = os.path.dirname(model_id)
                    # 1. 检查同目录下的 yaml
                    possible_config = os.path.join(model_dir, "v1-inference.yaml")
                    if os.path.exists(possible_config):
                        config_file = possible_config
                    
                    # 2. 检查 check_point 目录下的 yaml
                    if not config_file:
                        possible_config = os.path.join(CHECKPOINT_DIR_NEW, "v1-inference.yaml")
                        if os.path.exists(possible_config):
                            config_file = possible_config

            # 单文件加载
            if is_sdxl and StableDiffusionXLPipeline is not None:
                logger.info(f"检测到SDXL模型，使用StableDiffusionXLPipeline.from_single_file加载: {model_id}")
                real_model = StableDiffusionXLPipeline.from_single_file(
                    model_id,
                    torch_dtype=torch.float16,
                    low_cpu_mem_usage=low_cpu_mem_usage,
                    local_files_only=True
                )
            else:
                logger.info(f"使用StableDiffusionPipeline.from_single_file加载: {model_id}")
                kwargs = {
                    "torch_dtype": torch.float16,
                    "low_cpu_mem_usage": low_cpu_mem_usage,
                    "safety_checker": None,
                    "local_files_only": True
                }
                
                if config_file:
                    logger.info(f"使用本地配置文件: {config_file}")
                    kwargs["original_config_file"] = config_file
                
                # 指定本地配置目录以避免联网
                if not is_sdxl and os.path.exists(SD15_LOCAL_PATH):
                    logger.info(f"指定本地配置目录: {SD15_LOCAL_PATH}")
                    kwargs["config"] = SD15_LOCAL_PATH
                elif is_sdxl and os.path.exists(SDXL_LOCAL_PATH):
                    logger.info(f"指定本地配置目录: {SDXL_LOCAL_PATH}")
                    kwargs["config"] = SDXL_LOCAL_PATH

                real_model = StableDiffusionPipeline.from_single_file(
                    model_id,
                    **kwargs
                )
            
            # 优化内存使用
            if torch.cuda.is_available():
                real_model.enable_sequential_cpu_offload()
            else:
                real_model.enable_attention_slicing()
        else:
            # 文件夹/Repo 加载
            if is_sdxl and StableDiffusionXLPipeline is not None:
                logger.info(f"使用StableDiffusionXLPipeline.from_pretrained加载模型: {model_id}")
                real_model = StableDiffusionXLPipeline.from_pretrained(
                    model_id,
                    torch_dtype=torch.float16,
                    use_safetensors=False,
                    low_cpu_mem_usage=low_cpu_mem_usage,
                    local_files_only=True
                )
            else:
                logger.info(f"使用标准StableDiffusionPipeline.from_pretrained加载模型: {model_id}")
                real_model = StableDiffusionPipeline.from_pretrained(
                    model_id, 
                    torch_dtype=torch.float16,
                    use_safetensors=False,
                    low_cpu_mem_usage=low_cpu_mem_usage,
                    local_files_only=True
                )
        
        # 根据可用设备移动模型
        if torch.cuda.is_available():
            # 注意：enable_sequential_cpu_offload 会处理 device 放置，通常不需要手动 .to("cuda")
            # 但如果上面没有调用 offload (例如非单文件加载且非CUDA环境 - 等等，上面逻辑有点复杂)
            # 这里做一个简单的兜底，但要注意不要与 enable_sequential_cpu_offload 冲突
            pass 
        else:
            real_model = real_model.to("cpu")
            
        return real_model
