# -*- coding: utf-8 -*-
"""生命状态（life）域聚合路由。

本文件不再直接实现端点，而是作为业务子域的聚合入口：
- life_status: 状态查询与情绪检测（/life/status, /life/emotion/detect）
- life_sleep: 睡眠唤醒（/life/sleep/wake）
- life_activity: 活动中断窗口（/life/activity/interrupt|skip|extend）
"""

from fastapi import APIRouter

from .life_activity import router as life_activity_router
from .life_sleep import router as life_sleep_router
from .life_status import router as life_status_router

router = APIRouter(tags=["生命与情绪"])

# 子路由自带 /life 前缀，本聚合层绝不能再声明 prefix，否则会叠加成 /life/life/*
router.include_router(life_status_router)
router.include_router(life_sleep_router)
router.include_router(life_activity_router)

__all__ = ["router"]
