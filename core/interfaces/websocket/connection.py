#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""WebSocket 客户端连接数据模型"""

import time
from dataclasses import dataclass, field
from typing import List

import websockets

from core.contracts import ConnectionState


@dataclass
class ClientConnection:
    """客户端连接信息"""

    websocket: websockets.WebSocketServerProtocol
    user_id: str = "anonymous"
    platform: str = "unknown"
    ip: str = "unknown"
    state: ConnectionState = ConnectionState.CONNECTING
    last_heartbeat: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    ping_count: int = 0
    pong_count: int = 0
    connected_at: float = field(default_factory=time.time)
    message_count: int = 0
    # 性能监控字段
    message_processing_times: List[float] = field(default_factory=list)
    error_count: int = 0
    # 移动端重连相关字段
    reconnect_count: int = 0
    is_mobile: bool = False

    def __post_init__(self):
        if not self.is_mobile:
            self.is_mobile = self.platform.lower() in (
                "android",
                "ios",
                "capacitor",
                "mobile",
            )

    @property
    def is_reconnect(self) -> bool:
        return self.reconnect_count > 0

    def get_connection_duration(self) -> float:
        return time.time() - self.connected_at

    def update_heartbeat(self) -> None:
        self.last_heartbeat = time.time()

    def is_alive(self, timeout: float) -> bool:
        now = time.time()
        last = max(self.last_heartbeat, self.last_activity)
        return (now - last) < timeout

    def increment_ping(self) -> None:
        self.ping_count += 1

    def increment_message_count(self) -> None:
        self.message_count += 1
