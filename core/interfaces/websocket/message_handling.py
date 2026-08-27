#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""消息处理 Mixin

为 WebSocketManager 提供消息处理和事件总线路由能力。
包含请求去重（基于 request_id）和通过事件总线分发消息。
"""

from core.utils.logger import get_logger
import asyncio

import time
from typing import Any, Awaitable, Callable, Dict

import websockets

from core.api.contract import error_response
from core.api.error_response import APIError, map_exception_to_error_code
from core.core_engine.event_bus import EventTypes

logger = get_logger(__name__)


class MessageHandlingMixin:
    """消息处理相关方法"""

    async def register_message_handler(
        self,
        message_type: str,
        handler: Callable[
            ["websockets.WebSocketServerProtocol", Dict[str, Any]], Awaitable[Any]
        ],
        priority: int = 0,
    ):
        """
        通过事件总线注册消息处理器

        Args:
            message_type: 消息类型
            handler: 处理函数
            priority: 处理优先级（数字越小优先级越高）
        """

        # 创建一个包装器，将事件参数转换为处理器参数格式
        async def event_handler_wrapper(websocket=None, data=None, **kwargs):
            if websocket and data:
                return await handler(websocket, data)
            return None

        # 在事件总线上注册处理器
        await self.event_bus.subscribe(
            f"ws_message_{message_type}", event_handler_wrapper, priority
        )
        logger.info(f"通过事件总线注册了消息处理器: ws_message_{message_type}")

    async def handle_message(
        self, websocket: "websockets.WebSocketServerProtocol", data: Dict[str, Any]
    ):
        """
        优化的消息处理，增加并发控制、性能监控和请求去重

        Args:
            websocket: WebSocket连接
            data: 消息数据
        """
        # 记录消息接收日志
        request_id = data.get("request_id")
        message_type = data.get("type")
        logger.info(
            f"[WebSocket] 收到消息 - 类型: {message_type}, 请求ID: {request_id}"
        )

        # 检查连接是否仍然有效
        # 注意：send_to_client -> send_with_retry 会再次获取 connections_lock，
        # 因此重复消息确认的发送必须放到锁外，否则会自死锁。
        is_duplicate = False
        async with self.connections_lock:
            if websocket not in self.connections:
                logger.debug("Message received for closed connection")
                return
            connection = self.connections[websocket]

            # 检查请求ID，避免重复处理
            if request_id and request_id in self.processed_requests:
                timestamp = self.processed_requests[request_id]
                elapsed = time.time() - timestamp
                logger.info(
                    f"[WebSocket] 忽略重复消息 - 请求ID: {request_id}, "
                    f"时间差: {elapsed:.2f}秒"
                )
                # 刷新该请求的时间戳，延长其保留时间
                self.processed_requests.move_to_end(request_id)
                is_duplicate = True
            else:
                # 如果有请求ID，添加到已处理集合
                if request_id:
                    logger.info(
                        f"[WebSocket] 添加新请求到处理队列 - 请求ID: {request_id}, "
                        f"当前队列大小: {len(self.processed_requests)}"
                    )
                    self.processed_requests[request_id] = time.time()
                    # 限制已处理集合大小，避免内存泄漏
                    if len(self.processed_requests) > 1000:
                        oldest_key, oldest_time = self.processed_requests.popitem(
                            last=False
                        )
                        age = time.time() - oldest_time
                        logger.info(
                            f"[WebSocket] 移除过期请求ID: {oldest_key}, "
                            f"存在时间: {age:.2f}秒"
                        )

        # 在锁外发送重复消息确认给客户端，避免与 send_with_retry 死锁
        if is_duplicate:
            try:
                await self.send_to_client(
                    websocket,
                    {
                        "type": "duplicate_message",
                        "request_id": request_id,
                        "status": "ignored",
                    },
                )
            except Exception as e:
                logger.debug(f"发送重复消息确认失败: {e}")
            return

        # 记录消息开始处理时间
        start_time = time.time()
        message_type = data.get("type", "text")

        try:
            # 更新连接的消息计数和活动时间
            async with self.connections_lock:
                connection.increment_message_count()
                connection.last_activity = time.time()
                self.stats["messages_processed"] += 1

            # 处理心跳消息 - 优先处理，减少延迟
            if message_type == "ping" or data.get("text") == "__heartbeat__":
                await self.handle_heartbeat(websocket)
                return

            # 并发控制：限制同时处理的消息数量
            async with self.query_semaphore:
                # 通过事件总线处理消息
                event_name = f"ws_message_{message_type}"
                handler_start_time = time.time()

                event_data = {
                    "websocket": websocket,
                    "data": data,
                    "connection": connection,
                    "message_type": message_type,
                    "timestamp": time.time(),
                }

                try:
                    # 发布事件到事件总线
                    result = await self.event_bus.publish(event_name, **event_data)

                    # 如果没有处理者，发布到通用消息处理事件
                    if not result["results"]:
                        logger.warning(
                            f"No handler for message type: {message_type}, "
                            f"publishing to general event"
                        )
                        general_event_name = getattr(
                            EventTypes, "USER_MESSAGE", "user.message"
                        )
                        await self.event_bus.publish(
                            general_event_name,
                            websocket=websocket,
                            message=data,
                            message_type=message_type,
                        )
                except Exception as e:
                    logger.error(f"Error publishing event {event_name}: {e}")
                    raise

                # 记录处理时间
                process_time = time.time() - handler_start_time
                async with self.connections_lock:
                    if websocket in self.connections:
                        # 只保留最近100个处理时间记录
                        self.connections[websocket].message_processing_times.append(
                            process_time
                        )
                        if (
                            len(self.connections[websocket].message_processing_times)
                            > 100
                        ):
                            self.connections[websocket].message_processing_times.pop(0)

        except Exception as e:
            logger.error(
                f"Error handling {message_type} message: {e}", exc_info=True
            )

            # 更新错误统计
            async with self.connections_lock:
                if websocket in self.connections:
                    self.connections[websocket].error_count += 1
                self.stats["errors"] += 1

            # 尝试发送错误响应，但不阻塞主流程
            try:
                request_id = None
                try:
                    request_id = data.get("request_id")
                except Exception:
                    request_id = None

                err_code = map_exception_to_error_code(e)
                err_msg = "处理消息时发生错误"
                err_details: Dict[str, Any] = {
                    "error_type": type(e).__name__,
                    "message_type": message_type,
                }
                if isinstance(e, APIError):
                    err_msg = e.message
                    try:
                        if isinstance(e.details, dict):
                            err_details.update(e.details)
                    except Exception:
                        pass

                payload = error_response(
                    err_code,
                    message=err_msg,
                    request_id=request_id,
                    details=err_details,
                )
                payload.update(
                    {
                        "type": "error",
                        "timestamp": time.time(),
                        "message_type": message_type,
                    }
                )
                await asyncio.shield(
                    self.send_to_client(
                        websocket,
                        payload,
                    )
                )
            except Exception:
                pass
            finally:
                total_process_time = time.time() - start_time
                if total_process_time > 5.0:
                    logger.info(
                        f"Slow message processing: {message_type}, "
                        f"time: {total_process_time:.3f}s"
                    )
