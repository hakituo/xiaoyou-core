"""
模型管理器
使用单例模式集中管理所有模型的加载、卸载和检查
防止重复加载和内存溢出
增强支持量化加载选项和显存/资源检测
"""
import os
import logging
import gc
import threading
import time
import subprocess
import re
from typing import Dict, Optional, Union, List, Any, Tuple
import torch
import psutil
import numpy as np
import asyncio
from typing import Any as _Any
try:
    from config.config import Config
except ImportError:
    Config = None

try:
    from watchdog.observers import Observer as _Observer
    from watchdog.events import FileSystemEventHandler as _FSEH
except Exception:
    _Observer = None
    _FSEH = object

# 获取logger
logger = logging.getLogger(__name__)


class ModelInfo:
    """
    模型信息类
    存储每个模型的元数据和状态
    """
    def __init__(self, model_name: str, model_type: str, model_path: str):
        self.model_name = model_name
        self.model_type = model_type  # 如 'llm', 'tts', 'stt', 'embedding', 'vision', 'image_gen'
        self.model_path = model_path
        self.load_time = None  # 加载时间戳
        self.last_used_time = None  # 最后使用时间戳
        self.is_loaded = False  # 模型是否已加载
        self.model_obj = None  # 模型对象
        self.tokenizer_obj = None  # 分词器对象（如果有）
        self.quantized = False  # 是否量化
        self.quantization_config = None  # 量化配置
        self.device = None  # 运行设备
        self.memory_used = None  # 内存使用估计值
        self.torch_dtype = None  # 数据类型
        self.load_options = {}  # 加载选项


class ModelManager:
    """
    模型管理器（单例模式）
    负责所有模型的生命周期管理
    """
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ModelManager, cls).__new__(cls)
                # 初始化实例属性
                cls._instance._models: Dict[str, ModelInfo] = {}
                cls._instance._registered_models: Dict[str, Dict] = {}
                cls._instance._processors: Dict[str, Any] = {}
                cls._instance._model_locks: Dict[str, threading.Lock] = {}
                cls._instance._global_lock = threading.RLock()
                cls._instance._max_models = int(os.environ.get('MAX_MODELS', 5))
                cls._instance._memory_threshold = float(os.environ.get('MODEL_MEMORY_THRESHOLD', 0.7))  # 70%
                cls._instance._pinned_models = set()
        return cls._instance
    
    def __init__(self):
        # 确保初始化代码只执行一次
        with self._global_lock:
            if not hasattr(self, '_initialized'):
                self._initialized = True
                # 初始化配置
                self._max_models = int(os.environ.get('MAX_MODELS', 5))
                self._memory_threshold = float(os.environ.get('MODEL_MEMORY_THRESHOLD', 0.7))  # 70%
                self._gpu_memory_threshold = float(os.environ.get('GPU_MEMORY_THRESHOLD', 0.8))  # 80%
                
                # 检测系统资源
                self.system_resources = self.detect_system_resources()
                
                logger.info(f"初始化模型管理器，最大模型数: {self._max_models}, 内存阈值: {self._memory_threshold}")
                logger.info(f"系统资源: {self.system_resources}")
                
                # 扫描模型
                self.scan_models()

    def scan_models(self):
        """扫描本地模型"""
        try:
            # 获取项目根目录
            root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            models_dir = os.path.join(root_dir, "models")
            
            logger.info(f"正在扫描模型目录: {models_dir}")
            
            if os.path.exists(models_dir):
                # 1. 扫描 LLM 目录
                llm_dir = os.path.join(models_dir, "llm")
                if os.path.exists(llm_dir):
                    for name in os.listdir(llm_dir):
                        path = os.path.join(llm_dir, name)
                        if os.path.isfile(path) and name.endswith(".gguf"):
                            model_name = os.path.splitext(name)[0]
                            if model_name not in self._models:
                                logger.info(f"发现本地 LLM 模型: {model_name}")
                                self.register_model(model_name, "llm", path)
                        elif os.path.isdir(path) and os.path.exists(os.path.join(path, "config.json")):
                             if name not in self._models:
                                logger.info(f"发现本地 LLM 模型: {name}")
                                self.register_model(name, "llm", path)

                # 3. 扫描 Image 目录
                img_dir = os.path.join(models_dir, "img")
                if not os.path.exists(img_dir):
                    img_dir = os.path.join(models_dir, "image")
                
                if os.path.exists(img_dir):
                    # 检查 check_point 子目录
                    ckpt_dir = os.path.join(img_dir, "check_point")
                    if os.path.exists(ckpt_dir):
                        for name in os.listdir(ckpt_dir):
                            path = os.path.join(ckpt_dir, name)
                            if os.path.isfile(path) and (name.endswith(".safetensors") or name.endswith(".ckpt")):
                                model_name = os.path.splitext(name)[0]
                                if model_name not in self._models:
                                    logger.info(f"发现本地图像模型: {model_name}")
                                    self.register_model(model_name, "image_gen", path)
                    
                    # 扫描 LORA 子目录
                    lora_dir = os.path.join(img_dir, "lora")
                    if os.path.exists(lora_dir):
                        for name in os.listdir(lora_dir):
                            path = os.path.join(lora_dir, name)
                            if os.path.isfile(path) and name.endswith(".safetensors"):
                                model_name = os.path.splitext(name)[0]
                                if model_name not in self._models:
                                    logger.info(f"发现本地 LORA 模型: {model_name}")
                                    self.register_model(model_name, "lora", path)

                    # 扫描 SDXL/Forge 目录 (已更新路径到 sdxl 文件夹内)
                    forge_dir = os.path.join(img_dir, "sdxl", "stable-diffusion-webui-forge-main", "models", "Stable-diffusion")
                    if os.path.exists(forge_dir):
                        logger.info(f"正在扫描 Forge 模型目录: {forge_dir}")
                        for name in os.listdir(forge_dir):
                            path = os.path.join(forge_dir, name)
                            if os.path.isfile(path) and (name.endswith(".safetensors") or name.endswith(".ckpt")):
                                model_name = os.path.splitext(name)[0]
                                if model_name not in self._models:
                                    logger.info(f"发现本地 SDXL/Forge 模型: {model_name}")
                                    self.register_model(model_name, "image_gen", path)
                    
                    # 扫描 Forge Lora 目录
                    forge_lora_dir = os.path.join(img_dir, "sdxl", "stable-diffusion-webui-forge-main", "models", "Lora")
                    if os.path.exists(forge_lora_dir):
                         logger.info(f"正在扫描 Forge Lora 目录: {forge_lora_dir}")
                         for name in os.listdir(forge_lora_dir):
                            path = os.path.join(forge_lora_dir, name)
                            if os.path.isfile(path) and name.endswith(".safetensors"):
                                model_name = os.path.splitext(name)[0]
                                if model_name not in self._models:
                                    logger.info(f"发现本地 Forge Lora 模型: {model_name}")
                                    self.register_model(model_name, "lora", path)

            # 4. 注册云端模型 (如果配置了 API Key)
            if Config and hasattr(Config, 'QIANWEN_API_KEY') and Config.QIANWEN_API_KEY and Config.QIANWEN_API_KEY != "your_api_key_here":
                if "qianwen-cloud" not in self._models:
                    logger.info("注册云端模型: qianwen-cloud")
                    # 使用特殊的路径标识云端模型
                    self.register_model("qianwen-cloud", "llm", "cloud:qianwen")
            elif Config and hasattr(Config, 'QIANWEN_API_KEY') and Config.QIANWEN_API_KEY == "your_api_key_here":
                 # 即使是默认key，也注册一个占位符，方便用户在前端看到并知道需要配置
                 if "qianwen-cloud-demo" not in self._models:
                    logger.info("注册云端模型演示: qianwen-cloud-demo")
                    self.register_model("qianwen-cloud-demo", "llm", "cloud:qianwen-demo")

            # 检查环境变量指定的模型
            env_path = os.environ.get("XIAOYOU_TEXT_MODEL_PATH")
            if env_path and os.path.exists(env_path):
                if os.path.isfile(env_path):
                     name = os.path.splitext(os.path.basename(env_path))[0]
                else:
                     name = os.path.basename(env_path)
                     
                if name not in self._models:
                    self.register_model(name, "llm", env_path)
                        
        except Exception as e:
            logger.error(f"扫描模型失败: {e}")

    def detect_system_resources(self) -> Dict[str, Any]:
        """检测系统资源"""
        # 获取CPU和内存使用率
        cpu_usage = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        
        # 尝试获取GPU使用率
        gpu_usage = 0
        gpu_info = {}
        
        if torch.cuda.is_available():
            try:
                # 获取GPU设备属性
                props = torch.cuda.get_device_properties(0)
                gpu_info = {
                    "name": props.name,
                    "total_memory_gb": props.total_memory / (1024**3)
                }
                
                # 尝试获取GPU利用率 (需要 pynvml 或 nvidia-smi)
                # 这里简单起见，如果安装了 pynvml 则使用
                try:
                    import pynvml
                    pynvml.nvmlInit()
                    handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    gpu_usage = util.gpu
                    pynvml.nvmlShutdown()
                except ImportError:
                    pass
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"获取GPU信息失败: {e}")

        resources = {
            "cpu_count": psutil.cpu_count(),
            "cpu_usage": cpu_usage,
            "memory_total_gb": memory.total / (1024**3),
            "memory_available_gb": memory.available / (1024**3),
            "memory_usage": memory.percent,
            "gpu_usage": gpu_usage,
            "has_gpu": torch.cuda.is_available(),
            "gpu": gpu_info
        }
        return resources

    def register_model(self, model_name: str, model_type: str, model_path: str):
        """注册模型"""
        with self._global_lock:
            if model_name not in self._models:
                self._models[model_name] = ModelInfo(model_name, model_type, model_path)
                # 自动检测量化状态
                if model_path.endswith(".gguf") or "cloud:" in model_path:
                    self._models[model_name].quantized = True
                logger.info(f"模型已注册: {model_name} ({model_type})")
    
    def load_model(self, model_name: str, **kwargs) -> Any:
        """加载模型"""
        with self._global_lock:
            if model_name not in self._models:
                raise ValueError(f"模型未注册: {model_name}")
            
            model_info = self._models[model_name]
            if model_info.is_loaded:
                model_info.last_used_time = time.time()
                return model_info.model_obj
            
            logger.info(f"正在加载模型: {model_name}")
            try:
                model, tokenizer = self._load_model_by_type(model_name, **kwargs)
                model_info.model_obj = model
                model_info.tokenizer_obj = tokenizer
                model_info.is_loaded = True
                model_info.load_time = time.time()
                model_info.last_used_time = time.time()
                logger.info(f"模型加载成功: {model_name}")
                return model
            except Exception as e:
                logger.error(f"加载模型失败 {model_name}: {e}")
                raise

    def unload_model(self, model_name: str):
        """卸载模型"""
        with self._global_lock:
            if model_name in self._models:
                model_info = self._models[model_name]
                if model_info.is_loaded:
                    model_info.model_obj = None
                    model_info.tokenizer_obj = None
                    model_info.is_loaded = False
                    gc.collect()
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    logger.info(f"模型已卸载: {model_name}")

    def get_loaded_models(self) -> List[str]:
        """获取已加载的模型列表"""
        return [name for name, info in self._models.items() if info.is_loaded]

    def list_models(self, model_type: str = None) -> List[Dict[str, Any]]:
        """
        获取所有注册的模型列表
        Args:
            model_type: 可选，按模型类型筛选 ('llm', 'image_gen', 'vision', etc.)
        """
        with self._global_lock:
            models_list = []
            for name, info in self._models.items():
                if model_type and info.model_type != model_type:
                    continue
                    
                models_list.append({
                    "id": info.model_name,  # Frontend expects 'id'
                    "name": info.model_name,
                    "type": info.model_type,
                    "path": info.model_path,
                    "is_loaded": info.is_loaded,
                    "load_time": info.load_time,
                    "last_used_time": info.last_used_time,
                    "quantized": info.quantized
                })
            return models_list

    def _load_model_by_type(self, model_name: str, **kwargs):
        """根据模型类型加载模型"""
        model_info = self._models[model_name]
        model_type = model_info.model_type
        model_path = model_info.model_path
        
        # 使用新的模块化加载器
        if model_type == 'llm':
            from core.modules.llm.module import LLMModule
            # 这里只是临时适配，实际上应该重构为使用Module类
            return self._load_llm_model(model_path, kwargs)
        elif model_type == 'vision' or model_type == 'vl':
            from core.modules.vision.module import VisionModule
            return self._load_vision_model(model_path, kwargs)
        elif model_type == 'image_gen':
            return self._load_image_gen_model(model_path, kwargs)
        else:
            # 其他类型暂未迁移
            raise ValueError(f"不支持的模型类型: {model_type}")
    
    def _load_llm_model(self, model_path: str, kwargs: Dict) -> Tuple[Any, Any]:
        """加载大语言模型"""
        from transformers import AutoModelForCausalLM, AutoTokenizer
        
        tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
        
        model_kwargs = kwargs.get('model_kwargs', {})
        device = kwargs.get('device', 'auto')
        
        if device == 'auto':
            model_kwargs['device_map'] = 'auto'
        else:
            model_kwargs['device_map'] = device
            
        model = AutoModelForCausalLM.from_pretrained(model_path, **model_kwargs)
        return model, tokenizer

    def _load_vision_model(self, model_path: str, kwargs: Dict) -> Tuple[Any, Any]:
        """加载视觉模型"""
        from transformers import AutoModelForVision2Seq, AutoTokenizer
        
        tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
        
        model_kwargs = kwargs.get('model_kwargs', {})
        if kwargs.get('device', 'auto') == 'auto':
            model_kwargs['device_map'] = 'auto'
            
        model = AutoModelForVision2Seq.from_pretrained(model_path, **model_kwargs)
        return model, tokenizer

    def _load_image_gen_model(self, model_path: str, kwargs: Dict) -> Tuple[Any, None]:
        """加载图像生成模型"""
        from diffusers import StableDiffusionPipeline
        
        # Extract parameters from kwargs
        model_kwargs = kwargs.get('model_kwargs', {})
        torch_dtype = kwargs.get('torch_dtype', torch.float16)
        
        # Prepare pipeline arguments
        pipe_kwargs = {
            "local_files_only": True, # Ensure offline mode
            "torch_dtype": torch_dtype,
        }
        
        # Merge model_kwargs into pipe_kwargs
        pipe_kwargs.update(model_kwargs)
        
        # Handle device/device_map defaults if not specified
        if 'device_map' not in pipe_kwargs:
            if kwargs.get('device', 'auto') == 'auto' or kwargs.get('device') == 'cuda':
                # Prefer explicit offloading over device_map="auto" for diffusers to avoid hanging
                # pipe_kwargs["device_map"] = "auto"
                pass
        
        # Check if it's a single file checkpoint
        if os.path.isfile(model_path):
             # Define local config paths (borrowed from model_loader.py)
             SD15_LOCAL_PATH = "d:\\AI\\xiaoyou-core\\models\\img\\stable-diffusion-webui-forge-main\\backend\\huggingface\\runwayml\\stable-diffusion-v1-5"
             SDXL_LOCAL_PATH = "d:\\AI\\xiaoyou-core\\models\\img\\stable-diffusion-webui-forge-main\\backend\\huggingface\\stabilityai\\stable-diffusion-xl-base-1.0"
             
             # Use from_single_file for .safetensors/.ckpt
             if hasattr(StableDiffusionPipeline, 'from_single_file'):
                 loader = StableDiffusionPipeline.from_single_file
                 
                 # For single file loading, let's try using device_map="auto" again but ensure safety_checker is None
                 # If device_map is already in kwargs (from model_kwargs), keep it.
                 # If not, and device is auto/cuda, we might want it.
                 # But wait, earlier logic sets device_map="auto" if device is auto.
                 
                 # Add safety_checker=None to avoid downloading config and fix potential boolean error
                 pipe_kwargs["safety_checker"] = None
                 
                 # Auto-detect config file if not provided
                 if 'original_config_file' not in pipe_kwargs:
                     # Check for v1-inference.yaml in the same directory
                     dir_path = os.path.dirname(model_path)
                     default_config = os.path.join(dir_path, 'v1-inference.yaml')
                     if os.path.exists(default_config):
                         pipe_kwargs['original_config_file'] = default_config
                         logger.info(f"Found local config file: {default_config}")
                     else:
                         # Check for file with same name but .yaml extension
                         base_name = os.path.splitext(model_path)[0]
                         same_name_config = base_name + ".yaml"
                         if os.path.exists(same_name_config):
                             pipe_kwargs['original_config_file'] = same_name_config
                             logger.info(f"Found local config file: {same_name_config}")
                 
                 # Specify local config directory to avoid network requests
                 is_sdxl = ('sdxl' in os.path.basename(model_path).lower()) or ('xl' in os.path.basename(model_path).lower())
                 if not is_sdxl and os.path.exists(SD15_LOCAL_PATH):
                     logger.info(f"Using local config directory: {SD15_LOCAL_PATH}")
                     pipe_kwargs["config"] = SD15_LOCAL_PATH
                 elif is_sdxl and os.path.exists(SDXL_LOCAL_PATH):
                     logger.info(f"Using local config directory: {SDXL_LOCAL_PATH}")
                     pipe_kwargs["config"] = SDXL_LOCAL_PATH
             else:
                 # Fallback for older diffusers versions
                 loader = StableDiffusionPipeline.from_ckpt
             
             logger.info(f"Calling loader with pipe_kwargs keys: {list(pipe_kwargs.keys())}")
             pipe = loader(model_path, **pipe_kwargs)
             
             # Enable offloading after loading if CUDA is available AND device_map was NOT used
             # If device_map was used, accelerate handles it.
             # Also skip if device is explicitly 'cpu'
             if torch.cuda.is_available() and "device_map" not in pipe_kwargs and kwargs.get('device') != 'cpu':
                 try:
                     # Prefer enable_model_cpu_offload if available (diffusers >= 0.12.0)
                     # This is generally faster and more stable than device_map="auto"
                     if hasattr(pipe, 'enable_model_cpu_offload'):
                         pipe.enable_model_cpu_offload()
                         logger.info("Enabled model cpu offload")
                     else:
                         pipe.enable_sequential_cpu_offload()
                         logger.info("Enabled sequential cpu offload")
                 except Exception as e:
                     logger.warning(f"Failed to enable CPU offload: {e}")
        else:
             # Directory based loading
             pipe = StableDiffusionPipeline.from_pretrained(model_path, **pipe_kwargs)
             
        return pipe, None

# Global instance
_model_manager = None

def get_model_manager() -> ModelManager:
    """
    Get the singleton ModelManager instance
    """
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager
