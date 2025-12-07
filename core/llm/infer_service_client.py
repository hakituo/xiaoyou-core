#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
推理服务客户端 (infer_service_client.py)

提供与推理服务通信的客户端工具，支持:
- 文本生成请求
- 模型状态查询
- 健康检查
- 错误处理和重试机制
"""
import os
import sys
import asyncio
import time
from typing import List, Dict, Optional, Any, Union
import aiohttp
from urllib.parse import urljoin

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 导入日志工具
from core.utils.logger import get_logger
logger = get_logger('infer_service_client')

# 导入配置管理
from config.config_loader import ConfigLoader, Config
_loader = ConfigLoader()
config = Config(_loader)


class InferServiceClient:
    """
    推理服务客户端类，提供与推理服务交互的方法
    """
    
    def __init__(self, base_url: Optional[str] = None, timeout: int = 300):
        """
        初始化客户端
        
        Args:
            base_url: 推理服务的基础URL
            timeout: 请求超时时间(秒)
        """
        # 从配置或参数获取基础URL
        if base_url is None:
            host = config.get('infer_service.host', 'localhost')
            port = config.get('infer_service.port', 8000)
            base_url = f"http://{host}:{port}"
        
        self.base_url = base_url
        self.timeout = timeout
        self.session = None
        self.retry_count = 3
        self.retry_delay = 1.0  # 初始重试延迟
        
        logger.info(f"初始化推理服务客户端，服务地址: {self.base_url}")
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """
        获取或创建aiohttp会话
        
        Returns:
            aiohttp.ClientSession: 异步HTTP会话
        """
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self.session
    
    async def _close_session(self):
        """关闭HTTP会话"""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
    
    async def _request_with_retry(
        self, 
        method: str, 
        endpoint: str, 
        **kwargs
    ) -> Dict[str, Any]:
        """
        带重试机制的HTTP请求
        
        Args:
            method: HTTP方法 (GET, POST等)
            endpoint: API端点
            **kwargs: 传递给aiohttp.request的其他参数
        
        Returns:
            Dict[str, Any]: 响应数据
        
        Raises:
            Exception: 请求失败
        """
        url = urljoin(self.base_url, endpoint)
        last_error = None
        
        for attempt in range(self.retry_count + 1):
            try:
                session = await self._get_session()
                
                async with session.request(method, url, **kwargs) as response:
                    # 检查响应状态
                    if response.status == 200:
                        return await response.json()
                    else:
                        error_data = await response.json() if response.content_type == 'application/json' else None
                        error_msg = f"请求失败: HTTP {response.status}, {error_data or await response.text()}"
                        logger.error(error_msg)
                        raise Exception(error_msg)
                        
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = str(e)
                logger.warning(f"请求尝试 {attempt + 1}/{self.retry_count + 1} 失败: {last_error}")
                
                # 如果不是最后一次尝试，等待后重试
                if attempt < self.retry_count:
                    delay = self.retry_delay * (2 ** attempt)  # 指数退避
                    logger.info(f"{delay:.2f}秒后重试...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"所有重试都失败了，最后错误: {last_error}")
                    raise Exception(f"请求失败: {last_error}")
            except Exception as e:
                last_error = str(e)
                if attempt < self.retry_count:
                    delay = self.retry_delay * (2 ** attempt)
                    logger.info(f"{delay:.2f}秒后重试...")
                    await asyncio.sleep(delay)
                else:
                    raise
        
        # 不应该到达这里，但为了安全
        raise Exception(f"所有重试都失败了，最后错误: {last_error}")
    
    async def health_check(self) -> Dict[str, Any]:
        """
        检查服务健康状态
        
        Returns:
            Dict[str, Any]: 健康状态信息
        """
        try:
            logger.debug("执行健康检查...")
            result = await self._request_with_retry('GET', '/health')
            logger.debug(f"健康检查结果: {result}")
            return result
        except Exception as e:
            logger.error(f"健康检查失败: {str(e)}")
            raise
    
    async def get_model_status(self) -> Dict[str, Any]:
        """
        获取模型状态
        
        Returns:
            Dict[str, Any]: 模型状态信息
        """
        try:
            logger.debug("获取模型状态...")
            result = await self._request_with_retry('GET', '/model/status')
            logger.debug(f"模型状态结果: {result}")
            return result
        except Exception as e:
            logger.error(f"获取模型状态失败: {str(e)}")
            raise
    
    async def generate(
        self, 
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        repetition_penalty: float = 1.0
    ) -> Dict[str, Any]:
        """
        生成文本响应
        
        Args:
            prompt: 推理提示文本
            history: 对话历史
            max_tokens: 最大生成令牌数
            temperature: 采样温度
            top_p: 核采样参数
            repetition_penalty: 重复惩罚参数
        
        Returns:
            Dict[str, Any]: 生成结果
        """
        start_time = time.time()
        
        # 准备请求数据
        request_data = {
            "prompt": prompt,
            "history": history or [],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "repetition_penalty": repetition_penalty
        }
        
        try:
            logger.info(f"发送生成请求，提示长度: {len(prompt)} 字符")
            result = await self._request_with_retry(
                'POST', 
                '/generate',
                json=request_data,
                headers={'Content-Type': 'application/json'}
            )
            
            processing_time = time.time() - start_time
            logger.info(f"生成请求完成，耗时: {processing_time:.2f}秒，响应长度: {len(result.get('text', ''))} 字符")
            
            return result
            
        except Exception as e:
            logger.error(f"生成请求失败: {str(e)}")
            raise
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self._close_session()


# 全局客户端实例
_global_client = None


def get_infer_client() -> InferServiceClient:
    """
    获取全局推理服务客户端实例
    
    Returns:
        InferServiceClient: 推理服务客户端实例
    """
    global _global_client
    
    if _global_client is None:
        _global_client = InferServiceClient()
    
    return _global_client
# 示例用法
async def example_usage():
    """示例用法"""
    async with InferServiceClient() as client:
        try:
            # 健康检查
            health = await client.health_check()
            print(f"健康检查: {health}")
            
            # 获取模型状态
            status = await client.get_model_status()
            print(f"模型状态: {status}")
            
            # 生成文本
            result = await client.generate(
                prompt="你好，请介绍一下你自己",
                max_tokens=200,
                temperature=0.7
            )
            print(f"生成结果: {result['text']}")
            
        except Exception as e:
            print(f"错误: {e}")


if __name__ == '__main__':
    # 运行示例
    asyncio.run(example_usage())