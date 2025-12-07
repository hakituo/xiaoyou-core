#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
增强型WebSocket连接管理器
提供更稳定、更高效的WebSocket连接管理、心跳机制和消息处理
"""

import asyncio
import websockets
import json
import time
import logging
import sys
from collections import defaultdict, OrderedDict
from typing import Dict, Set, Optional, Any, List, Callable, Tuple, Awaitable
from dataclasses import dataclass, field
from enum import Enum, auto

# Set up event loop policy for Windows at the module level
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 导入配置
from config import config, get_settings
# 导入事件总线
from core.core_engine.event_bus import get_event_bus, EventTypes

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """连接状态枚举"""

    CONNECTING = auto()
    CONNECTED = auto()
    CLOSING = auto()
    CLOSED = auto()


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
    # 新增：性能监控字段
    message_processing_times: List[float] = field(default_factory=list)
    error_count: int = 0

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
class WebSocketManager:
    """
    增强型WebSocket连接管理器
    集成EventBus用于模块间解耦通信
    """

    def __init__(self):
        # 配置参数
        # 从统一配置系统获取WebSocket相关配置
        # 使用try-except处理配置访问，支持Pydantic模型访问方式
        try:
            settings = get_settings()
            # 尝试从嵌套结构访问配置，如果不存在则使用默认值
            if hasattr(settings, 'app') and hasattr(settings.app, 'websocket'):
                self.max_connections = getattr(settings.app.websocket, 'max_connections', 50)
                self.heartbeat_interval = getattr(settings.app.websocket, 'heartbeat_interval', 30)
                self.heartbeat_timeout = getattr(settings.app.websocket, 'timeout', 60)
                self.max_concurrent_queries = getattr(settings.app.websocket, 'max_concurrent_queries', 10)
            else:
                # 使用默认值
                self.max_connections = 50
                self.heartbeat_interval = 30
                self.heartbeat_timeout = 60
                self.max_concurrent_queries = 5
        except Exception as e:
            # 如果配置访问出错，使用默认值
            logging.warning(f"无法访问WebSocket配置，使用默认值: {e}")
            self.max_connections = 10
            self.heartbeat_interval = 30
            self.heartbeat_timeout = 60
            self.max_concurrent_queries = 5

        # 连接管理
        self.connections: Dict[websockets.WebSocketServerProtocol, ClientConnection] = (
            {}
        )
        self.connections_lock = asyncio.Lock()  # 使用普通锁保护连接集合
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
        
        # 存储已处理的消息请求ID，防止重复处理，使用OrderedDict实现FIFO
        self.processed_requests = OrderedDict()

    async def add_connection(
        self,
        websocket: websockets.WebSocketServerProtocol,
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
            if websocket.remote_address:
                client_ip = websocket.remote_address[0]

            # 统计此IP的连接数
            ip_connections = sum(
                1 for conn in self.connections.values() if conn.ip == client_ip
            )
            # 设置每个IP的最大连接数
            try:
                settings = get_settings()
                if hasattr(settings, 'app') and hasattr(settings.app, 'websocket'):
                    max_per_ip = getattr(settings.app.websocket, 'max_connections_per_ip', 20)
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
                    f"IP connection limit reached: {client_ip} has {ip_connections} connections"
                )
                return False

            # 检查连接是否已经存在（避免重复添加）
            if websocket in self.connections:
                logger.warning(f"Connection already exists: {client_ip}")
                return False

            # 创建连接信息对象
            connection = ClientConnection(
                websocket=websocket,
                user_id=user_id,
                platform=platform,
                ip=client_ip,
                state=ConnectionState.CONNECTED,
            )

            # 添加到连接管理
            self.connections[websocket] = connection
            self.user_connections[user_id].append(connection)

            # 更新统计信息
            self.stats["total_connections"] += 1
            self.stats["active_connections"] = len(self.connections)

            logger.info(
                f"New client connected: {client_ip}, User: {user_id}, "
                f"Platform: {platform}, Connections: {len(self.connections)}/{self.max_connections}, "
                f"IP connections: {ip_connections + 1}/{max_per_ip}"
            )

            return True

    async def remove_connection(self, websocket: websockets.WebSocketServerProtocol):
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

                # 移除连接
                del self.connections[websocket]

                # 更新统计信息
                self.stats["active_connections"] = len(self.connections)

                logger.info(
                    f"Client disconnected: {connection.ip}, User: {connection.user_id}, "
                    f"Platform: {connection.platform}, Duration: {connection.get_connection_duration():.2f}s, "
                    f"Messages: {connection.message_count}"
                )

    async def send_with_retry(
        self,
        websocket: websockets.WebSocketServerProtocol,
        message: str,
        max_retries: int = 3,
        retry_delay: float = 0.2,
    ) -> bool:
        """
        带重试机制的消息发送函数

        Args:
            websocket: WebSocket连接
            message: 要发送的消息
            max_retries: 最大重试次数
            retry_delay: 初始重试延迟

        Returns:
            是否发送成功
        """
        # 验证输入
        if not websocket or not message:
            logger.error("Invalid websocket or message parameter")
            return False

        # 检查连接状态
        if hasattr(websocket, "closed") and websocket.closed:
            logger.warning("Connection closed, skipping sending")
            await self.remove_connection(websocket)
            return False

        retries = 0
        while retries <= max_retries:
            try:
                # 使用shield防止取消操作影响发送
                await asyncio.shield(websocket.send(message))
                return True
            except (
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.ConnectionClosedOK,
            ) as conn_err:
                # 连接已关闭，停止重试
                logger.warning(f"Connection closed during send: {conn_err}")
                await self.remove_connection(websocket)
                return False
            except asyncio.TimeoutError:
                # 超时错误，记录并重试
                logger.warning(
                    f"Message send timeout, retrying ({retries}/{max_retries})"
                )
            except Exception as e:
                logger.error(f"Failed to send message: {e}")

            retries += 1
            if retries > max_retries:
                logger.error(f"Failed to send message after {max_retries} retries")
                return False

            # 指数退避算法，增加抖动以避免惊群效应
            backoff = retry_delay * (1.5 ** (retries - 1))
            jitter = (
                backoff * 0.1 * (1 - 2 * asyncio.get_event_loop().time() % 1)
            )  # 随机抖动
            await asyncio.sleep(backoff + jitter)

        return False

    async def send_to_client(
        self, websocket: websockets.WebSocketServerProtocol, data: Dict[str, Any]
    ) -> bool:
        """
        发送消息给指定客户端

        Args:
            websocket: 目标WebSocket连接
            data: 要发送的数据

        Returns:
            是否发送成功
        """
        # 提取消息中的请求ID用于日志记录
        request_id = data.get('request_id', 'unknown')
        message_type = data.get('type', 'unknown')
        logger.info(f"[WebSocket] 准备发送消息 - 类型: {message_type}, 请求ID: {request_id}")
        
        try:
            message = json.dumps(data, ensure_ascii=False)
            result = await self.send_with_retry(websocket, message)
            logger.info(f"[WebSocket] 消息发送完成 - 类型: {message_type}, 请求ID: {request_id}, 状态: {'成功' if result else '失败'}")
            return result
        except Exception as e:
            logger.error(f"[WebSocket] 格式化消息失败 - 请求ID: {request_id}, 错误: {e}")
            async with self.connections_lock:
                self.stats["errors"] += 1
            return False

    async def broadcast(
        self,
        data: Dict[str, Any],
        exclude_client: Optional[websockets.WebSocketServerProtocol] = None,
        user_id: Optional[str] = None,
    ):
        """
        广播消息给所有客户端或指定用户的所有客户端

        Args:
            data: 要广播的数据
            exclude_client: 排除的客户端
            user_id: 如果指定，只广播给该用户的所有客户端
        """
        # 提取消息中的请求ID和类型用于日志记录
        request_id = data.get('request_id', 'unknown')
        message_type = data.get('type', 'unknown')
        
        # 获取目标连接
        if user_id:
            logger.info(f"[WebSocket] 开始广播消息给特定用户 - 用户ID: {user_id}, 消息类型: {message_type}, 请求ID: {request_id}")
        else:
            logger.info(f"[WebSocket] 开始广播消息给所有用户 - 消息类型: {message_type}, 请求ID: {request_id}")
        
        async with self.connections_lock:
            # 确定要广播的目标连接
            target_connections = []

            if user_id and user_id in self.user_connections:
                # 只广播给指定用户
                target_connections = [
                    conn
                    for conn in self.user_connections[user_id]
                    if conn.websocket != exclude_client
                ]
            else:
                # 广播给所有客户端（排除指定客户端）
                target_connections = [
                    conn
                    for conn in self.connections.values()
                    if conn.websocket != exclude_client
                ]

            logger.info(f"[WebSocket] 广播目标连接数: {len(target_connections)}, 请求ID: {request_id}")
            
            if not target_connections:
                logger.info(f"[WebSocket] 没有找到符合条件的目标连接，取消广播 - 请求ID: {request_id}")
                return

            # 准备消息
            message = json.dumps(data, ensure_ascii=False)

            # 创建发送任务列表
            send_tasks = []
            for connection in target_connections:
                if connection.state == ConnectionState.CONNECTED:
                    send_tasks.append(
                        self.send_with_retry(connection.websocket, message)
                    )

            # 并行发送所有消息
            if send_tasks:
                logger.info(f"[WebSocket] 开始并行发送广播消息 - 请求ID: {request_id}, 任务数: {len(send_tasks)}")
                results = await asyncio.gather(*send_tasks, return_exceptions=True)

                # 处理失败的发送
                failed_count = sum(
                    1 for r in results if isinstance(r, Exception) or not r
                )
                success_count = len(results) - failed_count
                
                if failed_count > 0:
                    logger.warning(
                        f"[WebSocket] 部分广播消息发送失败 - 请求ID: {request_id}, 成功: {success_count}, 失败: {failed_count}"
                    )
                else:
                    logger.info(
                        f"[WebSocket] 所有广播消息发送成功 - 请求ID: {request_id}, 数量: {success_count}"
                    )

    async def handle_heartbeat(self, websocket: websockets.WebSocketServerProtocol):
        """
        处理心跳响应

        Args:
            websocket: WebSocket连接
        """
        async with self.connections_lock:
            if websocket in self.connections:
                connection = self.connections[websocket]
                connection.update_heartbeat()
                logger.debug(
                    f"Heartbeat received from {connection.ip}, User: {connection.user_id}"
                )

                # 发送心跳响应
                await self.send_to_client(
                    websocket, {"type": "pong", "timestamp": time.time()}
                )

    async def _send_ping_with_semaphore(
        self,
        websocket: websockets.WebSocketServerProtocol,
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

    async def send_ping(self, websocket: websockets.WebSocketServerProtocol):
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
            ):
                return

            connection.increment_ping()
            ping_time = time.time()

        try:
            # 使用超时控制发送ping，避免长时间阻塞
            ping_data = json.dumps(
                {
                    "type": "ping",
                    "timestamp": ping_time,
                    "ping_id": f"{id(websocket)}-{ping_time}",  # 添加唯一ID便于跟踪
                }
            )

            # 设置5秒超时
            await asyncio.wait_for(websocket.send(ping_data), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning(f"Ping send timeout to {connection.ip}")
            # 超时也标记为可能断开的连接
            async with self.connections_lock:
                if websocket in self.connections:
                    self.connections[websocket].last_heartbeat = 0  # 强制超时
        except Exception as e:
            logger.warning(f"Failed to send ping to {connection.ip}: {e}")
            # 标记为可能断开的连接
            async with self.connections_lock:
                if websocket in self.connections:
                    self.connections[websocket].last_heartbeat = 0  # 强制超时

    async def heartbeat_checker(self):
        """优化的心跳检查器，增加连接监控和资源回收"""
        # 统计信息收集
        last_stats_time = time.time()
        stats_interval = 60  # 每分钟打印一次统计信息

        # 控制并发任务数量，避免创建过多任务
        ping_task_semaphore = asyncio.Semaphore(10)  # 最多同时进行10个ping操作

        while self.running:
            try:
                current_time = time.time()
                to_close = []

                async with self.connections_lock:
                    # 检查所有连接的状态
                    for websocket, connection in list(self.connections.items()):
                        # 检查连接是否已关闭但未从管理器中移除
                        if hasattr(websocket, "closed") and websocket.closed:
                            to_close.append((websocket, connection))
                            logger.debug(
                                f"Found closed connection: {connection.ip}, User: {connection.user_id}"
                            )
                            continue

                        # 检查是否超时
                        if not connection.is_alive(self.heartbeat_timeout):
                            to_close.append((websocket, connection))
                            # 区分心跳超时和活动超时
                            if (
                                current_time - connection.last_heartbeat
                                >= self.heartbeat_timeout
                            ):
                                logger.info(
                                    f"Heartbeat timed out: {connection.ip}, User: {connection.user_id}, "
                                    f"Last heartbeat: {current_time - connection.last_heartbeat:.2f}s ago"
                                )
                            else:
                                logger.info(
                                    f"Activity timed out: {connection.ip}, User: {connection.user_id}, "
                                    f"Last activity: {current_time - connection.last_activity:.2f}s ago"
                                )
                            self.stats["heartbeat_failures"] += 1

                        # 对于活跃的连接，发送ping
                        elif connection.state == ConnectionState.CONNECTED:
                            # 只在需要时发送ping（避免频繁发送）
                            next_ping_time = (
                                connection.last_heartbeat + self.heartbeat_interval
                            )
                            if current_time >= next_ping_time:
                                # 使用信号量控制并发ping任务数量
                                asyncio.create_task(
                                    self._send_ping_with_semaphore(
                                        websocket, ping_task_semaphore
                                    )
                                )

                # 关闭超时连接
                for websocket, connection in to_close:
                    try:
                        # 使用标准的连接关闭代码
                        await websocket.close(code=1001, reason="Connection timed out")
                    except Exception as e:
                        # 连接可能已经关闭，忽略错误
                        logger.debug(f"Error closing timed-out connection: {e}")
                    finally:
                        try:
                            await self.remove_connection(websocket)
                        except Exception:
                            # 忽略移除过程中的错误
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

                # 等待一段时间后再次检查
                # 动态调整检查间隔，连接数越少，间隔越长
                check_interval = min(self.heartbeat_interval / 2, 5.0)
                active_count = len(self.connections)
                if active_count < 10:
                    check_interval = min(check_interval * 1.5, 10.0)
                await asyncio.sleep(check_interval)

            except Exception as e:
                logger.error(f"Error in heartbeat checker: {e}", exc_info=True)
                # 出错后等待一段时间再继续
                await asyncio.sleep(5.0)
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
        return dict(self.stats)
    async def _cleanup_stale_connections(self):
        """
        清理可能已经断开但未正确关闭的连接
        
        此方法检查所有连接的状态，如果发现连接已关闭但仍在管理器中，
        则将其从管理器中移除并清理相关资源。
        """
        async with self.connections_lock:
            for websocket in list(self.connections.keys()):
                try:
                    # 检查连接是否真的仍然可用
                    if hasattr(websocket, "closed") and websocket.closed:
                        await self.remove_connection(websocket)
                except Exception as e:
                    logger.debug(f"Error checking connection state: {e}")
                    await self.remove_connection(websocket)

    async def register_message_handler(
        self,
        message_type: str,
        handler: Callable[
            [websockets.WebSocketServerProtocol, Dict[str, Any]], Awaitable[Any]
        ],
        priority: int = 0
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
        await self.event_bus.subscribe(f"ws_message_{message_type}", event_handler_wrapper, priority)
        logger.info(f"通过事件总线注册了消息处理器: ws_message_{message_type}")

    async def handle_message(
        self, websocket: websockets.WebSocketServerProtocol, data: Dict[str, Any]
    ):
        """
        优化的消息处理，增加并发控制、性能监控和请求去重

        Args:
            websocket: WebSocket连接
            data: 消息数据
        """
        # 记录消息接收日志
        request_id = data.get('request_id')
        message_type = data.get('type')
        logger.info(f"[WebSocket] 收到消息 - 类型: {message_type}, 请求ID: {request_id}")
        
        # 检查连接是否仍然有效
        async with self.connections_lock:
            if websocket not in self.connections:
                logger.debug("Message received for closed connection")
                return
            connection = self.connections[websocket]
            
            # 检查请求ID，避免重复处理
            if request_id and request_id in self.processed_requests:
                timestamp = self.processed_requests[request_id]
                elapsed = time.time() - timestamp
                logger.info(f"[WebSocket] 忽略重复消息 - 请求ID: {request_id}, 时间差: {elapsed:.2f}秒")
                # 刷新该请求的时间戳，延长其保留时间
                self.processed_requests.move_to_end(request_id)
                # 发送重复消息确认给客户端
                await self.send_to_client(
                    websocket,
                    {
                        "type": "duplicate_message",
                        "request_id": request_id,
                        "status": "ignored"
                    }
                )
                return
            
            # 如果有请求ID，添加到已处理集合
            if request_id:
                logger.info(f"[WebSocket] 添加新请求到处理队列 - 请求ID: {request_id}, 当前队列大小: {len(self.processed_requests)}")
                self.processed_requests[request_id] = time.time()  # 存储时间戳便于调试
                # 限制已处理集合大小，避免内存泄漏
                if len(self.processed_requests) > 1000:
                    oldest_key, oldest_time = self.processed_requests.popitem(last=False)  # FIFO移除第一个元素
                    age = time.time() - oldest_time
                    logger.info(f"[WebSocket] 移除过期请求ID: {oldest_key}, 存在时间: {age:.2f}秒")

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
                
                # 记录消息处理的开始时间
                handler_start_time = time.time()
                
                # 构建事件数据
                event_data = {
                    'websocket': websocket,
                    'data': data,
                    'connection': connection,
                    'message_type': message_type,
                    'timestamp': time.time()
                }
                
                try:
                    # 发布事件到事件总线
                    result = await self.event_bus.publish(event_name, **event_data)
                    
                    # 如果没有处理者，发布到通用消息处理事件
                    if not result['results']:
                        logger.warning(
                            f"No handler for message type: {message_type}, publishing to general event"
                        )
                        # 发布到通用消息事件
                        general_result = await self.event_bus.publish(
                            EventTypes.USER_MESSAGE,
                            websocket=websocket,
                            message=data,
                            message_type=message_type
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
                            len(
                                self.connections[websocket].message_processing_times
                            )
                            > 100
                        ):
                            self.connections[
                                websocket
                            ].message_processing_times.pop(0)

        except Exception as e:
            logger.error(f"Error handling {message_type} message: {e}", exc_info=True)

            # 更新错误统计
            async with self.connections_lock:
                if websocket in self.connections:
                    self.connections[websocket].error_count += 1
                self.stats["errors"] += 1

            # 尝试发送错误响应，但不阻塞主流程
        try:
            await asyncio.shield(
                self.send_to_client(
                    websocket,
                    {
                        "type": "error",
                        "message": "处理消息时发生错误",
                        "error_type": type(e).__name__,
                        "timestamp": time.time(),
                        "message_type": message_type,
                        "request_id": data.get("request_id"),  # 添加请求ID到错误响应
                    },
                )
            )
        except Exception:
            # 忽略发送错误
            pass
        finally:
            # 记录总处理时间
            total_process_time = time.time() - start_time
            if total_process_time > 5.0:  # 记录超过5秒的消息处理
                logger.info(
                    f"Slow message processing: {message_type}, time: {total_process_time:.3f}s"
                )


# 添加缺失的导入

# 创建全局WebSocket管理器实例
global_websocket_manager = None


def get_websocket_manager() -> WebSocketManager:
    """
    获取全局WebSocket管理器实例
    
    使用单例模式确保整个应用中只有一个WebSocket管理器实例
    
    Returns:
        WebSocketManager: 全局WebSocket管理器实例
    """
    global global_websocket_manager
    if global_websocket_manager is None:
        global_websocket_manager = WebSocketManager()
    return global_websocket_manager


async def initialize_websocket_manager():
    manager = get_websocket_manager()
    manager.max_connections = 100
    manager.heartbeat_interval = 30
    manager.max_message_queue_size = 1000
    logger.info("WebSocket管理器初始化完成")
    return manager

# 导出有用的装饰器
