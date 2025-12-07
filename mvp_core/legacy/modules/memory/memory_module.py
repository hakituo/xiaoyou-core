#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
记忆模块
管理短期记忆和长期记忆
"""
import logging
import asyncio
import json
import os
from typing import Dict, Any, List, Optional
from mvp_core.core import get_core_engine

logger = logging.getLogger(__name__)

class MemoryModule:
    """
    记忆模块
    管理短期记忆和长期记忆
    """
    
    def __init__(self):
        """
        初始化记忆模块
        """
        self.core_engine = get_core_engine()
        self.event_bus = self.core_engine.event_bus
        self.config = self.core_engine.get_config()
        
        # 内存存储
        self.short_term_memory = []
        self.long_term_memory = {}
        
        # 配置
        self.max_short_term = 50
        
        logger.info("MemoryModule initialized")
        
        # 注册事件监听器
        self._register_events()
    
    def _register_events(self):
        """
        注册事件监听器
        """
        async def on_memory_store(data: Dict[str, Any]):
            """处理记忆存储请求"""
            await self.store_memory(data)
            
        async def on_memory_retrieve(data: Dict[str, Any]):
            """处理记忆检索请求"""
            # This is a placeholder for retrieval logic
            pass
        
        # 注册事件
        asyncio.create_task(self.event_bus.subscribe("memory.store", on_memory_store))
        asyncio.create_task(self.event_bus.subscribe("memory.retrieve", on_memory_retrieve))
    
    async def initialize(self):
        """
        初始化模块
        """
        pass

    async def store_memory(self, data: Dict[str, Any]):
        """
        存储记忆
        
        Args:
            data: 记忆数据
        """
        try:
            memory_type = data.get("type", "short_term")
            content = data.get("content")
            
            if not content:
                return
                
            if memory_type == "short_term":
                self.short_term_memory.append({
                    "content": content,
                    "timestamp": asyncio.get_event_loop().time()
                })
                
                # 保持短期记忆大小
                if len(self.short_term_memory) > self.max_short_term:
                    self.short_term_memory.pop(0)
                    
            elif memory_type == "long_term":
                key = data.get("key")
                if key:
                    self.long_term_memory[key] = content
            
            logger.debug(f"Memory stored: {memory_type}")
            
        except Exception as e:
            logger.error(f"Error storing memory: {e}")

    async def get_recent_memory(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取最近的短期记忆
        
        Args:
            limit: 获取数量
            
        Returns:
            记忆列表
        """
        return self.short_term_memory[-limit:]

# Global instance
_memory_module = None

def get_memory_module() -> MemoryModule:
    """
    获取记忆模块单例
    """
    global _memory_module
    if _memory_module is None:
        _memory_module = MemoryModule()
    return _memory_module
