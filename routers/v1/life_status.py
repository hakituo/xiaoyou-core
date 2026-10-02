# -*- coding: utf-8 -*-
"""生命状态域 - 状态查询与情绪检测。

GET  /life/status
POST /life/emotion/detect"""

import logging
import uuid
from core.utils.time_utils import now_iso
from typing import Any, Optional
from fastapi import APIRouter, Body, Query
from core.api.contract import error_response
from core.api.error_response import ErrorCode
from core.services.character_daily.activity_model import (
    ActivityType,
    CHAT_ELIGIBLE_ACTIVITIES,
)
from .life_shared import (
    _get_life_simulation_service,
    _get_character_daily_engine,
    _build_reply_policy_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/life", tags=["生命与情绪"])

@router.get("/status", summary="获取角色生命状态")
async def get_life_status(
    scope: str = Query("aveline", description="角色 scope（aveline/ling/rushuang/yeye 等）"),
    persona: Optional[str] = Query(None, description="人格文件名（如 core_aveline.json），传入后按角色隔离生命状态，优先级高于 scope"),
):
    try:
        # persona 文件名优先：用后端权威映射解析成角色 scope，避免前端 slug 与后端不一致
        if persona:
            try:
                from core.utils.data_paths import (
                    build_shared_persona_conversation_id,
                    resolve_memory_user_id,
                    resolve_data_scope_from_conversation_id,
                )
                cid = build_shared_persona_conversation_id(persona)
                scope = resolve_data_scope_from_conversation_id(resolve_memory_user_id(cid))
            except Exception as e:
                logger.warning(f"按 persona 解析生命状态 scope 失败，回退传入 scope: {e}")
        sim = _get_life_simulation_service()
        # 按 scope 取该角色的独立生命状态（energy/hunger/thirst/mood_score 等）
        state = sim.get_state_for_scope(scope)

        # 状态面板需要和回复策略看到同一份“当前活动”。这里主动刷新一次，
        # 避免 character_daily 的两分钟 tick 让 App 长时间展示旧活动。
        sleep_summary = sim.get_sleep_summary(scope)
        engine = _get_character_daily_engine()
        current_activity = ActivityType.SLEEPING
        if not bool(sleep_summary.get("is_sleeping")):
            current_activity = (
                engine.refresh_current_activity(scope)
                if engine is not None
                else ActivityType.IDLE
            )
        reply_policy = _build_reply_policy_summary(current_activity, engine)
        daily_plan = engine.state.get_plan(scope) if engine is not None else None

        # 获取当前情绪（per-scope 端口，当前为 mock，待后端情绪 per-scope 改造后接入）
        emo_data = sim.get_emotion_for_scope(scope)
        current_emotion = emo_data.get("primary_emotion", "calm")
        emotion_mix = emo_data.get("emotion_mix", {})

        return {
            "status": "success",
            "data": state,
            "life_status": state,  # 兼容旧字段
            "emotion": current_emotion,
            "emotion_mix": emotion_mix,
            "emotion_mock": emo_data.get("mock", False),
            "activity": current_activity.value,
            "activity_chat_eligible": current_activity in CHAT_ELIGIBLE_ACTIVITIES,
            "reply_policy": reply_policy,
            "sleep_summary": sleep_summary,
            "daily_plan": daily_plan.to_dict() if daily_plan is not None else None,
            "scope": scope,
            "timestamp": now_iso(),
        }
    except Exception as e:
        logger.error(f"获取生活模拟状态失败: {e}")
        resp = error_response(ErrorCode.INTERNAL_ERROR, message=str(e))
        resp["retryable"] = True
        resp["retry_after_seconds"] = 5
        return resp


@router.post("/emotion/detect", summary="检测文本情绪")
async def detect_emotion(payload: Any = Body(...)):
    request_id = str(uuid.uuid4())
    try:
        if not isinstance(payload, dict):
            return error_response(
                ErrorCode.INVALID_PAYLOAD,
                message="请求体必须是JSON对象",
                request_id=request_id,
            )

        text = str(payload.get("text") or "").strip()
        if not text:
            return {
                "status": "success",
                "emotion": "neutral",
                "confidence": 0.0,
                "request_id": request_id,
            }

        from core.emotion.detector_v2 import get_emotion_detector_v2
        detector = get_emotion_detector_v2()
        state = detector.detect(text)

        return {
            "status": "success",
            "emotion": state.primary_emotion.value if state.primary_emotion else "neutral",
            "confidence": state.confidence,
            "request_id": request_id,
        }
    except Exception as e:
        logger.error(f"Emotion detect error: {e}", exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e), request_id=request_id)
