# -*- coding: utf-8 -*-
"""admin 域：运维 / 开发态端点聚合入口。

业务端永远不应引用此目录下的端点。

注意：
- 本 router 无 prefix，直接 include 进 api_v1_router（prefix=/api/v1）。
- admin 域的规范入口统一为 /api/v1/admin/*。
- memory_watchdog 历史上曾暴露为 /api/v1/memory/*，现保留旧地址兼容，
  同时新增规范入口 /api/v1/admin/memory/*。
- openai_compat 因需要保留 /v1 标准前缀（OpenAI SDK 兼容），
  独立挂在顶层，不纳入此 admin 子聚合。
"""
from fastapi import APIRouter, WebSocket

from core.middleware.security import authorize_websocket

from .auto_heal import router as auto_heal_router
from .data_ops import router as data_ops_router
from .remote_ops import router as remote_ops_router
from .memory_watchdog import (
    router as memory_watchdog_router,
    websocket_memory_monitor,
)

router = APIRouter()

# memory_watchdog.py 的历史 WebSocket handler 会直接 accept，没有统一鉴权。
# 聚合时先把它从子 router 中移除，避免 include_router 再复制出匿名入口；
# 下方两个显式包装路由是该 handler 唯一的公网注册入口。
memory_watchdog_router.routes = [
    route
    for route in memory_watchdog_router.routes
    if getattr(route, "path", "") != "/memory/ws"
]


async def _secure_memory_websocket(websocket: WebSocket) -> None:
    """给 memory watchdog 的业务 handler 补统一握手鉴权。"""
    if not await authorize_websocket(websocket):
        return
    await websocket_memory_monitor(websocket)


@router.websocket("/admin/memory/ws")
async def secure_admin_memory_websocket(websocket: WebSocket):
    """规范 admin 内存监控 WS 入口。"""
    await _secure_memory_websocket(websocket)


@router.websocket("/memory/ws")
async def secure_legacy_memory_websocket(websocket: WebSocket):
    """历史兼容内存监控 WS 入口。"""
    await _secure_memory_websocket(websocket)


router.include_router(auto_heal_router)
router.include_router(data_ops_router)
router.include_router(remote_ops_router)
router.include_router(memory_watchdog_router, prefix="/admin")
router.include_router(memory_watchdog_router)

__all__ = ["router"]
