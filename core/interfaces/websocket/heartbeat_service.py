#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""心跳检测 Mixin

为 WebSocketManager 提供心跳检查器和 ping 发送能力。
心跳检查器定期扫描所有连接，清理已断开/超时的连接，
对活跃连接发送应用层 ping 以维持连接活性。
"""

from core.utils.logger import get_logger
import asyncio
import json

import time

import websockets

from core.contracts import ConnectionState

logger = get_logger(__name__)


class HeartbeatMixin:
    """心跳检测相关方法"""

    async def handle_heartbeat(self, websocket: "websockets.WebSocketServerProtocol"):
        """
        处理心跳响应

        Args:
            websocket: WebSocket连接
        """
        # 注意：send_to_client -> send_with_retry 会再次获取 connections_lock，
        # 因此发送动作必须放到锁外，否则会自死锁。
        should_send_pong = False
        async with self.connections_lock:
            if websocket in self.connections:
                connection = self.connections[websocket]
                connection.update_heartbeat()
                logger.debug(
                    f"Heartbeat received from {connection.ip}, "
                    f"User: {connection.user_id}"
                )
                should_send_pong = True

        if should_send_pong:
            try:
                await self.send_to_client(
                    websocket, {"type": "pong", "timestamp": time.time()}
                )
            except Exception as e:
                logger.debug(f"发送心跳响应失败: {e}")

    async def _send_ping_with_semaphore(
        self,
        websocket: "websockets.WebSocketServerProtocol",
        semaphore: asyncio.Semaphore,
    ):
        """
        使用信号量控制的ping发送方法

        Args:
            websocket: WebSocket连接对象
            semaphore: 用于控制并发的信号量
        """
        async with semaphore:
            await self.send_ping(websocket)

    async def send_ping(self, websocket: "websockets.WebSocketServerProtocol"):
        """
        优化的ping消息发送，增加超时控制和重试机制

        Args:
            websocket: WebSocket连接
        """
        async with self.connections_lock:
            if websocket not in self.connections:
                return

            connection = self.connections[websocket]
            # 再次检查状态，确保连接仍然有效
            if connection.state != ConnectionState.CONNECTED or (
                hasattr(websocket, "closed") and websocket.closed
            ) or self._is_starlette_websocket_closed(websocket):
                return

            connection.increment_ping()
            ping_time = time.time()

        try:
            ping_data = json.dumps(
                {
                    "type": "ping",
                    "timestamp": ping_time,
                    "ping_id": f"{id(websocket)}-{ping_time}",
                }
            )
            # FastAPI/Starlette WebSocket 用 send_text，websockets 库用 send
            if hasattr(websocket, "send_text"):
                await asyncio.wait_for(websocket.send_text(ping_data), timeout=5.0)
            else:
                await asyncio.wait_for(websocket.send(ping_data), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning(f"Ping send timeout to {connection.ip}")
            async with self.connections_lock:
                if websocket in self.connections:
                    self.connections[websocket].last_heartbeat = 0
        except Exception as e:
            logger.warning(f"Failed to send ping to {connection.ip}: {e}")
            async with self.connections_lock:
                if websocket in self.connections:
                    self.connections[websocket].last_heartbeat = 0

    async def heartbeat_checker(self):
        """优化的心跳检查器，增加连接监控和资源回收"""
        last_stats_time = time.time()
        stats_interval = 60  # 每分钟打印一次统计信息
        ping_task_semaphore = asyncio.Semaphore(10)  # 最多同时进行10个ping操作

        while self.running:
            try:
                current_time = time.time()
                to_close = []

                async with self.connections_lock:
                    for websocket, connection in list(self.connections.items()):
                        # 检查连接是否已关闭但未从管理器中移除
                        if (
                            hasattr(websocket, "closed") and websocket.closed
                        ) or self._is_starlette_websocket_closed(websocket):
                            to_close.append((websocket, connection))
                            logger.debug(
                                f"Found closed connection: {connection.ip}, "
                                f"User: {connection.user_id}"
                            )
                            continue

                        # 检查是否超时
                        if not connection.is_alive(self.heartbeat_timeout):
                            to_close.append((websocket, connection))
                            if (
                                current_time - connection.last_heartbeat
                                >= self.heartbeat_timeout
                            ):
                                logger.info(
                                    f"Heartbeat timed out: {connection.ip}, "
                                    f"User: {connection.user_id}, "
                                    f"Last heartbeat: "
                                    f"{current_time - connection.last_heartbeat:.2f}s ago"
                                )
                            else:
                                logger.info(
                                    f"Activity timed out: {connection.ip}, "
                                    f"User: {connection.user_id}, "
                                    f"Last activity: "
                                    f"{current_time - connection.last_activity:.2f}s ago"
                                )
                            self.stats["heartbeat_failures"] += 1

                        # 对于活跃的连接，发送ping
                        elif connection.state == ConnectionState.CONNECTED:
                            next_ping_time = (
                                connection.last_heartbeat + self.heartbeat_interval
                            )
                            if current_time >= next_ping_time:
                                asyncio.create_task(
                                    self._send_ping_with_semaphore(
                                        websocket, ping_task_semaphore
                                    )
                                )

                # 关闭超时连接
                for websocket, connection in to_close:
                    try:
                        await websocket.close(
                            code=1001, reason="Connection timed out"
                        )
                    except Exception as e:
                        logger.debug(f"Error closing timed-out connection: {e}")
                    finally:
                        try:
                            await self.remove_connection(websocket)
                        except Exception:
                            pass

                # 定期打印统计信息
                if current_time - last_stats_time >= stats_interval:
                    stats = self.get_stats()
                    logger.info(
                        f"WebSocket Statistics: Active: {stats['active_connections']}, "
                        f"Total: {stats['total_connections']}, "
                        f"Messages: {stats['messages_processed']}, "
                        f"Errors: {stats['errors']}"
                    )
                    last_stats_time = current_time

                # 动态调整检查间隔，连接数越少，间隔越长
                check_interval = min(self.heartbeat_interval / 2, 5.0)
                active_count = len(self.connections)
                if active_count < 10:
                    check_interval = min(check_interval * 1.5, 10.0)
                await asyncio.sleep(check_interval)

            except Exception as e:
                logger.error(f"Error in heartbeat checker: {e}", exc_info=True)
                await asyncio.sleep(5.0)
