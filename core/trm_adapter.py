# 异步通信：负责封装所有对 trm_reflector.py (HTTP) 的异步调用逻辑
import os
import logging
import asyncio
import httpx
import json
from typing import Dict, Any, Optional

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TRMAdapter:
    """TRM异步通信适配器"""
    
    def __init__(self):
        # 从环境变量获取TRM服务地址，默认localhost:8000
        self.trm_base_url = os.getenv("TRM_BASE_URL", "http://localhost:8000")
        self.timeout = int(os.getenv("TRM_TIMEOUT", "30"))
        self._client = None
    
    @property
    def client(self) -> httpx.AsyncClient:
        """获取或创建httpx异步客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True
            )
        return self._client
    
    async def close(self):
        """关闭httpx客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()
    
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """通用请求方法"""
        url = f"{self.trm_base_url}{endpoint}"
        headers = {
            "Content-Type": "application/json",
            **kwargs.pop("headers", {})
        }
        
        try:
            logger.info(f"TRM请求: {method} {endpoint}")
            
            if method.lower() == "get":
                response = await self.client.get(url, params=data, headers=headers, **kwargs)
            else:
                response = await self.client.post(url, json=data, headers=headers, **kwargs)
            
            response.raise_for_status()
            result = response.json()
            logger.info(f"TRM请求成功: {endpoint}")
            return result
            
        except httpx.HTTPError as e:
            logger.error(f"TRM HTTP错误 ({endpoint}): {str(e)}")
            raise Exception(f"TRM服务通信失败: {str(e)}")
        except Exception as e:
            logger.error(f"TRM请求失败 ({endpoint}): {str(e)}")
            raise
    
    async def llm_query(
        self,
        prompt: str,
        model: str = "default",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        **kwargs
    ) -> str:
        """
        异步调用LLM查询接口
        
        Args:
            prompt: 查询提示词
            model: 模型名称
            max_tokens: 最大生成长度
            temperature: 温度参数
            **kwargs: 其他参数
            
        Returns:
            LLM生成的文本
        """
        data = {
            "prompt": prompt,
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **kwargs
        }
        
        result = await self._make_request("POST", "/api/llm/query", data=data)
        return result.get("result", "")
    
    async def stt_decode(
        self,
        audio_path: str,
        language: str = "auto",
        **kwargs
    ) -> str:
        """
        异步调用语音转文字接口
        
        Args:
            audio_path: 音频文件路径
            language: 语言代码，默认自动检测
            **kwargs: 其他参数
            
        Returns:
            转写后的文本
        """
        data = {
            "audio_path": audio_path,
            "language": language,
            **kwargs
        }
        
        result = await self._make_request("POST", "/api/stt/decode", data=data)
        return result.get("text", "")
    
    async def image_generate(
        self,
        prompt: str,
        style: str = "default",
        size: str = "1024x1024",
        **kwargs
    ) -> str:
        """
        异步调用图像生成接口
        
        Args:
            prompt: 图像生成提示词
            style: 图像风格
            size: 图像尺寸
            **kwargs: 其他参数
            
        Returns:
            生成的图像路径
        """
        data = {
            "prompt": prompt,
            "style": style,
            "size": size,
            **kwargs
        }
        
        result = await self._make_request("POST", "/api/image/generate", data=data)
        return result.get("image_path", "")
    
    async def health_check(self) -> bool:
        """
        检查TRM服务健康状态
        
        Returns:
            服务是否健康
        """
        try:
            result = await self._make_request("GET", "/health")
            return result.get("status") == "healthy"
        except:
            return False
    
    async def batch_llm_queries(
        self,
        queries: list[Dict[str, Any]],
        concurrency_limit: int = 5
    ) -> list[Dict[str, Any]]:
        """
        并发批量处理LLM查询
        
        Args:
            queries: 查询列表，每项包含查询参数
            concurrency_limit: 并发限制
            
        Returns:
            查询结果列表
        """
        semaphore = asyncio.Semaphore(concurrency_limit)
        
        async def _process_query(query):
            async with semaphore:
                try:
                    result = await self.llm_query(**query)
                    return {"success": True, "result": result, "query": query}
                except Exception as e:
                    logger.error(f"批量查询失败: {str(e)}")
                    return {"success": False, "error": str(e), "query": query}
        
        tasks = [_process_query(q) for q in queries]
        return await asyncio.gather(*tasks)

# 创建全局TRM适配器实例
trm_adapter = None

def get_trm_adapter() -> TRMAdapter:
    """
    获取TRM适配器实例（单例模式）
    
    Returns:
        TRMAdapter实例
    """
    global trm_adapter
    if trm_adapter is None:
        trm_adapter = TRMAdapter()
    return trm_adapter

async def initialize_trm_adapter():
    """
    初始化TRM适配器
    """
    adapter = get_trm_adapter()
    # 验证连接
    is_healthy = await adapter.health_check()
    if is_healthy:
        logger.info("TRM适配器初始化成功")
    else:
        logger.warning("TRM服务可能不可用，将在需要时重试")
    return adapter

async def shutdown_trm_adapter():
    """
    关闭TRM适配器
    """
    global trm_adapter
    if trm_adapter:
        await trm_adapter.close()
        trm_adapter = None
        logger.info("TRM适配器已关闭")

# 示例使用
async def example_usage():
    """示例使用方法"""
    async with TRMAdapter() as adapter:
        try:
            # LLM查询示例
            response = await adapter.llm_query(
                prompt="你好，请介绍一下自己",
                model="gpt-3.5-turbo",
                max_tokens=500
            )
            print(f"LLM响应: {response}")
            
            # 健康检查
            is_healthy = await adapter.health_check()
            print(f"TRM服务状态: {'健康' if is_healthy else '不健康'}")
            
        except Exception as e:
            print(f"错误: {str(e)}")

if __name__ == "__main__":
    asyncio.run(example_usage())