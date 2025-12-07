#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
图像服务客户端
负责与venv_models环境中的图像服务进行通信
添加了任务队列、缓存机制和并发控制
"""

import asyncio
import hashlib
import logging
import time
import uuid
from typing import Dict, Any, Optional, Union, Tuple
from pathlib import Path
from collections import OrderedDict

# 配置日志
logger = logging.getLogger("IMAGE_CLIENT")

# 导入配置
from config.integrated_config import get_settings

# 导入WebSocket客户端
from core.env.websocket_client import get_websocket_client

class ImageServiceClient:
    """图像服务客户端类 - 带任务队列和缓存机制"""
    
    def __init__(self, max_queue_size: int = 10, cache_size: int = 50):
        self.websocket_client = None
        self.connected = False
        self.request_timeout = 30.0  # 请求超时时间（秒）
        self.session_id = str(uuid.uuid4())[:8]
        self.requests = {}  # 存储待处理的请求
        
        # 任务队列配置
        self.max_queue_size = max_queue_size
        self.queue = asyncio.Queue(maxsize=max_queue_size)
        self.worker_task = None
        
        # 缓存配置
        self.cache_size = cache_size
        self.cache = OrderedDict()  # LRU缓存
        self.cache_lock = asyncio.Lock()
        
        # 启动工作线程
        self._start_worker()
    
    async def connect(self, ws_url: str = None):
        """连接到图像服务"""
        try:
            if self.connected:
                logger.warning("图像服务客户端已经连接")
                return True
            
            if ws_url is None:
                settings = get_settings()
                ws_url = settings.model.image_service_url
            
            logger.info(f"正在连接到图像服务: {ws_url}")
            
            # 获取WebSocket客户端
            self.websocket_client = get_websocket_client()
            
            # 注册响应处理器
            self.websocket_client.register_handler("image_response", self.handle_image_response)
            
            # 连接WebSocket服务
            await self.websocket_client.connect(
                ws_url,
                service_name="image_client",
                service_type="image_client"
            )
            
            # 验证连接
            connected = await self._verify_connection()
            if connected:
                self.connected = True
                logger.info("图像服务客户端连接成功")
                return True
            else:
                logger.error("图像服务连接验证失败")
                return False
                
        except Exception as e:
            logger.error(f"连接图像服务失败: {str(e)}")
            return False
    
    async def _verify_connection(self) -> bool:
        """验证与图像服务的连接"""
        try:
            # 发送ping消息到图像服务
            request_id = str(uuid.uuid4())
            response = await self._send_request_and_wait(
                request_id=request_id,
                request_type="ping",
                data={"target": "image_service"},
                timeout=5.0
            )
            
            return response.get("status") == "success"
            
        except asyncio.TimeoutError:
            logger.error("图像服务连接验证超时")
            return False
        except Exception as e:
            logger.error(f"验证连接时出错: {str(e)}")
            return False
    
    def _start_worker(self):
        """启动队列工作线程"""
        if self.worker_task is None:
            self.worker_task = asyncio.create_task(self._process_queue())
    
    async def _stop_worker(self):
        """停止队列工作线程"""
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
            self.worker_task = None
    
    async def _process_queue(self):
        """处理队列中的任务"""
        while True:
            try:
                # 从队列中获取任务
                task = await self.queue.get()
                try:
                    # 执行任务
                    await self._execute_task(task)
                finally:
                    # 标记任务完成
                    self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"任务处理线程异常: {str(e)}")
    
    async def _execute_task(self, task: Dict[str, Any]):
        """执行单个任务"""
        task_type = task.get("type")
        future = task.get("future")
        
        try:
            if task_type == "generate_image":
                # 执行图像生成
                result = await self._generate_image_impl(
                    task["prompt"],
                    task["width"],
                    task["height"],
                    task["num_inference_steps"],
                    task["guidance_scale"],
                    task["instance_id"],
                    task["save_to_file"]
                )
                future.set_result(result)
            elif task_type == "process_image":
                # 执行图像处理
                result = await self._process_image_impl(
                    task["image_data"],
                    task["file_path"],
                    task["instance_id"]
                )
                future.set_result(result)
        except Exception as e:
            if not future.done():
                future.set_exception(e)
    
    def _get_prompt_hash(self, prompt: str, width: int, height: int, 
                        num_inference_steps: int, guidance_scale: float) -> str:
        """生成提示词的哈希值用于缓存"""
        key = f"{prompt}:{width}:{height}:{num_inference_steps}:{guidance_scale}"
        return hashlib.md5(key.encode()).hexdigest()
    
    async def _get_from_cache(self, key: str) -> Optional[Dict[str, Any]]:
        """从缓存获取结果"""
        async with self.cache_lock:
            if key in self.cache:
                # 更新访问顺序（LRU）
                value = self.cache.pop(key)
                self.cache[key] = value
                logger.info(f"缓存命中: {key[:10]}...")
                return value
            return None
    
    async def _add_to_cache(self, key: str, value: Dict[str, Any]):
        """添加结果到缓存"""
        async with self.cache_lock:
            # 限制缓存大小
            if len(self.cache) >= self.cache_size:
                self.cache.popitem(last=False)  # 移除最旧的项
            self.cache[key] = value
            logger.info(f"结果已缓存: {key[:10]}...")
    
    async def disconnect(self):
        """断开连接"""
        # 停止工作线程
        await self._stop_worker()
        
        if self.connected and self.websocket_client:
            logger.info("正在断开图像服务连接")
            try:
                # 取消所有待处理的请求
                for request_id, (future, _) in self.requests.items():
                    if not future.done():
                        future.cancel()
                
                # 清空队列中的任务
                while not self.queue.empty():
                    try:
                        task = self.queue.get_nowait()
                        future = task.get("future")
                        if future and not future.done():
                            future.set_exception(RuntimeError("服务已断开连接"))
                        self.queue.task_done()
                    except asyncio.QueueEmpty:
                        break
                
                # 断开WebSocket连接
                await self.websocket_client.disconnect()
                self.connected = False
                logger.info("图像服务连接已断开")
            except Exception as e:
                logger.error(f"断开图像服务连接失败: {str(e)}")
    
    async def handle_image_response(self, data: Dict[str, Any]):
        """处理来自图像服务的响应"""
        try:
            request_id = data.get("request_id")
            
            if request_id and request_id in self.requests:
                future, _ = self.requests[request_id]
                
                if not future.done():
                    future.set_result(data)
                
                # 移除已处理的请求
                del self.requests[request_id]
                
        except Exception as e:
            logger.error(f"处理图像服务响应时出错: {str(e)}")
    
    async def _send_request_and_wait(self, 
                                   request_id: str,
                                   request_type: str,
                                   data: Dict[str, Any],
                                   timeout: float = None) -> Dict[str, Any]:
        """发送请求并等待响应"""
        if not self.connected or not self.websocket_client:
            raise ConnectionError("图像服务未连接")
        
        if timeout is None:
            timeout = self.request_timeout
        
        # 创建一个future用于等待响应
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        
        # 记录请求
        self.requests[request_id] = (future, loop.time())
        
        try:
            # 构建请求数据
            request_data = {
                "type": request_type,
                "request_id": request_id,
                "session_id": self.session_id,
                "timestamp": loop.time(),
                "data": data
            }
            
            # 发送请求
            await self.websocket_client.send(request_data)
            
            # 等待响应
            response = await asyncio.wait_for(future, timeout=timeout)
            
            return response
            
        except asyncio.TimeoutError:
            # 超时处理
            logger.error(f"请求 {request_id} 超时")
            if request_id in self.requests:
                del self.requests[request_id]
            raise asyncio.TimeoutError(f"图像服务请求超时: {request_type}")
        except Exception as e:
            # 其他错误处理
            if request_id in self.requests:
                del self.requests[request_id]
            raise
    
    async def _generate_image_impl(
        self, 
        prompt: str,
        width: int = 512,
        height: int = 512,
        num_inference_steps: int = 1,
        guidance_scale: float = 0.0,
        instance_id: str = "default",
        save_to_file: bool = False
    ) -> Dict[str, Any]:
        """图像生成的实际实现"""
        # 生成缓存键
        cache_key = self._get_prompt_hash(prompt, width, height, num_inference_steps, guidance_scale)
        
        # 检查缓存
        cached_result = await self._get_from_cache(cache_key)
        if cached_result and not save_to_file:  # 如果需要保存文件则不使用缓存
            return cached_result
        
        # 确保连接
        if not self.connected:
            await self.connect()
        
        request_id = str(uuid.uuid4())
        
        logger.info(f"发送图像生成请求 {request_id}: {prompt[:50]}...")
        
        # 构建请求数据
        data = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "instance_id": instance_id,
            "save_to_file": save_to_file
        }
        
        # 发送请求并等待响应
        response = await self._send_request_and_wait(
            request_id=request_id,
            request_type="generate_image",
            data=data
        )
        
        # 检查响应状态
        if response.get("status") != "success":
            error_msg = response.get("error", "未知错误")
            logger.error(f"图像生成失败: {error_msg}")
            raise RuntimeError(f"图像生成失败: {error_msg}")
        
        logger.info(f"图像生成成功: {request_id}")
        
        # 添加到缓存
        if not save_to_file:  # 如果需要保存文件则不缓存
            await self._add_to_cache(cache_key, response)
        
        return response
    
    async def generate_image(
        self, 
        prompt: str,
        width: int = 512,
        height: int = 512,
        num_inference_steps: int = 1,
        guidance_scale: float = 0.0,
        instance_id: str = "default",
        save_to_file: bool = False
    ) -> Dict[str, Any]:
        """生成图像 - 通过任务队列处理"""
        # 生成缓存键并检查缓存
        cache_key = self._get_prompt_hash(prompt, width, height, num_inference_steps, guidance_scale)
        cached_result = await self._get_from_cache(cache_key)
        if cached_result and not save_to_file:
            return cached_result
        
        # 创建future用于等待结果
        future = asyncio.get_event_loop().create_future()
        
        # 构建任务
        task = {
            "type": "generate_image",
            "future": future,
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "instance_id": instance_id,
            "save_to_file": save_to_file,
            "timestamp": time.time()
        }
        
        try:
            # 将任务添加到队列，设置超时以避免无限等待
            await asyncio.wait_for(
                self.queue.put(task),
                timeout=1.0
            )
            logger.info(f"图像生成请求已加入队列: {prompt[:30]}...")
        except asyncio.TimeoutError:
            # 队列已满，拒绝请求
            error_msg = "请求队列已满，请稍后再试"
            logger.warning(f"{error_msg}: {prompt[:30]}...")
            raise RuntimeError(error_msg)
        
        # 等待任务完成
        return await future
    
    async def _process_image_impl(
        self,
        image_data: Optional[bytes] = None,
        file_path: Optional[Union[str, Path]] = None,
        instance_id: str = "default"
    ) -> Dict[str, Any]:
        """图像处理的实际实现"""
        # 确保连接
        if not self.connected:
            await self.connect()
        
        request_id = str(uuid.uuid4())
        
        logger.info(f"发送图像处理请求 {request_id}")
        
        # 构建请求数据
        data = {"instance_id": instance_id}
        
        # 添加图像数据
        if image_data:
            data["image_data"] = image_data.hex()
        elif file_path:
            data["file_path"] = str(file_path)
        else:
            raise ValueError("必须提供图像数据或文件路径")
        
        # 发送请求并等待响应
        response = await self._send_request_and_wait(
            request_id=request_id,
            request_type="process_image",
            data=data
        )
        
        # 检查响应状态
        if response.get("status") != "success":
            error_msg = response.get("error", "未知错误")
            logger.error(f"图像处理失败: {error_msg}")
            raise RuntimeError(f"图像处理失败: {error_msg}")
        
        logger.info(f"图像处理成功: {request_id}")
        
        return response
    
    async def process_image(
        self,
        image_data: Optional[bytes] = None,
        file_path: Optional[Union[str, Path]] = None,
        instance_id: str = "default"
    ) -> Dict[str, Any]:
        """处理图像 - 通过任务队列处理"""
        # 创建future用于等待结果
        future = asyncio.get_event_loop().create_future()
        
        # 构建任务
        task = {
            "type": "process_image",
            "future": future,
            "image_data": image_data,
            "file_path": file_path,
            "instance_id": instance_id,
            "timestamp": time.time()
        }
        
        try:
            # 将任务添加到队列，设置超时以避免无限等待
            await asyncio.wait_for(
                self.queue.put(task),
                timeout=1.0
            )
            logger.info(f"图像处理请求已加入队列")
        except asyncio.TimeoutError:
            # 队列已满，拒绝请求
            error_msg = "请求队列已满，请稍后再试"
            logger.warning(error_msg)
            raise RuntimeError(error_msg)
        
        # 等待任务完成
        return await future
    
    async def get_service_status(self) -> Dict[str, Any]:
        """获取图像服务状态"""
        request_id = str(uuid.uuid4())
        
        logger.info(f"获取图像服务状态: {request_id}")
        
        # 发送状态请求
        response = await self._send_request_and_wait(
            request_id=request_id,
            request_type="get_status",
            data={"target": "image_service"},
            timeout=5.0
        )
        
        return response
    
    async def is_service_available(self) -> bool:
        """检查图像服务是否可用"""
        try:
            if not self.connected:
                return False
            
            status = await self.get_service_status()
            return status.get("status") == "success"
            
        except Exception as e:
            logger.error(f"检查服务可用性时出错: {str(e)}")
            return False


# 全局客户端实例
_image_service_client = None


def get_image_service_client() -> ImageServiceClient:
    """获取图像服务客户端实例"""
    global _image_service_client
    
    if _image_service_client is None:
        _image_service_client = ImageServiceClient()
    
    return _image_service_client


# 便捷函数：获取队列状态
async def get_queue_status() -> Dict[str, Any]:
    """获取当前任务队列状态"""
    client = get_image_service_client()
    return {
        "current_size": client.queue.qsize(),
        "max_size": client.max_queue_size,
        "cache_size": len(client.cache),
        "connected": client.connected
    }


async def connect_image_service() -> bool:
    """连接到图像服务的便捷函数"""
    client = get_image_service_client()
    return await client.connect()


async def disconnect_image_service():
    """断开图像服务连接的便捷函数"""
    client = get_image_service_client()
    await client.disconnect()


async def generate_image_async(
    prompt: str,
    width: int = 512,
    height: int = 512,
    num_inference_steps: int = 1,
    guidance_scale: float = 0.0,
    instance_id: str = "default",
    save_to_file: bool = False
) -> Dict[str, Any]:
    """异步生成图像的便捷函数"""
    client = get_image_service_client()
    
    # 确保连接
    if not client.connected:
        connected = await client.connect()
        if not connected:
            raise ConnectionError("无法连接到图像服务")
    
    return await client.generate_image(
        prompt=prompt,
        width=width,
        height=height,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        instance_id=instance_id,
        save_to_file=save_to_file
    )


async def process_image_async(
    image_data: Optional[bytes] = None,
    file_path: Optional[Union[str, Path]] = None,
    instance_id: str = "default"
) -> Dict[str, Any]:
    """异步处理图像的便捷函数"""
    client = get_image_service_client()
    
    # 确保连接
    if not client.connected:
        connected = await client.connect()
        if not connected:
            raise ConnectionError("无法连接到图像服务")
    
    return await client.process_image(
        image_data=image_data,
        file_path=file_path,
        instance_id=instance_id
    )


# 兼容性包装器函数，用于非异步环境