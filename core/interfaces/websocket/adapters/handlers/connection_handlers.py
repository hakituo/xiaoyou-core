#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
连接相关的消息处理器
处理 ping、pong、reconnect 等连接管理消息
"""

from core.utils.logger import get_logger

import time
from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = get_logger(__name__)


class ConnectionHandlers:
    """连接相关的消息处理器"""

    def __init__(self, adapter):
        self.adapter = adapter

    def _is_websocket_closed(self, websocket: WebSocket) -> bool:
        """检测 WebSocket 是否已断开/已发送关闭帧

        在发送响应前调用，避免对已关闭的连接调用 send 触发
        RuntimeError: Cannot call "send" once a close message has been sent.
        """
        # 优先复用 WebSocketManager 的检测逻辑（更全面）
        ws_manager = getattr(self.adapter, "websocket_manager", None)
        if ws_manager is not None:
            try:
                checker = getattr(ws_manager, "_is_starlette_websocket_closed", None)
                if checker is not None and checker(websocket):
                    return True
            except Exception:
                pass

        # 兜底：直接看 application_state / client_state
        try:
            app_state = getattr(websocket, "application_state", None)
            if app_state == WebSocketState.DISCONNECTED:
                return True
            client_state = getattr(websocket, "client_state", None)
            if client_state == WebSocketState.DISCONNECTED:
                return True
        except Exception:
            pass

        # close_code 被设置也说明已断开
        if getattr(websocket, "close_code", None) is not None:
            return True
        return False

    async def _refresh_connection_metadata(self, websocket: WebSocket, message: dict):
        """刷新连接元数据"""
        manager = self.adapter.websocket_manager
        if not manager or not isinstance(message, dict):
            return
        incoming_user_id = str(message.get("user_id") or "").strip()
        incoming_platform = str(message.get("platform") or "").strip().lower()
        incoming_client_id = str(message.get("client_id") or "").strip()
        if not incoming_user_id and not incoming_platform and not incoming_client_id:
            return
        async with manager.connections_lock:
            conn = manager.connections.get(websocket)
            if not conn:
                return
            old_user_id = str(getattr(conn, "user_id", "") or "").strip()
            if incoming_user_id and incoming_user_id != old_user_id:
                if old_user_id in manager.user_connections:
                    manager.user_connections[old_user_id] = [
                        c for c in manager.user_connections[old_user_id] if c is not conn
                    ]
                    if not manager.user_connections[old_user_id]:
                        del manager.user_connections[old_user_id]
                manager.user_connections[incoming_user_id].append(conn)
                conn.user_id = incoming_user_id
                setattr(websocket, "user_id", incoming_user_id)
            if incoming_platform:
                conn.platform = incoming_platform
                setattr(websocket, "platform", incoming_platform)
            if incoming_client_id:
                setattr(websocket, "client_id", incoming_client_id)

    async def handle_ping(self, websocket: WebSocket, message: dict):
        """处理 ping 消息"""
        if self._is_websocket_closed(websocket):
            logger.debug("收到 ping，但连接已关闭，跳过 pong 响应")
            return
        await self._refresh_connection_metadata(websocket, message)
        await websocket.send_json(
            {"type": "pong", "timestamp": message.get("timestamp", time.time())}
        )

    async def handle_pong(self, websocket: WebSocket, message: dict):
        """处理 pong 消息"""
        if self.adapter.websocket_manager:
            await self.adapter.websocket_manager.handle_heartbeat(websocket)

    async def handle_reconnect(self, websocket: WebSocket, message: dict):
        """
        处理移动端重连请求
        客户端从后台恢复时发送 reconnect 消息以同步状态
        """
        user_id = getattr(websocket, "user_id", "unknown")
        platform = getattr(websocket, "platform", "unknown")

        logger.info(f"Mobile reconnect request from user: {user_id}, platform: {platform}")

        # 更新连接元数据
        await self._refresh_connection_metadata(websocket, message)

        # 同步当前状态
        sync_data = {
            "type": "reconnect_sync",
            "timestamp": time.time(),
            "data": {
                "user_id": user_id,
                "platform": platform,
                "reconnected": True,
            },
        }

        # 同步当前模型状态
        try:
            from config.integrated_config import get_settings
            settings = get_settings()
            if settings and settings.model and settings.model.llm:
                sync_data["data"]["model"] = {
                    "provider": settings.model.llm.provider,
                    "model": settings.model.llm.model,
                    "text_path": settings.model.text_path,
                }
        except Exception:
            pass

        # 同步当前情绪状态
        try:
            from core.emotion.manager import get_emotion_manager
            emo_manager = get_emotion_manager()
            emo_state = emo_manager.get_current_state(user_id)
            if emo_state:
                sync_data["data"]["emotion"] = {
                    "primary": emo_state.primary_emotion.value if emo_state.primary_emotion else "neutral",
                    "intensity": getattr(emo_state, "intensity", 0.5),
                    "emotion_mix": getattr(emo_state, "emotion_mix", None) or getattr(emo_state, "sub_emotions", {}),
                }
        except Exception:
            pass

        # 同步生命模拟状态
        try:
            from core.services.life_simulation.service import get_life_simulation_service
            sim = get_life_simulation_service()
            state = sim.get_state()
            if state:
                sync_data["data"]["life_status"] = state
        except Exception:
            pass

        # 推送离线消息
        if self.adapter.websocket_manager:
            try:
                await self.adapter.websocket_manager._flush_offline_messages(user_id, websocket)
            except Exception:
                pass

        if self._is_websocket_closed(websocket):
            logger.debug(f"重连同步前连接已关闭，跳过发送: {user_id}")
            return
        await websocket.send_json(sync_data)
        logger.info(f"Reconnect sync sent to user: {user_id}")

    async def handle_mobile_switch_model(self, websocket: WebSocket, message: dict):
        """处理移动端切换模型消息"""
        target_model = message.get("model")
        request_id = message.get("request_id") or str(int(time.time() * 1000))

        if target_model:
            # 将模型偏好绑定到当前 WebSocket 连接实例上
            setattr(websocket, "forced_model_preference", target_model)

            logger.info(
                f"移动端专属切换: 为连接 {getattr(websocket, 'user_id', 'unknown')} 锁定模型为 {target_model}"
            )

            await websocket.send_json(
                {
                    "type": "system",
                    "content": f"已切换至指定模型：{target_model}（会话级锁定）",
                    "current_model": target_model,
                    "request_id": request_id,
                    "timestamp": time.time(),
                }
            )
        else:
            await websocket.send_json(
                {"type": "error", "message": "未指定目标模型", "request_id": request_id}
            )
