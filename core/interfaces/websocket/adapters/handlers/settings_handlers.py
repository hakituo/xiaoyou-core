#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设置相关的消息处理器
处理更新设置、更新生理状态等消息
"""

from core.utils.logger import get_logger

import time
from typing import Any, Dict
from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

logger = get_logger(__name__)


def _is_local_websocket(websocket: WebSocket) -> bool:
    """判断 WebSocket 是否来自本地回环连接（127.0.0.1 / ::1 / localhost）。

    本地连接被视为受信任来源，可以修改全局 LLM 配置；
    远程连接即使持有有效的 web_access_token，也不允许篡改全局配置。
    """
    try:
        client = getattr(websocket, "client", None)
        if not client:
            return False
        host = str(getattr(client, "host", "") or "").strip().lower()
        return host in ("127.0.0.1", "::1", "localhost", "")
    except Exception:
        return False


class SettingsHandlers:
    """设置相关的消息处理器"""

    def __init__(self, adapter):
        self.adapter = adapter

    async def handle_update_settings(self, websocket: WebSocket, message: dict):
        """处理更新设置消息"""
        request_id = message.get("request_id") or str(int(time.time() * 1000))

        try:
            # 更新交互统计
            try:
                from core.services.life_simulation.service import (
                    get_life_simulation_service,
                )

                get_life_simulation_service().update_interaction(xp_gain=0)
            except Exception:
                pass

            settings_data = message.get("settings", {})
            if not isinstance(settings_data, dict):
                settings_data = {}

            # 权限校验：全局 LLM 配置属于系统级资源，仅允许本地回环连接修改
            llm_conf = settings_data.get("llm")
            if isinstance(llm_conf, dict) and not _is_local_websocket(websocket):
                logger.warning(
                    "拒绝对全局 LLM 配置的远程修改请求 (client=%s)",
                    getattr(getattr(websocket, "client", None), "host", "unknown"),
                )
                await websocket.send_json(
                    jsonable_encoder(
                        {
                            "type": "error",
                            "message": "权限拒绝：远程连接不允许修改全局 LLM 配置，请通过本地管理通道操作",
                            "request_id": request_id,
                            "timestamp": time.time(),
                            "error_code": "forbidden_global_config",
                        }
                    )
                )
                return

            from config.integrated_config import get_settings

            settings = get_settings()

            # 处理 LLM 配置
            if isinstance(llm_conf, dict):
                await self._update_llm_settings(settings, llm_conf, websocket)

            # 重载 LLM 模块
            try:
                from core.llm import get_llm_module
                import asyncio as _asyncio

                module = get_llm_module()
                if hasattr(module, "reload"):
                    if _asyncio.iscoroutinefunction(module.reload):
                        await module.reload()
                    else:
                        module.reload()
            except Exception as e:
                await websocket.send_json(
                    jsonable_encoder(
                        {
                            "type": "error",
                            "message": f"设置已更新，但重载模型失败: {e}",
                            "request_id": request_id,
                            "timestamp": time.time(),
                        }
                    )
                )
                return

            await websocket.send_json(
                jsonable_encoder(
                    {
                        "type": "system",
                        "content": "Settings updated successfully",
                        "request_id": request_id,
                        "timestamp": time.time(),
                    }
                )
            )

        except Exception as e:
            await websocket.send_json(
                jsonable_encoder(
                    {
                        "type": "error",
                        "message": f"更新设置失败: {e}",
                        "request_id": request_id,
                        "timestamp": time.time(),
                    }
                )
            )

    async def _update_llm_settings(
        self, settings, llm_conf: dict, websocket: WebSocket
    ):
        """更新 LLM 设置"""
        provider = llm_conf.get("provider")
        model = llm_conf.get("model")
        text_path = (
            llm_conf.get("text_path")
            or llm_conf.get("model_path")
            or llm_conf.get("path")
        )

        # Mobile compatibility: If model is explicitly "local", force provider to "local"
        if model and str(model).lower().strip() in ["local", "default"]:
            if not provider or str(provider).lower() != "local":
                logger.info(
                    f"Detected mobile request for local model ('{model}'), forcing provider to 'local'"
                )
                provider = "local"
                model = "local"

        # Handle Cloud Provider Switch
        elif provider and str(provider).lower() != "local":
            settings.model.llm.provider = str(provider)
            settings.model.llm.model = str(model)
            logger.info(f"Switching to Cloud Provider: {provider} - {model}")

        if provider == "local":
            settings.model.llm.provider = "local"
            if model and "cloud:" in str(model).lower():
                settings.model.llm.model = "local"
            elif model:
                settings.model.llm.model = str(model)

            # Fix for mobile switch to local: Ensure valid local path exists
            current_path = settings.model.text_path
            import os

            if not current_path or not os.path.exists(current_path):
                logger.warning(
                    f"Switched to local provider but path '{current_path}' is invalid. Attempting auto-detection..."
                )
                try:
                    from config.integrated_config import _auto_detect_models

                    _auto_detect_models(settings)
                    if settings.model.text_path and os.path.exists(
                        settings.model.text_path
                    ):
                        logger.info(
                            f"Auto-detected local model path: {settings.model.text_path}"
                        )
                    else:
                        logger.error("Failed to auto-detect any local GGUF model.")
                except Exception as e:
                    logger.error(f"Error during model auto-detection: {e}")

        if text_path and str(provider) == "local":
            settings.model.text_path = str(text_path)

    async def handle_update_physiology(self, websocket: WebSocket, message: dict):
        """处理更新用户生理状态消息"""
        request_id = message.get("request_id") or str(int(time.time() * 1000))

        try:
            try:
                from core.services.life_simulation.service import (
                    get_life_simulation_service,
                )

                get_life_simulation_service().update_interaction(xp_gain=0)
            except Exception:
                pass

            user_id = (
                str(
                    message.get("user_id")
                    or getattr(websocket, "user_id", "default_user")
                ).strip()
                or "default_user"
            )
            from core.services.user_physiology.service import (
                get_user_physiology_service,
            )

            rec = get_user_physiology_service().update(user_id=user_id, payload=message)

            await websocket.send_json(
                jsonable_encoder(
                    {
                        "type": "system",
                        "content": "User physiology updated",
                        "data": rec,
                        "request_id": request_id,
                        "timestamp": time.time(),
                    }
                )
            )
        except Exception as e:
            await websocket.send_json(
                jsonable_encoder(
                    {
                        "type": "error",
                        "message": f"更新用户生理状态失败: {e}",
                        "request_id": request_id,
                        "timestamp": time.time(),
                    }
                )
            )

    async def handle_active_care_control(
        self, websocket: WebSocket, data: Dict[str, Any]
    ):
        """
        处理主程序对 Active Care 的控制请求。
        
        支持的操作:
        - set_sleep_mode: 设置/取消睡眠模式
        - schedule_reminder: 安排延迟提醒
        - pause: 暂停 Active Care
        """
        action = str(data.get("action") or "").strip().lower()
        
        try:
            from core.services.active_care.core.service import get_active_care_service
            
            ac_service = get_active_care_service()
            
            if action == "set_sleep_mode":
                active = bool(data.get("active", True))
                reason = str(data.get("reason") or "user_request")
                delay_seconds = int(data.get("delay_seconds") or 7200)
                
                success = await ac_service.set_sleep_mode(
                    active=active,
                    reason=reason,
                    delay_next_check_seconds=delay_seconds
                )
                
                if success:
                    status_msg = "睡眠模式已激活" if active else "睡眠模式已取消"
                    await websocket.send_json({
                        "type": "active_care_control_response",
                        "action": action,
                        "success": True,
                        "message": status_msg,
                    })
                    logger.info(f"Active Care 控制成功: {action}, active={active}")
                else:
                    await websocket.send_json({
                        "type": "active_care_control_response",
                        "action": action,
                        "success": False,
                        "message": "设置失败",
                    })
                    
            elif action == "schedule_reminder":
                delay_seconds = int(data.get("delay_seconds") or 1800)
                reminder_type = str(data.get("reminder_type") or "general")
                message_hint = str(data.get("message_hint") or "")
                
                success = await ac_service.schedule_reminder(
                    delay_seconds=delay_seconds,
                    reminder_type=reminder_type,
                    message_hint=message_hint
                )
                
                if success:
                    await websocket.send_json({
                        "type": "active_care_control_response",
                        "action": action,
                        "success": True,
                        "message": f"提醒已安排，将在 {delay_seconds} 秒后触发",
                    })
                else:
                    await websocket.send_json({
                        "type": "active_care_control_response",
                        "action": action,
                        "success": False,
                        "message": "安排提醒失败",
                    })
                    
            elif action == "pause":
                duration_seconds = int(data.get("duration_seconds") or 3600)
                
                success = await ac_service.pause(duration_seconds=duration_seconds)
                
                if success:
                    await websocket.send_json({
                        "type": "active_care_control_response",
                        "action": action,
                        "success": True,
                        "message": f"Active Care 已暂停 {duration_seconds} 秒",
                    })
                else:
                    await websocket.send_json({
                        "type": "active_care_control_response",
                        "action": action,
                        "success": False,
                        "message": "暂停失败",
                    })
                    
            else:
                await websocket.send_json({
                    "type": "active_care_control_response",
                    "action": action,
                    "success": False,
                    "message": f"未知操作: {action}",
                })
                
        except Exception as e:
            logger.error(f"Active Care 控制失败: {e}", exc_info=True)
            await websocket.send_json({
                "type": "active_care_control_response",
                "action": action,
                "success": False,
                "message": str(e),
            })