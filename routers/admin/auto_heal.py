# -*- coding: utf-8 -*-
"""自愈系统（auto-heal）端点。

提供异常检测、补丁生成 / 应用 / 回滚、源文件读写、看板与晨报等运维能力。
属于开发态功能，业务端不应引用。
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

router = APIRouter(prefix="/admin/auto-heal", tags=["自愈系统"])


class PatchActionRequest(BaseModel):
    patch_id: str


class SourceReadRequest(BaseModel):
    path: str
    max_chars: int = 200000


class SourceWriteRequest(BaseModel):
    path: str
    content: str


@router.get("/stats", summary="获取自愈系统统计数据")
async def get_auto_heal_stats():
    from core.services.auto_heal.heal_service import get_auto_heal_service

    svc = get_auto_heal_service()
    return svc.get_stats()


@router.get("/patches/pending", summary="获取待处理补丁列表")
async def get_pending_patches():
    from core.services.auto_heal.heal_service import get_auto_heal_service

    svc = get_auto_heal_service()
    return {"patches": svc.get_pending_patches()}


@router.get("/patches", summary="获取全部补丁列表")
async def get_all_patches(limit: int = 50):
    from core.services.auto_heal.heal_service import get_auto_heal_service

    svc = get_auto_heal_service()
    return {"patches": svc.get_all_patches(limit=limit)}


@router.get("/patches/{patch_id}", summary="获取指定补丁详情")
async def get_patch_detail(patch_id: str):
    from core.services.auto_heal.heal_service import get_auto_heal_service

    svc = get_auto_heal_service()
    detail = svc.get_patch_detail(patch_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="补丁不存在")
    return detail


@router.post("/patches/{patch_id}/apply", summary="应用指定补丁")
async def apply_patch(patch_id: str):
    from core.services.auto_heal.heal_service import get_auto_heal_service

    svc = get_auto_heal_service()
    result = await svc.apply_patch(patch_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "应用失败"))
    return result


@router.post("/patches/{patch_id}/rollback", summary="回滚指定补丁")
async def rollback_patch(patch_id: str):
    from core.services.auto_heal.heal_service import get_auto_heal_service

    svc = get_auto_heal_service()
    result = await svc.rollback_patch(patch_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "回滚失败"))
    return result


@router.post("/patches/{patch_id}/reject", summary="驳回指定补丁")
async def reject_patch(patch_id: str):
    from core.services.auto_heal.heal_service import get_auto_heal_service

    svc = get_auto_heal_service()
    result = await svc.reject_patch(patch_id)
    return result


@router.post("/check", summary="手动触发异常检测")
async def trigger_check():
    from core.services.auto_heal.heal_service import get_auto_heal_service

    svc = get_auto_heal_service()
    results = await svc.trigger_check()
    return {"anomalies": results}


@router.post("/source/read", summary="读取项目源文件")
async def read_source_file(req: SourceReadRequest):
    from core.services.workspace.service import get_workspace_service

    ws = get_workspace_service()
    try:
        return await ws.read_source_file(req.path, max_chars=req.max_chars)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/source/write", summary="写入项目源文件")
async def write_source_file(req: SourceWriteRequest):
    from core.services.workspace.service import get_workspace_service

    ws = get_workspace_service()
    try:
        return await ws.write_source_file(req.path, req.content)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/reports", summary="获取自愈报告列表")
async def get_reports(limit: int = 20, type: Optional[str] = None):
    from core.services.auto_heal.heal_service import get_auto_heal_service

    svc = get_auto_heal_service()
    return {"reports": svc.get_reports(limit=limit, report_type=type)}


@router.get(
    "/reports/{report_id}",
    response_class=PlainTextResponse,
    summary="获取指定自愈报告（Markdown）",
)
async def get_report_detail(report_id: str):
    from core.services.auto_heal.heal_service import get_auto_heal_service

    svc = get_auto_heal_service()
    md = svc.get_report_detail(report_id)
    if md is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return md


@router.get("/kanban", summary="获取自愈看板")
async def get_kanban():
    from core.services.auto_heal.heal_service import get_auto_heal_service

    svc = get_auto_heal_service()
    return svc.get_kanban()


@router.get(
    "/morning-brief",
    response_class=PlainTextResponse,
    summary="获取自愈晨报",
)
async def get_morning_brief():
    from core.services.auto_heal.heal_service import get_auto_heal_service

    svc = get_auto_heal_service()
    brief = svc.get_morning_brief()
    return brief or "昨晚一切正常，没有需要汇报的自愈活动。"
