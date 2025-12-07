#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket适配器模块
处理WebSocket连接和事件转换
"""
import logging
import asyncio
from typing import Dict, Any, Set, Optional
from fastapi import WebSocket, WebSocketDisconnect
from mvp_core.core import get_core_engine

logger = logging.getLogger(__name__)

class ConnectionManager:
    """
    WebSocket连接管理器
    """
    
    def __init__(self):
        """
        初始化连接管理器
        """
        self.active_connections: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket):
        """
        接受新连接
        
        Args:
            websocket: WebSocket连接实例
        """
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket connection established, total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        """
        断开连接
        
        Args:
            websocket: WebSocket连接实例
        """
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket connection closed, total connections: {len(self.active_connections)}")
    
    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket):
        """
        发送个人消息
        
        Args:
            message: 要发送的消息
            websocket: WebSocket连接实例
        """
        await websocket.send_json(message)
    
    async def broadcast(self, message: Dict[str, Any]):
        """
        广播消息给所有连接
        
        Args:
            message: 要广播的消息
        """
        for connection in self.active_connections:
            await connection.send_json(message)

class WebSocketAdapter:
    """
    WebSocket适配器
    处理WebSocket连接和事件转换
    """
    
    def __init__(self):
        """
        初始化WebSocket适配器
        """
        self.core_engine = get_core_engine()
        self.event_bus = self.core_engine.event_bus
        self.connection_manager = ConnectionManager()
        self._running = False
        
        logger.info("WebSocketAdapter initialized")
        
        # 注册事件监听器
        self._register_events()
    
    def _register_events(self):
        """
        注册事件监听器
        """
        async def on_core_response(data: Dict[str, Any]):
            """处理核心服务响应事件"""
            await self._handle_core_response(data)
        
        async def on_system_event(data: Dict[str, Any]):
            """处理系统事件"""
            await self._handle_system_event(data)
        
        # 注册事件
        asyncio.create_task(self.event_bus.subscribe("core.response", on_core_response))
        asyncio.create_task(self.event_bus.subscribe("system.health_check", on_system_event))
    
    async def _handle_core_response(self, data: Dict[str, Any]):
        """
        处理核心服务响应，转发给WebSocket客户端
        
        Args:
            data: 核心服务响应数据
        """
        # 转换为WebSocket消息格式
        websocket_message = {
            "type": "core_response",
            "data": data
        }
        
        # 广播给所有连接的客户端
        await self.connection_manager.broadcast(websocket_message)
    
    async def _handle_system_event(self, data: Dict[str, Any]):
        """
        处理系统事件，转发给WebSocket客户端
        
        Args:
            data: 系统事件数据
        """
        # 转换为WebSocket消息格式
        websocket_message = {
            "type": "system_event",
            "event_type": data.get("type", "system_event"),
            "data": data
        }
        
        # 广播给所有连接的客户端
        await self.connection_manager.broadcast(websocket_message)
    
    async def handle_websocket(self, websocket: WebSocket):
        """
        处理WebSocket连接
        
        Args:
            websocket: WebSocket连接实例
        """
        # 接受连接
        await self.connection_manager.connect(websocket)
        
        try:
            while True:
                # 接收客户端消息
                data = await websocket.receive_json()
                
                # 处理客户端消息
                await self._process_client_message(data, websocket)
        except WebSocketDisconnect:
            # 客户端断开连接
            self.connection_manager.disconnect(websocket)
        except Exception as e:
            # 处理其他错误
            logger.error(f"WebSocket error: {e}")
            self.connection_manager.disconnect(websocket)
    
    async def _process_client_message(self, data: Dict[str, Any], websocket: WebSocket):
        """
        处理客户端消息
        
        Args:
            data: 客户端消息数据
            websocket: WebSocket连接实例
        """
        message_type = data.get("type", "unknown")
        message_data = data.get("data", {})
        
        logger.info(f"Received WebSocket message: {message_type}")
        
        # 根据消息类型处理
        if message_type == "user_message":
            # 转发用户消息给事件总线
            await self.event_bus.publish("user.message", {
                "message": message_data.get("message"),
                "user_id": message_data.get("user_id", "anonymous"),
                "timestamp": asyncio.get_event_loop().time(),
                "websocket": websocket
            })
        elif message_type == "ping":
            # 处理心跳请求
            await self.connection_manager.send_personal_message({
                "type": "pong",
                "timestamp": asyncio.get_event_loop().time()
            }, websocket)
        else:
            # 未知消息类型
            logger.warning(f"Unknown WebSocket message type: {message_type}")
            await self.connection_manager.send_personal_message({
                "type": "error",
                "error": f"Unknown message type: {message_type}",
                "timestamp": asyncio.get_event_loop().time()
            }, websocket)
    
    async def initialize(self):
        """
        初始化WebSocket适配器
        """
        if self._running:
            logger.warning("WebSocketAdapter is already running")
            return
        
        self._running = True
        logger.info("WebSocketAdapter initialized successfully")
    
    async def shutdown(self):
        """
        关闭WebSocket适配器
        """
        if not self._running:
            logger.warning("WebSocketAdapter is not running")
            return
        
        self._running = False
        logger.info("WebSocketAdapter shutdown successfully")
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取WebSocket适配器状态
        
        Returns:
            状态信息
        """
        return {
            "running": self._running,
            "active_connections": len(self.connection_manager.active_connections)
        }

# 全局WebSocketAdapter实例
_websocket_adapter_instance = None

def get_websocket_adapter() -> WebSocketAdapter:
    """
    获取WebSocketAdapter实例
    
    Returns:
        WebSocketAdapter实例
    """
    global _websocket_adapter_instance
    if _websocket_adapter_instance is None:
        _websocket_adapter_instance = WebSocketAdapter()
    return _websocket_adapter_instance