#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""消息发送 Mixin

为 WebSocketManager 提供带重试的消息发送、单点发送和广播能力。
所有发送动作在锁外执行，避免与 connections_lock 重入死锁。
"""

from core.utils.logger import get_logger
import asyncio
import json
import logging
import random
from typing import Any, Dict, Optional

import websockets
import websockets.exceptions  # websockets>=11 需显式导入，否则 websockets.exceptions 属性访问会 AttributeError
from starlette.websockets import WebSocketDisconnect

from core.contracts import ConnectionState

logger = get_logger(__name__)


def get_qq_target_role_id(data: Dict[str, Any]) -> str:
    """从主动消息中提取目标 QQ 角色 ID。"""
    if str(data.get("client_type") or "").strip().lower() != "qq":
        return ""
    explicit_role = str(data.get("target_role_id") or "").strip().lower()
    if explicit_role:
        return explicit_role
    conversation_id = str(data.get("conversation_id") or "").strip().lower()
    if "__persona__" not in conversation_id:
        return ""
    persona_suffix = conversation_id.split("__persona__", 1)[1]
    if persona_suffix.startswith("core_"):
        persona_suffix = persona_suffix[len("core_") :]
    return persona_suffix.split("_", 1)[0].strip()


def qq_connection_accepts_message(connection_or_websocket: Any, data: Dict[str, Any]) -> bool:
    """判断一个 QQ WebSocket 是否属于主动消息指定的角色。

    旧客户端没有 client_id 时保留兼容广播；新版双 QQ 连接使用
    qq_{role_id}_{session_id}，必须只让目标角色连接接收或重放消息。
    """
    target_role_id = get_qq_target_role_id(data)
    if not target_role_id:
        return True

    websocket = getattr(connection_or_websocket, "websocket", connection_or_websocket)
    client_id = str(
        getattr(connection_or_websocket, "client_id", "")
        or getattr(websocket, "client_id", "")
        or ""
    ).strip().lower()
    if not client_id:
        return True
    return client_id == f"qq_{target_role_id}" or client_id.startswith(
        f"qq_{target_role_id}_"
    )


class MessageSendingMixin:
    """消息发送相关方法"""

    def _is_disconnect_exception(self, error: Exception) -> bool:
        """判断异常是否表示连接已断开"""
        if isinstance(
            error,
            (
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.ConnectionClosedOK,
                WebSocketDisconnect,
            ),
        ):
            return True
        if error.__class__.__name__ == "ClientDisconnected":
            return True
        error_message = str(error).lower()
        disconnect_signals = (
            "keepalive ping timeout",
            "no close frame received",
            "close message has been sent",
            "connection closed",
            "client disconnected",
            # Starlette/uvicorn 在连接已关闭（close 已发送或响应已完成）后
            # 再调用 send 会抛该 RuntimeError，属于连接断开，不应重试
            "unexpected asgi message",
            "after sending 'websocket.close'",
            "response already completed",
        )
        return any(signal in error_message for signal in disconnect_signals)

    async def send_with_retry(
        self,
        websocket: "websockets.WebSocketServerProtocol",
        message: str,
        max_retries: int = 3,
        retry_delay: float = 0.2,
        send_timeout: float = 5.0,
    ) -> bool:
        """
        带重试机制的消息发送函数

        Args:
            websocket: WebSocket连接
            message: 要发送的消息
            max_retries: 最大重试次数
            retry_delay: 初始重试延迟
            send_timeout: 发送超时时间

        Returns:
            是否发送成功
        """
        # 验证输入
        if not websocket or not message:
            logger.error("Invalid websocket or message parameter")
            return False

        # 检查连接状态
        if (
            hasattr(websocket, "closed") and websocket.closed
        ) or self._is_starlette_websocket_closed(websocket):
            logger.warning("Connection closed, skipping sending")
            await self.remove_connection(websocket)
            return False
        async with self.connections_lock:
            connection = self.connections.get(websocket)
            if connection and connection.state in (
                ConnectionState.CLOSING,
                ConnectionState.CLOSED,
            ):
                logger.warning("Connection closing or closed, skipping sending")
                return False

        retries = 0
        while retries <= max_retries:
            try:
                # 检测 WebSocket 类型并使用相应的发送方法
                # FastAPI WebSocket 使用 send_json/send_text
                # websockets 库使用 send
                if hasattr(websocket, "send_text"):
                    await asyncio.wait_for(
                        websocket.send_text(message),
                        timeout=send_timeout,
                    )
                else:
                    await asyncio.wait_for(
                        websocket.send(message),
                        timeout=send_timeout,
                    )
                return True
            except (
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.ConnectionClosedOK,
            ) as conn_err:
                logger.warning(f"Connection closed during send: {conn_err}")
                await self.remove_connection(websocket)
                return False
            except WebSocketDisconnect as disconnect_err:
                logger.info(f"Client disconnected during send: {disconnect_err}")
                await self.remove_connection(websocket)
                return False
            except RuntimeError as runtime_err:
                if self._is_disconnect_exception(runtime_err):
                    logger.warning(f"Connection closed during send: {runtime_err}")
                    await self.remove_connection(websocket)
                    return False
                logger.error(f"Failed to send message: {runtime_err}", exc_info=True)
            except asyncio.TimeoutError:
                logger.warning(
                    f"Message send timeout ({send_timeout}s), "
                    f"retrying ({retries}/{max_retries})"
                )
            except Exception as e:
                if self._is_disconnect_exception(e):
                    logger.info(f"Connection disconnected during send: {e}")
                    await self.remove_connection(websocket)
                    return False
                logger.error(f"Failed to send message: {e}", exc_info=True)

            retries += 1
            if retries > max_retries:
                logger.error(f"Failed to send message after {max_retries} retries")
                try:
                    await self.remove_connection(websocket)
                except Exception:
                    pass
                return False

            # 指数退避算法，增加抖动以避免惊群效应
            backoff = retry_delay * (1.5 ** (retries - 1))
            # 双向抖动：[-50%, +50%] 区间，确保退避间隔随机分散
            jitter = backoff * (random.random() - 0.5)
            await asyncio.sleep(backoff + jitter)

        return False

    async def send_to_client(
        self, websocket: "websockets.WebSocketServerProtocol", data: Dict[str, Any]
    ) -> bool:
        """
        发送消息给指定客户端

        Args:
            websocket: 目标WebSocket连接
            data: 要发送的数据

        Returns:
            是否发送成功
        """
        request_id = data.get("request_id", "unknown")
        message_type = data.get("type", "unknown")

        # 心跳消息使用 DEBUG 级别，避免日志刷屏
        is_heartbeat = message_type in ("pong", "ping")
        log_level = logging.DEBUG if is_heartbeat else logging.INFO

        logger.log(
            log_level,
            f"[WebSocket] 准备发送消息 - 类型: {message_type}, 请求ID: {request_id}"
        )

        try:
            message = json.dumps(data, ensure_ascii=False)
            result = await self.send_with_retry(websocket, message)
            logger.log(
                log_level,
                f"[WebSocket] 消息发送完成 - 类型: {message_type}, "
                f"请求ID: {request_id}, 状态: {'成功' if result else '失败'}"
            )
            return result
        except Exception as e:
            logger.error(
                f"[WebSocket] 格式化消息失败 - 请求ID: {request_id}, 错误: {e}"
            )
            async with self.connections_lock:
                self.stats["errors"] += 1
            return False

    async def broadcast(
        self,
        data: Dict[str, Any],
        exclude_client: Optional["websockets.WebSocketServerProtocol"] = None,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        广播消息给所有客户端或指定用户的所有客户端

        Args:
            data: 要广播的数据
            exclude_client: 排除的客户端
            user_id: 如果指定，只广播给该用户的所有客户端
        """
        request_id = data.get("request_id", "unknown")
        message_type = data.get("type", "unknown")

        if user_id:
            logger.debug(
                f"[WebSocket] 开始广播消息给特定用户 - 用户ID: {user_id}, "
                f"消息类型: {message_type}, 请求ID: {request_id}"
            )
        else:
            logger.debug(
                f"[WebSocket] 开始广播消息给所有用户 - "
                f"消息类型: {message_type}, 请求ID: {request_id}"
            )

        # 在锁内只做连接快照，避免发送路径重入锁导致阻塞
        async with self.connections_lock:
            if user_id:
                if user_id in self.user_connections:
                    target_connections = [
                        conn
                        for conn in self.user_connections[user_id]
                        if conn.websocket != exclude_client
                    ]
                else:
                    target_connections = []
            else:
                target_connections = [
                    conn
                    for conn in self.connections.values()
                    if conn.websocket != exclude_client
                ]

        # 双 QQ 的多个角色共用同一个主人 user_id。主动消息若广播给所有角色，
        # 非目标角色会在客户端忽略它，而服务端仍可能误判为已送达。
        # 只要连接带可识别 client_id，就严格选择目标角色；目标角色离线时
        # 让消息进入真实主人 ID 的离线队列，等待对应角色重连。
        target_role_id = get_qq_target_role_id(data)
        if target_role_id and target_connections:
            identifiable_connections = [
                conn
                for conn in target_connections
                if str(
                    getattr(conn, "client_id", "")
                    or getattr(conn.websocket, "client_id", "")
                    or ""
                ).strip()
            ]
            if identifiable_connections:
                target_connections = [
                    conn
                    for conn in target_connections
                    if qq_connection_accepts_message(conn, data)
                ]
                logger.debug(
                    "[WebSocket] QQ 角色定向广播: role=%s, connections=%d, request_id=%s",
                    target_role_id,
                    len(target_connections),
                    request_id,
                )

        logger.debug(
            f"[WebSocket] 广播目标连接数: {len(target_connections)}, "
            f"请求ID: {request_id}"
        )

        if not target_connections:
            if user_id:
                logger.info(
                    f"[WebSocket] User {user_id} offline, storing message in queue "
                    f"for later delivery - 请求ID: {request_id}"
                )
                self.store_offline_message(user_id, data)
                return True
            else:
                logger.debug(
                    f"[WebSocket] 没有找到符合条件的目标连接，取消广播 - 请求ID: {request_id}"
                )
            return False

        message = json.dumps(data, ensure_ascii=False)
        send_tasks = []
        for connection in target_connections:
            if connection.state == ConnectionState.CONNECTED:
                send_tasks.append(self.send_with_retry(connection.websocket, message))

        if send_tasks:
            logger.debug(
                f"[WebSocket] 开始并行发送广播消息 - 请求ID: {request_id}, "
                f"任务数: {len(send_tasks)}"
            )
            results = await asyncio.gather(*send_tasks, return_exceptions=True)

            failed_count = sum(1 for r in results if isinstance(r, Exception) or not r)
            success_count = len(results) - failed_count

            if failed_count > 0:
                logger.warning(
                    f"[WebSocket] 部分广播消息发送失败 - 请求ID: {request_id}, "
                    f"成功: {success_count}, 失败: {failed_count}"
                )
                if user_id and success_count == 0:
                    self.store_offline_message(user_id, data)
                    logger.info(
                        f"[WebSocket] 用户 {user_id} 广播全部失败，消息已写入离线队列，"
                        f"等待重连后送达 - 请求ID: {request_id}"
                    )
                    return True
            else:
                logger.debug(
                    f"[WebSocket] 所有广播消息发送成功 - 请求ID: {request_id}, "
                    f"数量: {success_count}"
                )
            return success_count > 0

        if user_id:
            self.store_offline_message(user_id, data)
            logger.info(
                f"[WebSocket] 用户 {user_id} 没有可发送的已连接客户端，消息已写入离线队列，"
                f"等待重连后送达 - 请求ID: {request_id}"
            )
            return True
        return False
