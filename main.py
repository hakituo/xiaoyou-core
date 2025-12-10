#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI主应用入口
高性能异步AI Agent核心系统
"""
import os
# [CRITICAL] 设置 HuggingFace 镜像地址
# 必须在导入 transformers/sentence_transformers/huggingface_hub 之前设置，否则不生效
# 这解决了国内网络环境下连接 huggingface.co 超时或 SSL 验证失败的问题
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import logging
import uvicorn


from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

# 核心组件导入
from core.core_engine.config_manager import ConfigManager
from core.utils.logger import get_logger, init_logging_system
from core.core_engine.event_bus import EventBus
from core.async_monitor import request_performance_middleware

# 路由导入
from routers import api_v1_router

# 重构后的模块导入
from core.utils.error_handlers import global_exception_handler
from core.utils.static_files import mount_static_files
from core.lifecycle.lifespan import lifespan

# 初始化配置和日志
config_manager = ConfigManager()
config = config_manager.get_all_config()
init_logging_system()
logger = get_logger(__name__)

# 全局事件总线
event_bus = EventBus()

# 创建FastAPI应用
app = FastAPI(
    title="XiaoYou AI Core",
    description="High-performance Asynchronous AI Agent Core",
    version="0.5.0",
    lifespan=lifespan
)

# 注册中间件
# 1. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制为特定域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. 性能监控中间件
@app.middleware("http")
async def performance_middleware(request: Request, call_next):
    return await request_performance_middleware(request, call_next)

# 注册异常处理器
app.add_exception_handler(Exception, global_exception_handler)

# 注册API路由
app.include_router(api_v1_router)

# 挂载静态文件 (前端)
mount_static_files(app)

if __name__ == "__main__":
    logger.info("启动应用服务器...")
    host = config.get("server", {}).get("host", "0.0.0.0")
    port = config.get("server", {}).get("port", 8000)
    reload = config.get("server", {}).get("reload", False)
    
    uvicorn.run(
        "main:app", 
        host=host, 
        port=port, 
        reload=reload,
        log_level="info"
    )
