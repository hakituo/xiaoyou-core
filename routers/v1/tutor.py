# -*- coding: utf-8 -*-
"""教学画像（tutor）域。

从原 study_router 拆出的「教学 / 画像」子系统：学生画像、每日简报、学习计划、
薄弱点、周分析、知识点记录与掌握、薄弱点报告与复习。
含从原 study 的 /notifications 并入的通知端点。
"""

from typing import Dict, Any

from fastapi import APIRouter, Body
import time

from core.utils.logger import get_logger
from core.api.contract import error_response
from core.api.error_response import ErrorCode

logger = get_logger("TUTOR_ROUTER")

router = APIRouter(prefix="/tutor", tags=["教学画像"])


def _get_study_service():
    """延迟导入，避免启动时加载 tkinter/matplotlib 等重型依赖"""
    from core.services.study.service import get_study_service
    return get_study_service()


# ==================== 学生画像与简报 ====================

@router.get("/state", summary="获取结构化学生画像")
async def get_student_state():
    try:
        service = _get_study_service()
        return {"status": "success", "data": service.get_student_state()}
    except Exception as e:
        logger.error(f"获取学生画像失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/today", summary="获取今日学习状态（详细）")
async def get_today_status():
    try:
        service = _get_study_service()
        return {"status": "success", "data": service.get_today_detailed()}
    except Exception as e:
        logger.error(f"获取今日状态失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/briefing", summary="获取每日教学简报")
async def get_daily_briefing():
    try:
        service = _get_study_service()
        return {"status": "success", "data": service.get_daily_briefing()}
    except Exception as e:
        logger.error(f"获取每日简报失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/plan", summary="获取今日学习计划")
async def get_study_plan():
    try:
        service = _get_study_service()
        return {"status": "success", "data": service.get_study_plan()}
    except Exception as e:
        logger.error(f"获取学习计划失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


# ==================== 薄弱点与周分析 ====================

@router.get("/weaknesses", summary="获取薄弱点报告")
async def get_weaknesses():
    try:
        service = _get_study_service()
        return {"status": "success", "data": service.get_weakness_report()}
    except Exception as e:
        logger.error(f"获取薄弱点报告失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/weekly-analysis", summary="获取周学习分析报告")
async def get_weekly_analysis():
    try:
        service = _get_study_service()
        return {"status": "success", "data": service.get_weekly_analysis()}
    except Exception as e:
        logger.error(f"获取周分析失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


# ==================== 知识点记录与掌握 ====================

@router.post("/topic/record", summary="记录知识点学习")
async def record_topic(data: Dict[str, Any] = Body(...)):
    """Body: {"subject": "math", "topic": "三角函数", "status": "new"}"""
    try:
        subject = data.get("subject", "")
        topic = data.get("topic", "")
        status = data.get("status", "new")
        if not subject or not topic:
            return error_response(ErrorCode.MISSING_PARAMETER, message="Missing subject or topic")
        service = _get_study_service()
        return {"status": "success", "data": service.record_topic_learned(subject, topic, status)}
    except Exception as e:
        logger.error(f"记录知识点失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.post("/topic/mastered", summary="标记知识点已掌握")
async def mark_mastered(data: Dict[str, Any] = Body(...)):
    """Body: {"subject": "math", "topic": "三角函数"}"""
    try:
        subject = data.get("subject", "")
        topic = data.get("topic", "")
        if not subject or not topic:
            return error_response(ErrorCode.MISSING_PARAMETER, message="Missing subject or topic")
        service = _get_study_service()
        return {"status": "success", "data": service.mark_topic_mastered(subject, topic)}
    except Exception as e:
        logger.error(f"标记掌握失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


# ==================== 薄弱点报告与复习 ====================

@router.post("/weakness/report", summary="报告薄弱点")
async def report_weakness(data: Dict[str, Any] = Body(...)):
    """Body: {"subject": "math", "topic": "三角函数", "source": "self_reported"}"""
    try:
        subject = data.get("subject", "")
        topic = data.get("topic", "")
        source = data.get("source", "self_reported")
        if not subject or not topic:
            return error_response(ErrorCode.MISSING_PARAMETER, message="Missing subject or topic")
        service = _get_study_service()
        return {"status": "success", "data": service.record_weakness(subject, topic, source)}
    except Exception as e:
        logger.error(f"报告薄弱点失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.post("/weakness/review", summary="记录薄弱点复习结果")
async def review_weakness(data: Dict[str, Any] = Body(...)):
    """Body: {"item_id": "abc123", "quality": 4}，quality 0-5"""
    try:
        item_id = data.get("item_id", "")
        quality = data.get("quality", 3)
        if not item_id:
            return error_response(ErrorCode.MISSING_PARAMETER, message="Missing item_id")
        service = _get_study_service()
        return {"status": "success", "data": service.review_weakness(item_id, int(quality))}
    except Exception as e:
        logger.error(f"记录复习结果失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


# ==================== 通知（从 study 并入） ====================

@router.get("/notifications", summary="获取待处理通知")
async def get_notifications(user_id: str = "default"):
    try:
        from core.managers.notification_manager import get_notification_manager
        nm = get_notification_manager()
        notifs = nm.get_pending_notifications(user_id)
        return {"status": "success", "data": notifs, "timestamp": time.time()}
    except Exception as e:
        logger.error(f"获取通知失败: {e}")
        return {"status": "error", "message": str(e)}
