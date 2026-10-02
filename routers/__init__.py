# -*- coding: utf-8 -*-
"""路由模块汇总（重构后）。

== 架构说明 ==
所有业务端点挂载在 /api/v1/* 之下，版本前缀 /api/v1 在本文件唯一声明。
各业务域按文件夹组织：
  - v1/      业务域（chat / sessions / life / memories / media / vocab / ... ）
  - admin/   运维 / 开发态（auto_heal / data_ops / remote_ops），业务端不应引用

特殊处理：
  - openai_compat 保留 OpenAI 标准 /v1/chat/completions 前缀，独立挂在顶层
    （main.py 需 app.include_router(openai_compat_router) 单独挂载）。

为保持 main.py 兼容，仍导出 api_v1_router（= 带 /api/v1 前缀的业务聚合），
main.py 只需额外 include openai_compat_router 即可。

旧 router 文件（session_router.py / memory_router.py / study_router.py /
workspace_router.py / peer_chat_router.py 等，以及 api_v1/ 子目录、
api_router.py）已废弃，待确认无外部引用后删除。
"""

from fastapi import APIRouter

# 新的业务域聚合
from .v1 import router as v1_router
from .admin import router as admin_router

# 独立挂在顶层的特殊端点
from .openai_compat import router as openai_compat_router
from .obsidian import router as obsidian_router


# ==================== 顶层聚合（唯一 /api/v1 声明点） ====================
# 所有业务端点 + 运维端点 + WebSocket 挂在此处。
# WebSocket 已包含在 v1_router 内（/api/v1/ws）。

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(v1_router)
api_v1_router.include_router(admin_router)


# ==================== 顶层独立挂载（不进 /api/v1） ====================
# openai_compat 需要 /v1/chat/completions 标准 OpenAI 路径。
# main.py 需单独执行：app.include_router(openai_compat_router)


__all__ = [
    "api_v1_router",
    "v1_router",
    "admin_router",
    "openai_compat_router",
    "obsidian_router",
]
