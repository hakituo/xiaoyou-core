#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
健康检查路由模块
提供系统状态监控端点
"""
import logging
from typing import Dict, Any
from fastapi import APIRouter
from core.async_monitor import get_health_checker, get_performance_monitor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

@router.get("")
async def health_check():
    """
    健康检查端点
    返回系统整体状态、各服务状态及当前性能指标
    """
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
