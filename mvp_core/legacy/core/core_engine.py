#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核心引擎模块
系统的核心控制器，管理所有组件的生命周期
"""
import logging
import asyncio
from typing import Dict, Any, Optional
from .event_bus import EventBus
from .lifecycle_manager import LifecycleManager
from .model_manager import ModelManager
from .config_manager import ConfigManager

logger = logging.getLogger(__name__)

class CoreEngine:
    """
    核心引擎
    实现单例模式，确保全局只有一个实例
    """
    
    _instance: Optional['CoreEngine'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        """
        单例模式实现
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """
        初始化核心引擎
        """
        if self._initialized:
            return
        
        self._initialized = True
        self._running = False
        self._components: Dict[str, Any] = {}
        
        logger.info("CoreEngine initializing...")
        
        # 初始化配置管理器
        self.config_manager = ConfigManager()
        self._components["config_manager"] = self.config_manager
        
        # 初始化事件总线
        self.event_bus = EventBus()
        self._components["event_bus"] = self.event_bus
        
        # 初始化生命周期管理器
        self.lifecycle_manager = LifecycleManager()
        self._components["lifecycle_manager"] = self.lifecycle_manager
        
        # 初始化模型管理器
        self.model_manager = ModelManager(self.config_manager)
        self._components["model_manager"] = self.model_manager
        
        # 注册核心事件监听器
        self._register_core_events()
        
        logger.info("CoreEngine initialized successfully")
    
    def _register_core_events(self):
        """
        注册核心事件监听器
        """
        async def on_system_started(data: Dict[str, Any]):
            logger.info("System started event received")
        
        async def on_system_shutdown(data: Dict[str, Any]):
            logger.info("System shutdown event received")
        
        # 注册事件监听器
        asyncio.create_task(self.event_bus.subscribe("system.started", on_system_started))
        asyncio.create_task(self.event_bus.subscribe("system.shutdown", on_system_shutdown))
    
    async def start(self):
        """
        启动核心引擎
        """
        if self._running:
            logger.warning("CoreEngine is already running")
            return
        
        logger.info("Starting CoreEngine...")
        
        try:
            # 初始化所有服务
            await self.lifecycle_manager.initialize_all()
            
            # 发布系统启动事件
            await self.event_bus.publish("system.started", {
                "timestamp": asyncio.get_event_loop().time(),
                "components": list(self._components.keys())
            })
            
            self._running = True
            logger.info("CoreEngine started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start CoreEngine: {e}")
            raise
    
    async def stop(self):
        """
        停止核心引擎
        """
        if not self._running:
            logger.warning("CoreEngine is not running")
            return
        
        logger.info("Stopping CoreEngine...")
        
        try:
            # 发布系统关闭事件
            await self.event_bus.publish("system.shutdown", {
                "timestamp": asyncio.get_event_loop().time()
            })
            
            # 关闭所有服务
            await self.lifecycle_manager.shutdown_all()
            
            self._running = False
            logger.info("CoreEngine stopped successfully")
            
        except Exception as e:
            logger.error(f"Failed to stop CoreEngine: {e}")
            raise
    
    def is_running(self) -> bool:
        """
        检查核心引擎是否正在运行
        
        Returns:
            是否正在运行
        """
        return self._running
    
    def get_component(self, component_name: str) -> Optional[Any]:
        """
        获取组件实例
        
        Args:
            component_name: 组件名称
            
        Returns:
            组件实例或None
        """
        return self._components.get(component_name)
    
    def get_all_components(self) -> Dict[str, Any]:
        """
        获取所有组件实例
        
        Returns:
            所有组件实例字典
        """
        return self._components.copy()
    
    def register_component(self, name: str, component: Any):
        """
        注册组件
        
        Args:
            name: 组件名称
            component: 组件实例
        """
        self._components[name] = component
        logger.info(f"Component registered: {name}")
    
    def get_config(self) -> Dict[str, Any]:
        """
        获取配置
        
        Returns:
            配置字典
        """
        return self.config_manager.get_all_config()
    
    async def restart(self):
        """
        重启核心引擎
        """
        logger.info("Restarting CoreEngine...")
        await self.stop()
        await self.start()
        logger.info("CoreEngine restarted successfully")

# 全局核心引擎实例访问函数
def get_core_engine() -> CoreEngine:
    """
    获取核心引擎实例
    
    Returns:
        核心引擎实例
    """
    return CoreEngine()