#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由模块汇总
"""
from fastapi import APIRouter

from .websocket_router import router as websocket_router
from .health_router import router as health_router
from .api_router import router as api_router
from .session_router import router as session_router
from .memory_router import router as memory_router

# 创建主路由
api_v1_router = APIRouter()

# 包含所有路由模块
api_v1_router.include_router(websocket_router)
api_v1_router.include_router(health_router)
api_v1_router.include_router(api_router)
api_v1_router.include_router(session_router)
api_v1_router.include_router(memory_router)

__all__ = [
    "api_v1_router",
    "websocket_router",
    "health_router",
    "api_router",
    "session_router",
    "memory_router"
]