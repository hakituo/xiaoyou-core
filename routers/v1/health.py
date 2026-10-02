# -*- coding: utf-8 -*-
"""健康检查端点。

返回系统整体状态、各服务状态及当前性能指标，供探活与监控使用。
"""

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["系统健康"])


@router.get("", summary="系统健康检查")
async def health_check():
    from core.async_monitor import get_health_checker, get_performance_monitor
    from core.services.monitoring.resource_monitor import get_resource_monitor
    from core.resource_manager import get_resource_manager
    from core.utils.resource_lock import get_resource_lock
    from core.core_engine.lifecycle_manager import get_lifecycle_manager
    from core.services.scheduler.task.task_scheduler import get_global_scheduler

    try:
        health_checker = get_health_checker()
        services_health = await health_checker.check_all_services()
        health_summary = health_checker.get_health_summary()

        monitor = get_performance_monitor()
        metrics = monitor.get_current_metrics()

        payload = {
            "status": health_summary["overall_status"],
            "services": services_health,
            "metrics": metrics,
            "timestamp": health_summary["timestamp"],
            "service": "AI Agent Core",
            "version_tag": "v_debug_1",
        }

        try:
            payload["lifecycle"] = get_lifecycle_manager().get_status()
        except Exception:
            pass

        try:
            payload["resources"] = get_resource_monitor().to_contract_dict()
        except Exception:
            pass

        try:
            payload["resource_manager"] = get_resource_manager().get_resource_stats()
        except Exception:
            pass

        try:
            payload["gpu_gate"] = get_resource_lock().get_status()
        except Exception:
            pass

        try:
            sched = get_global_scheduler()
            active = await sched.get_active_tasks()
            payload["tasks"] = {
                "active_count": len(active or {}),
                "active": {
                    tid: {
                        "task_id": t.task_id,
                        "name": t.name,
                        "status": getattr(t.status, "value", str(t.status)),
                        "priority": getattr(t.priority, "value", None),
                        "task_type": getattr(t.task_type, "value", None),
                        "created_at": float(t.created_at or 0.0),
                        "start_time": float(t.start_time or 0.0)
                        if t.start_time
                        else None,
                    }
                    for tid, t in (active or {}).items()
                },
            }
        except Exception:
            pass

        return payload
    except Exception as e:
        # P1-5: 对外模糊化错误，详细错误仅写日志，避免泄露内部细节（堆栈路径/模块名等）
        logger.error(f"健康检查失败: {e}", exc_info=True)
        return {"status": "degraded", "error": "internal error", "service": "AI Agent Core"}
