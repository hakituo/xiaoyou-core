#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
阿里云 DashScope Qwen3-TTS 云端 API 客户端
支持声音克隆功能
"""
import os
import base64
import aiohttp
from typing import Optional, Dict, Any
import numpy as np

from core.utils.logger import get_logger
from core.contracts import ModuleInitState
from .tts_engine import TTSEngine

logger = get_logger('qwen3_tts_cloud')

class Qwen3TTSCloudEngine(TTSEngine):
    """
    阿里云 DashScope Qwen3-TTS 云端引擎
    
    支持模型：
    - qwen3-tts-instruct-flash-realtime (实时语音合成)
    - qwen3-tts-flash (标准语音合成)
    
    功能特性：
    - ✅ 声音克隆（通过参考音频）
    - ✅ 多语言支持（中/英/法/德/意/日/韩/西/葡/俄/西班牙）
    - ✅ 情感控制
    - ✅ 语速/音量调节
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "qwen3-tts-flash",
        base_url: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    ):
        """
        初始化 Qwen3-TTS 云端引擎
        
        Args:
            api_key: DashScope API Key
            model: 模型名称（qwen3-tts-flash 或 qwen3-tts-instruct-flash）
            base_url: API 端点
        """
        super().__init__()
        
        # 优先级：参数 > 环境变量
        self.api_key = api_key or os.getenv('DASHSCOPE_API_KEY')
        
        self.model = model
        self.base_url = base_url
        self.timeout = 300  # 5 分钟超时（生成长音频可能需要）
        self.session: Optional[aiohttp.ClientSession] = None
        self.initialized = False
        
        # 默认参数
        self.default_voice = "Cherry"  # 默认音色（中文女声）
        self.default_language = "Chinese"
        self.default_speed = 1.0
        self.default_volume = 1.0
        
        if not self.api_key:
            logger.warning("DashScope API Key not found. Please set DASHSCOPE_API_KEY in .env or config.")
        else:
            logger.info(f"Qwen3-TTS Cloud Engine initialized with model: {self.model}")
    
    async def initialize(self):
        """初始化引擎"""
        if not self.initialized:
            await self._get_session()
            self.initialized = True
            logger.info("Qwen3-TTS Cloud Engine initialized")
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 HTTP 会话"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
            )
        return self.session
    
    async def _close_session(self):
        """关闭 HTTP 会话"""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
    
    async def shutdown(self):
        """关闭引擎"""
        await self._close_session()
        self.initialized = False
    
    async def synthesize(
        self,
        text: str,
        ref_audio_path: Optional[str] = None,
        ref_text: Optional[str] = None,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        speed: Optional[float] = None,
        volume: Optional[float] = None,
        instructions: Optional[str] = None,
        **kwargs
    ) -> np.ndarray:
        """
        合成语音（支持声音克隆）
        
        Args:
            text: 要合成的文本
            ref_audio_path: 参考音频路径（用于声音克隆）
            ref_text: 参考音频的文本内容
            voice: 音色名称（不克隆时使用）
            language: 语种（Chinese, English 等）
            speed: 语速（0.5-2.0）
            volume: 音量（0.5-2.0）
            instructions: 指令控制（仅 qwen3-tts-instruct-flash 支持）
            **kwargs: 其他参数
            
        Returns:
            numpy.ndarray: 音频数据 (float32)
        """
        if not self.initialized:
            await self.initialize()
        
        # 构建请求参数（根据官方文档格式）
        payload = {
            "model": self.model,
            "input": {
                "text": text,
                "voice": voice or self.default_voice,
                "language_type": language or self.default_language,
            }
        }
        
        # 声音克隆模式：添加参考音频
        if ref_audio_path and os.path.exists(ref_audio_path):
            logger.info(f"Using voice cloning with reference audio: {ref_audio_path}")
            
            # 读取并编码参考音频
            ref_audio_data = await self._encode_audio_to_base64(ref_audio_path)
            
            # 构建声音克隆参数
            payload["input"]["ref_audio"] = ref_audio_data
            
            # 如果有参考文本，也加上（提高克隆质量）
            if ref_text:
                payload["input"]["ref_text"] = ref_text
                logger.info(f"Using reference text: {ref_text[:50]}...")
        
        # 指令控制（仅 instruct 模型支持）
        if instructions and "instruct" in self.model.lower():
            payload["input"]["instructions"] = instructions
            
            # 是否优化指令
            if kwargs.get("optimize_instructions", False):
                payload["input"]["optimize_instructions"] = True
        
        # 发送请求
        try:
            async with self.session.post(self.base_url, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Qwen3-TTS API Error: {response.status} - {error_text}")
                    raise RuntimeError(f"Qwen3-TTS API Error: {response.status} - {error_text}")
                
                # 读取响应
                result = await response.json()
                
                # 调试：打印完整响应
                logger.debug(f"API Response: {result}")
                
                # 检查任务状态
                if result.get("output", {}).get("task_status") == "FAILED":
                    error_msg = result.get("output", {}).get("error_msg", "Unknown error")
                    raise RuntimeError(f"Qwen3-TTS task failed: {error_msg}")
                
                # 获取音频数据（支持两种格式）
                # 格式 1: output.audio.url (URL 形式)
                # 格式 2: output.audio.data (Base64 形式)
                output_audio = result.get("output", {}).get("audio", {})
                
                # 如果是 dict，提取 url 或 data
                if isinstance(output_audio, dict):
                    audio_url = output_audio.get("url")
                    audio_data_base64 = output_audio.get("data")
                else:
                    # 兼容旧格式
                    audio_url = result.get("output", {}).get("audio_url")
                    audio_data_base64 = result.get("output", {}).get("audio", "")
                
                logger.debug(f"Audio URL: {audio_url}")
                logger.debug(f"Audio data (first 50 chars): {str(audio_data_base64)[:50] if audio_data_base64 else None}")
                
                if audio_url:
                    # 下载音频
                    async with aiohttp.ClientSession() as download_session:
                        async with download_session.get(audio_url) as audio_response:
                            if audio_response.status != 200:
                                raise RuntimeError(f"Failed to download audio: {audio_response.status}")
                            audio_bytes = await audio_response.read()
                elif audio_data_base64:
                    # 直接使用 Base64 数据
                    if isinstance(audio_data_base64, str):
                        audio_bytes = base64.b64decode(audio_data_base64)
                    elif isinstance(audio_data_base64, dict):
                        # 嵌套结构
                        audio_bytes = audio_data_base64.get("data")
                        if isinstance(audio_bytes, str):
                            audio_bytes = base64.b64decode(audio_bytes)
                    else:
                        audio_bytes = audio_data_base64
                else:
                    raise RuntimeError("No audio URL or data found in response")
                
                # 转换为 numpy 数组
                import io
                import soundfile as sf
                
                audio_io = io.BytesIO(audio_bytes)
                audio_data, sample_rate = sf.read(audio_io, dtype='float32')
                
                logger.info(f"Qwen3-TTS synthesis completed. Duration: {len(audio_data)/sample_rate:.2f}s")
                
                return audio_data
                
        except Exception as e:
            logger.error(f"Qwen3-TTS synthesis failed: {e}")
            raise
    
    async def _encode_audio_to_base64(self, audio_path: str) -> str:
        """
        将音频文件编码为 Base64
        
        Args:
            audio_path: 音频文件路径
            
        Returns:
            str: Base64 编码的音频数据
        """
        try:
            # 异步读取文件
            import asyncio
            
            def _read_file():
                with open(audio_path, 'rb') as f:
                    return f.read()
            
            loop = asyncio.get_running_loop()
            audio_data = await loop.run_in_executor(None, _read_file)
            
            # 编码为 Base64
            base64_data = base64.b64encode(audio_data).decode('utf-8')
            
            # 获取文件扩展名
            ext = os.path.splitext(audio_path)[1].lower()
            mime_type = {
                '.wav': 'audio/wav',
                '.mp3': 'audio/mpeg',
                '.flac': 'audio/flac',
                '.aac': 'audio/aac',
            }.get(ext, 'audio/wav')
            
            # 返回 Data URL 格式
            return f"data:{mime_type};base64,{base64_data}"
            
        except Exception as e:
            logger.error(f"Failed to encode audio to base64: {e}")
            raise
    
    async def synthesize_bytes(
        self,
        text: str,
        ref_audio_path: Optional[str] = None,
        ref_text: Optional[str] = None,
        **kwargs
    ) -> Optional[bytes]:
        """
        合成语音并返回字节
        
        Args:
            text: 要合成的文本
            ref_audio_path: 参考音频路径
            ref_text: 参考音频文本
            **kwargs: 其他参数
            
        Returns:
            bytes: WAV 格式的音频字节
        """
        try:
            audio_array = await self.synthesize(
                text=text,
                ref_audio_path=ref_audio_path,
                ref_text=ref_text,
                **kwargs
            )
            
            # 转换为 WAV 字节
            import io
            import soundfile as sf
            
            wav_io = io.BytesIO()
            sf.write(wav_io, audio_array, 24000, format='WAV')  # Qwen3-TTS 通常是 24kHz
            return wav_io.getvalue()
            
        except Exception as e:
            logger.error(f"Qwen3-TTS synthesize_bytes failed: {e}")
            return None
    
    def get_status(self) -> Dict[str, Any]:
        """获取引擎状态"""
        init_state = (
            ModuleInitState.INITIALIZED
            if bool(self.initialized)
            else ModuleInitState.NOT_INITIALIZED
        )
        return {
            "status": init_state.value,  # legacy
            "init_state": init_state.value,
            "model": self.model,
            "api_key_configured": bool(self.api_key),
            "session_active": self.session is not None and not self.session.closed,
            "default_voice": self.default_voice,
            "supports_voice_cloning": True,
        }
