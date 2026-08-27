# -*- coding: utf-8 -*-
"""远程操作（remote-ops）域 - AI agent 远程文件审批。

从原 workspace_router 拆出：远程文件操作、动作审批与拒绝。
属于 AI agent / 开发态能力，归入 admin 域，业务端不应引用。
"""

from typing import Optional, Literal

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

from core.api.contract import success_response, error_response
from core.api.error_response import ErrorCode, get_friendly_error_message

router = APIRouter(prefix="/admin/remote", tags=["远程操作"])


def _remote():
    from core.services.remote_ops.service import get_remote_ops_service
    return get_remote_ops_service()


class RemoteFileActionRequest(BaseModel):
    action: Literal["list", "read", "write", "append", "mkdir", "exists"]
    path: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None)
    max_chars: Optional[int] = Field(default=200000)
    limit: Optional[int] = Field(default=200)


class RemoteApprovalRequest(BaseModel):
    token: str = Field(description="审批 Token")


@router.post("/file/action", summary="执行远程文件操作")
async def run_remote_file_action(payload: RemoteFileActionRequest = Body(...)):
    remote_ops = _remote()
    try:
        data = await remote_ops.run_workspace_file_action(
            action=payload.action,
            path=payload.path,
            content=payload.content,
            max_chars=payload.max_chars or 200000,
            limit=payload.limit or 200,
        )
        return success_response(data=data)
    except ValueError as ve:
        return error_response(ErrorCode.INVALID_PARAMETER, message=str(ve))
    except FileNotFoundError as fe:
        return error_response(ErrorCode.RESOURCE_NOT_FOUND, message=str(fe))
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


@router.post("/approve", summary="批准远程动作")
async def run_remote_approval(payload: RemoteApprovalRequest = Body(...)):
    remote_ops = _remote()
    try:
        data = await remote_ops.approve_action(payload.token)
        return success_response(data=data)
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))


@router.post("/reject", summary="拒绝远程动作")
async def run_remote_rejection(payload: RemoteApprovalRequest = Body(...)):
    remote_ops = _remote()
    try:
        data = await remote_ops.reject_action(payload.token)
        return success_response(data=data)
    except Exception as e:
        return error_response(ErrorCode.INTERNAL_ERROR, message=get_friendly_error_message(e))
