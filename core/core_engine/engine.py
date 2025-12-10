#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
核心引擎模块
负责管理系统的核心功能和组件
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from .event_bus import get_event_bus, EventTypes

logger = logging.getLogger(__name__)


class CoreEngine:
    """核心引擎类，管理系统的核心功能和模块"""
    
    def __init__(self):
        """初始化核心引擎"""
        self.modules = {}
        self.config = {}
        self.running = False
        self.event_bus = get_event_bus()
    
    async def initialize(self):
        """初始化引擎和所有组件"""
        logger.info("初始化核心引擎...")
        self.running = True
        
        # 注册引擎相关的事件处理
        await self._register_event_handlers()
        
        # 加载基础配置
        await self._load_config()
        
        logger.info("核心引擎初始化完成")
    
    async def _register_event_handlers(self):
        """注册事件处理器"""
        @self.event_bus.on(EventTypes.ENGINE_SHUTDOWN)
        async def handle_shutdown(event):
            await self.shutdown()
    
    async def _load_config(self):
        """加载引擎配置"""
        try:
            from config.config_loader import ConfigLoader, Config
            _loader = ConfigLoader()
            settings = Config(_loader)
            self.config = settings
            logger.info("配置已加载到核心引擎")
        except Exception as e:
            logger.warning(f"无法加载配置: {e}")
    
    async def load_module(self, module_name: str) -> Any:
        """动态加载指定模块
        
        Args:
            module_name: 模块名称
            
        Returns:
            加载的模块实例
        """
        if module_name in self.modules:
            return self.modules[module_name]
        
        logger.info(f"尝试加载模块: {module_name}")
        
        try:
            # 动态导入模块
            if module_name == "llm":
                from .llm import LLMService
                module = LLMService()
                await module.initialize()
            elif module_name == "image":
                from .image import ImageService
                module = ImageService()
                await module.initialize()
            elif module_name == "voice":
                from .voice import VoiceService
                module = VoiceService()
                await module.initialize()
            elif module_name == "vl":
                from .vl import VLService
                module = VLService()
                await module.initialize()
            elif module_name == "memory":
                # from .memory import MemoryManager # 假设的路径，实际可能不同
                # 使用 memory module 包装器
                from core.modules.memory.module import MemoryModule
                module = MemoryModule()
                # await module.initialize() # MemoryModule __init__ 中已部分初始化，这里可能不需要
            else:
                logger.warning(f"未知模块: {module_name}")
                return None
            
            self.modules[module_name] = module
            logger.info(f"模块 {module_name} 加载成功")
            return module
            
        except Exception as e:
            logger.error(f"加载模块 {module_name} 失败: {e}")
            return None
    
    async def unload_module(self, module_name: str):
        """卸载指定模块
        
        Args:
            module_name: 模块名称
        """
        if module_name in self.modules:
            logger.info(f"卸载模块: {module_name}")
            try:
                module = self.modules[module_name]
                if hasattr(module, 'shutdown'):
                    await module.shutdown()
                del self.modules[module_name]
                logger.info(f"模块 {module_name} 卸载成功")
            except Exception as e:
                logger.error(f"卸载模块 {module_name} 失败: {e}")
    
    async def shutdown(self):
        """关闭引擎，释放所有资源"""
        logger.info("正在关闭核心引擎...")
        
        # 卸载所有模块
        for module_name in list(self.modules.keys()):
            await self.unload_module(module_name)
        
        self.running = False
        logger.info("核心引擎已关闭")
    
    def get_status(self) -> Dict[str, Any]:
        """获取引擎状态
        
        Returns:
            包含引擎状态的字典
        """
        return {
            "running": self.running,
            "loaded_modules": list(self.modules.keys()),
            "config_available": len(self.config) > 0
        }

# Global instance
_core_engine = None

def get_core_engine() -> CoreEngine:
    """
    Get the singleton CoreEngine instance
    """
    global _core_engine
    if _core_engine is None:
        _core_engine = CoreEngine()
    return _core_engine
