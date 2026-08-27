# -*- coding: utf-8 -*-
"""专注番茄钟会话路由（阶段1+2 MVP）。

端点：
- POST /study/focus-sessions            开始
- GET  /study/focus-sessions/current    当前状态
- POST /study/focus-sessions/{id}/observations  批量观察 + 心跳
- POST /study/focus-sessions/{id}/pause 暂停
- POST /study/focus-sessions/{id}/resume恢复
- POST /study/focus-sessions/{id}/finish结束
- POST /study/focus-sessions/{id}/nudge 主动评估并触发探班（走统一发送链路）
- GET  /study/focus-sessions/{id}/summary 总结
- GET  /study/focus-sessions/history    历史

隐私：observation 只接受结构化字段，拒绝 base64/图片/音频/视频。
"""
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
from config.focus_monitor_config import get_focus_monitor_config

router = APIRouter(prefix="/study", tags=["专注番茄钟"])


# ---------------------------------------------------------------------------
# 请求体
# ---------------------------------------------------------------------------
class StartSessionReq(BaseModel):
    subject: str = Field("", description="学习事项")
    planned_minutes: int = Field(25, ge=1, le=240, description="计划时长（分钟）")
    mode: str = Field("gentle", description="gentle / strict")
    monitoring: bool = Field(True, description="是否有摄像头监控")


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


# ---------------------------------------------------------------------------
# 服务包装（同步 service 跑在线程池）
# ---------------------------------------------------------------------------
def _svc() -> FocusSessionService:
    return get_focus_session_service()


def _ok(data: Any, status: int = 200):
    from fastapi.responses import JSONResponse
    return JSONResponse(content={"ok": True, "data": data}, status_code=status)


@router.post("/focus-sessions")
async def start_session(
    body: StartSessionReq,
    user_id: str = Query("default", description="用户 ID"),
):
    try:
        sess = await asyncio.to_thread(
            _svc().start_session, user_id, body.subject, body.planned_minutes,
            body.mode, body.monitoring,
        )
        return _ok(sess.to_dict(), status=201)
    except FocusSessionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/focus-sessions/current")
async def current_session(user_id: str = Query("default")):
    sess = await asyncio.to_thread(_svc().get_current, user_id)
    if not sess:
        return _ok(None)
    # 顺带检查掉线自动暂停
    await asyncio.to_thread(_svc().check_offline_and_pause, user_id)
    sess = await asyncio.to_thread(_svc().get_current, user_id)
    return _ok(sess.to_dict() if sess else None)


@router.post("/focus-sessions/{session_id}/observations")
async def post_observations(
    session_id: str,
    body: ObservationsReq,
    user_id: str = Query("default"),
):
    # 校验 session_id 匹配（防止越权写别人的会话）
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
    sess = await asyncio.to_thread(_svc().get_current, user_id)
    if not sess or sess.session_id != session_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        sess = await asyncio.to_thread(
            _svc().finish, user_id, body.self_rating, body.note
        )
        return _ok(sess.to_dict())
    except FocusSessionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/focus-sessions/{session_id}/nudge")
async def trigger_nudge(session_id: str, user_id: str = Query("default")):
    """评估专注监控策略，若需探班则通过 Active Care 统一链路发送。"""
    sess = await asyncio.to_thread(_svc().get_current, user_id)
    if not sess or sess.session_id != session_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    event = await asyncio.to_thread(_svc().maybe_nudge, user_id)
    if not event:
        return _ok({"sent": False, "reason": "policy_skip"})
    # 走统一发送链路
    from core.services.active_care.core.executor import get_active_care_executor
    executor = get_active_care_executor()
    try:
        delivered = await executor.trigger_message(
            sys_prompt_type="focus_nudge",
            user_input_mock="[FOCUS_NUDGE]",
            reminder_msg=event.message,
            user_id=user_id,
        )
        return _ok({"sent": bool(delivered), "message": event.message, "reason": event.reason})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"探班发送失败: {e}")


@router.post("/focus-sessions/{session_id}/vision-review")
async def vision_review(
    session_id: str,
    body: VisionReviewReq = VisionReviewReq(),
    user_id: str = Query("default"),
):
    """严格模式低频视觉复核。

    隐私约束：上传的帧（base64）只在本请求内临时送给视觉模型，
    绝不落盘、绝不写进会话任何字段；会话只记录结构化结论文本。
    非 strict 模式或非 active 会话直接 400。
    """
    sess = await asyncio.to_thread(_svc().get_current, user_id)
    if not sess or sess.session_id != session_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    if sess.mode != "strict":
        raise HTTPException(status_code=400, detail="仅 strict 模式支持视觉复核")
    if not body.frame_b64:
        raise HTTPException(status_code=400, detail="缺少待复核帧")

    cfg = get_focus_monitor_config()
    # 先让策略判定是否允许（冷却 / 最短专注 / 信号）
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

    # 把结论回流到会话（不保存图像），并触发一次探班（若策略判定需要）
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
