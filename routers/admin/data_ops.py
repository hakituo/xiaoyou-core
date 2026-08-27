# -*- coding: utf-8 -*-
"""数据运维（data-ops）端点。

包含日 / 周摘要生成、任务规划、记忆规则分析、AI 影子分析、融合裁决，
以及从 memory 域迁入的记忆降噪任务。所有端点均需内部 token 鉴权，
属于运维 / 开发态功能，业务端不应引用。
"""

import time
import logging
from typing import Optional

from fastapi import APIRouter, Header, Path
from pydantic import BaseModel, Field

logger = logging.getLogger("DATA_OPS_ROUTER")

router = APIRouter(prefix="/admin/data-ops", tags=["数据运维"])


def _data_ops():
    from core.services.data_ops import (
        validate_internal_token,
        unauthorized_response,
        submit_daily_digest,
        submit_weekly_report,
        submit_task_plan,
        submit_human_daily_digest,
        submit_human_weekly_report,
        submit_memory_rule_analysis,
        submit_memory_ai_shadow_analysis,
        submit_memory_fusion_adjudication,
        run_data_ops_task,
        get_data_ops_task,
        get_memory_rule_analysis_metrics,
        get_memory_ai_shadow_metrics,
        get_memory_fusion_metrics,
    )
    return {
        "validate_internal_token": validate_internal_token,
        "unauthorized_response": unauthorized_response,
        "submit_daily_digest": submit_daily_digest,
        "submit_weekly_report": submit_weekly_report,
        "submit_task_plan": submit_task_plan,
        "submit_human_daily_digest": submit_human_daily_digest,
        "submit_human_weekly_report": submit_human_weekly_report,
        "submit_memory_rule_analysis": submit_memory_rule_analysis,
        "submit_memory_ai_shadow_analysis": submit_memory_ai_shadow_analysis,
        "submit_memory_fusion_adjudication": submit_memory_fusion_adjudication,
        "run_data_ops_task": run_data_ops_task,
        "get_data_ops_task": get_data_ops_task,
        "get_memory_rule_analysis_metrics": get_memory_rule_analysis_metrics,
        "get_memory_ai_shadow_metrics": get_memory_ai_shadow_metrics,
        "get_memory_fusion_metrics": get_memory_fusion_metrics,
    }


# ==================== 请求模型 ====================

class DailyDigestRequest(BaseModel):
    date: str = Field(default="")
    include_diary_summary: bool = Field(default=True)
    use_queue: bool = Field(default=False)
    idempotency_key: str = Field(default="")


class WeeklyReportRequest(BaseModel):
    anchor_date: str = Field(default="")
    use_queue: bool = Field(default=False)
    idempotency_key: str = Field(default="")


class TaskPlanRequest(BaseModel):
    date: str = Field(default="")
    force: bool = Field(default=False)
    use_queue: bool = Field(default=False)
    idempotency_key: str = Field(default="")


class HumanDailyDigestRequest(BaseModel):
    date: str = Field(default="")
    include_device_context: bool = Field(default=True)
    use_queue: bool = Field(default=False)
    idempotency_key: str = Field(default="")


class HumanWeeklyReportRequest(BaseModel):
    anchor_date: str = Field(default="")
    include_device_context: bool = Field(default=False)
    use_queue: bool = Field(default=False)
    idempotency_key: str = Field(default="")


class MemoryRuleAnalysisRequest(BaseModel):
    user_id: str = Field(default="default_user")
    use_queue: bool = Field(default=True)
    idempotency_key: str = Field(default="")
    limit: int = Field(default=0)


class MemoryAIShadowAnalysisRequest(BaseModel):
    user_id: str = Field(default="default_user")
    use_queue: bool = Field(default=True)
    idempotency_key: str = Field(default="")
    limit: int = Field(default=0)
    timeout_ms: int = Field(default=0)
    strategy: str = Field(default="")


class MemoryFusionAdjudicationRequest(BaseModel):
    user_id: str = Field(default="default_user")
    use_queue: bool = Field(default=True)
    idempotency_key: str = Field(default="")
    limit: int = Field(default=0)
    override_min_confidence: float = Field(default=0.0)
    supplement_min_confidence: float = Field(default=0.0)
    allow_override: Optional[bool] = Field(default=None)


class MemoryDenoiseSummaryRequest(BaseModel):
    user_id: str = Field(default="default_user")
    min_weight: float = Field(default=1.0, ge=0.0)
    max_items: int = Field(default=200, ge=10, le=2000)
    use_queue: bool = Field(default=False)
    idempotency_key: str = Field(default="")


# ==================== 摘要与任务规划 ====================

@router.post("/summary/daily", summary="触发每日摘要生成")
async def trigger_daily_digest(
    request: DailyDigestRequest,
    x_internal_token: Optional[str] = Header(default=None),
):
    ops = _data_ops()
    if not ops["validate_internal_token"](x_internal_token):
        return ops["unauthorized_response"]()
    try:
        return await ops["submit_daily_digest"](
            date=request.date,
            include_diary_summary=request.include_diary_summary,
            use_queue=request.use_queue,
            idempotency_key=request.idempotency_key,
        )
    except Exception as e:
        logger.error(f"触发 DataOps 日摘要失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


@router.post("/summary/weekly", summary="触发每周报告生成")
async def trigger_weekly_digest(
    request: WeeklyReportRequest,
    x_internal_token: Optional[str] = Header(default=None),
):
    ops = _data_ops()
    if not ops["validate_internal_token"](x_internal_token):
        return ops["unauthorized_response"]()
    try:
        return await ops["submit_weekly_report"](
            anchor_date=request.anchor_date,
            use_queue=request.use_queue,
            idempotency_key=request.idempotency_key,
        )
    except Exception as e:
        logger.error(f"触发 DataOps 周报失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


@router.post("/summary/human/daily", summary="触发可读日摘要生成")
async def trigger_human_daily_digest(
    request: HumanDailyDigestRequest,
    x_internal_token: Optional[str] = Header(default=None),
):
    ops = _data_ops()
    if not ops["validate_internal_token"](x_internal_token):
        return ops["unauthorized_response"]()
    try:
        return await ops["submit_human_daily_digest"](
            date=request.date,
            include_device_context=request.include_device_context,
            use_queue=request.use_queue,
            idempotency_key=request.idempotency_key,
        )
    except Exception as e:
        logger.error(f"触发 DataOps 可读日摘要失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


@router.post("/summary/human/weekly", summary="触发可读周报生成")
async def trigger_human_weekly_digest(
    request: HumanWeeklyReportRequest,
    x_internal_token: Optional[str] = Header(default=None),
):
    ops = _data_ops()
    if not ops["validate_internal_token"](x_internal_token):
        return ops["unauthorized_response"]()
    try:
        return await ops["submit_human_weekly_report"](
            anchor_date=request.anchor_date,
            include_device_context=request.include_device_context,
            use_queue=request.use_queue,
            idempotency_key=request.idempotency_key,
        )
    except Exception as e:
        logger.error(f"触发 DataOps 可读周报失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


@router.post("/planner/tasks", summary="触发任务规划")
async def trigger_task_plan_worker(
    request: TaskPlanRequest,
    x_internal_token: Optional[str] = Header(default=None),
):
    ops = _data_ops()
    if not ops["validate_internal_token"](x_internal_token):
        return ops["unauthorized_response"]()
    try:
        return await ops["submit_task_plan"](
            date=request.date,
            force=request.force,
            use_queue=request.use_queue,
            idempotency_key=request.idempotency_key,
        )
    except Exception as e:
        logger.error(f"触发 DataOps 任务规划失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


# ==================== 记忆分析 ====================

@router.post("/memory/rule/analysis", summary="触发记忆规则分析")
async def trigger_memory_rule_analysis(
    request: MemoryRuleAnalysisRequest,
    x_internal_token: Optional[str] = Header(default=None),
):
    ops = _data_ops()
    if not ops["validate_internal_token"](x_internal_token):
        return ops["unauthorized_response"]()
    try:
        return await ops["submit_memory_rule_analysis"](
            user_id=request.user_id,
            use_queue=request.use_queue,
            idempotency_key=request.idempotency_key,
            limit=request.limit,
        )
    except Exception as e:
        logger.error(f"触发 DataOps 规则记忆分析失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


@router.get("/memory/rule/metrics", summary="获取记忆规则分析指标")
async def get_memory_rule_metrics(
    x_internal_token: Optional[str] = Header(default=None),
):
    ops = _data_ops()
    if not ops["validate_internal_token"](x_internal_token):
        return ops["unauthorized_response"]()
    try:
        return ops["get_memory_rule_analysis_metrics"]()
    except Exception as e:
        logger.error(f"获取 DataOps 规则分析指标失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


@router.post("/memory/ai-shadow/analysis", summary="触发 AI 影子记忆分析")
async def trigger_memory_ai_shadow_analysis(
    request: MemoryAIShadowAnalysisRequest,
    x_internal_token: Optional[str] = Header(default=None),
):
    ops = _data_ops()
    if not ops["validate_internal_token"](x_internal_token):
        return ops["unauthorized_response"]()
    try:
        return await ops["submit_memory_ai_shadow_analysis"](
            user_id=request.user_id,
            use_queue=request.use_queue,
            idempotency_key=request.idempotency_key,
            limit=request.limit,
            timeout_ms=request.timeout_ms,
            strategy=request.strategy,
        )
    except Exception as e:
        logger.error(f"触发 DataOps AI影子分析失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


@router.get("/memory/ai-shadow/metrics", summary="获取 AI 影子分析指标")
async def get_memory_ai_shadow_metrics_endpoint(
    x_internal_token: Optional[str] = Header(default=None),
):
    ops = _data_ops()
    if not ops["validate_internal_token"](x_internal_token):
        return ops["unauthorized_response"]()
    try:
        return ops["get_memory_ai_shadow_metrics"]()
    except Exception as e:
        logger.error(f"获取 DataOps AI影子分析指标失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


@router.post("/memory/fusion/adjudicate", summary="触发记忆融合裁决")
async def trigger_memory_fusion_adjudication(
    request: MemoryFusionAdjudicationRequest,
    x_internal_token: Optional[str] = Header(default=None),
):
    ops = _data_ops()
    if not ops["validate_internal_token"](x_internal_token):
        return ops["unauthorized_response"]()
    try:
        return await ops["submit_memory_fusion_adjudication"](
            user_id=request.user_id,
            use_queue=request.use_queue,
            idempotency_key=request.idempotency_key,
            limit=request.limit,
            override_min_confidence=request.override_min_confidence,
            supplement_min_confidence=request.supplement_min_confidence,
            allow_override=request.allow_override,
        )
    except Exception as e:
        logger.error(f"触发 DataOps 融合裁决失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


@router.get("/memory/fusion/metrics", summary="获取记忆融合裁决指标")
async def get_memory_fusion_metrics_endpoint(
    x_internal_token: Optional[str] = Header(default=None),
):
    ops = _data_ops()
    if not ops["validate_internal_token"](x_internal_token):
        return ops["unauthorized_response"]()
    try:
        return ops["get_memory_fusion_metrics"]()
    except Exception as e:
        logger.error(f"获取 DataOps 融合裁决指标失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


# ==================== 记忆降噪（从 memory 域迁入） ====================

@router.post("/memory/denoise/summary", summary="生成记忆降噪摘要")
async def build_memory_denoise_summary(
    request: MemoryDenoiseSummaryRequest,
    x_internal_token: Optional[str] = Header(default=None),
):
    from core.api.contract import validate_internal_token

    if not validate_internal_token(x_internal_token):
        return {"status": "error", "message": "未授权的内部调用", "timestamp": time.time()}
    try:
        from core.services.data_ops.service import get_data_ops_service
        svc = get_data_ops_service()
        result = await svc.submit_memory_denoise_summary(
            user_id=request.user_id,
            min_weight=request.min_weight,
            max_items=request.max_items,
            use_queue=request.use_queue,
            idempotency_key=request.idempotency_key,
        )
        return result
    except Exception as e:
        logger.error(f"生成记忆降噪摘要失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


@router.post("/memory/denoise/tasks/{task_id}/run", summary="执行记忆降噪任务")
async def run_memory_denoise_task(
    task_id: str = Path(..., description="Task ID"),
    x_internal_token: Optional[str] = Header(default=None),
):
    from core.api.contract import validate_internal_token

    if not validate_internal_token(x_internal_token):
        return {"status": "error", "message": "未授权的内部调用", "timestamp": time.time()}
    try:
        from core.services.data_ops.service import get_data_ops_service
        svc = get_data_ops_service()
        return await svc.run_task(task_id)
    except Exception as e:
        logger.error(f"执行记忆降噪任务失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


@router.get("/memory/denoise/tasks/{task_id}", summary="获取记忆降噪任务状态")
async def get_memory_denoise_task(
    task_id: str = Path(..., description="Task ID"),
    x_internal_token: Optional[str] = Header(default=None),
):
    from core.api.contract import validate_internal_token

    if not validate_internal_token(x_internal_token):
        return {"status": "error", "message": "未授权的内部调用", "timestamp": time.time()}
    try:
        from core.services.data_ops.service import get_data_ops_service
        svc = get_data_ops_service()
        return svc.get_task(task_id)
    except Exception as e:
        logger.error(f"获取记忆降噪任务失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


# ==================== 通用任务执行 ====================

@router.post("/tasks/{task_id}/run", summary="执行 DataOps 任务")
async def run_task(
    task_id: str = Path(..., description="Task ID"),
    x_internal_token: Optional[str] = Header(default=None),
):
    ops = _data_ops()
    if not ops["validate_internal_token"](x_internal_token):
        return ops["unauthorized_response"]()
    try:
        return await ops["run_data_ops_task"](task_id)
    except Exception as e:
        logger.error(f"执行 DataOps 任务失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}


@router.get("/tasks/{task_id}", summary="获取 DataOps 任务状态")
async def get_task(
    task_id: str = Path(..., description="Task ID"),
    x_internal_token: Optional[str] = Header(default=None),
):
    ops = _data_ops()
    if not ops["validate_internal_token"](x_internal_token):
        return ops["unauthorized_response"]()
    try:
        return ops["get_data_ops_task"](task_id)
    except Exception as e:
        logger.error(f"获取 DataOps 任务失败: {e}")
        return {"status": "error", "message": str(e), "timestamp": time.time()}
