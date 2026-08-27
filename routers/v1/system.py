# -*- coding: utf-8 -*-
"""系统（system）域。

提供系统级偏好设置、资源 / 统计、主动关怀（active-care）状态与触发，
以及通用工具端点（联网搜索、LLM 直调）。
"""

import logging
import os
import time
import uuid
from core.utils.time_utils import now_iso
from typing import Any, Dict

from fastapi import APIRouter, Body

from core.api.contract import error_response, success_response
from core.api.error_response import ErrorCode
from core.managers.preference_manager import get_preference_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["系统与工具"])


# ==================== 偏好设置 ====================

@router.post("/preferences", summary="更新用户偏好设置")
async def update_preferences(payload: Dict[str, Any] = Body(...)):
    """更新用户偏好设置（如 mode / active_care_enabled 等）"""
    try:
        manager = get_preference_manager()

        allowed_keys = [
            "mode",
            "active_care_enabled",
            "response_length",
            "conversation_style",
            "sensitivity",
            "debug_visible",
        ]

        updates = {}
        for key, value in payload.items():
            if key in allowed_keys:
                await manager.set(key, value)
                updates[key] = value

        return success_response(data=updates, message="偏好设置已更新")
    except Exception as e:
        logger.error(f"更新偏好设置失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/preferences", summary="获取用户偏好设置")
async def get_preferences():
    try:
        manager = get_preference_manager()
        data = manager.preferences.copy()
        return success_response(data=data)
    except Exception as e:
        logger.error(f"获取偏好设置失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.post("/mobile-push-token", summary="注册移动端推送 token")
async def register_mobile_push_token(payload: Dict[str, Any] = Body(...)):
    try:
        manager = get_preference_manager()

        token = str(payload.get("token") or "").strip()
        if not token:
            return error_response(ErrorCode.INVALID_REQUEST, message="token 不能为空")

        platform = str(payload.get("platform") or "android").strip() or "android"
        user_id = str(payload.get("user_id") or "").strip()
        user_name = str(payload.get("user_name") or "").strip()

        await manager.set("mobile_push_token", token)
        await manager.set("mobile_push_platform", platform)
        await manager.set("mobile_push_user_id", user_id)
        await manager.set("mobile_push_user_name", user_name)
        await manager.set("mobile_push_updated_at", now_iso())

        return success_response(
            data={
                "platform": platform,
                "has_token": True,
                "user_id": user_id,
            },
            message="移动端推送 token 已更新",
        )
    except Exception as e:
        logger.error(f"注册移动端推送 token 失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


# ==================== 命令清单（供 QQ 端等前端同步） ====================

@router.get("/commands", summary="获取服务端命令清单")
async def get_server_commands():
    """返回 Aveline 服务端支持的全部命令清单（结构化 JSON）。

    QQ 端等前端通过此接口同步 /help 展示，后端命令变更后前端自动更新。
    """
    try:
        from core.services.aveline.command_registry import get_command_list_for_api

        return success_response({"commands": get_command_list_for_api()})
    except Exception as e:
        logger.error(f"获取命令清单失败: {e}", exc_info=True)
        return error_response(ErrorCode.INTERNAL_ERROR, message="internal error")


# ==================== 资源与统计 ====================

@router.get("/resources", summary="获取系统资源信息")
async def get_system_resources():
    try:
        from core.core_engine.model_manager import get_model_manager

        manager = get_model_manager()
        data = manager.detect_system_resources()
        from core.services.scheduler.cpp_scheduler_engine import get_scheduler_status
        scheduler_status = get_scheduler_status()
        if scheduler_status:
            data["scheduler"] = scheduler_status
        return {"status": "success", "data": data, "timestamp": time.time()}
    except Exception as e:
        logger.error(f"获取系统资源失败: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))


@router.get("/stats", summary="获取系统运行统计")
async def get_system_stats():
    from core.async_monitor import get_performance_monitor

    request_id = str(uuid.uuid4())
    try:
        monitor = get_performance_monitor()
        metrics = monitor.get_current_metrics()

        from core.services.scheduler.cpp_scheduler_engine import get_scheduler_status
        scheduler_status = get_scheduler_status()
        if scheduler_status:
            metrics["scheduler"] = scheduler_status

        return {
            "status": "success",
            "metrics": metrics,
            "data": metrics,
            "request_id": request_id,
            "timestamp": now_iso(),
        }
    except Exception as e:
        logger.error(f"获取系统统计失败: {str(e)}", exc_info=True)
        resp = error_response(
            ErrorCode.INTERNAL_ERROR, message="获取系统统计失败", request_id=request_id
        )
        resp["timestamp"] = now_iso()
        return resp


# ==================== 主动关怀（Active Care） ====================

@router.get("/active-care/status", summary="获取主动关怀运行状态")
async def get_active_care_status():
    request_id = str(uuid.uuid4())
    try:
        from core.services.active_care.core.service import get_active_care_service

        service = get_active_care_service()
        data = service.get_runtime_status()
        data["service"] = "active_care"
        data["timestamp"] = now_iso()
        return success_response(data=data, message="Active Care 状态获取成功")
    except Exception as e:
        logger.error(f"获取 Active Care 状态失败: {str(e)}", exc_info=True)
        return error_response(
            ErrorCode.INTERNAL_ERROR,
            message="获取 Active Care 状态失败",
            request_id=request_id,
            details={"error": str(e)},
        )


@router.post("/active-care/check", summary="触发主动关怀检查")
async def trigger_active_care_check(payload: Dict[str, Any] = Body(default={})):
    request_id = str(uuid.uuid4())
    try:
        from core.services.active_care.core.service import get_active_care_service

        is_startup = bool((payload or {}).get("is_startup", False))
        service = get_active_care_service()
        await service.check_active_care(is_startup=is_startup)
        data = service.get_runtime_status()
        data["service"] = "active_care"
        data["is_startup"] = is_startup
        data["timestamp"] = now_iso()
        return success_response(data=data, message="Active Care 手动检查已触发")
    except Exception as e:
        logger.error(f"触发 Active Care 检查失败: {str(e)}", exc_info=True)
        return error_response(
            ErrorCode.INTERNAL_ERROR,
            message="触发 Active Care 检查失败",
            request_id=request_id,
            details={"error": str(e)},
        )


@router.post("/active-care/force-send", summary="强制发送主动关怀消息")
async def force_send_active_care(payload: Dict[str, Any] = Body(default={})):
    request_id = str(uuid.uuid4())
    try:
        from core.services.active_care.core.service import get_active_care_service

        service = get_active_care_service()
        prompt_type = str((payload or {}).get("prompt_type") or "checking").strip() or "checking"
        thought = str((payload or {}).get("thought") or "manual runtime probe").strip()
        user_input_mock = str((payload or {}).get("user_input_mock") or "[ACTIVE_CARE_TRIGGER]").strip()
        client_type = str((payload or {}).get("client_type") or "qq").strip()

        await service.executor.trigger_message(
            sys_prompt_type=prompt_type,
            user_input_mock=user_input_mock,
            thought=thought,
            client_type=client_type,
        )
        data = service.get_runtime_status()
        data["resolved_conversation_id"] = (
            await service.executor.context.resolve_primary_conversation_id()
        )
        data["service"] = "active_care"
        data["prompt_type"] = prompt_type
        data["client_type"] = client_type
        data["timestamp"] = now_iso()
        return success_response(data=data, message="Active Care 强制发送已触发")
    except Exception as e:
        logger.error(f"强制发送 Active Care 失败: {str(e)}", exc_info=True)
        return error_response(
            ErrorCode.INTERNAL_ERROR,
            message="强制发送 Active Care 失败",
            request_id=request_id,
            details={"error": str(e)},
        )


# ==================== 通用工具（从 misc 域并入） ====================

@router.post("/search/web", summary="联网搜索")
async def search_web(payload: Dict[str, Any] = Body(...)):
    request_id = str(uuid.uuid4())
    try:
        if not isinstance(payload, dict):
            return error_response(
                ErrorCode.INVALID_PAYLOAD,
                message="请求体必须是JSON对象",
                request_id=request_id,
            )
        query = str(payload.get("query", "")).strip()
        provider = str(payload.get("provider", "bocha")).lower()
        if not query:
            return error_response(
                ErrorCode.EMPTY_QUERY, message="查询内容不能为空", request_id=request_id
            )
        if provider not in ("bocha", "tavily"):
            return error_response(
                ErrorCode.UNSUPPORTED_PROVIDER,
                message=f"不支持的provider: {provider}",
                request_id=request_id,
            )
        if provider == "bocha":
            api_key = os.environ.get("BOCHA_API_KEY")
            if not api_key:
                resp = error_response(
                    ErrorCode.MISSING_API_KEY,
                    message="未配置BOCHA_API_KEY，已留API占位",
                    request_id=request_id,
                    details={"placeholder": True},
                )
                resp["data"] = {"placeholder": True}
                return resp
            try:
                import requests as _req

                url = "https://api.bochaai.com/v1/web-search"
                body = {
                    "query": query,
                    "freshness": payload.get("freshness", "noLimit"),
                    "summary": bool(payload.get("summary", True)),
                    "count": int(payload.get("count", 3)),
                }
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                resp = _req.post(url, json=body, headers=headers, timeout=30)
                data = {}
                try:
                    data = resp.json()
                except Exception:
                    data = {"status_code": resp.status_code, "text": resp.text[:1000]}
                return {
                    "status": "success" if resp.status_code == 200 else "error",
                    "data": data,
                    "request_id": request_id,
                    "timestamp": now_iso(),
                }
            except Exception as e:
                logger.error(f"Bocha搜索失败: {e}", exc_info=True)
                return error_response(
                    ErrorCode.SEARCH_FAILED,
                    message="搜索服务调用失败",
                    request_id=request_id,
                )
        resp = error_response(
            ErrorCode.MISSING_API_KEY,
            message="未配置TAVILY_API_KEY，已留API占位",
            request_id=request_id,
            details={"placeholder": True},
        )
        resp["data"] = {"placeholder": True}
        return resp
    except Exception as e:
        logger.error(f"搜索接口失败: {str(e)}", exc_info=True)
        return error_response(
            ErrorCode.INTERNAL_ERROR, message="服务器内部错误", request_id=request_id
        )


@router.post("/generate", summary="通用 LLM 直调（不经过人设）")
async def generate_endpoint(payload: Dict[str, Any] = Body(...)):
    from core.llm import get_llm_module
    llm = get_llm_module()
    prompt = payload.get("prompt")
    messages = payload.get("messages")
    max_tokens = int(payload.get("max_tokens", 512))

    try:
        if hasattr(llm, "initialize"):
            await llm.initialize()

        if messages:
            response = await llm.chat(messages=messages, max_tokens=max_tokens)
        else:
            if isinstance(prompt, str):
                msgs = [{"role": "user", "content": prompt}]
            else:
                msgs = [{"role": "user", "content": str(prompt)}]
            response = await llm.chat(messages=msgs, max_tokens=max_tokens)

        if isinstance(response, dict) and "response" in response:
            final_text = response["response"]
        else:
            final_text = str(response)

        return {
            "status": "success",
            "text": final_text,
            "timestamp": now_iso(),
        }
    except Exception as e:
        logger.error(f"Generation error: {e}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(e))
