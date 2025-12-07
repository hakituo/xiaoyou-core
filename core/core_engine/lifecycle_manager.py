#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生命周期管理器
统一管理所有异步服务的初始化和关闭
"""
import logging
import asyncio
import sys
from typing import Dict, Any, List, Optional, Callable, Awaitable
import signal

logger = logging.getLogger(__name__)


class ServiceLifecycle:
    """
    服务生命周期管理类
    """
    def __init__(self):
        self._initialized = False
        self._shutdown = False
        self._services: Dict[str, Dict[str, Any]] = {}
        self._shutdown_tasks: List[Callable[[], Awaitable[None]]] = []
        self._startup_tasks: List[Callable[[], Awaitable[None]]] = []
        
    def register_service(
        self,
        name: str,
        initialize_func: Callable[[], Awaitable[None]],
        shutdown_func: Callable[[], Awaitable[None]],
        priority: int = 100
    ):
        """
        注册服务
        
        Args:
            name: 服务名称
            initialize_func: 初始化函数
            shutdown_func: 关闭函数
            priority: 优先级，数字越小优先级越高
        """
        self._services[name] = {
            "initialize": initialize_func,
            "shutdown": shutdown_func,
            "priority": priority,
            "initialized": False
        }
        
        # 根据优先级排序
        self._startup_tasks = sorted(
            self._services.values(),
            key=lambda x: x["priority"]
        )
        
        # 关闭时按相反顺序
        self._shutdown_tasks = sorted(
            self._services.values(),
            key=lambda x: x["priority"],
            reverse=True
        )
        
        logger.info(f"服务已注册: {name} (优先级: {priority})")
    
    async def initialize_all(self):
        """
        初始化所有服务
        """
        if self._initialized:
            logger.warning("生命周期管理器已经初始化")
            return
        
        logger.info("开始初始化所有服务...")
        
        try:
            # 按优先级初始化服务
            for service_config in self._startup_tasks:
                service_name = next(
                    k for k, v in self._services.items() if v is service_config
                )
                
                try:
                    logger.info(f"初始化服务: {service_name}")
                    await service_config["initialize"]()
                    service_config["initialized"] = True
                    logger.info(f"服务初始化成功: {service_name}")
                    
                except Exception as e:
                    logger.error(
                        f"初始化服务失败: {service_name}. 错误: {str(e)}",
                        exc_info=True
                    )
                    # 可以选择是否继续或终止
                    # 这里我们选择继续，但记录错误
                    
            self._initialized = True
            logger.info("所有服务初始化完成")
            
        except Exception as e:
            logger.error(f"初始化过程出错: {str(e)}", exc_info=True)
            # 尝试清理已初始化的服务
            await self.shutdown_all()
            raise
    
    async def shutdown_all(self):
        """
        关闭所有服务
        """
        if self._shutdown:
            logger.warning("生命周期管理器已经关闭")
            return
        
        logger.info("开始关闭所有服务...")
        
        try:
            # 按相反优先级关闭服务
            for service_config in self._shutdown_tasks:
                if not service_config["initialized"]:
                    continue
                    
                service_name = next(
                    k for k, v in self._services.items() if v is service_config
                )
                
                try:
                    logger.info(f"关闭服务: {service_name}")
                    await service_config["shutdown"]()
                    service_config["initialized"] = False
                    logger.info(f"服务关闭成功: {service_name}")
                    
                except Exception as e:
                    logger.error(
                        f"关闭服务失败: {service_name}. 错误: {str(e)}",
                        exc_info=True
                    )
                    # 继续关闭其他服务
            
            self._shutdown = True
            self._initialized = False
            logger.info("所有服务关闭完成")
            
        except Exception as e:
            logger.error(f"关闭过程出错: {str(e)}", exc_info=True)
            raise
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取所有服务的状态
        """
        status = {
            "manager_initialized": self._initialized,
            "manager_shutdown": self._shutdown,
            "services": {}
        }
        
        for name, service_config in self._services.items():
            status["services"][name] = {
                "initialized": service_config["initialized"],
                "priority": service_config["priority"]
            }
        
        return status
    
    async def check_health(self) -> Dict[str, Any]:
        """
        检查所有服务的健康状态
        """
        # 默认健康状态
        health_status = {
            "status": "healthy",
            "services": {}
        }
        
        # 检查每个服务的状态
        for name, service_config in self._services.items():
            service_health = {
                "status": "healthy" if service_config["initialized"] else "unhealthy"
            }
            health_status["services"][name] = service_health
            
            # 如果有任何服务未初始化，则整体状态为unhealthy
            if not service_config["initialized"]:
                health_status["status"] = "unhealthy"
        
        return health_status


# 创建全局生命周期管理器实例
_lifecycle_manager = ServiceLifecycle()


def get_lifecycle_manager() -> ServiceLifecycle:
    """
    获取全局生命周期管理器实例
    """
    return _lifecycle_manager


async def setup_lifecycle_management(app):
    """
    设置FastAPI应用的生命周期管理
    
    Args:
        app: FastAPI应用实例
    """
    lifecycle = get_lifecycle_manager()
    
    # 注册信号处理
    def handle_signal(signum, frame):
        logger.info(f"接收到信号: {signum}, 准备关闭服务...")
        # 创建一个任务来关闭服务
        loop = asyncio.get_event_loop()
        loop.create_task(shutdown_all_services())
    
    # 注册信号处理器
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    
    
    # 关闭时关闭所有服务
    @app.on_event("shutdown")
    async def shutdown_event():
        try:
            logger.info("FastAPI应用关闭中...")
            await lifecycle.shutdown_all()
            logger.info("FastAPI应用关闭完成")
        except Exception as e:
            logger.error(f"关闭过程中发生错误: {str(e)}", exc_info=True)


async def shutdown_all_services():
    """
    关闭所有服务（用于信号处理）
    """
    lifecycle = get_lifecycle_manager()
    await lifecycle.shutdown_all()


# 全局Aveline服务实例
_aveline_service = None

def get_aveline_service():
    """
    获取全局Aveline服务实例
    如果未初始化，尝试懒加载
    """
    global _aveline_service
    if _aveline_service is None:
        return initialize_aveline_service_sync()
    return _aveline_service

def initialize_aveline_service_sync():
    """同步初始化Aveline服务（懒加载用）"""
    global _aveline_service
    try:
        from core.services.aveline.service import AvelineService
        from core.utils.logger import get_logger
        logger = get_logger(__name__)
        
        if _aveline_service is None:
            logger.info("Aveline服务懒加载初始化...")
            _aveline_service = AvelineService()
            logger.info("Aveline服务懒加载成功")
        return _aveline_service
    except Exception as e:
        import traceback
        print(f"Aveline服务懒加载失败: {e}")
        traceback.print_exc()
        return None

async def initialize_aveline_service():
    """
    生命周期初始化Aveline服务
    """
    global _aveline_service
    from core.utils.logger import get_logger
    logger = get_logger(__name__)
    
    try:
        if _aveline_service is None:
            logger.info("开始初始化Aveline服务...")
            from core.services.aveline.service import AvelineService
            _aveline_service = AvelineService()
        
        if hasattr(_aveline_service, 'initialize'):
            await _aveline_service.initialize()
            
        logger.info("Aveline服务初始化成功")
        return _aveline_service
    except Exception as e:
        logger.error(f"Aveline服务初始化失败: {type(e).__name__}: {str(e)}")
        import traceback
        logger.error(f"详细错误堆栈:\n{traceback.format_exc()}")
        # 即使初始化失败，尝试创建一个基本实例
        try:
            if _aveline_service is None:
                from core.services.aveline.service import AvelineService
                _aveline_service = AvelineService()
            return _aveline_service
        except:
            return None

async def shutdown_aveline_service():
    """
    关闭Aveline服务
    """
    global _aveline_service
    from core.utils.logger import get_logger
    logger = get_logger(__name__)
    
    try:
        if _aveline_service:
            logger.info("开始关闭Aveline服务...")
            if hasattr(_aveline_service, 'shutdown'):
                if asyncio.iscoroutinefunction(_aveline_service.shutdown):
                    await _aveline_service.shutdown()
                else:
                    _aveline_service.shutdown()
            _aveline_service = None
            logger.info("Aveline服务关闭成功")
    except Exception as e:
        logger.error(f"Aveline服务关闭失败: {str(e)}")

async def initialize_active_care_service():
    """
    初始化主动关怀服务
    """
    from core.services.active_care.service import get_active_care_service
    service = get_active_care_service()
    await service.initialize()

async def shutdown_active_care_service():
    """
    关闭主动关怀服务
    """
    from core.services.active_care.service import get_active_care_service
    service = get_active_care_service()
    await service.shutdown()

async def initialize_default_services():
    """
    初始化默认服务
    """
    from core.utils.logger import get_logger
    logger = get_logger(__name__)
    lifecycle = get_lifecycle_manager()
    
    # 导入必要的服务初始化函数
    from core.services.scheduler.task_scheduler_adapter import initialize_scheduler, shutdown_scheduler
    from core.interfaces.websocket.fastapi_websocket_adapter import initialize_websocket_adapter, shutdown_websocket_adapter
    
    from core.services.scheduler.cpu_task_processor import initialize_cpu_processor, shutdown_cpu_processor, get_cpu_processor
    from core.async_cache import initialize_cache, shutdown_cache, get_cache_manager
    from core.async_monitor import initialize_monitoring, shutdown_monitoring, get_performance_monitor, get_health_checker
    from core.services.monitoring.system_memory_service import initialize_system_memory_manager, shutdown_system_memory_manager
    
    # 注册CPU任务处理器（最高优先级）
    lifecycle.register_service(
        name="cpu_processor",
        initialize_func=initialize_cpu_processor,
        shutdown_func=shutdown_cpu_processor,
        priority=5
    )
    
    # 注册缓存系统（高优先级，仅次于CPU处理器）
    lifecycle.register_service(
        name="cache_system",
        initialize_func=initialize_cache,
        shutdown_func=shutdown_cache,
        priority=6
    )

    # 注册系统内存管理服务（高优先级）
    async def init_memory_manager_wrapper():
        import asyncio
        await asyncio.to_thread(initialize_system_memory_manager)

    lifecycle.register_service(
        name="system_memory_manager",
        initialize_func=init_memory_manager_wrapper,
        shutdown_func=shutdown_system_memory_manager,
        priority=7
    )
    
    # 注册任务调度器（高优先级）
    lifecycle.register_service(
        name="task_scheduler",
        initialize_func=initialize_scheduler,
        shutdown_func=shutdown_scheduler,
        priority=10
    )
    
    # 注册监控系统（中等优先级）
    lifecycle.register_service(
        name="monitoring_system",
        initialize_func=initialize_monitoring,
        shutdown_func=shutdown_monitoring,
        priority=15
    )
    
    # 注册WebSocket适配器
    lifecycle.register_service(
        name="websocket_adapter",
        initialize_func=initialize_websocket_adapter,
        shutdown_func=shutdown_websocket_adapter,
        priority=20
    )
    
    # 注册Aveline服务
    lifecycle.register_service(
        name="aveline_service",
        initialize_func=initialize_aveline_service,
        shutdown_func=shutdown_aveline_service,
        priority=30
    )
    
    # 注册主动关怀服务
    lifecycle.register_service(
        name="active_care_service",
        initialize_func=initialize_active_care_service,
        shutdown_func=shutdown_active_care_service,
        priority=40
    )
    
    logger.info("默认服务注册完成")
