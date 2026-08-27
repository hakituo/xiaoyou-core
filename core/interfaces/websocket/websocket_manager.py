#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
增强型WebSocket连接管理器

门面类，通过 Mixin 组合实现连接管理、消息发送、心跳检测、
离线队列和消息处理等能力。各子模块位于同目录下的独立文件中。

外部 API 保持不变：
    from core.interfaces.websocket.websocket_manager import (
        WebSocketManager, ClientConnection, ConnectionState,
        get_websocket_manager,
    )
"""

from core.utils.logger import get_logger
import asyncio
import logging
import sys
import time
from collections import OrderedDict, defaultdict, deque
from typing import Any, Dict, List, Optional

import websockets

# Windows 事件循环策略
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from config import get_settings

from core.contracts import ConnectionState
from core.core_engine.event_bus import EventTypes, get_event_bus
from core.utils.async_locks import LazyAsyncLock

from .connection import ClientConnection
from .connection_management import ConnectionManagementMixin
from .heartbeat_service import HeartbeatMixin
from .message_handling import MessageHandlingMixin
from .message_sending import MessageSendingMixin
from .offline_queue import OfflineQueueMixin

logger = get_logger(__name__)

# re-export，保持外部 import 路径不变
__all__ = [
    "WebSocketManager",
    "ClientConnection",
    "ConnectionState",
    "get_websocket_manager",
    "initialize_websocket_manager",
]


class WebSocketManager(
    ConnectionManagementMixin,
    MessageSendingMixin,
    HeartbeatMixin,
    OfflineQueueMixin,
    MessageHandlingMixin,
):
    """
    增强型WebSocket连接管理器
    集成EventBus用于模块间解耦通信

    方法实现分散在各 Mixin 中：
    - ConnectionManagementMixin: add_connection / remove_connection / 状态检测
    - MessageSendingMixin: send_with_retry / send_to_client / broadcast
    - HeartbeatMixin: heartbeat_checker / send_ping / handle_heartbeat
    - OfflineQueueMixin: store_offline_message / _flush_offline_messages
    - MessageHandlingMixin: handle_message / register_message_handler
    """

    def __init__(self):
        """初始化连接管理器，加载配置并创建共享状态"""
        # 配置参数
        try:
            settings = get_settings()
            if hasattr(settings, "app") and hasattr(settings.app, "websocket"):
                self.max_connections = getattr(
                    settings.app.websocket, "max_connections", 50
                )
                self.heartbeat_interval = getattr(
                    settings.app.websocket, "heartbeat_interval", 30
                )
                self.heartbeat_timeout = getattr(
                    settings.app.websocket, "timeout", 60
                )
                self.max_concurrent_queries = getattr(
                    settings.app.websocket, "max_concurrent_queries", 10
                )
            else:
                self.max_connections = 50
                self.heartbeat_interval = 30
                self.heartbeat_timeout = 60
                self.max_concurrent_queries = 5
        except Exception as e:
            logging.warning(f"无法访问WebSocket配置，使用默认值: {e}")
            self.max_connections = 10
            self.heartbeat_interval = 30
            self.heartbeat_timeout = 60
            self.max_concurrent_queries = 5

        # 连接管理（所有 Mixin 共享）
        self.connections: Dict[
            websockets.WebSocketServerProtocol, ClientConnection
        ] = {}
        self.connections_lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self.user_connections: Dict[str, List[ClientConnection]] = defaultdict(list)

        # 并发控制
        self.query_semaphore = asyncio.Semaphore(self.max_concurrent_queries)

        # 心跳相关
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.running = False

        # 事件总线实例
        self.event_bus = get_event_bus()

        # 统计信息
        self.stats = {
            "total_connections": 0,
            "active_connections": 0,
            "messages_processed": 0,
            "errors": 0,
            "heartbeat_failures": 0,
        }

        # 已处理消息请求ID（防重复处理）
        self.processed_requests = OrderedDict()

        # 离线消息队列: user_id -> deque of (timestamp, message_dict)
        self.offline_queue: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=50)
        )
        self.offline_ttl = 24 * 3600  # 24 hours

    async def initialize(self):
        """初始化 WebSocket 管理器、订阅事件并启动心跳检查器"""
        try:
            await self.event_bus.subscribe(
                EventTypes.PREFERENCE_CHANGED, self._handle_preference_change
            )

            # 启动心跳检查器（清理僵尸连接、发送 ping）
            self.running = True
            self.heartbeat_task = asyncio.create_task(self.heartbeat_checker())
            logger.info(
                f"WebSocketManager initialized: max_connections={self.max_connections}, "
                f"heartbeat_interval={self.heartbeat_interval}s, heartbeat_timeout={self.heartbeat_timeout}s"
            )
        except Exception as e:
            logger.error(f"Failed to initialize WebSocketManager: {e}")

    async def _handle_preference_change(
        self, key: str, value: Any, old_value: Any, **kwargs
    ):
        """处理偏好变更事件，广播给所有客户端"""
        try:
            message = {
                "type": "preference_update",
                "data": {"key": key, "value": value, "old_value": old_value},
                "timestamp": time.time(),
            }
            await self.broadcast(message)
        except Exception as e:
            logger.error(f"Failed to broadcast preference change: {e}")

    async def stop(self):
        """停止连接管理器"""
        if not self.running:
            return

        self.running = False

        # 取消心跳检查任务
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass

        # 关闭所有连接
        async with self.connections_lock:
            connections_to_close = list(self.connections.keys())

        for websocket in connections_to_close:
            try:
                await websocket.close(code=1000, reason="Server shutting down")
            except Exception as e:
                logger.debug(f"Error closing connection during shutdown: {e}")
            await self.remove_connection(websocket)

        logger.info("WebSocket connection manager stopped")

    def get_stats(self) -> Dict[str, Any]:
        """返回统计信息副本"""
        return dict(self.stats)


# 全局 WebSocket 管理器实例
global_websocket_manager = None


def get_websocket_manager() -> WebSocketManager:
    """
    获取全局WebSocket管理器实例（单例）

    Returns:
        WebSocketManager: 全局WebSocket管理器实例
    """
    global global_websocket_manager
    if global_websocket_manager is None:
        global_websocket_manager = WebSocketManager()
    return global_websocket_manager


async def initialize_websocket_manager():
    """初始化全局 WebSocket 管理器"""
    manager = get_websocket_manager()
    manager.max_connections = 100
    manager.heartbeat_interval = 30
    manager.max_message_queue_size = 1000
    logger.info("WebSocket管理器初始化完成")
    return manager
