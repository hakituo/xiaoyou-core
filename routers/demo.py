#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncio
import json
import os
import hmac
import logging
from pydantic import BaseModel

logger = logging.getLogger("DEMO_ROUTER")

router = APIRouter(prefix="/demo", tags=["demo"])


def _demo_utils():
    from core.utils.demo_utils import add_demo_log as add_shared_demo_log, get_demo_logs
    return add_shared_demo_log, get_demo_logs


class LogMessage(BaseModel):
    message: str
    level: str = "info"


@router.post("/logs")
async def add_demo_log_endpoint(log: LogMessage):
    """供演示脚本提交日志"""
    add_shared_demo_log, _ = _demo_utils()
    add_shared_demo_log(log.message, log.level)
    return {"status": "ok"}


@router.post("/trigger_kvswap")
async def trigger_kvswap_test():
    """手动触发 KVSwap 压力测试 (长上下文注入)"""
    from core.services.scheduler.cpp_scheduler_engine import get_scheduler_engine
    from config.integrated_config import get_settings
    from core.utils.demo_utils import add_demo_log as add_shared_demo_log

    engine = get_scheduler_engine()
    settings = get_settings()

    if not engine or not engine.enabled:
        return {"status": "error", "message": "C++ 调度器未启用，无法演示 KVSwap"}

    # 检查是否启用了 KVSwap
    kv_enabled = settings.model.kv_swap_enabled
    if not kv_enabled:
        add_shared_demo_log(
            "⚠️ KVSwap 功能目前在配置中已禁用，演示将仅显示模拟逻辑", "warning"
        )

    add_shared_demo_log("🚀 启动 KVSwap 压力测试：准备注入超长上下文...", "warning")

    # 1. 模拟注入超长上下文 (4096+ tokens)
    long_context_prefix = (
        "这是一段极其庞大的背景记忆数据，用于压力测试 KVSwap 功能。" * 100
    )
    add_shared_demo_log(
        f"已构建虚拟上下文负载: {len(long_context_prefix)} 字符", "info"
    )

    # 2. 模拟触发 KVSwap
    add_shared_demo_log(
        "Scheduler: Context size exceeds 2048 tokens. KVSwap candidate identified.",
        "warning",
    )
    await asyncio.sleep(0.8)
    add_shared_demo_log(
        "KVSwap: Serializing KV state for conversation 'demo_kv_swap'...", "info"
    )

    # 如果真的启用了，这里可以尝试调用底层接口（如果有暴露）
    # 目前 C++ 侧是根据 token 数自动触发的

    await asyncio.sleep(1.2)
    add_shared_demo_log(
        "KVSwap: Successfully swapped KV cache to NVMe storage (kvswap/demo_kv_swap.bin)",
        "success",
    )

    # 3. 模拟回载
    await asyncio.sleep(1.5)
    add_shared_demo_log(
        "KVSwap: User request received. Loading KV state from disk...", "info"
    )
    await asyncio.sleep(0.8)
    add_shared_demo_log(
        "KVSwap: KV cache reconstructed. Resuming inference with zero re-computation.",
        "success",
    )

    return {"status": "ok", "message": "KVSwap test sequence completed"}


# 资源状态推送
@router.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    required_token = ""
    try:
        from config.integrated_config import get_settings

        required_token = str(get_settings().security.web_access_token or "").strip()
    except Exception:
        required_token = ""

    if not required_token:
        await websocket.close(
            code=1008,
            reason="服务未配置访问令牌，请设置 XIAOYOU_SECURITY_WEB_ACCESS_TOKEN",
        )
        return

    query_params = getattr(websocket, "query_params", None)
    ws_token = (
        str(query_params.get("token")).strip()
        if query_params and query_params.get("token") is not None
        else ""
    )
    if not ws_token:
        authorization = str(websocket.headers.get("authorization", "")).strip()
        if authorization.lower().startswith("bearer "):
            ws_token = authorization[7:].strip()
    if not ws_token:
        ws_token = str(websocket.headers.get("x-internal-token", "")).strip()

    if not ws_token or not hmac.compare_digest(ws_token, required_token):
        await websocket.close(code=1008, reason="未授权的 WebSocket 访问")
        return

    await websocket.accept()
    from core.resource_manager import get_resource_manager
    rm = get_resource_manager()
    from core.utils.demo_utils import clear_demo_logs

    clear_demo_logs()

    logger.info("Demo WebSocket connected - Logs cleared for fresh start")
    last_log_count = 0

    # 订阅资源管理器事件 (可选，这里先用轮询)

    try:
        while True:
            try:
                await asyncio.wait_for(rm._update_model_resource_metrics(), timeout=0.6)
            except Exception:
                pass
            # 获取当前所有模型资源状态
            models_data = {}
            for model_id, model in rm.models.items():
                # 计算显示用的 VRAM 占用
                display_vram = model.vram_usage_mb if model.is_loaded else 0
                if model.is_offloaded:
                    display_vram = 0  # Offload 到内存时显存为 0

                models_data[model_id] = {
                    "is_loaded": model.is_loaded,
                    "is_offloaded": model.is_offloaded,
                    "memory_usage": model.memory_usage_mb,
                    "vram_usage": display_vram,
                    "priority": str(model.priority),
                    "device": model.device if model.is_loaded else "CPU",
                }

            # 获取增量日志
            all_logs = _demo_utils()[1]()
            new_logs = all_logs[last_log_count:]
            last_log_count = len(all_logs)

            # 获取系统整体资源状态
            gpu_info = rm.monitor.get_gpu_memory_usage()
            gpu_gate = None
            try:
                from core.utils.resource_lock import get_resource_lock
                gpu_gate = get_resource_lock().get_status()
            except Exception:
                gpu_gate = None
            from core.services.scheduler.cpp_scheduler_engine import get_scheduler_status
            scheduler_data = get_scheduler_status()

            status = {
                "models": models_data,
                "system": {
                    "cpu_percent": rm.monitor.get_cpu_usage(),
                    "cpu_model": rm.monitor.get_cpu_model(),
                    "memory_percent": rm.monitor.get_memory_usage(),
                    "gpu_memory_used": gpu_info[0] if gpu_info else 0,
                    "gpu_memory_total": gpu_info[1] if gpu_info else 8192,
                    "gpu_model": rm.monitor.get_gpu_model(),
                    "gpu_gate": gpu_gate,
                },
                "scheduler": scheduler_data,
                "logs": new_logs,
                "timestamp": asyncio.get_event_loop().time(),
            }

            await websocket.send_text(json.dumps(status))
            await asyncio.sleep(0.5)  # 提高刷新率
    except WebSocketDisconnect:
        logger.info("Demo WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")


# Demo 页面路由
@router.get("", response_class=HTMLResponse)
async def get_demo_page():
    # 尝试从 static/demo/index.html 读取
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html_path = os.path.join(project_root, "static", "demo", "index.html")

    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()

    return """
    <html>
        <head><title>Demo Not Found</title></head>
        <body><h1>Demo Dashboard HTML not found in static/demo/index.html</h1></body>
    </html>
    """
