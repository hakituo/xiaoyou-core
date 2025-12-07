#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模型管理模块
负责模型加载、管理和系统资源检测
"""
import logging
import os
import time
import threading
import gc
from typing import Dict, List, Any, Optional, Tuple, Union
import torch
import psutil
from .config_manager import ConfigManager

logger = logging.getLogger(__name__)

class ModelInfo:
    """模型信息类"""
    def __init__(self, model_name: str, model_type: str, model_path: str):
        self.model_name = model_name
        self.model_type = model_type
        self.model_path = model_path
        self.load_time = None
        self.last_used_time = None
        self.is_loaded = False
        self.model_obj = None
        self.tokenizer_obj = None
        self.device = None
        self.memory_used = 0.0
        self.load_options = {}

class ModelManager:
    """
    模型管理器
    负责管理和监控系统中的模型，支持动态加载、卸载和资源管理
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ModelManager, cls).__new__(cls)
                cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config_manager: ConfigManager):
        """
        初始化模型管理器
        
        Args:
            config_manager: 配置管理器实例
        """
        if self._initialized:
            return
            
        self.config_manager = config_manager
        self._models: Dict[str, ModelInfo] = {}
        self._registered_models: Dict[str, Dict] = {}
        self._model_locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.RLock()
        
        # 配置参数
        self.max_models = config_manager.get("model.max_models", 3)
        self.memory_threshold = config_manager.get("model.memory_threshold", 0.8)
        
        self._initialized = True
        logger.info(f"ModelManager initialized with max_models={self.max_models}, memory_threshold={self.memory_threshold}")

    def register_model(self, model_name: str, model_type: str, model_path: str, **kwargs):
        """注册模型"""
        with self._global_lock:
            self._registered_models[model_name] = {
                "type": model_type,
                "path": model_path,
                **kwargs
            }
            logger.info(f"Registered model: {model_name} ({model_type})")

    def load_model(self, model_name: str, **kwargs) -> Optional[Any]:
        """
        加载模型
        
        Args:
            model_name: 模型名称
            **kwargs: 加载参数
            
        Returns:
            模型对象
        """
        if model_name not in self._registered_models:
            logger.error(f"Model not registered: {model_name}")
            return None

        # 初始化ModelInfo
        if model_name not in self._models:
            reg_info = self._registered_models[model_name]
            self._models[model_name] = ModelInfo(model_name, reg_info['type'], reg_info['path'])
            if 'load_config' in reg_info:
                self._models[model_name].load_options.update(reg_info['load_config'])

        model_info = self._models[model_name]

        # 检查是否已加载
        if model_info.is_loaded:
            model_info.last_used_time = time.time()
            return model_info.model_obj

        # 确保锁存在
        if model_name not in self._model_locks:
            self._model_locks[model_name] = threading.Lock()
            
        with self._model_locks[model_name]:
            # 双重检查
            if model_info.is_loaded:
                return model_info.model_obj

            # 检查资源并尝试清理
            self._ensure_resources()

            try:
                logger.info(f"Loading model: {model_name}...")
                model_obj, tokenizer_obj = self._load_model_by_type(model_info, **kwargs)
                
                model_info.model_obj = model_obj
                model_info.tokenizer_obj = tokenizer_obj
                model_info.is_loaded = True
                model_info.load_time = time.time()
                model_info.last_used_time = time.time()
                model_info.device = kwargs.get('device', 'cuda' if torch.cuda.is_available() else 'cpu')
                
                logger.info(f"Model loaded successfully: {model_name}")
                return model_obj
            except Exception as e:
                logger.error(f"Failed to load model {model_name}: {e}")
                return None

    def unload_model(self, model_name: str) -> bool:
        """卸载模型"""
        if model_name not in self._models:
            return False
            
        with self._global_lock: # 简单起见使用全局锁
            model_info = self._models[model_name]
            if not model_info.is_loaded:
                return True
                
            try:
                logger.info(f"Unloading model: {model_name}")
                model_info.model_obj = None
                model_info.tokenizer_obj = None
                model_info.is_loaded = False
                
                self._perform_resource_cleanup()
                return True
            except Exception as e:
                logger.error(f"Failed to unload model {model_name}: {e}")
                return False

    def get_model(self, model_name: str) -> Optional[Any]:
        """获取已加载的模型"""
        if model_name in self._models and self._models[model_name].is_loaded:
            self._models[model_name].last_used_time = time.time()
            return self._models[model_name].model_obj
        return None
        
    def get_tokenizer(self, model_name: str) -> Optional[Any]:
        """获取已加载的分词器"""
        if model_name in self._models and self._models[model_name].is_loaded:
            return self._models[model_name].tokenizer_obj
        return None

    def list_models(self) -> List[Dict[str, Any]]:
        """列出所有模型状态"""
        result = []
        for name, info in self._models.items():
            result.append({
                "name": name,
                "type": info.model_type,
                "loaded": info.is_loaded,
                "path": info.model_path
            })
        # 添加未加载但注册的模型
        for name, info in self._registered_models.items():
            if name not in self._models:
                result.append({
                    "name": name,
                    "type": info['type'],
                    "loaded": False,
                    "path": info['path']
                })
        return result

    def _ensure_resources(self):
        """确保有足够的资源加载新模型"""
        # 简单策略：如果达到最大模型数，卸载最久未使用的
        loaded_count = sum(1 for m in self._models.values() if m.is_loaded)
        if loaded_count >= self.max_models:
            self._unload_oldest_model()
            
        # 检查内存（简化版）
        mem = psutil.virtual_memory()
        if mem.percent > self.memory_threshold * 100:
            logger.warning("System memory high, attempting to free resources...")
            self._unload_oldest_model()
            self._perform_resource_cleanup()

    def _unload_oldest_model(self):
        """卸载最久未使用的模型"""
        loaded = [m for m in self._models.values() if m.is_loaded]
        if not loaded:
            return
        
        # 按最后使用时间排序
        loaded.sort(key=lambda x: x.last_used_time or 0)
        victim = loaded[0]
        self.unload_model(victim.model_name)

    def _perform_resource_cleanup(self):
        """清理系统资源"""
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _load_model_by_type(self, model_info: ModelInfo, **kwargs) -> Tuple[Any, Any]:
        """根据类型加载模型的具体实现"""
        model_path = model_info.model_path
        device = kwargs.get('device', 'auto')
        
        if device == 'auto':
            device = 'cuda' if torch.cuda.is_available() else 'cpu'

        if model_info.model_type == 'llm':
            from transformers import AutoModelForCausalLM, AutoTokenizer
            
            logger.info(f"Loading LLM from {model_path}...")
            tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
            
            model_kwargs = {
                "trust_remote_code": True, 
                "local_files_only": True,
                "low_cpu_mem_usage": True
            }
            
            # 简单的量化处理
            if kwargs.get("quantization", False):
                model_kwargs["load_in_4bit"] = True
            elif device == "cuda":
                model_kwargs["torch_dtype"] = torch.float16
                model_kwargs["device_map"] = "auto"
            else:
                model_kwargs["torch_dtype"] = torch.float32
                
            model = AutoModelForCausalLM.from_pretrained(model_path, **model_kwargs)
            if device != "cuda" and not model_kwargs.get("device_map"):
                model = model.to(device)
                
            return model, tokenizer
            
        elif model_info.model_type == 'vision':
            from transformers import AutoModelForVision2Seq, AutoTokenizer
            
            logger.info(f"Loading Vision Model from {model_path}...")
            tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True, local_files_only=True)
            
            model_kwargs = {"trust_remote_code": True, "local_files_only": True}
            if device == "cuda":
                model_kwargs["device_map"] = "auto"
                model_kwargs["torch_dtype"] = torch.float16
                
            model = AutoModelForVision2Seq.from_pretrained(model_path, **model_kwargs)
            return model, tokenizer
            
        elif model_info.model_type == 'image_gen':
            from diffusers import StableDiffusionPipeline
            
            logger.info(f"Loading Stable Diffusion from {model_path}...")
            pipe_kwargs = {"local_files_only": True}
            if device == "cuda":
                pipe_kwargs["torch_dtype"] = torch.float16
                pipe_kwargs["variant"] = "fp16"
                
            pipe = StableDiffusionPipeline.from_pretrained(model_path, **pipe_kwargs)
            if device == "cuda":
                pipe = pipe.to("cuda")
                
            return pipe, None
            
        else:
            raise ValueError(f"Unknown model type: {model_info.model_type}")
