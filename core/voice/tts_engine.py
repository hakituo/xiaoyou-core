#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TTS引擎模块
"""
import logging
import asyncio
import io
import os
import uuid
import aiohttp
from typing import Dict, Any, Optional
import numpy as np
try:
    import soundfile as sf
except ImportError:
    sf = None

try:
    import edge_tts
except ImportError:
    edge_tts = None

from config.integrated_config import get_settings
from core.utils.logger import get_logger

logger = get_logger("TTS_ENGINE")

class TTSEngine:
    """
    TTS引擎抽象基类
    """
    
    def __init__(self):
        self.initialized = False
    
    async def initialize(self):
        """
        初始化引擎
        """
        self.initialized = True
    
    async def synthesize(self, text: str, **kwargs) -> np.ndarray:
        """
        合成语音
        
        Args:
            text: 要合成的文本
            **kwargs: 其他参数
            
        Returns:
            numpy.ndarray: 音频数据 (float32)
        """
        raise NotImplementedError("子类必须实现synthesize方法")
    
    async def shutdown(self):
        """
        关闭引擎
        """
        self.initialized = False


class GPTSoVITSEngine(TTSEngine):
    """
    GPT-SoVITS 引擎实现
    """
    def __init__(self, api_url="http://127.0.0.1:9880/tts", default_lang="zh"):
        super().__init__()
        self.api_url = api_url
        self.default_lang = default_lang
        self.sample_rate = 32000 # GPT-SoVITS 默认通常是 32000
        
    async def initialize(self):
        await super().initialize()
        # Check for configured models and set them
        settings = get_settings()
        if settings.voice.gpt_model_path:
            await self.set_gpt_weights(settings.voice.gpt_model_path)
        if settings.voice.sovits_model_path:
            await self.set_sovits_weights(settings.voice.sovits_model_path)

    async def set_gpt_weights(self, weights_path: str):
        # 增加防御性检查：如果是 "default" 或空，直接忽略
        if not weights_path or weights_path.lower() == "default":
            logger.debug(f"Ignoring set_gpt_weights for value: {weights_path}")
            return
            
        try:
            url = self.api_url.replace("/tts", "/set_gpt_weights")
            params = {"weights_path": weights_path}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        logger.info(f"Successfully set GPT weights to {weights_path}")
                    else:
                        logger.error(f"Failed to set GPT weights: {await response.text()}")
        except Exception as e:
            logger.error(f"Error setting GPT weights: {e}")

    async def set_sovits_weights(self, weights_path: str):
        # 增加防御性检查
        if not weights_path or weights_path.lower() == "default":
            logger.debug(f"Ignoring set_sovits_weights for value: {weights_path}")
            return

        try:
            url = self.api_url.replace("/tts", "/set_sovits_weights")
            params = {"weights_path": weights_path}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        logger.info(f"Successfully set SoVITS weights to {weights_path}")
                    else:
                        logger.error(f"Failed to set SoVITS weights: {await response.text()}")
        except Exception as e:
            logger.error(f"Error setting SoVITS weights: {e}")

    async def synthesize(self, text: str, **kwargs) -> np.ndarray:
        """
        调用 GPT-SoVITS API 合成语音
        """
        lang = kwargs.get("lang", self.default_lang)
        # 提取情感参数，GPT-SoVITS可能支持 emotion_prompt 等，这里先做基础映射
        # 实际API参数取决于部署的GPT-SoVITS版本，这里假设标准GET接口
        
        # 动态获取默认参考音频路径
        settings = get_settings()
        default_ref_audio = settings.voice.reference_audio
        
        if not default_ref_audio:
            default_ref_audio = os.path.join(os.getcwd(), "ref_audio", "female", "ref_calm.wav")
        elif not os.path.isabs(default_ref_audio):
             # Ensure relative paths are resolved relative to CWD
             default_ref_audio = os.path.join(os.getcwd(), default_ref_audio)
        
        # 确定最终使用的参考音频路径
        ref_audio_path = kwargs.get("ref_audio_path") or kwargs.get("reference_audio") or default_ref_audio
        
        # 确保 ref_audio_path 是绝对路径
        if ref_audio_path and not os.path.isabs(ref_audio_path):
            # 如果是相对路径，尝试拼接当前工作目录
            # 注意：如果 ref_audio_path 已经包含了 ref_audio/female/ 前缀，直接拼接即可
            ref_audio_path = os.path.abspath(os.path.join(os.getcwd(), ref_audio_path))
            
        # 再次检查文件是否存在
        if ref_audio_path and not os.path.exists(ref_audio_path):
             logger.warning(f"Reference audio path does not exist locally: {ref_audio_path}")
             # 如果本地不存在，可能 GPT-SoVITS 服务端也访问不到（假设在同一机器）
             # 但也有可能服务端能访问，所以还是传过去，只是记录警告
        
        params = {
            "text": text,
            "text_lang": lang,
            "ref_audio_path": ref_audio_path,
            "prompt_text": kwargs.get("prompt_text", "这是中文纯语音测试，不包含英文内容"),
            "prompt_lang": kwargs.get("prompt_lang", "zh"),
            "top_k": kwargs.get("top_k", 5),
            "top_p": kwargs.get("top_p", 1.0),
            "temperature": kwargs.get("temperature", 1.0),
            "speed": kwargs.get("speed", 1.0),
        }
        
        # 可选参数，如果存在则添加
        if "batch_size" in kwargs:
            params["batch_size"] = kwargs["batch_size"]
        if "speed_factor" in kwargs:
            params["speed_factor"] = kwargs["speed_factor"]
        if "pitch" in kwargs: # 部分API可能支持
            params["pitch"] = kwargs["pitch"]

        
        # 如果有参考音频参数，也可以在这里添加
        # if "ref_audio_path" in kwargs:
        #     params["ref_audio_path"] = kwargs["ref_audio_path"]
        # if "prompt_text" in kwargs:
        #     params["prompt_text"] = kwargs["prompt_text"]
        # if "prompt_lang" in kwargs:
        #     params["prompt_lang"] = kwargs["prompt_lang"]

        try:
            logger.info(f"[GPT-SoVITS] Synthesizing: {text[:20]}... (Lang: {lang})")
            async with aiohttp.ClientSession() as session:
                # 增加timeout，防止慢请求导致的默认超时
                timeout = aiohttp.ClientTimeout(total=300)
                async with session.get(self.api_url, params=params, timeout=timeout) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"GPT-SoVITS API Error: {response.status} - {error_text}")
                        return np.zeros(24000, dtype=np.float32)
                    
                    audio_content = await response.read()
                    
            if not audio_content:
                logger.warning("GPT-SoVITS returned empty audio data (bytes length is 0)")
                return np.zeros(24000, dtype=np.float32)

            # Decode using soundfile
            if sf:
                try:
                    with io.BytesIO(audio_content) as f:
                        data, sample_rate = sf.read(f, dtype='float32')
                    return data
                except Exception as decode_err:
                     logger.error(f"Failed to decode audio content (len={len(audio_content)}): {decode_err}")
                     return np.zeros(24000, dtype=np.float32)
            else:
                logger.error("soundfile not installed, cannot decode audio")
                return np.zeros(24000, dtype=np.float32)
                
        except Exception as e:
            logger.error(f"GPT-SoVITS synthesis failed: {e}", exc_info=True)
            return np.zeros(24000, dtype=np.float32)


class EdgeTTSEngine(TTSEngine):
    """
    Edge TTS 引擎实现
    """
    def __init__(self, voice="zh-CN-XiaoxiaoNeural", rate="+0%"):
        super().__init__()
        self.voice = voice
        self.rate = rate
        self.sample_rate = 24000 # Edge-TTS 默认通常是 24000
        if not edge_tts:
            logger.warning("edge-tts package not found. Please install it with: pip install edge-tts")
        if not sf:
            logger.warning("soundfile package not found. Please install it with: pip install soundfile")

    async def synthesize(self, text: str, **kwargs) -> np.ndarray:
        if not edge_tts:
            logger.error("edge-tts not installed, falling back to zeros")
            return np.zeros(16000, dtype=np.float32)
            
        voice = kwargs.get("voice", self.voice)
        rate = kwargs.get("rate", self.rate)
        
        # 处理语速格式
        if isinstance(rate, (int, float)):
            rate_str = f"{int(rate * 100 - 100):+d}%"
        else:
            rate_str = str(rate)
            if not rate_str.endswith("%") and not rate_str.startswith("+") and not rate_str.startswith("-"):
                 rate_str = "+0%"

        try:
            logger.info(f"[EdgeTTS] Synthesizing: {text[:20]}... (Voice: {voice}, Rate: {rate_str})")
            communicate = edge_tts.Communicate(text, voice, rate=rate_str)
            
            # Capture audio data in memory
            audio_data = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data += chunk["data"]
            
            if not audio_data:
                logger.warning("EdgeTTS returned empty audio data")
                return np.zeros(24000, dtype=np.float32)

            # Decode using soundfile
            if sf:
                with io.BytesIO(audio_data) as f:
                    data, sample_rate = sf.read(f, dtype='float32')
                return data
            else:
                # 如果没有soundfile，我们无法解码mp3/webm数据为numpy数组
                # 这里只能返回空或者抛出异常
                logger.error("soundfile not installed, cannot decode audio")
                return np.zeros(24000, dtype=np.float32)
                
        except Exception as e:
            logger.error(f"EdgeTTS synthesis failed: {e}")
            return np.zeros(24000, dtype=np.float32)


class DummyTTSEngine(TTSEngine):
    """
    虚拟TTS引擎 (用于测试或未配置真实引擎时)
    """
    def __init__(self, sample_rate=24000):
        super().__init__()
        self.sample_rate = sample_rate
        
    async def synthesize(self, text: str, **kwargs) -> np.ndarray:
        logger.info(f"[DummyTTS] Synthesizing text: {text[:50]}...")
        # 生成静音音频，长度根据文本长度估算
        duration = min(len(text) * 0.1, 5.0)  # 每个字符0.1秒，最多5秒
        num_samples = int(duration * self.sample_rate)
        return np.zeros(num_samples, dtype=np.float32)


class TTSManager:
    """
    TTS管理器
    负责管理TTS引擎实例和分发合成任务
    """
    
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TTSManager, cls).__new__(cls)
            cls._instance._initialized_manager = False
        return cls._instance

    def __init__(self):
        """
        初始化TTS管理器
        """
        if self._initialized_manager:
            return
            
        self.settings = get_settings()
        self.sample_rate = 24000
        self.engine: Optional[TTSEngine] = None
        self.initialized = False
        self._initialized_manager = True
        logger.info("TTSManager created")
    
    async def initialize(self):
        """
        初始化TTS引擎
        """
        if self.initialized:
            return
            
        logger.info("Initializing TTS Manager...")
        
        # 根据配置选择引擎
        engine_type = self.settings.voice.default_engine
        default_voice = self.settings.voice.default_voice
        default_speed = self.settings.voice.default_speed
        
        if engine_type == "edge-tts" or engine_type == "edge":
            logger.info(f"Initializing EdgeTTS engine with voice: {default_voice}")
            self.engine = EdgeTTSEngine(voice=default_voice, rate=default_speed)
        elif engine_type == "gpt-sovits" or engine_type == "gpt_sovits":
            logger.info(f"Initializing GPT-SoVITS engine")
            # 可以从配置中读取API URL，这里暂用默认值
            self.engine = GPTSoVITSEngine()
        else:
            logger.info(f"Using default/dummy engine for type: {engine_type}")
            self.engine = DummyTTSEngine(self.sample_rate)
            
        await self.engine.initialize()
        
        # 动态更新采样率
        if hasattr(self.engine, 'sample_rate'):
            self.sample_rate = self.engine.sample_rate
            logger.info(f"Updated TTSManager sample rate to: {self.sample_rate}")
            
        self.initialized = True
        logger.info("TTS engine initialized")
    
    async def synthesize(self, text: str, **kwargs) -> np.ndarray:
        """
        合成语音
        """
        if not self.initialized or not self.engine:
            await self.initialize()
            
        return await self.engine.synthesize(text, **kwargs)

    async def clone(self, **kwargs) -> np.ndarray:
        """
        克隆语音 (保留旧接口兼容性)
        """
        text = kwargs.pop("text", "")
        # reference_audio = kwargs.get("reference_audio") # 目前未使用的参数
        
        return await self.synthesize(text, **kwargs)
    
    async def shutdown(self):
        """
        关闭TTS引擎
        """
        if self.engine:
            await self.engine.shutdown()
        self.initialized = False
        logger.info("TTS engine shutdown")

# 方便导入的工厂函数
def get_tts_manager() -> TTSManager:
    return TTSManager()
