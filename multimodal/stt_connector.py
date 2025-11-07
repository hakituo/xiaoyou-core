# STT 异步连接：负责封装所有对 trm_reflector.py (STT 接口) 的异步调用逻辑
import os
import logging
import asyncio
import httpx
from typing import Dict, Any, Optional
import tempfile
import shutil

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class STTConnector:
    """STT服务异步连接器"""
    
    def __init__(self):
        # 从环境变量获取配置
        self.trm_base_url = os.getenv("TRM_BASE_URL", "http://localhost:8000")
        self.timeout = int(os.getenv("STT_TIMEOUT", "60"))  # STT通常需要更长时间
        self.temp_audio_dir = os.getenv("TEMP_AUDIO_DIR", "voice")
        self._client = None
        
        # 确保临时音频目录存在
        os.makedirs(self.temp_audio_dir, exist_ok=True)
    
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
    
    async def _make_stt_request(
        self,
        endpoint: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """发送STT相关请求"""
        url = f"{self.trm_base_url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        
        try:
            logger.info(f"STT请求: POST {endpoint}")
            response = await self.client.post(url, json=data, headers=headers)
            response.raise_for_status()
            result = response.json()
            logger.info(f"STT请求成功: {endpoint}")
            return result
            
        except httpx.HTTPError as e:
            logger.error(f"STT HTTP错误 ({endpoint}): {str(e)}")
            raise Exception(f"STT服务通信失败: {str(e)}")
        except Exception as e:
            logger.error(f"STT请求失败 ({endpoint}): {str(e)}")
            raise
    
    async def transcribe_audio_file(
        self,
        audio_path: str,
        language: str = "auto",
        speaker_diarization: bool = False
    ) -> Dict[str, Any]:
        """
        转录音频文件（使用asyncio.to_thread隔离文件操作）
        
        Args:
            audio_path: 音频文件路径
            language: 语言代码，默认自动检测
            speaker_diarization: 是否启用说话人分离
            
        Returns:
            包含转录文本和元数据的字典
        """
        # 使用asyncio.to_thread隔离文件存在检查，避免阻塞事件循环
        file_exists = await asyncio.to_thread(os.path.exists, audio_path)
        if not file_exists:
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")
        
        # 准备请求数据
        data = {
            "audio_path": audio_path,
            "language": language,
            "speaker_diarization": speaker_diarization
        }
        
        # 发送请求
        result = await self._make_stt_request("/api/stt/decode", data)
        
        # 处理响应
        return {
            "text": result.get("text", ""),
            "confidence": result.get("confidence", 0.0),
            "language": result.get("detected_language", language),
            "speakers": result.get("speakers", []),
            "audio_path": audio_path
        }
    
    async def transcribe_audio_data(
        self,
        audio_data: bytes,
        audio_format: str = "wav",
        language: str = "auto"
    ) -> Dict[str, Any]:
        """
        转录音频数据（内存中的音频）- 使用asyncio.to_thread隔离文件操作
        
        Args:
            audio_data: 音频二进制数据
            audio_format: 音频格式（如wav, mp3等）
            language: 语言代码，默认自动检测
            
        Returns:
            包含转录文本和元数据的字典
        """
        # 创建临时文件
        temp_file_path = None
        try:
            # 生成临时文件名
            temp_filename = f"temp_{hash(audio_data)}_{asyncio.get_event_loop().time()}.{audio_format}"
            temp_file_path = os.path.join(self.temp_audio_dir, temp_filename)
            
            # 使用asyncio.to_thread隔离文件写入操作
            await asyncio.to_thread(
                lambda: open(temp_file_path, 'wb').write(audio_data)
            )
            
            # 调用转录方法
            return await self.transcribe_audio_file(temp_file_path, language)
            
        finally:
            # 清理临时文件 - 使用asyncio.to_thread隔离文件删除操作
            if temp_file_path:
                file_exists = await asyncio.to_thread(os.path.exists, temp_file_path)
                if file_exists:
                    try:
                        await asyncio.to_thread(os.remove, temp_file_path)
                    except Exception as e:
                        logger.warning(f"无法删除临时音频文件: {str(e)}")
    
    async def batch_transcribe(
        self,
        audio_files: list[str],
        language: str = "auto",
        concurrency_limit: int = 3
    ) -> list[Dict[str, Any]]:
        """
        批量转录多个音频文件
        
        Args:
            audio_files: 音频文件路径列表
            language: 语言代码
            concurrency_limit: 并发限制
            
        Returns:
            转录结果列表
        """
        semaphore = asyncio.Semaphore(concurrency_limit)
        
        async def _transcribe_file(file_path):
            async with semaphore:
                try:
                    result = await self.transcribe_audio_file(file_path, language)
                    return {"success": True, "result": result, "file": file_path}
                except Exception as e:
                    logger.error(f"转录文件失败 {file_path}: {str(e)}")
                    return {"success": False, "error": str(e), "file": file_path}
        
        tasks = [_transcribe_file(file) for file in audio_files]
        return await asyncio.gather(*tasks)
    
    async def get_supported_languages(self) -> list[str]:
        """
        获取支持的语言列表
        
        Returns:
            支持的语言代码列表
        """
        try:
            response = await self.client.get(f"{self.trm_base_url}/api/stt/languages")
            response.raise_for_status()
            return response.json().get("languages", ["zh-CN", "en-US"])
        except:
            # 如果接口不可用，返回默认列表
            logger.warning("获取支持的语言列表失败，返回默认值")
            return ["zh-CN", "en-US"]
    
    async def health_check(self) -> bool:
        """
        检查STT服务健康状态
        
        Returns:
            服务是否健康
        """
        try:
            response = await self.client.get(f"{self.trm_base_url}/health")
            return response.status_code == 200
        except:
            return False
    
    def estimate_transcription_time(self, audio_file_path: str) -> float:
        """
        估算转录时间（基于文件大小）
        
        Args:
            audio_file_path: 音频文件路径
            
        Returns:
            估算的秒数
        """
        try:
            file_size = os.path.getsize(audio_file_path) / (1024 * 1024)  # MB
            # 简单估算：每MB音频约需要2秒处理时间
            return max(1.0, file_size * 2)
        except:
            return 5.0  # 默认返回5秒
    
    async def estimate_transcription_time_async(self, audio_file_path: str) -> float:
        """
        异步版本的转录时间估算
        
        Args:
            audio_file_path: 音频文件路径
            
        Returns:
            估算的秒数
        """
        # 使用asyncio.to_thread隔离文件大小获取操作
        try:
            file_size = await asyncio.to_thread(
                lambda: os.path.getsize(audio_file_path) / (1024 * 1024)
            )
            return max(1.0, file_size * 2)
        except:
            return 5.0  # 默认返回5秒

# 创建全局STT连接器实例
stt_connector = None

def get_stt_connector() -> STTConnector:
    """
    获取STT连接器实例（单例模式）
    
    Returns:
        STTConnector实例
    """
    global stt_connector
    if stt_connector is None:
        stt_connector = STTConnector()
    return stt_connector

async def initialize_stt_connector():
    """
    初始化STT连接器
    """
    connector = get_stt_connector()
    # 验证连接
    is_healthy = await connector.health_check()
    if is_healthy:
        logger.info("STT连接器初始化成功")
    else:
        logger.warning("STT服务可能不可用，将在需要时重试")
    return connector

async def shutdown_stt_connector():
    """
    关闭STT连接器
    """
    global stt_connector
    if stt_connector:
        await stt_connector.close()
        stt_connector = None
        logger.info("STT连接器已关闭")

# 示例使用
async def example_usage():
    """示例使用方法"""
    async with STTConnector() as connector:
        try:
            # 健康检查
            is_healthy = await connector.health_check()
            print(f"STT服务状态: {'健康' if is_healthy else '不健康'}")
            
            # 获取支持的语言
            languages = await connector.get_supported_languages()
            print(f"支持的语言: {languages}")
            
            # 注意：实际使用时需要提供真实的音频文件路径
            # result = await connector.transcribe_audio_file(
            #     "path/to/audio.wav",
            #     language="zh-CN"
            # )
            # print(f"转录结果: {result['text']}")
            
        except Exception as e:
            print(f"错误: {str(e)}")

if __name__ == "__main__":
    asyncio.run(example_usage())