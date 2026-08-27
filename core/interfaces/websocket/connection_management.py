#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""连接管理 Mixin

为 WebSocketManager 提供连接的注册、移除、状态检测和僵尸连接清理。
add_connection 在新连接注册前会清理同 user_id 的已断开连接，
避免移动端重连时旧连接残留导致连接数持续增长。
"""

from core.utils.logger import get_logger
import asyncio

import time

import websockets
from starlette.websockets import WebSocketState

from config import get_settings
from core.contracts import ConnectionState
from .connection import ClientConnection

logger = get_logger(__name__)


class ConnectionManagementMixin:
    """连接管理相关方法"""

    # P1-2: 跟踪离线消息推送任务，防止被 GC 后用户收不到上线前的离线消息
    # 类变量共享所有实例的 pending 任务（mixin 无法在 __init__ 中初始化）
    _pending_offline_flush_tasks: set = set()

    @classmethod
    def _spawn_offline_flush_task(cls, coro) -> None:
        """P1-2: 提交离线消息推送任务并保存引用。"""
        task = asyncio.create_task(coro)
        cls._pending_offline_flush_tasks.add(task)

        def _on_done(t: asyncio.Task) -> None:
            cls._pending_offline_flush_tasks.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.error("离线消息推送任务异常: %r", exc, exc_info=exc)

        task.add_done_callback(_on_done)

    async def add_connection(
        self,
        websocket: "websockets.WebSocketServerProtocol",
        user_id: str = "anonymous",
        platform: str = "unknown",
    ) -> bool:
        """
        添加新连接，增加IP级连接限制和更严格的并发控制

        Args:
            websocket: WebSocket连接对象
            user_id: 用户ID
            platform: 平台类型

        Returns:
            是否成功添加
        """
        async with self.connections_lock:
            # 获取客户端IP
            client_ip = "unknown"
            if hasattr(websocket, "client") and websocket.client:
                client_ip = websocket.client.host
            elif hasattr(websocket, "remote_address") and websocket.remote_address:
                client_ip = websocket.remote_address[0]
            elif (
                hasattr(websocket, "scope")
                and "client" in websocket.scope
                and websocket.scope["client"]
            ):
                client_ip = websocket.scope["client"][0]

            # 统计此IP的连接数
            ip_connections = sum(
                1 for conn in self.connections.values() if conn.ip == client_ip
            )
            try:
                settings = get_settings()
                if hasattr(settings, "app") and hasattr(settings.app, "websocket"):
                    max_per_ip = getattr(
                        settings.app.websocket, "max_connections_per_ip", 20
                    )
                else:
                    max_per_ip = 20
            except Exception:
                max_per_ip = 20

            # 检查连接限制：全局限制和IP级限制
            if len(self.connections) >= self.max_connections:
                logger.warning(f"Connection limit reached: {self.max_connections}")
                return False

            if ip_connections >= max_per_ip:
                logger.warning(
                    f"IP connection limit reached: {client_ip} "
                    f"has {ip_connections} connections"
                )
                return False

            # 检查连接是否已经存在（避免重复添加）
            if websocket in self.connections:
                logger.warning(f"Connection already exists: {client_ip}")
                return False

            # 清理同一 user_id 的僵尸连接（已断开但未被 remove 的连接）
            # 避免移动端重连时旧连接残留导致连接数持续增长
            if user_id in self.user_connections:
                stale_conns = [
                    conn
                    for conn in self.user_connections[user_id]
                    if (hasattr(conn.websocket, "closed") and conn.websocket.closed)
                    or self._is_starlette_websocket_closed(conn.websocket)
                ]
                for conn in stale_conns:
                    stale_ws = conn.websocket
                    logger.info(
                        f"[WebSocket] 清理僵尸连接 - User: {conn.user_id}, "
                        f"Platform: {conn.platform}, "
                        f"Duration: {conn.get_connection_duration():.2f}s"
                    )
                    if stale_ws in self.connections:
                        del self.connections[stale_ws]
                    conn.state = ConnectionState.CLOSED
                if stale_conns:
                    self.user_connections[user_id] = [
                        conn
                        for conn in self.user_connections[user_id]
                        if conn not in stale_conns
                    ]
                    if not self.user_connections[user_id]:
                        del self.user_connections[user_id]
                    self.stats["active_connections"] = len(self.connections)

            # 创建连接信息对象
            is_mobile = platform.lower() in (
                "android",
                "ios",
                "capacitor",
                "mobile",
            )
            reconnect_count = 0
            if is_mobile and user_id in self.user_connections:
                for existing_conn in self.user_connections[user_id]:
                    if (
                        existing_conn.platform == platform
                        and existing_conn.state == ConnectionState.CLOSED
                    ):
                        reconnect_count += existing_conn.reconnect_count + 1
                        break

            connection = ClientConnection(
                websocket=websocket,
                user_id=user_id,
                platform=platform,
                ip=client_ip,
                state=ConnectionState.CONNECTED,
                is_mobile=is_mobile,
                reconnect_count=reconnect_count,
            )

            self.connections[websocket] = connection
            self.user_connections[user_id].append(connection)

            self.stats["total_connections"] += 1
            self.stats["active_connections"] = len(self.connections)

            logger.info(
                f"New client connected: {client_ip}, User: {user_id}, "
                f"Platform: {platform}, "
                f"Connections: {len(self.connections)}/{self.max_connections}, "
                f"IP connections: {ip_connections + 1}/{max_per_ip}, "
                f"Registered User IDs: {list(self.user_connections.keys())}"
            )

            # 尝试推送离线消息
            self._spawn_offline_flush_task(self._flush_offline_messages(user_id, websocket))

            # 对移动端连接发送连接确认（含心跳配置）
            if is_mobile:
                try:
                    await websocket.send_json(
                        {
                            "type": "connection_established",
                            "timestamp": time.time(),
                            "heartbeat_interval": self.heartbeat_interval,
                            "heartbeat_timeout": self.heartbeat_timeout,
                            "reconnect_supported": True,
                            "data": {
                                "user_id": user_id,
                                "platform": platform,
                                "is_reconnect": reconnect_count > 0,
                            },
                        }
                    )
                except Exception:
                    pass

            return True

    async def remove_connection(
        self, websocket: "websockets.WebSocketServerProtocol"
    ):
        """
        移除连接并清理资源

        Args:
            websocket: 要移除的WebSocket连接
        """
        async with self.connections_lock:
            if websocket in self.connections:
                connection = self.connections[websocket]

                # 从用户连接映射中移除
                user_id = connection.user_id
                if user_id in self.user_connections:
                    self.user_connections[user_id] = [
                        conn
                        for conn in self.user_connections[user_id]
                        if conn.websocket != websocket
                    ]
                    if not self.user_connections[user_id]:
                        del self.user_connections[user_id]

                # 更新状态
                connection.state = ConnectionState.CLOSED
                del self.connections[websocket]
                self.stats["active_connections"] = len(self.connections)

                logger.info(
                    f"Client disconnected: {connection.ip}, "
                    f"User: {connection.user_id}, "
                    f"Platform: {connection.platform}, "
                    f"Duration: {connection.get_connection_duration():.2f}s, "
                    f"Messages: {connection.message_count}"
                )

    def _is_starlette_websocket_closed(
        self, websocket: "websockets.WebSocketServerProtocol"
    ) -> bool:
        """检测 Starlette/FastAPI WebSocket 是否已断开"""
        state = getattr(websocket, "application_state", None)
        if state is not None and state == WebSocketState.DISCONNECTED:
            return True
        client_state = getattr(websocket, "client_state", None)
        if client_state is not None and client_state == WebSocketState.DISCONNECTED:
            return True
        close_code = getattr(websocket, "close_code", None)
        if close_code is not None:
            return True
        return False

    async def _cleanup_stale_connections(self):
        """
        清理可能已经断开但未正确关闭的连接

        此方法检查所有连接的状态，如果发现连接已关闭但仍在管理器中，
        则将其从管理器中移除并清理相关资源。
        """
        stale_websockets = []
        async with self.connections_lock:
            for websocket in list(self.connections.keys()):
                try:
                    if (
                        hasattr(websocket, "closed") and websocket.closed
                    ) or self._is_starlette_websocket_closed(websocket):
                        stale_websockets.append(websocket)
                except Exception as e:
                    logger.debug(f"Error checking connection state: {e}")
                    stale_websockets.append(websocket)
        # 在锁外清理，避免与 remove_connection 的锁重入死锁
        for websocket in stale_websockets:
            await self.remove_connection(websocket)
