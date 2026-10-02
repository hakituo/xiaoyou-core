# -*- coding: utf-8 -*-
"""专注番茄钟会话路由。"""
from __future__ import annotations

import asyncio
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.services.study.focus_session_service import (
    FocusSessionService,
    FocusSessionError,
    get_focus_session_service,
)
from core.utils.logger import get_logger
from core.utils.time_utils import ts_to_str
from config.focus_monitor_config import get_focus_monitor_config

router = APIRouter(prefix="/study", tags=["专注番茄钟"])
logger = get_logger("STUDY_FOCUS_ROUTE")


class StartSessionReq(BaseModel):
    subject: str = Field("", description="学习事项")
    planned_minutes: int = Field(25, ge=1, le=240, description="计划时长（分钟）")
    mode: str = Field("gentle", description="gentle / strict")
    monitoring: bool = Field(False, description="是否有摄像头监控")
    plan_item_id: Optional[str] = Field(
        None,
        description="从 DailyPlan 启动时绑定的稳定计划项 ID；手动番茄钟可为空",
    )
    plan_date: Optional[str] = Field(
        None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="绑定计划项所属日期 YYYY-MM-DD；旧客户端可不传",
    )


class ObservationIn(BaseModel):
    sequence: int
    observed_at: float
    presence: str
    activity: str
    confidence: float = 0.0
    signals: List[str] = Field(default_factory=list)
    page_visible: bool = True
    client_ts: float = 0.0


class ObservationsReq(BaseModel):
    observations: List[ObservationIn]


class FinishReq(BaseModel):
    self_rating: Optional[int] = Field(None, ge=1, le=5)
    note: Optional[str] = None


class VisionReviewReq(BaseModel):
    frame_b64: str = Field("", description="待复核帧（base64），仅本请求内临时使用，绝不落盘")


def _svc() -> FocusSessionService:
    return get_focus_session_service()


def _ok(data: Any, status: int = 200):
    from fastapi.responses import JSONResponse
    return JSONResponse(content={"ok": True, "data": data}, status_code=status)


def _live_session_payload(sess) -> dict:
    payload = sess.to_dict()
    effective_seconds = max(0.0, float(sess.effective_elapsed()))
    payload["effective_minutes"] = round(effective_seconds / 60, 1)
    payload["remaining_seconds"] = max(
        0.0, float(sess.planned_minutes * 60) - effective_seconds
    )
    total = (
        float(sess.sec_focused or 0.0)
        + float(sess.sec_possibly_distracted or 0.0)
        + float(sess.sec_away or 0.0)
        + float(sess.sec_unknown or 0.0)
    )
    payload["focus_rate"] = (
        round(float(sess.sec_focused or 0.0) / total * 100, 1)
        if total > 0
        else 0.0
    )
    payload["nudge_count"] = len(sess.nudge_events or [])
    payload["session"] = dict(payload)
    return payload


def _linked_plan_date(sess) -> str:
    """优先使用客户端显式关联日期；旧客户端回退到会话开始日期。"""
    plan_date = str(getattr(sess, "plan_date", "") or "").strip()
    if plan_date:
        return plan_date
    started_at = float(getattr(sess, "started_at", 0.0) or 0.0)
    if started_at > 0:
        return ts_to_str(started_at, "%Y-%m-%d")
    return ts_to_str(float(getattr(sess, "created_at", 0.0) or 0.0), "%Y-%m-%d")


async def _project_finished_session_to_plan(sess) -> None:
    """把已结束 FocusSession 的真实 WORK 时长幂等回写到 PlanItem。"""
    plan_item_id = str(getattr(sess, "plan_item_id", "") or "").strip()
    if not plan_item_id:
        return

    from core.services.journal.service import get_journal_service

    plan_date = _linked_plan_date(sess)
    actual_minutes = max(0.0, float(sess.accumulated_active_seconds or 0.0)) / 60.0
    plan = await get_journal_service().apply_focus_session_result(
        plan_date,
        plan_item_id,
        sess.session_id,
        actual_minutes,
    )
    if plan is None:
        logger.warning(
            "FocusSession 已结束但未找到绑定 PlanItem: session=%s plan_date=%s plan_item=%s",
            sess.session_id,
            plan_date,
            plan_item_id,
        )


@router.post("/focus-sessions")
async def start_session(
    body: StartSessionReq,
    user_id: str = Query("default", description="用户 ID"),
):
    try:
        service = _svc()
        sess = await asyncio.to_thread(
            service.start_session,
            user_id,
            body.subject,
            body.planned_minutes,
            body.mode,
            body.monitoring,
            body.plan_item_id,
            body.plan_date,
        )
        return _ok(sess.to_dict(), status=201)
    except FocusSessionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/focus-sessions/current")
async def current_session(user_id: str = Query("default")):
    sess = await asyncio.to_thread(_svc().get_current, user_id)
    if not sess:
        return _ok(None)
    await asyncio.to_thread(_svc().check_offline_and_pause, user_id)
    sess = await asyncio.to_thread(_svc().get_current, user_id)
    return _ok(_live_session_payload(sess) if sess else None)


@router.post("/focus-sessions/{session_id}/observations")
async def post_observations(
    session_id: str,
    body: ObservationsReq,
    user_id: str = Query("default"),
):
    sess = await asyncio.to_thread(_svc().get_current, user_id)
    if not sess or sess.session_id != session_id:
        raise HTTPException(status_code=404, detail="会话不存在或不属于该用户")
    obs_list = [o.model_dump() for o in body.observations]
    result = await asyncio.to_thread(_svc().record_observations, user_id, obs_list)
    return _ok(result)


@router.post("/focus-sessions/{session_id}/pause")
async def pause_session(session_id: str, user_id: str = Query("default")):
    sess = await asyncio.to_thread(_svc().get_current, user_id)
    if not sess or sess.session_id != session_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        sess = await asyncio.to_thread(_svc().pause, user_id, "user")
        return _ok(sess.to_dict())
    except FocusSessionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/focus-sessions/{session_id}/resume")
async def resume_session(session_id: str, user_id: str = Query("default")):
    sess = await asyncio.to_thread(_svc().get_current, user_id)
    if not sess or sess.session_id != session_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        sess = await asyncio.to_thread(_svc().resume, user_id)
        return _ok(sess.to_dict())
    except FocusSessionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/focus-sessions/{session_id}/finish")
async def finish_session(
    session_id: str,
    body: FinishReq = FinishReq(),
    user_id: str = Query("default"),
):
    try:
        # service.finish 对相同 session_id 的重试是幂等的；即使下一轮 WORK 已开始，
        # 旧请求也只会返回旧 finished 会话，不会误结束新会话。
        sess = await asyncio.to_thread(
            _svc().finish,
            user_id,
            body.self_rating,
            body.note,
            session_id,
        )
    except FocusSessionError as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        await _project_finished_session_to_plan(sess)
    except Exception as e:
        # 会话本身已经结束；返回失败促使客户端重试同一个 finish。
        # 重试不会重复结算 FocusSession，PlanItem 也会按 session_id 去重。
        logger.error(
            "FocusSession -> PlanItem 投影失败: session=%s error=%s",
            sess.session_id,
            e,
        )
        raise HTTPException(
            status_code=500,
            detail="专注会话已结束，但计划执行结果写入失败，请重试结束请求",
        )
    return _ok(sess.to_dict())


@router.post("/focus-sessions/{session_id}/nudge")
async def trigger_nudge(session_id: str, user_id: str = Query("default")):
    sess = await asyncio.to_thread(_svc().get_current, user_id)
    if not sess or sess.session_id != session_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return _ok({"sent": False, "reason": "formal_focus_session_suppressed"})


@router.post("/focus-sessions/{session_id}/vision-review")
async def vision_review(
    session_id: str,
    body: VisionReviewReq = VisionReviewReq(),
    user_id: str = Query("default"),
):
    sess = await asyncio.to_thread(_svc().get_current, user_id)
    if not sess or sess.session_id != session_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    if sess.mode != "strict":
        raise HTTPException(status_code=400, detail="仅 strict 模式支持视觉复核")
    if not body.frame_b64:
        raise HTTPException(status_code=400, detail="缺少待复核帧")

    cfg = get_focus_monitor_config()
    vr_dec = await asyncio.to_thread(_svc().policy.evaluate_strict_vision_review, sess)
    if not vr_dec.should_nudge or not vr_dec.vision_review:
        return _ok({"reviewed": False, "reason": vr_dec.reason})

    from core.services.aveline.vision_service import analyze_screen
    from core.core_engine.service_singletons import get_aveline_service
    svc = get_aveline_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="视觉服务未初始化")

    try:
        result = await analyze_screen(svc, body.frame_b64, prompt=cfg.vision_review_prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"视觉复核失败: {e}")

    conclusion = ""
    if isinstance(result, dict) and result.get("status") == "success":
        conclusion = result.get("description", "")

    out = await asyncio.to_thread(_svc().request_vision_review, user_id, lambda: conclusion)
    out["reviewed"] = bool(conclusion)
    return _ok(out)


@router.get("/focus-sessions/{session_id}/summary")
async def get_summary(session_id: str, user_id: str = Query("default")):
    data = await asyncio.to_thread(_svc().get_summary, user_id, session_id)
    if not data:
        raise HTTPException(status_code=404, detail="未找到总结")
    return _ok(data)


@router.get("/focus-sessions/history")
async def get_history(
    user_id: str = Query("default"),
    limit: int = Query(20, ge=1, le=100),
):
    results = await asyncio.to_thread(_svc().get_history, user_id, limit)
    return _ok(results)
