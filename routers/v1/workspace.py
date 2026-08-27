# -*- coding: utf-8 -*-
"""工作区（workspace）域 - 学习文件操作。

从原 workspace_router 拆出：Study 根目录下的文件列表、读写、学习进度记录、
学习概览、学习面板、文件操作动作。
注意：日记 / 定时消息 / 快照已迁至 diary 域，每日任务已迁至 tasks 域，
远程审批已迁至 admin 域。
"""

from fastapi import APIRouter, Body, Query
from typing import Optional, Dict, Any, Literal

from pydantic import BaseModel, Field

from core.api.contract import success_response, error_response
from core.api.error_response import ErrorCode, get_friendly_error_message

router = APIRouter(prefix="/workspace", tags=["工作区文件"])


def _ws():
    from core.services.workspace.service import get_workspace_service
    return get_workspace_service()


# ==================== 请求模型 ====================

class StudyWriteRequest(BaseModel):
    path: str = Field(description="Study 根目录下的相对路径")
    content: str = Field(description="要写入的文本内容")
    append: bool = Field(default=False, description="是否追加写入")


class StudyRecordRequest(BaseModel):
    topic: str = Field(description="学习主题")
    content: str = Field(description="学习内容记录")
    path: Optional[str] = Field(default=None, description="可选：同时写入到目标文件")


class StudyActionRequest(BaseModel):
    action: Literal[
        "list", "read_text", "write_text", "append_text",
        "read_json", "write_json", "mkdir", "exists", "highlight",
    ] = Field(description="study_data_tool 动作")
    path: Optional[str] = Field(default=None, description="Study 根目录下路径")
    content: Optional[str] = Field(default=None, description="写入文本内容")
    json_content: Optional[Dict[str, Any]] = Field(default=None, description="write_json 时写入的 JSON")


# ==================== 学习文件读写 ====================

@router.get("/study/root", summary="获取 Study 根目录路径")
async def get_study_root_path():
    ws = _ws()
    try:
        path = await ws.get_study_root_path()
        return success_response(data={"study_root": path})
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


@router.get("/study/list", summary="列出 Study 目录内容")
async def list_study_items(
    path: str = Query(".", description="Study 根目录下的相对路径"),
    recursive: bool = Query(False, description="是否递归列出子目录"),
    limit: int = Query(200, ge=1, le=2000, description="返回的最大条目数"),
):
    ws = _ws()
    try:
        data = await ws.list_study_items(path, recursive=recursive, limit=limit)
        return success_response(data=data)
    except ValueError as ve:
        return error_response(ErrorCode.INVALID_PARAMETER, message=str(ve))
    except FileNotFoundError as fe:
        return error_response(ErrorCode.RESOURCE_NOT_FOUND, message=str(fe))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


@router.get("/study/read", summary="读取 Study 文件文本")
async def read_study_text(
    path: str = Query(..., description="Study 根目录下的相对文件路径"),
    max_chars: int = Query(200000, ge=1, le=2_000_000, description="最大返回字符数"),
):
    ws = _ws()
    try:
        data = await ws.read_study_text(path, max_chars=max_chars)
        return success_response(data=data)
    except ValueError as ve:
        return error_response(ErrorCode.INVALID_PARAMETER, message=str(ve))
    except FileNotFoundError as fe:
        return error_response(ErrorCode.RESOURCE_NOT_FOUND, message=str(fe))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


@router.post("/study/write", summary="写入 Study 文件文本")
async def write_study_text(payload: StudyWriteRequest = Body(...)):
    ws = _ws()
    try:
        data = await ws.write_study_text(payload.path, payload.content, append=payload.append)
        return success_response(data=data)
    except ValueError as ve:
        return error_response(ErrorCode.INVALID_PARAMETER, message=str(ve))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


@router.post("/study/record", summary="记录学习进度")
async def record_study_progress(payload: StudyRecordRequest = Body(...)):
    ws = _ws()
    try:
        data = await ws.record_study_progress(topic=payload.topic, content=payload.content, relative_path=payload.path)
        return success_response(data=data)
    except ValueError as ve:
        return error_response(ErrorCode.INVALID_PARAMETER, message=str(ve))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


@router.get("/study/overview", summary="获取学习联动概览")
async def get_study_overview():
    ws = _ws()
    try:
        data = await ws.get_study_linked_overview()
        return success_response(data=data)
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


@router.get("/study/panel", summary="获取学习面板聚合数据")
async def get_study_panel_bundle(
    conversation_id: str = Query("default_user", description="会话ID"),
    date: Optional[str] = Query(None, description="日期(YYYY-MM-DD)，为空则今天"),
    history_limit: int = Query(20, ge=5, le=200, description="最近聊天消息条数"),
):
    ws = _ws()
    try:
        data = await ws.get_learning_panel_bundle(
            conversation_id=conversation_id, date=date, history_limit=history_limit,
        )
        return success_response(data=data)
    except ValueError as ve:
        return error_response(ErrorCode.INVALID_PARAMETER, message=str(ve))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


@router.post("/study/action", summary="执行 Study 数据工具动作")
async def run_study_action(payload: StudyActionRequest = Body(...)):
    ws = _ws()
    try:
        if payload.action in {
            "read_text", "write_text", "append_text", "read_json",
            "write_json", "mkdir", "exists", "highlight",
        } and not str(payload.path or "").strip():
            return error_response(ErrorCode.INVALID_PARAMETER, message=f"{payload.action} 需要 path")
        if payload.action in {"write_text", "append_text"} and payload.content is None:
            return error_response(ErrorCode.INVALID_PARAMETER, message=f"{payload.action} 需要 content")
        if payload.action == "write_json" and payload.json_content is None:
            return error_response(ErrorCode.INVALID_PARAMETER, message="write_json 需要 json_content")
        data = await ws.run_study_data_action(
            action=payload.action, path=payload.path,
            content=payload.content, json_content=payload.json_content,
        )
        return success_response(data=data)
    except ValueError as ve:
        return error_response(ErrorCode.INVALID_PARAMETER, message=str(ve))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))
