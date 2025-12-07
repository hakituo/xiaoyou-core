#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM模块
提供大语言模型的封装和调用接口
"""
import logging
import asyncio
import torch
from typing import Dict, Any, Optional
from mvp_core.core import get_core_engine

logger = logging.getLogger(__name__)

class LLMModule:
    """
    LLM模块
    封装大语言模型的调用和管理
    """
    
    def __init__(self):
        """初始化LLM模块"""
        self.core_engine = get_core_engine()
        self.event_bus = self.core_engine.event_bus
        self.config = self.core_engine.config_manager
        self.model_manager = self.core_engine.model_manager
        
        self._default_model = self.config.get("models.llm.default", "qwen")
        self._register_events()
        logger.info("LLMModule initialized")
    
    def _register_events(self):
        """注册事件监听器"""
        async def on_llm_request(data: Dict[str, Any]):
            await self._handle_llm_request(data)
        
        asyncio.create_task(self.event_bus.subscribe("llm.request", on_llm_request))
    
    async def _handle_llm_request(self, data: Dict[str, Any]):
        """处理LLM请求"""
        try:
            prompt = data.get("prompt")
            request_id = data.get("request_id")
            
            if not prompt:
                raise ValueError("Prompt is empty")
                
            model_name = data.get("model_name", self._default_model)
            
            # 异步执行生成任务
            response = await asyncio.to_thread(self.generate, prompt, model_name)
            
            await self.event_bus.publish("llm.response", {
                "request_id": request_id,
                "success": True,
                "response": response,
                "model_name": model_name,
                "timestamp": asyncio.get_event_loop().time()
            })
            
        except Exception as e:
            logger.error(f"LLM request error: {e}")
            await self.event_bus.publish("llm.response", {
                "request_id": data.get("request_id"),
                "success": False,
                "error": str(e),
                "timestamp": asyncio.get_event_loop().time()
            })

    def generate(self, prompt: str, model_name: Optional[str] = None, **kwargs) -> str:
        """
        生成文本响应 (同步阻塞方法，建议在线程池中运行)
        
        Args:
            prompt: 提示文本
            model_name: 模型名称
            
        Returns:
            生成的文本
        """
        if not model_name:
            model_name = self._default_model
            
        # 获取模型
        model = self.model_manager.get_model(model_name)
        if not model:
            # 尝试加载
            logger.info(f"Model {model_name} not loaded, attempting to load...")
            # 注意：load_model 可能会耗时
            model = self.model_manager.load_model(model_name)
            if not model:
                raise ValueError(f"Failed to load model: {model_name}")
        
        tokenizer = self.model_manager.get_tokenizer(model_name)
        
        try:
            # 构建消息
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]
            
            text = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
            
            device = model.device
            inputs = tokenizer([text], return_tensors="pt").to(device)
            
            with torch.no_grad():
                generated_ids = model.generate(
                    inputs.input_ids,
                    max_new_tokens=kwargs.get("max_new_tokens", 512),
                    temperature=kwargs.get("temperature", 0.7),
                    do_sample=True
                )
                
            generated_ids = [
                output_ids[len(input_ids):] for input_ids, output_ids in zip(inputs.input_ids, generated_ids)
            ]
            
            response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
            return response
            
        except Exception as e:
            logger.error(f"Generation error: {e}")
            raise

# 全局LLMModule实例
def get_llm_module() -> LLMModule:
    return LLMModule()
