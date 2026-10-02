"""WebSocket 入站消息路由。"""

from __future__ import annotations

import time
import traceback

from fastapi import WebSocket

from core.utils.logger import get_logger

logger = get_logger(__name__)


class WebSocketMessageRouterMixin:
    """刷新连接活跃状态并把消息分派给领域处理器。"""

    async def _process_message(self, websocket: WebSocket, message: dict) -> None:
        try:
            if not isinstance(message, dict):
                logger.warning("接收到非字典消息：%s", message)
                return
            msg_type = message.get("type")
            logger.debug("收到消息类型：%s", msg_type)
            if self.websocket_manager is not None:
                try:
                    async with self.websocket_manager.connections_lock:
                        connection = self.websocket_manager.connections.get(websocket)
                        if connection is not None:
                            now = time.time()
                            connection.last_activity = now
                            if connection.last_heartbeat < now:
                                connection.last_heartbeat = now
                except Exception:  # noqa: BLE001
                    logger.debug("更新连接心跳计时器失败", exc_info=True)

            if msg_type == "ping":
                await self.handlers.handle_ping(websocket, message)
            elif msg_type == "pong":
                await self.handlers.handle_pong(websocket, message)
            elif msg_type == "greeting":
                await self.handlers.handle_greeting_message(websocket, message, self.streaming)
            elif msg_type == "update_settings":
                await self.handlers.handle_update_settings(websocket, message)
            elif msg_type == "update_user_physiology":
                await self.handlers.handle_update_physiology(websocket, message)
            elif msg_type == "mobile_switch_model":
                await self.handlers.handle_mobile_switch_model(websocket, message)
            elif msg_type == "reconnect":
                await self.handlers.handle_reconnect(websocket, message)
            elif msg_type in ("text", "text_input"):
                normalized = await self.handlers.handle_text_message(websocket, message)
                if normalized:
                    await self.handlers.handle_chat_message(websocket, normalized, self.streaming)
            elif msg_type in ("message", "chat"):
                await self.handlers.handle_chat_message(websocket, message, self.streaming)
            elif msg_type in ("demo_voice_input", "demo_generate_image", "generate_image"):
                await self._handle_demo_message(websocket, message)
            elif msg_type == "device_command_result":
                await self._handle_device_command_result(message)
            elif self.websocket_manager:
                await self.websocket_manager.handle_message(websocket, message)
        except Exception as exc:  # noqa: BLE001
            error_text = str(exc)
            if "close message has been sent" in error_text or "not connected" in error_text.lower():
                logger.debug("连接关闭竞态导致消息处理跳过：%s", error_text)
            else:
                logger.error("处理消息时出错：%s", exc)
                logger.error(traceback.format_exc())

    async def _handle_device_command_result(self, message: dict) -> None:
        try:
            from core.services.device_command import get_device_command_bridge

            await get_device_command_bridge().resolve_result(message)
        except Exception as exc:  # noqa: BLE001
            logger.error("处理设备指令结果失败: %s", exc, exc_info=True)
