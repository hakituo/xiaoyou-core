#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI主应用入口
高性能异步AI Agent核心系统
"""
import logging
import os
import asyncio

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
import uvicorn
import json
import time
from datetime import datetime

# 导入配置和日志
from core.core_engine.config_manager import ConfigManager
from core.utils.logger import get_logger, init_logging_system
from core.core_engine.event_bus import EventBus
from core.core_engine.lifecycle_manager import (
    setup_lifecycle_management,
    initialize_default_services,
    get_lifecycle_manager
)
from core.log_config import log_request
from core.async_monitor import request_performance_middleware

# 导入路由模块
from routers import api_v1_router
from core.core_engine.model_manager import get_model_manager

# 初始化配置和日志
config_manager = ConfigManager()
config = config_manager.get_all_config()
logger = get_logger(__name__)
# 初始化日志系统
init_logging_system()

# 全局事件总线
event_bus = EventBus()


# 设置生命周期管理
from contextlib import asynccontextmanager
from core.core_engine.lifecycle_manager import shutdown_all_services

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    """
    logger.info(">>> STARTUP EVENT STARTED <<<")
    
    # 初始化默认服务
    await initialize_default_services()
    
    # 设置生命周期管理
    # await setup_lifecycle_management(app) # setup_lifecycle_management is largely redundant with lifespan now, but keeps signal handlers
    # We can manually register signal handlers if needed, or rely on uvicorn's signal handling.
    # For now, let's keep setup_lifecycle_management's signal handling logic but avoid its on_event hook if possible,
    # OR just replicate the logic here.
    # setup_lifecycle_management(app) attaches on_event("shutdown"), which we want to avoid mixing with lifespan.
    # Let's just call initialize_all here.
    
    # 初始化所有注册的服务
    await get_lifecycle_manager().initialize_all()
    
    logger.info(">>> APPLICATION SETUP COMPLETED <<<")
    
    try:
        from core.voice import get_tts_manager
        # TTS管理器可以在后台初始化
        manager = get_tts_manager()
        asyncio.create_task(manager.initialize())
    except Exception:
        pass

    try:
        from core.services.life_simulation.service import get_life_simulation_service
        logger.info(">>> STARTING LIFE SIMULATION <<<")
        # 启动生活模拟监控
        await get_life_simulation_service().start_monitor()
        logger.info(">>> LIFE SIMULATION STARTED <<<")
    except Exception as e:
        logger.error(f"启动生活模拟监控失败: {e}")
        
    
    # 确保监控服务已启动
    try:
        from core.async_monitor import get_performance_monitor, initialize_monitoring
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
    
    # try:
    #     loop = asyncio.get_running_loop()
    #     start_models_watcher(loop)
    # except Exception as e:
    #     logger.error(f"模型目录监听启动失败: {e}")
    try:
        os.environ.setdefault("XIAOYOU_TEXT_MODEL_PATH", "d:\\AI\\xiaoyou-core\\models\\L3-8B-Stheno-v3.2")
    except Exception:
        pass

    # 主动关怀服务已集成到生命周期管理器中，无需在此处手动启动
    
    yield
    
    logger.info(">>> SHUTDOWN EVENT STARTED <<<")
    
    await get_lifecycle_manager().shutdown_all()
    logger.info(">>> APPLICATION SHUTDOWN COMPLETED <<<")


# 创建FastAPI应用实例
app = FastAPI(
    title="高性能异步AI Agent核心系统",
    description="基于FastAPI的异步AI Agent后端服务",
    version="1.0.0",
    lifespan=lifespan
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该设置具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router)

# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器"""
    logger.error(f"全局异常: {str(exc)}", exc_info=True)
    # 记录请求详情
    log_request(logger, request, error=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)}
    )

# 添加性能监控中间件
app.middleware("http")(request_performance_middleware)

# 健康检查端点
@app.get("/health")
async def health_check():
    """健康检查端点"""
    from core.async_monitor import get_health_checker, get_performance_monitor
    
    try:
        # 检查所有服务健康状态
        health_checker = get_health_checker()
        services_health = await health_checker.check_all_services()
        health_summary = health_checker.get_health_summary()
        
        # 获取当前性能指标
        monitor = get_performance_monitor()
        metrics = monitor.get_current_metrics()
        
        return {
            "status": health_summary["overall_status"],
            "services": services_health,
            "metrics": metrics,
            "timestamp": health_summary["timestamp"],
            "service": "AI Agent Core"
        }
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return {"status": "degraded", "error": str(e), "service": "AI Agent Core"}

# 挂载前端静态文件
try:
    frontend_dir = os.path.join(os.path.dirname(__file__), "frontend", "Aveline_UI", "dist")
    if os.path.exists(frontend_dir):
        logger.info(f"挂载前端静态文件: {frontend_dir}")
        
        # 移动端路由
        @app.get("/app")
        async def mobile_app():
            """Serving Mobile App"""
            mobile_file = os.path.join(frontend_dir, "mobile.html")
            if os.path.exists(mobile_file):
                return FileResponse(mobile_file)
            return FileResponse(os.path.join(frontend_dir, "index.html")) # Fallback

        # 挂载静态资源
        app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dir, "assets")), name="assets")
        if os.path.exists(os.path.join(frontend_dir, "icons")):
            app.mount("/icons", StaticFiles(directory=os.path.join(frontend_dir, "icons")), name="icons")
        
        # 服务其他静态文件
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    else:
        logger.warning(f"前端目录不存在，跳过静态文件挂载: {frontend_dir}")
        
        # 如果静态文件不存在，注册默认根路径
        @app.get("/")
        async def root():
            """
            API根路径 (Fallback)
            """
            return {
                "message": "Welcome to Xiaoyou Core API",
                "version": "1.0.0",
                "docs": "/docs",
                "note": "Frontend static files not found."
            }

    # 兼容前端在生产环境误请求Vite客户端脚本，返回空脚本避免报错
    @app.get("/@vite/client")
    async def vite_client_stub():
        return Response("", media_type="application/javascript")

except Exception as e:
    logger.error(f"挂载前端静态文件失败: {e}")
    # 出错时注册默认根路径
    @app.get("/")
    async def root():
        return {
            "message": "Welcome to Xiaoyou Core API",
            "error": str(e)
        }


# 主入口函数
if __name__ == "__main__":
    # 使用uvicorn启动FastAPI应用
    uvicorn.run(
        "main:app",
        host=config.get("server", {}).get("host", "0.0.0.0"),
        port=int(os.environ.get("SERVER_PORT", config.get("server", {}).get("port", 8000))),
        reload=config.get("server", {}).get("reload", False),
        workers=config.get("server", {}).get("workers", 1),
        log_level="info",
        lifespan="on"
    )

@app.get("/health/metrics")
async def health_metrics():
    from core.async_monitor import get_health_checker, get_performance_monitor
    try:
        health_checker = get_health_checker()
        services_health = await health_checker.check_all_services()
        monitor = get_performance_monitor()
        metrics = monitor.get_current_metrics()
        return {"status": "ok", "services": services_health, "metrics": metrics}
    except Exception as e:
        logger.error(f"健康指标失败: {e}")
        return {"status": "degraded", "error": str(e)}


