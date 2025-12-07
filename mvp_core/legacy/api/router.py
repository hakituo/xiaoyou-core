#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API路由模块
"""
from fastapi import APIRouter, Depends, WebSocket
from mvp_core.core import get_core_engine
from mvp_core.api.websocket.websocket_adapter import get_websocket_adapter

# 创建路由
api_router = APIRouter(tags=["api"])

# WebSocket路由
@api_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket端点
    """
    websocket_adapter = get_websocket_adapter()
    await websocket_adapter.handle_websocket(websocket)

# 系统状态相关路由
@api_router.get("/status")
async def get_status():
    """
    获取系统状态
    """
    core_engine = get_core_engine()
    return {
        "status": "ok",
        "service": "AI Core MVP",
        "core_running": core_engine.is_running(),
        "components": list(core_engine.get_all_components().keys())
    }

# 模型相关路由
@api_router.get("/models")
async def list_models():
    """
    获取可用模型列表
    """
    core_engine = get_core_engine()
    models = core_engine.model_manager.list_models()
    return {
        "status": "success",
        "models": models,
        "count": len(models)
    }

@api_router.get("/models/{model_name}/load")
async def load_model(model_name: str):
    """
    加载模型
    """
    core_engine = get_core_engine()
    success = core_engine.model_manager.load_model(model_name)
    return {
        "status": "success" if success else "error",
        "model_name": model_name,
        "loaded": success
    }

@api_router.get("/models/{model_name}/unload")
async def unload_model(model_name: str):
    """
    卸载模型
    """
    core_engine = get_core_engine()
    success = core_engine.model_manager.unload_model(model_name)
    return {
        "status": "success" if success else "error",
        "model_name": model_name,
        "unloaded": success
    }

# 系统资源相关路由
@api_router.get("/system/resources")
async def get_system_resources():
    """
    获取系统资源使用情况
    """
    core_engine = get_core_engine()
    resources = core_engine.model_manager.get_system_resources()
    return {
        "status": "success",
        "resources": resources
    }

# 服务相关路由
@api_router.get("/services")
async def list_services():
    """
    获取服务列表
    """
    core_engine = get_core_engine()
    lifecycle_manager = core_engine.lifecycle_manager
    services = [{"name": service["name"], "priority": service["priority"]} 
                for service in lifecycle_manager.services]
    return {
        "status": "success",
        "services": services,
        "count": len(services)
    }

# 健康检查路由
@api_router.get("/health")
async def health_check():
    """
    健康检查
    """
    core_engine = get_core_engine()
    lifecycle_manager = core_engine.lifecycle_manager
    health_status = await lifecycle_manager.health_check()
    return {
        "status": health_status["status"],
        "timestamp": health_status["timestamp"],
        "services": health_status["services"]
    }
