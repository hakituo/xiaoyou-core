#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
健康检查路由模块
提供系统状态监控端点
"""
import logging
import asyncio
import psutil
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from core.interfaces.websocket.fastapi_websocket_adapter import get_fastapi_websocket_adapter
from core.services.scheduler.task_scheduler_adapter import get_task_scheduler
from core.core_engine.lifecycle_manager import get_aveline_service

async def get_aveline_service_status():
    """获取Aveline服务状态"""
    service = get_aveline_service()
    if service and getattr(service, '_initialized', False):
        return {
            "status": "active", 
            "message": "服务正在运行",
            "performance": getattr(service, 'performance_stats', {})
        }
    return {"status": "inactive", "message": "服务未初始化"}

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


async def get_system_metrics() -> Dict[str, Any]:
    """
    获取系统资源指标
    """
    try:
        # CPU使用率
        cpu_percent = psutil.cpu_percent(interval=0.1, percpu=False)
        
        # 内存使用情况
        memory = psutil.virtual_memory()
        
        # 磁盘使用情况
        disk = psutil.disk_usage('/')
        
        # 网络统计
        net_io = psutil.net_io_counters()
        
        # 进程数
        process_count = len(psutil.pids())
        
        # 系统正常运行时间
        uptime_seconds = psutil.boot_time()
        uptime = datetime.now().timestamp() - uptime_seconds
        
        gpu_info = {}
        gpu_percent = 0.0
        try:
            import torch
            if torch.cuda.is_available():
                props = torch.cuda.get_device_properties(0)
                total_mb = float(props.total_memory) / (1024.0 * 1024.0)
                used_mb = float(torch.cuda.memory_allocated(0)) / (1024.0 * 1024.0)
                percent = (used_mb / total_mb) * 100.0 if total_mb > 0 else 0.0
                gpu_info = {
                    "index": 0,
                    "total_mb": total_mb,
                    "used_mb": used_mb,
                    "percent": percent
                }
                gpu_percent = percent
        except Exception:
            pass
        return {
            "cpu_percent": cpu_percent,
            "memory": {
                "total": memory.total,
                "available": memory.available,
                "used": memory.used,
                "percent": memory.percent
            },
            "disk": {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "percent": disk.percent
            },
            "network": {
                "bytes_sent": net_io.bytes_sent,
                "bytes_recv": net_io.bytes_recv,
                "packets_sent": net_io.packets_sent,
                "packets_recv": net_io.packets_recv
            },
            "process_count": process_count,
            "uptime_seconds": uptime,
            "system_time": datetime.now().isoformat(),
            "gpu": gpu_info,
            "gpu_percent": gpu_percent
        }
    except Exception as e:
        logger.error(f"获取系统指标失败: {str(e)}")
        return {"error": str(e)}


async def get_service_status() -> Dict[str, Any]:
    """
    获取服务状态
    """
    status = {
        "websocket": {"status": "unknown"},
        "scheduler": {"status": "unknown"},
        "aveline_service": {"status": "unknown"}
    }
    
    try:
        # 检查WebSocket适配器状态
        websocket_adapter = get_fastapi_websocket_adapter()
        if websocket_adapter:
            ws_stats = await websocket_adapter.get_connection_stats()
            status["websocket"] = {
                "status": "active",
                **ws_stats
            }
    except Exception as e:
        logger.error(f"获取WebSocket状态失败: {str(e)}")
        status["websocket"] = {"status": "error", "error": str(e)}
    
    try:
        # 检查任务调度器状态
        scheduler = get_task_scheduler()
        if scheduler:
            status["scheduler"] = {
                "status": "active",
                "stats": scheduler.get_stats()
            }
    except Exception as e:
        logger.error(f"获取任务调度器状态失败: {str(e)}")
        status["scheduler"] = {"status": "error", "error": str(e)}
    
    try:
        # 检查Aveline服务状态
        aveline_status = get_aveline_service_status()
        status["aveline_service"] = aveline_status
    except Exception as e:
        logger.error(f"获取Aveline服务状态失败: {str(e)}")
        status["aveline_service"] = {"status": "error", "error": str(e)}
    
    return status


@router.get("/")
async def health_check():
    """
    基础健康检查端点
    返回系统运行状态
    """
    try:
        # 快速健康检查，只返回基本状态
        return JSONResponse(
            status_code=200,
            content={
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "service": "xiaoyou-core-api"
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
        )


@router.get("/detailed")
async def detailed_health_check():
    """
    详细健康检查端点
    返回系统资源使用情况和各服务状态
    """
    try:
        # 并行获取系统指标和服务状态
        system_metrics, service_status = await asyncio.gather(
            get_system_metrics(),
            get_service_status()
        )
        
        # 综合状态判断
        overall_status = "healthy"
        for service_name, service_data in service_status.items():
            if service_data.get("status") != "active" and service_data.get("status") != "ok":
                overall_status = "degraded"
                break
        
        return JSONResponse(
            status_code=200 if overall_status == "healthy" else 503,
            content={
                "status": overall_status,
                "timestamp": datetime.now().isoformat(),
                "system": system_metrics,
                "services": service_status
            }
        )
    except Exception as e:
        logger.error(f"详细健康检查失败: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
        )


@router.get("/metrics")
async def system_metrics():
    """
    系统指标端点
    返回详细的系统资源使用情况
    """
    metrics = await get_system_metrics()
    return {
        "status": "ok",
        "metrics": metrics,
        "timestamp": datetime.now().isoformat()
    }


@router.get("/services")
async def service_status():
    """
    服务状态端点
    返回各核心服务的运行状态
    """
    status = await get_service_status()
    return {
        "status": "ok",
        "services": status,
        "timestamp": datetime.now().isoformat()
    }


@router.get("/version")
async def get_version():
    """
    获取API版本信息
    """
    # 在实际应用中，应该从配置或版本文件中读取
    return {
        "version": "1.0.0",
        "build": "dev",
        "timestamp": datetime.now().isoformat()
    }
