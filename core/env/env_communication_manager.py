#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
环境通信管理器 - 实现不同虚拟环境之间的通信和数据共享
"""

import os
import json
import asyncio
import threading
import aiohttp
import aiofiles
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from pathlib import Path
import time
import uuid
from queue import Queue, Empty
import tempfile

# 配置日志
from core.utils.logger import get_logger
logger = get_logger("ENV_COMM_MANAGER")

@dataclass
class Message:
    """消息数据结构"""
    message_id: str = None  # 唯一消息ID
    source: str = ""       # 消息来源环境
    target: str = ""       # 消息目标环境
    topic: str = ""        # 消息主题
    data: dict = None      # 消息数据
    timestamp: float = None  # 时间戳
    response_to: str = None  # 回复的消息ID
    priority: int = 0      # 优先级，默认为0，数值越大优先级越高
    
    def __post_init__(self):
        """初始化默认值"""
        if self.message_id is None:
            self.message_id = str(uuid.uuid4())
        if self.timestamp is None:
            self.timestamp = time.time()
        if self.data is None:
            self.data = {}

class MessageQueue:
    """进程间消息队列"""
    
    def __init__(self, queue_name: str):
        self.queue_name = queue_name
        self.queue = Queue()
        self.lock = threading.RLock()
        self.subscribers: Dict[str, List[Callable]] = {}
        logger.info(f"创建消息队列: {queue_name}")
    def _notify_subscribers(self, message: Message):
        """通知主题订阅者"""
        if message.topic in self.subscribers:
            for callback in self.subscribers[message.topic]:
                try:
                    callback(message)
                except Exception as e:
                    logger.error(f"通知订阅者失败: {e}")
class FileBasedSharedStorage:
    """基于文件的共享存储，用于不同环境间的数据交换"""
    
    def __init__(self, storage_dir: str = None):
        # 使用临时目录作为默认共享存储
        self.storage_dir = storage_dir or os.path.join(tempfile.gettempdir(), "xiaoyou_shared")
        os.makedirs(self.storage_dir, exist_ok=True)
        logger.info(f"初始化共享存储目录: {self.storage_dir}")
    
    async def write(self, key: str, data: Any, env_id: str = "global") -> bool:
        """写入共享数据"""
        try:
            # 创建环境子目录
            env_dir = os.path.join(self.storage_dir, env_id)
            os.makedirs(env_dir, exist_ok=True)
            
            # 构建文件路径
            file_path = os.path.join(env_dir, f"{key}.json")
            
            # 异步写入文件
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
            
            logger.debug(f"写入共享数据: {env_id}/{key}")
            return True
        except Exception as e:
            logger.error(f"写入共享数据失败: {e}")
            return False
    
    async def read(self, key: str, env_id: str = "global") -> Optional[Any]:
        """读取共享数据"""
        try:
            file_path = os.path.join(self.storage_dir, env_id, f"{key}.json")
            
            if not os.path.exists(file_path):
                logger.debug(f"共享数据不存在: {env_id}/{key}")
                return None
            
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                content = await f.read()
                data = json.loads(content)
            
            logger.debug(f"读取共享数据: {env_id}/{key}")
            return data
        except Exception as e:
            logger.error(f"读取共享数据失败: {e}")
            return None
    
    async def delete(self, key: str, env_id: str = "global") -> bool:
        """删除共享数据"""
        try:
            file_path = os.path.join(self.storage_dir, env_id, f"{key}.json")
            
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.debug(f"删除共享数据: {env_id}/{key}")
                return True
            
            return False
        except Exception as e:
            logger.error(f"删除共享数据失败: {e}")
            return False
class HTTPClient:
    """HTTP客户端，用于不同环境间的REST API通信"""
    
    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url
        self.timeout = timeout
        self.session = None
        logger.info(f"初始化HTTP客户端: {base_url}")
    
    async def _ensure_session(self):
        """确保aiohttp会话已创建"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
    
    async def close(self):
        """关闭会话"""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("HTTP客户端会话已关闭")
    
    async def get(self, endpoint: str, params: dict = None) -> Dict[str, Any]:
        """发送GET请求"""
        try:
            await self._ensure_session()
            url = f"{self.base_url}{endpoint}"
            
            async with self.session.get(url, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                logger.debug(f"GET请求成功: {endpoint}")
                return data
        except Exception as e:
            logger.error(f"GET请求失败: {endpoint} - {e}")
            raise
    
    async def post(self, endpoint: str, data: dict = None, json_data: dict = None) -> Dict[str, Any]:
        """发送POST请求"""
        try:
            await self._ensure_session()
            url = f"{self.base_url}{endpoint}"
            
            async with self.session.post(url, data=data, json=json_data) as response:
                response.raise_for_status()
                result = await response.json()
                logger.debug(f"POST请求成功: {endpoint}")
                return result
        except Exception as e:
            logger.error(f"POST请求失败: {endpoint} - {e}")
            raise

class EnvironmentCommunicationManager:
    """
    环境通信管理器 - 整合多种通信机制
    1. 本地消息队列
    2. 基于文件的共享存储
    3. HTTP/REST API通信
    """
    
    def __init__(self, env_id: str = "base"):
        self.env_id = env_id
        self.message_queues: Dict[str, MessageQueue] = {}
        self.shared_storage = FileBasedSharedStorage()
        self.http_clients: Dict[str, HTTPClient] = {}
        self.running = False
        self._process_thread = None
        self._process_queue = Queue()
        logger.info(f"初始化环境通信管理器: {env_id}")
    async def _close_all_http_clients(self):
        """关闭所有HTTP客户端"""
        for client in self.http_clients.values():
            await client.close()
    
    def _process_messages_loop(self):
        """消息处理循环"""
        while self.running:
            try:
                # 从处理队列获取消息
                message = self._process_queue.get(timeout=1.0)
                
                if message is None:  # 终止信号
                    break
                    
                # 处理消息
                self._process_message(message)
                
            except Empty:
                continue
            except Exception as e:
                logger.error(f"处理消息循环错误: {e}")
    
    def start(self):
        """启动通信管理器"""
        self.running = True
        # 创建并启动消息处理线程
        self._process_thread = threading.Thread(target=self._process_messages_loop, daemon=True)
        self._process_thread.start()
        logger.info(f"环境通信管理器已启动: {self.env_id}")
    
    def _process_message(self, message: Message):
        """处理单个消息"""
        try:
            # 根据目标环境处理消息
            if message.target == self.env_id or message.target == "broadcast":
                # 本地处理或广播消息
                queue_name = message.topic.split('.')[0] if '.' in message.topic else message.topic
                queue = self._get_or_create_queue(queue_name)
                queue.put(message)
                logger.debug(f"处理消息: {message.topic} 目标: {message.target}")
            else:
                # 需要转发到其他环境
                self._forward_message(message)
        except Exception as e:
            logger.error(f"处理消息失败: {message.message_id} - {e}")
    
    def _forward_message(self, message: Message):
        """转发消息到其他环境"""
        # 这里可以实现基于HTTP、WebSocket等不同的转发机制
        # 现在简单实现为通过共享存储中转
        asyncio.run(self._forward_via_shared_storage(message))
    
    async def _forward_via_shared_storage(self, message: Message):
        """通过共享存储转发消息"""
        try:
            # 写入到目标环境的消息队列
            await self.shared_storage.write(
                key=f"msg_{message.message_id}",
                data={
                    "message_id": message.message_id,
                    "source": message.source,
                    "target": message.target,
                    "topic": message.topic,
                    "data": message.data,
                    "timestamp": message.timestamp,
                    "response_to": message.response_to,
                    "priority": message.priority,
                    "status": "pending"
                },
                env_id=message.target
            )
            logger.debug(f"通过共享存储转发消息: {message.message_id} 到 {message.target}")
        except Exception as e:
            logger.error(f"转发消息失败: {e}")
    def _get_or_create_queue(self, queue_name: str) -> MessageQueue:
        """获取或创建消息队列"""
        if queue_name not in self.message_queues:
            self.message_queues[queue_name] = MessageQueue(queue_name)
        return self.message_queues[queue_name]
    async def check_messages_from_shared_storage(self):
        """检查共享存储中的待处理消息"""
        try:
            keys = self.shared_storage.list_keys(env_id=self.env_id)
            
            for key in keys:
                if key.startswith("msg_"):
                    # 读取消息
                    message_data = await self.shared_storage.read(key, env_id=self.env_id)
                    
                    if message_data and message_data.get("status") == "pending":
                        # 创建消息对象
                        message = Message(
                            message_id=message_data["message_id"],
                            source=message_data["source"],
                            target=message_data["target"],
                            topic=message_data["topic"],
                            data=message_data["data"],
                            timestamp=message_data["timestamp"],
                            response_to=message_data.get("response_to"),
                            priority=message_data.get("priority", 0)
                        )
                        
                        # 处理消息
                        queue_name = message.topic.split('.')[0] if '.' in message.topic else message.topic
                        queue = self._get_or_create_queue(queue_name)
                        queue.put(message)
                        
                        # 更新消息状态为已处理
                        message_data["status"] = "processed"
                        await self.shared_storage.write(key, message_data, env_id=self.env_id)
                        
                        logger.debug(f"从共享存储处理消息: {message.message_id}")
        except Exception as e:
            logger.error(f"检查共享存储消息失败: {e}")

# 创建全局环境通信管理器实例
_communication_manager = None
_manager_lock = None

def get_communication_manager(env_id: str = "base") -> EnvironmentCommunicationManager:
    """
    获取全局环境通信管理器实例
    
    Args:
        env_id: 环境ID
        
    Returns:
        EnvironmentCommunicationManager: 通信管理器实例
    """
    global _communication_manager, _manager_lock
    
    if _manager_lock is None:
        _manager_lock = threading.RLock()
    
    with _manager_lock:
        if _communication_manager is None:
            _communication_manager = EnvironmentCommunicationManager(env_id)
            _communication_manager.start()
            logger.info("创建全局环境通信管理器实例")
    
    return _communication_manager

# 为其他环境提供的辅助函数
# 定期检查共享存储的任务
async def start_shared_storage_checker(interval: float = 2.0):
    """启动共享存储检查器，定期检查新消息"""
    manager = get_communication_manager()
    
    while True:
        await manager.check_messages_from_shared_storage()
        await asyncio.sleep(interval)

# 应用程序关闭时清理
def cleanup_communication_manager():
    """清理通信管理器资源"""
    global _communication_manager
    
    if _communication_manager:
        try:
            # 停止消息处理线程
            _communication_manager.running = False
            if _communication_manager._process_thread and _communication_manager._process_thread.is_alive():
                # 发送终止信号
                _communication_manager._process_queue.put(None)
                _communication_manager._process_thread.join(timeout=2.0)
                logger.info("通信管理器消息处理线程已停止")
            
            # 关闭所有HTTP客户端
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_communication_manager._close_all_http_clients())
            loop.close()
            
            logger.info("通信管理器资源已清理")
        except Exception as e:
            logger.error(f"清理通信管理器资源失败: {e}")

# 注册退出时的清理处理
import atexit
atexit.register(cleanup_communication_manager)