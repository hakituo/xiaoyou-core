#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aveline服务模块
实现情感智能体的核心功能
"""
import logging
import asyncio
import time
import uuid
from typing import Dict, Any, Optional
from mvp_core.core import get_core_engine
from mvp_core.modules.llm.llm_module import get_llm_module
from mvp_core.modules.image.image_module import get_image_module
from mvp_core.modules.memory.memory_module import get_memory_module

logger = logging.getLogger(__name__)

class AvelineService:
    """
    Aveline服务
    处理用户消息，生成响应，管理情感状态和记忆
    """
    
    def __init__(self):
        """
        初始化Aveline服务
        """
        self.core_engine = get_core_engine()
        self.event_bus = self.core_engine.event_bus
        self.config = self.core_engine.config_manager
        self._running = False
        
        # 获取模块实例
        self.llm_module = get_llm_module()
        self.image_module = get_image_module()
        
        # 服务状态
        self._status = "initialized"
        
        logger.info("AvelineService initialized")
        
        # 注册事件监听器
        self._register_events()
    
    def _register_events(self):
        """
        注册事件监听器
        """
        async def on_user_message(data: Dict[str, Any]):
            """处理用户消息事件"""
            await self.handle_user_message(data)
        
        # 注册事件
        asyncio.create_task(self.event_bus.subscribe("user.message", on_user_message))
    
    async def initialize(self):
        """
        初始化Aveline服务
        """
        if self._running:
            logger.warning("AvelineService is already running")
            return
        
        logger.info("Initializing AvelineService...")
        
        self._running = True
        self._status = "running"
        
        # 发布服务启动事件
        await self.event_bus.publish("service.aveline.started", {
            "status": "running"
        })
        
        logger.info("AvelineService initialized successfully")
    
    async def shutdown(self):
        """
        关闭Aveline服务
        """
        if not self._running:
            logger.warning("AvelineService is not running")
            return
        
        logger.info("Shutting down AvelineService...")
        
        self._running = False
        self._status = "stopped"
        
        # 发布服务关闭事件
        await self.event_bus.publish("service.aveline.stopped", {
            "status": "stopped"
        })
        
        logger.info("AvelineService shutdown successfully")
    
    async def handle_user_message(self, data: Dict[str, Any]):
        """
        处理用户消息
        """
        user_id = data.get("user_id")
        message = data.get("message")
        request_id = data.get("request_id", str(uuid.uuid4()))
        
        if not message:
            return
            
        logger.info(f"Handling user message from {user_id}: {message}")
        
        # 这里应该包含更复杂的逻辑：
        # 1. 检索记忆
        # 2. 分析情感
        # 3. 构建Prompt
        # 4. 调用LLM
        # 5. 更新记忆
        
        try:
            # 简单的直接调用LLM
            prompt = f"User: {message}\nAveline:"
            
            # 等待LLM响应
            # 注意：这里为了简化直接等待，实际可能需要更复杂的流式处理或异步回调
            # 但由于LLMModule.generate是同步的并在线程中运行，我们可以等待它
            
            response_text = await asyncio.to_thread(
                self.llm_module.generate, 
                prompt=prompt
            )
            
            # 发布响应事件
            await self.event_bus.publish("aveline.response", {
                "request_id": request_id,
                "user_id": user_id,
                "response": response_text,
                "timestamp": time.time()
            })
            
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            await self.event_bus.publish("aveline.error", {
                "request_id": request_id,
                "error": str(e)
            })

# 全局AvelineService实例
def get_aveline_service() -> AvelineService:
    return AvelineService()
