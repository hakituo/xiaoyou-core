#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
WebSocket客户端 - 用于各虚拟环境连接到WebSocket服务器
"""

import json
import asyncio
import time
import uuid
import traceback
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass

import websockets
from websockets.client import WebSocketClientProtocol
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError

# 配置日志
from core.utils.logger import get_logger
logger = get_logger("WEBSOCKET_CLIENT")

@dataclass
class WebSocketMessage:
    """WebSocket消息数据结构"""
    type: str = "message"        # 消息类型
    data: dict = None           # 消息数据
    message_id: str = None      # 消息ID
    topic: str = "default"      # 消息主题
    target_env: str = None      # 目标环境
    source_env: str = None      # 源环境
    timestamp: float = None     # 时间戳
    
    def __post_init__(self):
        """初始化默认值"""
        if self.message_id is None:
            self.message_id = str(uuid.uuid4())
        if self.timestamp is None:
            self.timestamp = time.time()
        if self.data is None:
            self.data = {}
    @classmethod
    def from_dict(cls, data: dict) -> "WebSocketMessage":
        return cls(
            type=data.get("type", "message"),
            data=data.get("data", {}) or {},
            message_id=data.get("message_id"),
            topic=data.get("topic", "default"),
            target_env=data.get("target_env"),
            source_env=data.get("source_env"),
            timestamp=data.get("timestamp")
        )

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "data": self.data or {},
            "message_id": self.message_id,
            "topic": self.topic,
            "target_env": self.target_env,
            "source_env": self.source_env,
            "timestamp": self.timestamp,
        }

class WebSocketClient:
    """WebSocket客户端，用于连接到WebSocket服务器"""
    
    def __init__(self, env_id: str, server_url: str = "ws://localhost:8010", reconnect_interval: int = 5):
        self.env_id = env_id
        # 兼容当前服务的路由：/ws/
        # 通过查询参数传递客户端标识与类型
        self.server_url = f"{server_url}/ws/?client_id={env_id}&user_agent=env-client"
        self.reconnect_interval = reconnect_interval
        
        # 连接状态
        self.websocket: Optional[WebSocketClientProtocol] = None
        self.connected = False
        self.connecting = False
        self.closing = False
        self.client_id = None
        
        # 消息处理
        self.message_handlers: Dict[str, List[Callable]] = {}
        self.topic_handlers: Dict[str, List[Callable]] = {}
        self.message_lock = asyncio.Lock()
        
        # 消息队列（用于同步发送）
        self.message_queue = asyncio.Queue()
        
        # 超时设置
        self.ping_interval = 30  # 秒
        self.ping_timeout = 10   # 秒
        
        # 任务引用
        self.receive_task = None
        self.ping_task = None
        
        logger.info(f"初始化WebSocket客户端: {env_id} -> {server_url}")

    async def connect(self) -> bool:
        """连接到WebSocket服务器"""
        if self.connected or self.connecting:
            logger.warning(f"客户端 {self.env_id} 已经连接或正在连接中")
            return self.connected
        
        self.connecting = True
        logger.info(f"正在连接到WebSocket服务器: {self.server_url}")
        
        try:
            self.websocket = await websockets.connect(
                self.server_url,
                ping_interval=self.ping_interval,
                ping_timeout=self.ping_timeout,
                extra_headers={
                    "X-Environment-ID": self.env_id
                }
            )
            
            self.connected = True
            self.connecting = False
            logger.info(f"成功连接到WebSocket服务器: {self.server_url}")
            
            # 启动接收任务
            self.receive_task = asyncio.create_task(self._receive_messages())
            
            # 启动ping任务
            self.ping_task = asyncio.create_task(self._ping_loop())
            
            return True
            
        except Exception as e:
            self.connected = False
            self.connecting = False
            logger.error(f"连接WebSocket服务器失败: {e}")
            logger.debug(traceback.format_exc())
            return False
    
    def is_connected(self) -> bool:
        return self.connected and self.websocket is not None

    def register_handler(self, message_type: str, handler: Callable) -> None:
        handlers = self.message_handlers.setdefault(message_type, [])
        handlers.append(handler)

    def unregister_handler(self, message_type: str, handler: Callable) -> None:
        handlers = self.message_handlers.get(message_type)
        if handlers:
            try:
                handlers.remove(handler)
            except ValueError:
                pass

    async def disconnect(self):
        """断开连接"""
        if not self.connected and not self.connecting:
            return
        
        self.closing = True
        logger.info(f"正在断开WebSocket连接: {self.env_id}")
        
        # 取消任务
        if self.receive_task:
            self.receive_task.cancel()
            try:
                await self.receive_task
            except asyncio.CancelledError:
                pass
        
        if self.ping_task:
            self.ping_task.cancel()
            try:
                await self.ping_task
            except asyncio.CancelledError:
                pass
        
        # 关闭连接
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception as e:
                logger.error(f"关闭WebSocket连接时错误: {e}")
        
        # 重置状态
        self.connected = False
        self.connecting = False
        self.closing = False
        self.websocket = None
        
        logger.info(f"WebSocket连接已断开: {self.env_id}")
    
    async def _receive_messages(self):
        """接收消息循环"""
        while self.connected:
            try:
                # 接收消息
                message_data = await self.websocket.recv()
                raw = json.loads(message_data)
                
                # 直接兼容当前路由的消息结构
                if isinstance(raw, dict):
                    t = raw.get("type")
                    if t == "connection_established":
                        self.client_id = raw.get("client_id") or self.env_id
                        logger.info(f"连接已建立，客户端ID: {self.client_id}")
                        continue
                    if t == "message":
                        subtype = raw.get("subtype")
                        if subtype == "acknowledged":
                            logger.info(f"消息已确认: message_id={raw.get('message_id')}")
                        elif subtype == "response":
                            logger.info(f"收到回复: {raw.get('content')}")
                        # 将原始负载包装为通用消息，便于回调处理
                        wrapped = WebSocketMessage(
                            type="message",
                            data=raw,
                            message_id=raw.get("message_id"),
                            timestamp=raw.get("timestamp")
                        )
                        await self._process_message(wrapped)
                        continue
                
                # 其他类型按通用结构处理
                message = WebSocketMessage.from_dict(raw)
                logger.debug(f"接收到消息: {message.type} from {message.source_env}")
                if message.type in ("connection_ack", "connection_established"):
                    self.client_id = message.data.get("client_id") if isinstance(message.data, dict) else None
                    logger.info(f"连接已建立，客户端ID: {self.client_id or self.env_id}")
                await self._process_message(message)
                
            except ConnectionClosedOK:
                logger.info("WebSocket连接正常关闭")
                break
                
            except ConnectionClosedError as e:
                logger.error(f"WebSocket连接错误关闭: {e}")
                break
                
            except Exception as e:
                logger.error(f"接收消息时错误: {e}")
                logger.debug(traceback.format_exc())
        
        # 连接断开，尝试重连
        if not self.closing:
            await self._handle_reconnect()
    
    async def _process_message(self, message: WebSocketMessage):
        """处理接收到的消息"""
        # 处理按类型注册的处理器
        if message.type in self.message_handlers:
            handlers = list(self.message_handlers[message.type])
            for handler in handlers:
                try:
                    await handler(message)
                except Exception as e:
                    logger.error(f"执行消息处理器时错误: {handler} - {e}")
        
        # 处理按主题注册的处理器
        if message.topic in self.topic_handlers:
            handlers = list(self.topic_handlers[message.topic])
            for handler in handlers:
                try:
                    await handler(message)
                except Exception as e:
                    logger.error(f"执行主题处理器时错误: {handler} - {e}")
    
    async def _ping_loop(self):
        """ping循环，保持连接活跃"""
        while self.connected:
            try:
                await asyncio.sleep(self.ping_interval)
                if self.connected:
                    await self.send_ping()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ping循环错误: {e}")
    
    async def _handle_reconnect(self):
        """处理重连逻辑"""
        if self.closing:
            return
        
        self.connected = False
        
        while not self.connected and not self.closing:
            logger.info(f"尝试重新连接WebSocket服务器，{self.reconnect_interval}秒后...")
            await asyncio.sleep(self.reconnect_interval)
            
            try:
                await self.connect()
            except Exception as e:
                logger.error(f"重连失败: {e}")
    
    async def send(self, message: WebSocketMessage) -> bool:
        """发送消息"""
        if not self.connected:
            logger.warning("客户端未连接，无法发送消息")
            return False
        
        try:
            async with self.message_lock:
                await self.websocket.send(json.dumps(message.to_dict(), ensure_ascii=False))
            logger.debug(f"发送消息: {message.type} -> {message.target_env}")
            return True
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            return False

    async def _send_router_message(self, payload: Dict[str, Any]) -> bool:
        """按当前WebSocket路由协议发送原始字典消息"""
        if not self.connected:
            logger.warning("客户端未连接，无法发送消息")
            return False
        try:
            async with self.message_lock:
                await self.websocket.send(json.dumps(payload, ensure_ascii=False))
            logger.debug(f"发送路由消息: {payload.get('type')}")
            return True
        except Exception as e:
            logger.error(f"发送路由消息失败: {e}")
            return False
    
    async def send_message(self, target_env: str, topic: str, data: dict = None) -> bool:
        """发送通用消息（与当前服务路由兼容）"""
        content = "" if not data else (
            data.get("content") if isinstance(data, dict) else str(data)
        )
        payload = {
            "type": "message",
            "content": content or f"topic={topic}",
            "message_id": str(uuid.uuid4()),
            "timestamp": time.time(),
        }
        return await self._send_router_message(payload)
    
    async def broadcast(self, data: dict = None) -> bool:
        """广播消息到所有连接（与当前服务路由兼容）"""
        payload = {
            "type": "broadcast",
            "content": (data or {}).get("content") if isinstance(data, dict) else None,
        }
        return await self._send_router_message(payload)
    
    async def send_ping(self) -> bool:
        """发送ping消息"""
        message = WebSocketMessage(
            type="ping",
            timestamp=time.time()
        )
        return await self.send(message)
    
    async def request_status(self) -> Optional[dict]:
        """请求服务器状态"""
        message = WebSocketMessage(
            type="get_status"
        )
        
        # 创建响应回调
        response_event = asyncio.Event()
        response_data = None
        
        async def response_handler(msg: WebSocketMessage):
            nonlocal response_data
            # 当前服务返回类型为 "status"
            if msg.type in ("status", "status_response"):
                response_data = msg.data
                response_event.set()
        
        # 注册临时处理器
        self.register_handler("status", response_handler)
        self.register_handler("status_response", response_handler)
        
        # 发送请求
        if await self.send(message):
            # 等待响应
            try:
                await asyncio.wait_for(response_event.wait(), timeout=10.0)
                return response_data
            except asyncio.TimeoutError:
                logger.error("获取服务器状态超时")
        
        # 移除临时处理器
        self.unregister_handler("status", response_handler)
        self.unregister_handler("status_response", response_handler)
        
        return None
# 创建全局WebSocket客户端实例
_websocket_client = None
_client_lock = asyncio.Lock()

async def get_websocket_client(env_id: str, server_url: str = "ws://localhost:8010") -> WebSocketClient:
    """
    获取全局WebSocket客户端实例
    
    Args:
        env_id: 环境ID
        server_url: WebSocket服务器URL
        
    Returns:
        WebSocketClient: WebSocket客户端实例
    """
    global _websocket_client
    
    async with _client_lock:
        if _websocket_client is None:
            _websocket_client = WebSocketClient(env_id, server_url)
            logger.info("创建全局WebSocket客户端实例")
        
        # 如果未连接，尝试连接
        if not _websocket_client.is_connected():
            await _websocket_client.connect()
    
    return _websocket_client

# 同步连接辅助函数
async def connect_websocket_client(env_id: str, server_url: str = "ws://localhost:8010") -> WebSocketClient:
    """连接WebSocket客户端"""
    client = await get_websocket_client(env_id, server_url)
    if not client.is_connected():
        await client.connect()
    return client

# 同步发送消息辅助函数
async def send_websocket_message(env_id: str, target_env: str, topic: str, data: dict = None) -> bool:
    """发送WebSocket消息"""
    client = await get_websocket_client(env_id)
    return await client.send_message(target_env, topic, data)

# 同步广播消息辅助函数
async def broadcast_websocket_message(env_id: str, data: dict = None) -> bool:
    """广播WebSocket消息"""
    client = await get_websocket_client(env_id)
    return await client.broadcast(data)

# 关闭WebSocket客户端的辅助函数
async def close_websocket_client():
    """关闭WebSocket客户端"""
    global _websocket_client
    
    if _websocket_client is not None:
        await _websocket_client.disconnect()
        _websocket_client = None
        logger.info("WebSocket客户端已关闭")

# 注册退出时的清理处理
import atexit

# 由于atexit无法执行异步函数，我们需要创建一个同步包装器
def _sync_close_websocket():
    if asyncio.get_event_loop().is_running():
        # 如果事件循环正在运行，使用call_soon_threadsafe
        asyncio.get_event_loop().call_soon_threadsafe(
            lambda: asyncio.create_task(close_websocket_client())
        )
    else:
        # 否则直接运行
        asyncio.run(close_websocket_client())

atexit.register(_sync_close_websocket)

pass