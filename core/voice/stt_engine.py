#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语音转文字引擎模块
"""
import logging
import asyncio
from typing import Dict, Any, Optional
from config.integrated_config import get_settings
from core.utils.logger import get_logger

logger = get_logger("STT_ENGINE")

class STTEngine:
    """
    STT引擎抽象基类
    """
    
    def __init__(self):
        self.initialized = False
    
    async def initialize(self):
        """
        初始化引擎
        """
        self.initialized = True
    
    async def transcribe(self, audio_data: bytes, **kwargs) -> Dict[str, Any]:
        """
        转录音频
        
        Args:
            audio_data: 音频数据
            **kwargs: 其他参数
        
        Returns:
            转录结果
        """
        raise NotImplementedError("子类必须实现transcribe方法")
    
    async def shutdown(self):
        """
        关闭引擎
        """
        self.initialized = False


class DummySTTEngine(STTEngine):
    """
    虚拟STT引擎 (用于测试或未配置真实引擎时)
    """
    async def transcribe(self, audio_data: bytes, **kwargs) -> Dict[str, Any]:
        logger.info(f"[DummySTT] Transcribing audio size: {len(audio_data)} bytes")
        # 简化实现，返回模拟转录结果
        return {
            "text": "这是一段模拟的转录文本",
            "segments": [],
            "language": "zh"
        }


class FasterWhisperSTTEngine(STTEngine):
    """
    Faster Whisper STT Engine
    """
    def __init__(self, model_size="base", device="cuda", compute_type="float16"):
        super().__init__()
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model = None

    async def initialize(self):
        if self.initialized:
            return
        
        try:
            from faster_whisper import WhisperModel
            import torch
            
            # Check for CUDA
            if self.device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA not available, falling back to CPU")
                self.device = "cpu"
                self.compute_type = "int8"
            
            logger.info(f"Loading Faster Whisper model: {self.model_size} on {self.device}...")
            # Run in executor to avoid blocking event loop
            loop = asyncio.get_running_loop()
            self.model = await loop.run_in_executor(
                None, 
                lambda: WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
            )
            self.initialized = True
            logger.info("Faster Whisper model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load Faster Whisper model: {e}")
            self.initialized = False
            raise e  # Re-raise to allow fallback

    async def transcribe(self, audio_data: bytes, **kwargs) -> Dict[str, Any]:
        if not self.initialized or not self.model:
            try:
                await self.initialize()
            except Exception as e:
                return {"text": "", "error": f"STT Engine failed to initialize: {e}"}
            
        try:
            # Faster Whisper expects file path or file-like object
            import io
            audio_file = io.BytesIO(audio_data)
            
            # Run in executor
            loop = asyncio.get_running_loop()
            
            def _transcribe():
                segments, info = self.model.transcribe(audio_file, beam_size=5)
                # Convert generator to list
                segment_list = list(segments)
                text = "".join([segment.text for segment in segment_list])
                return {
                    "text": text,
                    "language": info.language,
                    "segments": [
                        {"start": s.start, "end": s.end, "text": s.text} 
                        for s in segment_list
                    ]
                }
                
            return await loop.run_in_executor(None, _transcribe)
            
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return {"text": "", "error": str(e)}


class STTManager:
    """
    STT管理器
    负责管理STT引擎实例和分发转录任务
    """
    
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(STTManager, cls).__new__(cls)
            cls._instance._initialized_manager = False
        return cls._instance

    def __init__(self):
        """
        初始化STT管理器
        """
        if self._initialized_manager:
            return
            
        self.settings = get_settings()
        self.engine: Optional[STTEngine] = None
        self.initialized = False
        self._initialized_manager = True
        logger.info("STTManager created")
    
    async def initialize(self):
        """
        初始化STT引擎
        """
        if self.initialized:
            return
            
        logger.info("Initializing STT Manager...")
        
        # 尝试自动检测最佳引擎，默认为 faster_whisper
        # 由于 VoiceSettings 可能没有 stt_engine 字段，我们使用 getattr 安全获取，或者直接默认
        engine_type = getattr(self.settings.voice, "stt_engine", "faster_whisper")
        
        # 尝试使用 Faster Whisper
        if engine_type == "whisper" or engine_type == "faster_whisper" or engine_type == "default" or engine_type == "auto":
             try:
                 import faster_whisper
                 import torch
                 device = "cuda" if torch.cuda.is_available() else "cpu"
                 compute_type = "float16" if device == "cuda" else "int8"
                 
                 # 使用配置的模型大小，默认为 base
                 model_size = "base"
                 
                 self.engine = FasterWhisperSTTEngine(model_size=model_size, device=device, compute_type=compute_type)
                 logger.info(f"Selected FasterWhisperSTTEngine (device={device}, model={model_size})")
                 # 立即尝试初始化以验证可用性
                 await self.engine.initialize()
             except ImportError:
                 logger.warning("faster_whisper not found, falling back to Dummy")
                 self.engine = DummySTTEngine()
             except Exception as e:
                 logger.error(f"Error initializing FasterWhisper: {e}, falling back to Dummy")
                 self.engine = DummySTTEngine()
                 await self.engine.initialize()
        else:
            logger.info(f"Using default/dummy engine for type: {engine_type}")
            self.engine = DummySTTEngine()
            await self.engine.initialize()
            
        self.initialized = True
        logger.info("STT engine initialized")
    
    async def get_engine(self) -> STTEngine:
        """
        获取STT引擎实例
        """
        if not self.initialized or not self.engine:
            await self.initialize()
        return self.engine
        
    async def transcribe(self, audio_data: bytes, **kwargs) -> Dict[str, Any]:
        """
        转录音频
        """
        engine = await self.get_engine()
        return await engine.transcribe(audio_data, **kwargs)
    
    async def shutdown(self):
        """
        关闭STT引擎
        """
        if self.engine:
            await self.engine.shutdown()
        self.initialized = False
        logger.info("STT engine shutdown")

# 方便导入的工厂函数
def get_stt_manager() -> STTManager:
    return STTManager()
