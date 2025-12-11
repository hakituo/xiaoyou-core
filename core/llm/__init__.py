#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM模块入口
"""
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

@dataclass
class LLMConfig:
    """
    LLM配置类
    """
    model_name: str
    device: str = "auto"
    max_context_length: int = 2048
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 50

class LLMModule(ABC):
    """
    LLM模块抽象基类
    """
    @abstractmethod
    async def initialize(self):
        """
        初始化LLM模块
        """
        pass
    
    @abstractmethod
    async def chat(self, messages: list, **kwargs):
        """
        聊天生成
        """
        pass
    
    @abstractmethod
    async def stream_chat(self, messages: list, **kwargs):
        """
        流式聊天生成
        """
        pass
    
    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """
        获取模块状态
        """
        pass

# 全局LLM模块实例
_llm_module_instance = None
_llm_instances = {}

def get_llm_module() -> LLMModule:
    """
    获取全局LLM模块实例
    """
    global _llm_module_instance
    if _llm_module_instance is None:
        from config.integrated_config import get_settings
        settings = get_settings()
        
        # Check if local models are preferred
        if settings.system.use_local_models_only:
            try:
                from core.modules.llm.module import LLMModule as LocalLLMModule
                
                class LocalLLMAdapter(LLMModule):
                    def __init__(self):
                        self.local_module = LocalLLMModule()
                        
                    async def initialize(self):
                        await self.local_module._load_model()
                        
                    async def chat(self, messages: list, **kwargs):
                        # Convert messages to prompt list for local module
                        # Local module expects [{"role":..., "content":...}] which is what messages is
                        result = await self.local_module.chat(messages, **kwargs)
                        if result.get("status") == "success":
                            return result.get("response")
                        else:
                            return f"Error: {result.get('error')}"
                            
                    async def stream_chat(self, messages: list, **kwargs):
                        content = await self.chat(messages, **kwargs)
                        yield {"content": content}
                        
                    def get_status(self) -> Dict[str, Any]:
                        return {
                            "status": "initialized" if self.local_module.is_loaded else "not_initialized",
                            "model_path": self.local_module.get_current_model_name(),
                            "type": "local",
                            "llm_status": {"instances_count": 1}
                        }
                        
                _llm_module_instance = LocalLLMAdapter()
                logger.info("Using Local LLM Module as per configuration.")
                return _llm_module_instance
            except Exception as e:
                logger.error(f"Failed to load Local LLM Module: {e}. Falling back to DashScope.")
        
        # Default to DashScope
        from .dashscope_client import DashScopeClient
        _llm_module_instance = DashScopeClient()
    return _llm_module_instance

def create_instance(instance_name: str, config: LLMConfig) -> None:
    """
    创建LLM实例
    """
    global _llm_instances
    # 这里简化实现，实际应该根据配置创建不同类型的LLM实例
    _llm_instances[instance_name] = config
    logger.info(f"创建LLM实例: {instance_name}, 模型: {config.model_name}")

def get_instance(instance_name: str) -> Optional[LLMConfig]:
    """
    获取指定名称的LLM实例
    """
    global _llm_instances
    return _llm_instances.get(instance_name)

def list_instances() -> Dict[str, LLMConfig]:
    """
    列出所有LLM实例
    """
    global _llm_instances
    return _llm_instances.copy()