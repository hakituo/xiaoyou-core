#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI WebSocket适配器
连接FastAPI的WebSocket和现有的WebSocketManager
"""
import logging
from typing import Optional, Dict, Any
import asyncio
from fastapi import WebSocket
import json
import time
import re

logger = logging.getLogger(__name__)


# 全局实例
_instance = None

# 实例锁
_instance_lock = asyncio.Lock()


class FastAPIWebSocketAdapter:
    """
    FastAPI WebSocket适配器
    将FastAPI的WebSocket接口转换为与现有WebSocketManager兼容的格式
    """
    def __init__(self):
        # 延迟导入以避免循环依赖
        self.websocket_manager = None
        self._initialized = False
    
    async def initialize(self):
        """
        初始化适配器，连接到现有的WebSocketManager
        """
        if not self._initialized:
            try:
                # 导入现有的WebSocketManager
                from core.interfaces.websocket.websocket_manager import get_websocket_manager
                
                # 获取全局唯一的管理器实例
                self.websocket_manager = get_websocket_manager()
                
                # 检查WebSocketManager是否已就绪
                # 注意：WebSocketManager可能没有start方法，我们直接使用它
                
                self._initialized = True
                logger.info("FastAPI WebSocket适配器初始化完成 (Connected to Global WebSocketManager)")
                
            except Exception as e:
                logger.error(f"初始化FastAPI WebSocket适配器失败: {str(e)}", exc_info=True)
                raise
    
    async def shutdown(self):
        """
        关闭适配器资源
        """
        if self._initialized:
            # 清理WebSocket管理器相关资源
            # 注意：避免调用可能不存在的方法
            self._initialized = False
            logger.info("FastAPI WebSocket适配器资源已释放")
    
    async def _process_message(self, websocket, message):
        try:
            if not isinstance(message, dict):
                logger.warning(f"接收到非字典消息: {message}")
                return

            msg_type = message.get("type")
            logger.debug(f"收到消息类型: {msg_type}")

            if msg_type == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "timestamp": message.get("timestamp", time.time())
                })
                return

            if msg_type == "pong":
                if self.websocket_manager:
                    await self.websocket_manager.handle_heartbeat(websocket)
                return

            if msg_type in ("message", "chat"):
                content = str(message.get("content", "") or "").strip()
                msg_id = message.get("message_id") or str(int(time.time() * 1000))
                conversation_id = message.get("conversation_id") or "websocket"
                model = message.get("model") or ""

                await websocket.send_json({
                    "type": "message",
                    "subtype": "acknowledged",
                    "message_id": msg_id,
                    "timestamp": time.time()
                })

                if not content:
                    await websocket.send_json({
                        "type": "message",
                        "subtype": "response",
                        "content": "请提供有效的输入内容。",
                        "message_id": msg_id,
                        "timestamp": time.time()
                    })
                    return

                try:
                    from core.lifecycle_manager import get_aveline_service
                    from core.core_engine.config_manager import ConfigManager
                    svc = get_aveline_service()
                    
                    # Use stream_generate_response to handle sensory triggers and behavior chains
                    async for chunk in svc.stream_generate_response(
                        user_input=content,
                        conversation_id=conversation_id,
                        model_hint=model
                    ):
                        # Check for special event types
                        if "type" in chunk and chunk["type"] in ("sensory_trigger", "behavior_chain"):
                             await websocket.send_json({
                                "type": chunk["type"],
                                "data": chunk["data"],
                                "timestamp": time.time(),
                                "message_id": msg_id
                            })
                             continue
                        
                        # Handle content chunks
                        if "content" in chunk:
                            content_chunk = chunk["content"]
                            if content_chunk:
                                await websocket.send_json({
                                    "type": "message",
                                    "subtype": "response_chunk", # New subtype for streaming
                                    "content": content_chunk,
                                    "message_id": msg_id,
                                    "timestamp": time.time(),
                                    "conversation_id": conversation_id
                                })
                        
                        # Check for completion
                        if chunk.get("done", False):
                             await websocket.send_json({
                                "type": "message",
                                "subtype": "response_done",
                                "message_id": msg_id,
                                "timestamp": time.time(),
                                "conversation_id": conversation_id
                            })

                except Exception as e:
                    logger.error(f"生成回复失败: {e}", exc_info=True)
                    await websocket.send_json({
                        "type": "error",
                        "message": "生成回复时发生错误",
                        "error": str(e),
                        "message_id": msg_id
                    })
                return

        except Exception as e:
            logger.error(f"处理消息出错: {str(e)}")


    async def handle_connection(self, websocket: WebSocket):
        """
        处理FastAPI的WebSocket连接
        """
        if not self._initialized:
            await self.initialize()
        
        # 接受连接
        await websocket.accept()
        
        # 从查询参数或消息中获取用户信息
        query_params = dict(websocket.query_params)
        user_id = query_params.get("user_id") or query_params.get("client_id") or "anonymous"
        platform = query_params.get("platform", "fastapi")
        
        logger.info(f"FastAPI WebSocket连接请求: user_id={user_id}, platform={platform}")
        
        try:
            # 创建一个包装类来适配FastAPI的WebSocket到websockets库的接口
            class WebSocketWrapper:
                def __init__(self, fastapi_ws):
                    self.fastapi_ws = fastapi_ws
                    # 获取真实的客户端地址
                    if fastapi_ws.client:
                        self.remote_address = (fastapi_ws.client.host, fastapi_ws.client.port)
                    else:
                        self.remote_address = ("127.0.0.1", 0)
                
                async def send_text(self, data):
                    await self.fastapi_ws.send_text(data)
                
                async def send(self, data):
                    """
                    适配websockets库的send方法
                    """
                    if isinstance(data, str):
                        await self.fastapi_ws.send_text(data)
                    else:
                        # 假设是bytes或json对象(如果被误传)
                        await self.fastapi_ws.send_text(str(data))

                async def send_json(self, data):
                    await self.fastapi_ws.send_json(data)
                
                async def recv_text(self):
                    return await self.fastapi_ws.receive_text()
                
                async def recv_json(self):
                    return await self.fastapi_ws.receive_json()
                
                async def close(self, code=1000, reason=""):
                    await self.fastapi_ws.close(code=code, reason=reason)
                
                @property
                def closed(self):
                    # FastAPI的WebSocket没有直接的closed属性，需要通过状态判断
                    return not self.fastapi_ws.client
            
            # 创建包装器
            ws_wrapper = WebSocketWrapper(websocket)
            
            # 添加到现有管理器
            # 注意：这里假设websocket_manager有add_connection方法
            # 如果没有，可能需要适配
            added = await self.websocket_manager.add_connection(
                ws_wrapper,
                user_id=user_id,
                platform=platform
            )
            
            if not added:
                logger.warning(f"Connection rejected by manager (Limit exceeded or other reason): {user_id}")
                await websocket.close(code=1008, reason="Connection limit exceeded")
                return
            
            logger.info(f"WebSocket connection accepted: {user_id}")

            # 处理消息循环
            while True:
                try:
                    # 检查WebSocketManager是否有关闭连接
                    if ws_wrapper.closed:
                        break
                        
                    # 读取消息以保持连接活跃并检测断开
                    message_text = await websocket.receive_text()
                    
                    # 尝试解析为JSON
                    try:
                        message = json.loads(message_text)
                    except json.JSONDecodeError:
                        message = {"type": "text", "content": message_text}
                    
                    # 记录活动时间（模拟现有管理器的行为）
                    # 这里的访问方式依赖于WebSocketManager的内部结构，可能需要调整
                    # 但为了简单起见，我们先跳过直接修改内部状态，而是让_process_message处理
                    
                    # 处理消息
                    await self._process_message(ws_wrapper, message)
                    
                except Exception as e:
                    # 连接断开或其他错误
                    logger.debug(f"WebSocket循环中断: {str(e)}")
                    break
                    
        except Exception as e:
            logger.error(f"处理WebSocket连接时出错: {str(e)}")
        finally:
            # 清理连接
            if self.websocket_manager:
                try:
                    # 尝试移除连接
                    # 注意：这里假设websocket_manager有remove_connection方法
                    # 且参数签名可能不同，这里尝试传递ws_wrapper
                    if hasattr(self.websocket_manager, 'remove_connection'):
                        # 检查方法签名或尝试调用
                        # 假设签名是 remove_connection(ws)
                        await self.websocket_manager.remove_connection(ws_wrapper)
                except Exception as e:
                    logger.error(f"移除WebSocket连接时出错: {str(e)}")

    async def broadcast_message(self, data: Dict[str, Any]):
        if not self._initialized:
            await self.initialize()
        if not self.websocket_manager:
            return
        try:
            await self.websocket_manager.broadcast(data)
        except Exception as e:
            logger.error(f"广播消息失败: {str(e)}", exc_info=True)

    @classmethod
    async def get_instance(cls):
        """
        获取适配器实例（异步方式）
        """
        global _instance
        async with _instance_lock:
            if _instance is None:
                _instance = cls()
                await _instance.initialize()
        return _instance


# 同步版本的获取函数，用于依赖注入
def get_fastapi_websocket_adapter() -> Optional[FastAPIWebSocketAdapter]:
    """
    获取FastAPI WebSocket适配器实例（同步方式）
    用于依赖注入
    """
    global _instance
    if _instance is None:
        # 创建实例但不初始化（初始化需要在异步上下文中进行）
        _instance = FastAPIWebSocketAdapter()
    return _instance


async def initialize_websocket_adapter():
    """
    初始化WebSocket适配器
    被生命周期管理器调用
    """
    global _instance
    async with _instance_lock:
        if _instance is None:
            _instance = FastAPIWebSocketAdapter()
            await _instance.initialize()
            logger.info("WebSocket适配器初始化成功")
        else:
            logger.info("WebSocket适配器已初始化")
    return _instance


async def shutdown_websocket_adapter():
        """
        关闭WebSocket适配器
        被生命周期管理器调用
        """
        global _instance
        async with _instance_lock:
            if _instance is not None:
                try:
                    # 实现shutdown方法关闭相关资源
                    await _instance.shutdown()
                    logger.info("WebSocket适配器关闭成功")
                except Exception as e:
                    logger.error(f"关闭WebSocket适配器时出错: {str(e)}")
                finally:
                    _instance = None
            else:
                logger.info("WebSocket适配器未初始化，无需关闭")
