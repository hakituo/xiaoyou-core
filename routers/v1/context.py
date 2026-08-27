# -*- coding: utf-8 -*-
"""上下文与日常（context）域聚合路由。

本文件不再直接实现端点,而是作为业务子域的聚合入口:
- context_device: 设备上下文同步 (/context/sync, /context/device)
- context_daily: 日常数据记录与画像 (/context/daily/*)
- context_health: Health Connect 健康数据同步 (/context/health/*)
- context_intent: 意图识别 (/context/intent/classify)
"""

from fastapi import APIRouter

from .context_device import router as context_device_router
from .context_daily import router as context_daily_router
from .context_health import router as context_health_router
from .context_intent import router as context_intent_router

router = APIRouter(tags=["上下文与日常"])

# 按业务域聚合;子路由各自持有 /context 前缀,本聚合层不追加额外前缀
router.include_router(context_device_router)
router.include_router(context_daily_router)
router.include_router(context_health_router)
router.include_router(context_intent_router)
