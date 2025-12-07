#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图像模块
处理图像生成和理解任务
"""
import logging
import asyncio
import torch
from typing import Dict, Any, Optional
from mvp_core.core import get_core_engine

logger = logging.getLogger(__name__)

class ImageModule:
    """
    图像模块
    提供图像生成、编辑和分析功能
    """
    
    def __init__(self):
        """
        初始化图像模块
        """
        self.core_engine = get_core_engine()
        self.event_bus = self.core_engine.event_bus
        self.config = self.core_engine.config_manager
        self.model_manager = self.core_engine.model_manager
        
        self._default_gen_model = self.config.get("models.image_gen.default", "sd_v1_5")
        self._default_vision_model = self.config.get("models.vision.default", "qwen_vl")
        
        logger.info("ImageModule initialized")
        
        # 注册事件监听器
        self._register_events()
    
    def _register_events(self):
        """
        注册事件监听器
        """
        async def on_image_request(data: Dict[str, Any]):
            """处理图像请求事件"""
            await self._handle_image_request(data)
        
        # 注册事件
        asyncio.create_task(self.event_bus.subscribe("image.request", on_image_request))
    
    async def _handle_image_request(self, data: Dict[str, Any]):
        """处理图像请求"""
        try:
            request_type = data.get("type", "generate")
            request_id = data.get("request_id")
            
            if request_type == "generate":
                # 异步执行生成
                result = await asyncio.to_thread(self.generate_image, data)
            elif request_type == "analyze":
                result = await asyncio.to_thread(self.analyze_image, data)
            else:
                result = {"success": False, "error": f"Unknown request type: {request_type}"}
            
            # 发布响应事件
            await self.event_bus.publish("image.response", {
                **result,
                "request_id": request_id,
                "timestamp": asyncio.get_event_loop().time()
            })
        except Exception as e:
            logger.error(f"Image request error: {e}")
            await self.event_bus.publish("image.response", {
                "request_id": data.get("request_id"),
                "success": False,
                "error": str(e),
                "timestamp": asyncio.get_event_loop().time()
            })
            
    def generate_image(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成图像 (同步方法)
        """
        prompt = data.get("prompt")
        model_name = data.get("model_name", self._default_gen_model)
        
        if not prompt:
            return {"success": False, "error": "Prompt is required"}
            
        # 获取模型
        pipe = self.model_manager.get_model(model_name)
        if not pipe:
            logger.info(f"Image gen model {model_name} not loaded, loading...")
            pipe = self.model_manager.load_model(model_name)
            if not pipe:
                return {"success": False, "error": f"Failed to load model {model_name}"}
                
        try:
            # 执行生成
            with torch.no_grad():
                image = pipe(
                    prompt=prompt,
                    negative_prompt=data.get("negative_prompt"),
                    height=data.get("height", 512),
                    width=data.get("width", 512),
                    num_inference_steps=data.get("steps", 20)
                ).images[0]
                
            # 这里应该保存图像并返回路径或Base64
            # 简化起见返回成功状态
            return {
                "success": True,
                "message": "Image generated",
                "image_object": image # 注意：这不能直接JSON序列化
            }
            
        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            return {"success": False, "error": str(e)}

    def analyze_image(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析图像 (同步方法)
        """
        image_data = data.get("image")
        prompt = data.get("prompt", "Describe this image")
        model_name = data.get("model_name", self._default_vision_model)
        
        if not image_data:
            return {"success": False, "error": "Image data required"}
            
        # 获取模型
        model = self.model_manager.get_model(model_name)
        tokenizer = self.model_manager.get_tokenizer(model_name)
        
        if not model:
            logger.info(f"Vision model {model_name} not loaded, loading...")
            model = self.model_manager.load_model(model_name)
            tokenizer = self.model_manager.get_tokenizer(model_name)
            if not model:
                return {"success": False, "error": f"Failed to load model {model_name}"}

        try:
            # 简单的视觉推理逻辑
            # 注意：需要根据具体的模型API调整
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image_data},
                        {"type": "text", "text": prompt},
                    ],
                }
            ]
            
            text = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
            
            inputs = tokenizer([text], return_tensors="pt").to(model.device)
            
            with torch.no_grad():
                generated_ids = model.generate(**inputs, max_new_tokens=128)
                
            response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
            
            return {
                "success": True,
                "description": response
            }
            
        except Exception as e:
            logger.error(f"Image analysis failed: {e}")
            return {"success": False, "error": str(e)}

# 全局ImageModule实例
def get_image_module() -> ImageModule:
    return ImageModule()
