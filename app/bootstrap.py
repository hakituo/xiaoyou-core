import os
import asyncio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from routers import api_v1_router
from core.utils.logger import get_logger, init_logging_system
from core.log_config import log_request
from core.async_monitor import request_performance_middleware
from contextlib import asynccontextmanager
from core.core_engine.lifecycle_manager import (
    setup_lifecycle_management,
    initialize_default_services,
    get_lifecycle_manager,
    shutdown_all_services
)
from core.core_engine.event_bus import EventBus
# from core.model_manager import start_models_watcher

logger = get_logger(__name__)
init_logging_system()
event_bus = EventBus()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Application startup...")
    asyncio.create_task(initialize_default_services())
    # setup_lifecycle_management is no longer needed in its old form if we handle shutdown here
    # but it registers signal handlers, so we might keep it or refactor it.
    # Let's look at setup_lifecycle_management again. It uses on_event("shutdown").
    # We should probably manually call shutdown in the finally block.
    
    # We'll manually register signal handlers or let the platform handle it?
    # setup_lifecycle_management registers signal handlers which is good.
    # But it also registers an on_event shutdown handler which we want to avoid if using lifespan.
    
    # Let's simplify. We will call initialize_all() here.
    await initialize_default_services() # Wait for registration
    await get_lifecycle_manager().initialize_all() # Wait for initialization
    
    # Signal handlers might still be useful, but we can just rely on lifespan for graceful shutdown usually.
    # However, for robust signal handling, we can keep a simplified setup.
    
    asyncio.create_task(event_bus.publish("app.startup_completed"))
    # try:
    #     loop = asyncio.get_running_loop()
    #     start_models_watcher(loop)
    # except Exception as e:
    #     logger.error(f"模型目录监听启动失败: {e}")
        
    yield
    
    # Shutdown
    logger.info("Application shutdown...")
    await get_lifecycle_manager().shutdown_all()

def create_app() -> FastAPI:
    app = FastAPI(
        title="高性能异步AI Agent核心系统",
        description="基于FastAPI的异步AI Agent后端服务",
        version="1.0.0",
        lifespan=lifespan
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_v1_router)

    @app.exception_handler(Exception)
    async def _global_exception_handler(request: Request, exc: Exception):
        logger.error(f"全局异常: {str(exc)}", exc_info=True)
        log_request(logger, request, error=exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error", "error": str(exc)})

    app.middleware("http")(request_performance_middleware)

    try:
        frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "Aveline_UI", "dist")
        if os.path.exists(frontend_dir):
            app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dir, "assets")), name="assets")
            icons_dir = os.path.join(frontend_dir, "icons")
            if os.path.exists(icons_dir):
                app.mount("/icons", StaticFiles(directory=icons_dir), name="icons")
            app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
        else:
            @app.get("/")
            async def _root():
                return {"message": "Welcome to Xiaoyou Core API", "version": "1.0.0", "docs": "/docs"}
    except Exception as e:
        @app.get("/")
        async def _root_error():
            return {"message": "Welcome to Xiaoyou Core API", "error": str(e)}

    return app

