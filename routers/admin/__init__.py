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
from fastapi import APIRouter

from .auto_heal import router as auto_heal_router
from .data_ops import router as data_ops_router
from .remote_ops import router as remote_ops_router
from .memory_watchdog import router as memory_watchdog_router

router = APIRouter()

router.include_router(auto_heal_router)
router.include_router(data_ops_router)
router.include_router(remote_ops_router)
router.include_router(memory_watchdog_router, prefix="/admin")
router.include_router(memory_watchdog_router)

__all__ = ["router"]
