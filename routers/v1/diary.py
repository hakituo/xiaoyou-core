# -*- coding: utf-8 -*-
"""日记（diary）域。

从原 workspace_router 拆出：日记读写与摘要、工作区快照、定时消息管理、
生物钟延迟画像。
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from core.api.contract import success_response, error_response
from core.api.error_response import ErrorCode, get_friendly_error_message

router = APIRouter(prefix="/diary", tags=["日记与工作区"])


def _ws():
    from core.services.workspace.service import get_workspace_service
    return get_workspace_service()


# ==================== 日记 ====================

@router.get("", summary="获取日记")
async def get_diaries(
    date: Optional[str] = Query(None, description="日期(YYYY-MM-DD)，为空则今天"),
):
    ws = _ws()
    try:
        return await ws.get_diary(date=date)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))


@router.get("/summary", summary="获取日记摘要")
async def get_diary_summary(
    date: Optional[str] = Query(None, description="日期(YYYY-MM-DD)，为空则今天"),
    persona: str = Query(
        "aveline",
        description="角色: aveline / ling / user（分别对应 Aveline / Ling / 主人自己的每日总结）",
    ),
):
    ws = _ws()
    try:
        summary = await ws.get_diary_summary(date=date, persona=persona)
        if not summary:
            return error_response(ErrorCode.RESOURCE_NOT_FOUND, message="日记总结不存在")
        return success_response(data={"summary": summary, "persona": persona})
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


@router.post("/summary", summary="生成日记摘要")
async def generate_diary_summary(
    date: Optional[str] = Query(None, description="日期(YYYY-MM-DD)，为空则今天"),
    force: bool = Query(False, description="是否强制重新生成"),
):
    ws = _ws()
    try:
        summary = await ws.generate_diary_summary(date=date, force=force)
        return success_response(data={"summary": summary})
    except ValueError as ve:
        return error_response(ErrorCode.INVALID_PARAMETER, message=str(ve))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


# ==================== 工作区快照 ====================

@router.get("/snapshot", summary="获取每日工作区快照")
async def get_workspace_snapshot(
    date: Optional[str] = Query(None, description="日期(YYYY-MM-DD)，为空则今天"),
    diary_limit: int = Query(20, ge=1, le=200, description="返回最近日记条数"),
):
    ws = _ws()
    try:
        snapshot = await ws.get_daily_workspace_snapshot(date=date, diary_limit=diary_limit)
        return success_response(data={"snapshot": snapshot})
    except ValueError as ve:
        return error_response(ErrorCode.INVALID_PARAMETER, message=str(ve))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


# ==================== 定时消息 ====================

@router.get("/scheduled", summary="获取待发送的定时消息")
async def get_scheduled_messages():
    ws = _ws()
    return await ws.get_pending_messages()


@router.delete("/scheduled/{msg_id}", summary="删除/取消定时消息")
async def delete_scheduled_message(msg_id: str):
    ws = _ws()
    success = await ws.delete_message(msg_id)
    if not success:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"status": "success", "message": "Scheduled message deleted"}


# ==================== 生物钟延迟画像 ====================

@router.get("/bionic-delay/profile", summary="获取仿生延迟画像")
async def get_bionic_delay_profile(
    date: Optional[str] = Query(None, description="日期(YYYY-MM-DD)，为空则今天"),
    session_id: str = Query("default_user", description="会话ID"),
    persona_scope: str = Query("auto", description="角色作用域(auto/aveline/ling)"),
    refresh: bool = Query(False, description="是否跳过缓存强制刷新"),
):
    try:
        from core.services.aveline_life.service import get_aveline_life_rhythm_service
        service = get_aveline_life_rhythm_service()
        profile = await service.build_bionic_delay_profile(
            date=date,
            session_id=session_id,
            persona_scope=persona_scope,
            force_refresh=refresh,
        )
        return success_response(data={"profile": profile})
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))
