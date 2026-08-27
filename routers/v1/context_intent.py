# -*- coding: utf-8 -*-
"""意图识别子路由。

从 routers.v1.context 解耦,提供 /context/intent/classify 端点,
用于对用户输入文本进行意图分类。
"""

import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Body

from core.api.contract import error_response
from core.api.error_response import ErrorCode
from core.utils.time_utils import now_iso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/context", tags=["意图识别"])


@router.post("/intent/classify", summary="识别用户意图")
async def classify_intent(payload: Any = Body(...)):
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
            return error_response(
                ErrorCode.MISSING_PARAMETER,
                message="text 不能为空",
                request_id=request_id,
            )

        candidates = payload.get("candidates")
        model_path = str(
            payload.get("model_path") or payload.get("modelPath") or ""
        ).strip()
        if not model_path:
            from core.services.intent.service import get_default_intent_model_path

            model_path = (
                os.environ.get("XIAOYOU_INTENT_MODEL_PATH")
                or get_default_intent_model_path()
            )

        temperature = float(payload.get("temperature") or 0.0)
        top_p = float(payload.get("top_p") or 0.9)
        max_tokens = int(payload.get("max_tokens") or 96)

        from core.services.intent.service import classify_intent as core_classify_intent

        result = await core_classify_intent(
            text=text,
            candidates=candidates,
            model_path=model_path,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )
        return {
            "status": "success",
            "intent": result.get("intent", "NONE"),
            "confidence": result.get("confidence", 0.0),
            "slots": result.get("slots", {}),
            "raw": result.get("raw", ""),
            "request_id": request_id,
            "timestamp": now_iso(),
        }
    except Exception as e:
        logger.error(f"意图分类失败: {e}", exc_info=True)
        resp = error_response(
            ErrorCode.INTERNAL_ERROR,
            message="意图分类失败",
            request_id=request_id,
            details={"error_type": type(e).__name__},
        )
        resp["timestamp"] = now_iso()
        return resp
