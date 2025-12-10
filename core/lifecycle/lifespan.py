import asyncio
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

from core.core_engine.lifecycle_manager import (
    initialize_default_services,
    get_lifecycle_manager,
    shutdown_all_services
)
from core.core_engine.event_bus import EventBus
from core.async_monitor import get_performance_monitor, initialize_monitoring

logger = logging.getLogger(__name__)
event_bus = EventBus()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    """
    logger.info(">>> STARTUP EVENT STARTED <<<")
    
    # 初始化默认服务
    await initialize_default_services()
    
    # 初始化所有注册的服务
    await get_lifecycle_manager().initialize_all()
    
    logger.info(">>> APPLICATION SETUP COMPLETED <<<")
    
    # 异步初始化 TTS (后台)
    try:
        from core.voice import get_tts_manager
        manager = get_tts_manager()
        asyncio.create_task(manager.initialize())
    except Exception:
        pass

    # 启动生活模拟监控
    try:
        from core.services.life_simulation.service import get_life_simulation_service
        logger.info(">>> STARTING LIFE SIMULATION <<<")
        await get_life_simulation_service().start_monitor()
        logger.info(">>> LIFE SIMULATION STARTED <<<")
    except Exception as e:
        logger.error(f"启动生活模拟监控失败: {e}")
        
    # 确保监控服务已启动
    try:
        from core.core_engine.config_manager import ConfigManager
        config = ConfigManager().get_all_config()
        monitor = get_performance_monitor()
        # 如果monitor未初始化或线程未运行
        if monitor is None or not monitor.monitor_thread or not monitor.monitor_thread.is_alive():
            logger.info("检测到监控服务未启动，正在强制启动...")
            await initialize_monitoring(config)
            logger.info("监控服务强制启动完成")
    except Exception as e:
        logger.error(f"强制启动监控服务失败: {e}")
    
    logger.info("所有路由已注册完成")
    for route in app.routes:
        if hasattr(route, "path"):
            logger.info(f"Registered Route: {route.path} [{','.join(route.methods) if hasattr(route, 'methods') else ''}]")
            
    asyncio.create_task(event_bus.publish("app.startup_completed"))
    logger.info("FastAPI应用启动完成")
    
    # 临时环境变量设置
    try:
        os.environ.setdefault("XIAOYOU_TEXT_MODEL_PATH", "d:\\AI\\xiaoyou-core\\models\\L3-8B-Stheno-v3.2")
    except Exception:
        pass

    yield
    
    logger.info(">>> SHUTDOWN EVENT STARTED <<<")
    await get_lifecycle_manager().shutdown_all()
    logger.info(">>> APPLICATION SHUTDOWN COMPLETED <<<")
