#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生命周期管理模块
负责服务的初始化和关闭
"""
import logging
import asyncio
from typing import List, Dict, Any, Callable, Awaitable, Optional

logger = logging.getLogger(__name__)

class LifecycleManager:
    """
    生命周期管理器
    负责管理服务的初始化和关闭
    支持服务优先级管理
    """
    
    def __init__(self):
        """
        初始化生命周期管理器
        """
        self.services = []
        self.initialized_services = []
        self.shutdown_handlers = []
        self._health_check_tasks = []
        
        logger.info("LifecycleManager initialized")
    
    def register_service(self, service_name: str, 
                         init_func: Callable[[], Awaitable[None]], 
                         shutdown_func: Optional[Callable[[], Awaitable[None]]] = None,
                         priority: int = 5):
        """
        注册服务
        
        Args:
            service_name: 服务名称
            init_func: 初始化函数
            shutdown_func: 关闭函数
            priority: 服务优先级，值越小优先级越高
        """
        self.services.append({
            "name": service_name,
            "init_func": init_func,
            "shutdown_func": shutdown_func,
            "priority": priority
        })
        logger.info(f"Service registered: {service_name} (priority: {priority})")
    
    def register_shutdown_handler(self, handler: Callable[[], Awaitable[None]]):
        """
        注册全局关闭处理器
        
        Args:
            handler: 关闭处理器函数
        """
        self.shutdown_handlers.append(handler)
        logger.info(f"Shutdown handler registered")
    
    async def initialize_all(self):
        """
        初始化所有服务
        按照优先级排序，优先级高的服务先初始化
        """
        logger.info("Initializing all services...")
        
        # 按照优先级排序服务，优先级值越小优先级越高
        sorted_services = sorted(self.services, key=lambda x: x["priority"])
        
        for service in sorted_services:
            try:
                logger.info(f"Initializing service: {service['name']} (priority: {service['priority']})")
                await service["init_func"]()
                self.initialized_services.append(service)
                logger.info(f"Service initialized: {service['name']}")
            except Exception as e:
                logger.error(f"Failed to initialize service {service['name']}: {e}")
                # 继续初始化其他服务，不中断整个初始化过程
    
    async def shutdown_all(self):
        """
        关闭所有服务
        按照初始化顺序的逆序关闭服务
        """
        logger.info("Shutting down all services...")
        
        # 先关闭所有服务，逆序关闭
        for service in reversed(self.initialized_services):
            if service["shutdown_func"]:
                try:
                    logger.info(f"Shutting down service: {service['name']}")
                    await service["shutdown_func"]()
                    logger.info(f"Service shutdown: {service['name']}")
                except Exception as e:
                    logger.error(f"Failed to shutdown service {service['name']}: {e}")
                    # 继续关闭其他服务，不中断整个关闭过程
        
        # 然后执行全局关闭处理器
        for handler in reversed(self.shutdown_handlers):
            try:
                await handler()
            except Exception as e:
                logger.error(f"Failed to execute shutdown handler: {e}")
        
        # 清理健康检查任务
        for task in self._health_check_tasks:
            if not task.done():
                task.cancel()
        
        logger.info("All services shutdown completed")
    
    async def health_check(self) -> Dict[str, Any]:
        """
        执行健康检查
        
        Returns:
            健康检查结果
        """
        logger.info("Performing health check...")
        
        health_status = {
            "status": "healthy",
            "timestamp": asyncio.get_event_loop().time(),
            "services": {}
        }
        
        # 检查每个服务的状态
        for service in self.services:
            service_name = service["name"]
            is_initialized = service in self.initialized_services
            health_status["services"][service_name] = {
                "initialized": is_initialized,
                "status": "healthy" if is_initialized else "not_initialized"
            }
        
        # 如果有未初始化的服务，健康状态为亚健康
        if any(not status["initialized"] for status in health_status["services"].values()):
            health_status["status"] = "degraded"
        
        return health_status
    
    async def start_health_monitoring(self, interval: int = 30):
        """
        启动健康监控
        
        Args:
            interval: 健康检查间隔（秒）
        """
        async def monitor_task():
            while True:
                try:
                    health_status = await self.health_check()
                    # 发布健康检查事件
                    from core import get_core_engine
                    core_engine = get_core_engine()
                    await core_engine.event_bus.publish("system.health_check", health_status)
                    await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Health monitoring error: {e}")
                    await asyncio.sleep(interval)
        
        task = asyncio.create_task(monitor_task())
        self._health_check_tasks.append(task)
        logger.info(f"Health monitoring started with interval: {interval}s")

# 全局生命周期管理器实例
_lifecycle_manager_instance = None

async def initialize_default_services():
    """
    初始化默认服务
    """
    logger.info("Initializing default services...")
    
    # 注册核心服务
    from services.core_service import get_core_service
    core_service = get_core_service()
    
    lifecycle_manager = get_lifecycle_manager()
    lifecycle_manager.register_service(
        service_name="CoreService",
        init_func=core_service.initialize,
        shutdown_func=core_service.shutdown,
        priority=1  # 高优先级
    )
    
    logger.info("Default services registered")

def get_lifecycle_manager() -> LifecycleManager:
    """
    获取全局生命周期管理器实例
    
    Returns:
        生命周期管理器实例
    """
    global _lifecycle_manager_instance
    if _lifecycle_manager_instance is None:
        _lifecycle_manager_instance = LifecycleManager()
    return _lifecycle_manager_instance
