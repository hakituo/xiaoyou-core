# -*- coding: utf-8 -*-
"""每日任务（tasks）域。

从原 workspace_router 拆出：每日任务的面板、生成、增改删。
任务可关联学习主题与学习文件路径。
"""

from fastapi import APIRouter, Body, Query
from typing import Optional, Literal

from pydantic import BaseModel, Field

from core.api.contract import success_response, error_response
from core.api.error_response import ErrorCode, get_friendly_error_message

router = APIRouter(prefix="/tasks", tags=["每日任务"])


def _ws():
    from core.services.workspace.service import get_workspace_service
    return get_workspace_service()


# ==================== 请求模型 ====================

class DailyTaskUpsertRequest(BaseModel):
    task_id: Optional[str] = Field(default=None, description="任务ID，传入表示更新")
    date: Optional[str] = Field(default=None, description="日期(YYYY-MM-DD)")
    title: str = Field(description="任务标题")
    category: Literal["timed", "untimed"] = Field(default="untimed", description="任务类型")
    execution_time: Optional[str] = Field(default=None, description="执行时间 HH:MM")
    window_start: Optional[str] = Field(default=None, description="可执行起始时间 HH:MM")
    window_end: Optional[str] = Field(default=None, description="可执行结束时间 HH:MM")
    duration_minutes: int = Field(default=30, ge=5, le=1440, description="预计耗时分钟")
    linked_study_topic: Optional[str] = Field(default=None, description="学习联动主题")
    linked_study_path: Optional[str] = Field(default=None, description="学习联动文件路径")
    notes: Optional[str] = Field(default="", description="备注")


class DailyTaskStatusRequest(BaseModel):
    status: Literal["pending", "completed", "cancelled"] = Field(description="任务状态")
    date: Optional[str] = Field(default=None, description="日期(YYYY-MM-DD)")


class DailyTaskGenerateRequest(BaseModel):
    date: Optional[str] = Field(default=None, description="日期(YYYY-MM-DD)")
    force: bool = Field(default=False, description="是否覆盖已存在任务")


# ==================== 任务面板与生成 ====================

@router.get("/panel", summary="获取每日任务面板")
async def get_daily_task_panel(
    date: Optional[str] = Query(None, description="日期(YYYY-MM-DD)，为空则今天"),
):
    ws = _ws()
    try:
        data = await ws.get_daily_task_panel(date=date)
        return success_response(data=data)
    except ValueError as ve:
        return error_response(ErrorCode.INVALID_PARAMETER, message=str(ve))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


@router.post("/generate", summary="从学习进度生成每日任务")
async def generate_daily_tasks(payload: DailyTaskGenerateRequest = Body(...)):
    ws = _ws()
    try:
        data = await ws.generate_daily_tasks_from_progress(date=payload.date, force=payload.force)
        return success_response(data=data)
    except ValueError as ve:
        return error_response(ErrorCode.INVALID_PARAMETER, message=str(ve))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


# ==================== 任务增改删 ====================

@router.post("", summary="创建或更新任务")
async def upsert_daily_task(payload: DailyTaskUpsertRequest = Body(...)):
    ws = _ws()
    try:
        data = await ws.upsert_daily_task(
            title=payload.title,
            category=payload.category,
            execution_time=payload.execution_time,
            window_start=payload.window_start,
            window_end=payload.window_end,
            duration_minutes=payload.duration_minutes,
            linked_study_topic=payload.linked_study_topic,
            linked_study_path=payload.linked_study_path,
            notes=payload.notes or "",
            task_id=payload.task_id,
            date=payload.date,
        )
        return success_response(data=data)
    except ValueError as ve:
        return error_response(ErrorCode.INVALID_PARAMETER, message=str(ve))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


@router.patch("/{task_id}/status", summary="更新任务状态")
async def update_daily_task_status(task_id: str, payload: DailyTaskStatusRequest = Body(...)):
    ws = _ws()
    try:
        data = await ws.update_daily_task_status(task_id=task_id, status=payload.status, date=payload.date)
        return success_response(data=data)
    except ValueError as ve:
        return error_response(ErrorCode.INVALID_PARAMETER, message=str(ve))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


@router.delete("/{task_id}", summary="删除任务")
async def delete_daily_task(
    task_id: str,
    date: Optional[str] = Query(None, description="日期(YYYY-MM-DD)，为空则今天"),
):
    ws = _ws()
    try:
        data = await ws.delete_daily_task(task_id=task_id, date=date)
        return success_response(data=data)
    except ValueError as ve:
        return error_response(ErrorCode.INVALID_PARAMETER, message=str(ve))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))
