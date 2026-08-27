#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主消息处理器
组合所有子处理器，提供统一的接口
"""

from core.utils.logger import get_logger

from typing import Any, Dict
from fastapi import WebSocket

from .connection_handlers import ConnectionHandlers
from .settings_handlers import SettingsHandlers
from .chat_handlers import ChatHandlers

logger = get_logger(__name__)


class MessageHandlers:
    """消息处理器集合"""

    def __init__(self, adapter):
        self.adapter = adapter
        self.connection_handlers = ConnectionHandlers(adapter)
        self.settings_handlers = SettingsHandlers(adapter)
        self.chat_handlers = ChatHandlers(adapter)

    async def cleanup_websocket(self, websocket: WebSocket):
        """清理 WebSocket 连接相关的资源"""
        await self.chat_handlers.cleanup_websocket(websocket)

    async def handle_ping(self, websocket: WebSocket, message: dict):
        """处理 ping 消息"""
        await self.connection_handlers.handle_ping(websocket, message)

    async def handle_pong(self, websocket: WebSocket, message: dict):
        """处理 pong 消息"""
        await self.connection_handlers.handle_pong(websocket, message)

    async def handle_reconnect(self, websocket: WebSocket, message: dict):
        """处理重连消息"""
        await self.connection_handlers.handle_reconnect(websocket, message)

    async def handle_update_settings(self, websocket: WebSocket, message: dict):
        """处理更新设置消息"""
        await self.settings_handlers.handle_update_settings(websocket, message)

    async def handle_update_physiology(self, websocket: WebSocket, message: dict):
        """处理更新生理状态消息"""
        await self.settings_handlers.handle_update_physiology(websocket, message)

    async def handle_mobile_switch_model(self, websocket: WebSocket, message: dict):
        """处理移动端切换模型消息"""
        await self.connection_handlers.handle_mobile_switch_model(websocket, message)

    async def handle_text_message(self, websocket: WebSocket, message: dict) -> dict:
        """处理文本消息"""
        return await self.chat_handlers.handle_text_message(websocket, message)

    async def handle_chat_message(
        self, websocket: WebSocket, message: dict, streaming_handler
    ):
        """处理聊天消息"""
        await self.chat_handlers.handle_chat_message(websocket, message, streaming_handler)

    async def handle_greeting_message(
        self, websocket: WebSocket, message: dict, streaming_handler
    ):
        """处理问候消息"""
        await self.chat_handlers.handle_greeting_message(websocket, message, streaming_handler)

    async def handle_active_care_control(
        self, websocket: WebSocket, data: Dict[str, Any]
    ):
        """处理 Active Care 控制消息"""
        await self.settings_handlers.handle_active_care_control(websocket, data)