# -*- coding: utf-8 -*-
"""v1 业务域聚合入口。

所有 v1 业务端点挂载在 /api/v1/* 之下。版本前缀由顶层 routers/__init__.py 唯一声明，
本聚合层只负责把各业务子域 include 进来。包含 WebSocket（/api/v1/ws）。
"""
from fastapi import APIRouter

from .sessions import router as sessions_router
from .health import router as health_router
from .user import router as user_router
from .personas import router as personas_router
from .models import router as models_router
from .plugins import router as plugins_router
from .peer_chat import router as peer_chat_router
from .food import router as food_router
from .vision import router as vision_router
from .life import router as life_router
from .chat import router as chat_router
from .system import router as system_router
from .memories import router as memories_router
from .context import router as context_router
from .media import router as media_router
from .vocab import router as vocab_router
from .tutor import router as tutor_router
from .diary import router as diary_router
from .tasks import router as tasks_router
from .workspace import router as workspace_router
from .study_daily import router as study_daily_router
from .study_focus import router as study_focus_router
from ..websocket import router as websocket_router

router = APIRouter()

# 按业务域分组
router.include_router(chat_router)
router.include_router(sessions_router)
router.include_router(health_router)
router.include_router(life_router)
router.include_router(user_router)
router.include_router(personas_router)
router.include_router(models_router)
router.include_router(plugins_router)
router.include_router(peer_chat_router)
router.include_router(food_router)
router.include_router(vision_router)
router.include_router(system_router)
router.include_router(memories_router)
router.include_router(context_router)
router.include_router(media_router)
router.include_router(vocab_router)
router.include_router(tutor_router)
router.include_router(diary_router)
router.include_router(tasks_router)
router.include_router(workspace_router)
router.include_router(study_focus_router)
router.include_router(study_daily_router)
router.include_router(websocket_router)

__all__ = ["router"]
