#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语音转文字引擎模块
"""

import os
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
from config.integrated_config import get_settings
from core.utils.logger import get_logger
from core.utils.async_locks import LazyAsyncLock

# 尝试加载C++音频预处理器
try:
    import importlib.util
    _audio_spec = importlib.util.find_spec("audio_processor_py")
    if _audio_spec is not None:
        import audio_processor_py
        _HAS_CPP_AUDIO = True
    else:
        audio_processor_py = None
        _HAS_CPP_AUDIO = False
except Exception:
    audio_processor_py = None
    _HAS_CPP_AUDIO = False

try:
    from core.resource_manager import (
        get_resource_manager,
        ResourcePriority,
        ResourceType,
    )
except ImportError:
    get_resource_manager = None
    ResourcePriority = None
    ResourceType = None

from core.utils.resource_lock import get_resource_lock

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
        return {"text": "这是一段模拟的转录文本", "segments": [], "language": "zh"}


class HuggingFaceSTTEngine(STTEngine):
    """
    Hugging Face Whisper STT Engine (Standard PyTorch)
    """

    def __init__(self, model_path, device="cpu"):
        super().__init__()
        self.model_path = model_path
        self.device = device
        self.model = None
        self.processor = None

    async def initialize(self):
        if self.initialized:
            return

        try:
            from transformers import WhisperProcessor, WhisperForConditionalGeneration
            import torch

            # 允许使用 CUDA
            if str(self.device).lower() == "cuda" and not torch.cuda.is_available():
                logger.warning("HF Whisper 请求了 CUDA 但不可用，回退至 CPU")
                self.device = "cpu"

            logger.info(
                f"Loading HF Whisper model from: {self.model_path} on {self.device}..."
            )

            def _load_model():
                processor = WhisperProcessor.from_pretrained(self.model_path)
                model = WhisperForConditionalGeneration.from_pretrained(self.model_path)
                model.to(self.device)
                return processor, model

            loop = asyncio.get_running_loop()
            self.processor, self.model = await loop.run_in_executor(None, _load_model)

            self.initialized = True
            logger.info("HF Whisper model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load HF Whisper model: {e}")
            self.initialized = False
            raise e

    async def transcribe(self, audio_data: bytes, **kwargs) -> Dict[str, Any]:
        if not self.initialized:
            return {"text": "", "error": "Model not initialized"}

        import librosa
        import io

        try:
            # Load audio using librosa (resample to 16000)
            def _process_audio():
                # Convert bytes to numpy array
                audio_stream = io.BytesIO(audio_data)
                y, sr = librosa.load(audio_stream, sr=16000)

                # Process inputs
                input_features = self.processor(
                    y, sampling_rate=16000, return_tensors="pt"
                ).input_features.to(self.device)

                # Generate
                # Force language if provided, otherwise auto-detect
                forced_decoder_ids = None
                lang = kwargs.get("language", "zh")
                if lang:
                    forced_decoder_ids = self.processor.get_decoder_prompt_ids(
                        language=lang, task="transcribe"
                    )

                predicted_ids = self.model.generate(
                    input_features, forced_decoder_ids=forced_decoder_ids
                )

                transcription = self.processor.batch_decode(
                    predicted_ids, skip_special_tokens=True
                )[0]
                return transcription

            loop = asyncio.get_running_loop()
            text = await loop.run_in_executor(None, _process_audio)

            return {
                "text": text,
                "segments": [],
                "language": kwargs.get("language", "zh"),
            }
        except Exception as e:
            logger.error(f"HF Whisper Transcription Error: {e}")
            return {"text": "", "error": str(e)}

    async def move_to_cpu(self):
        if self.model and self.device == "cuda":
            logger.info("Moving HF Whisper model to CPU to save VRAM...")
            self.model.cpu()
            import torch

            torch.cuda.empty_cache()

    async def move_to_gpu(self):
        if self.model and self.device == "cpu":
            try:
                import torch

                if torch.cuda.is_available():
                    logger.info("Moving HF Whisper model to GPU...")
                    self.model.cuda()
                    self.device = "cuda"
                    return True
            except Exception as e:
                logger.error(f"Failed to move HF Whisper to GPU: {e}")
        return False


class FasterWhisperSTTEngine(STTEngine):
    """
    Faster Whisper STT Engine (CTranslate2 Backend)
    极速、显存友好，支持 VAD 过滤。
    支持动态加载/卸载以节省显存。
    """

    def __init__(self, model_size="small", device="cpu", compute_type="int8"):
        super().__init__()
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model = None
        # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._lock = LazyAsyncLock()  # 用于确保切换设备时的线程安全

    async def initialize(self):
        if self.initialized:
            return

        async with self._lock:
            await self._load_model()
            self.initialized = True
            logger.info(f"Faster-Whisper 引擎初始化成功 ({self.device})")

    async def _load_model(self):
        """内部加载模型逻辑"""
        # 使用全局 GPU 资源锁，防止与 LLM 等其他模型加载冲突
        async with get_resource_lock().acquire("STT_Load"):
            try:
                try:
                    from faster_whisper import WhisperModel
                except ModuleNotFoundError as e:
                    if str(e.name) == "faster_whisper":
                        logger.error(
                            "Faster-Whisper 未安装。请先安装: pip install faster-whisper"
                        )
                    raise
                import torch
                from core.utils.common import get_project_root

                # 允许使用 CUDA
                if str(self.device).lower() == "cuda" and not torch.cuda.is_available():
                    logger.warning("Faster-Whisper 请求了 CUDA 但不可用，回退至 CPU")
                    self.device = "cpu"
                    self.compute_type = "int8"

                logger.info(
                    f"正在加载 Faster-Whisper ({self.model_size}) 于 {self.device} (精度: {self.compute_type})..."
                )

                def _load():
                    # 如果 models/faster-whisper 目录下有模型文件，直接加载该路径
                    model_path = str(get_project_root() / "models" / "faster-whisper")

                    # 显式清理旧模型（如果存在）
                    if self.model:
                        try:
                            # CTranslate2 模型没有显式的 unload，通常通过删除引用并 gc 释放
                            del self.model
                            if torch.cuda.is_available():
                                torch.cuda.empty_cache()
                        except Exception:
                            pass

                    if os.path.exists(os.path.join(model_path, "model.bin")):
                        return WhisperModel(
                            model_path,
                            device=self.device,
                            compute_type=self.compute_type,
                        )

                    # 否则按 size 下载/加载
                    return WhisperModel(
                        self.model_size,
                        device=self.device,
                        compute_type=self.compute_type,
                        download_root=model_path,
                    )

                loop = asyncio.get_running_loop()
                self.model = await loop.run_in_executor(None, _load)

            except Exception as e:
                logger.error(f"Faster-Whisper 加载失败: {e}")
                raise e

    async def transcribe(self, audio_data: bytes, **kwargs) -> Dict[str, Any]:
        if not self.initialized:
            return {"text": "", "error": "引擎未初始化"}

        # 1. 如果正在切换设备，等待切换完成
        async with self._lock:
            if not self.model:
                return {"text": "", "error": "模型未加载"}

            # 2. 检查显存压力。如果压力大且在 GPU 运行，尝试动态切换到 CPU 以避免阻塞
            if self.device == "cuda" and get_resource_manager:
                rm = get_resource_manager()
                if rm and rm.monitor.is_resource_pressure(ResourceType.GPU_MEMORY):
                    logger.warning(
                        "检测到显存压力且 GPU 被占用，STT 将动态切换至 CPU 执行以保证交互流畅..."
                    )
                    await self._move_to_cpu_impl()
                    # 在 CPU 执行不需要争夺 GPU 锁
                    result = await self._do_transcribe_impl(audio_data, **kwargs)
                    # 记录一个标记，提示后续可以恢复
                    return {**result, "device_fallback": "cpu"}

            # 3. 正常执行（显存充裕或已在 CPU 运行）
            return await self._do_transcribe_impl(audio_data, **kwargs)

    async def _do_transcribe_impl(self, audio_data: bytes, **kwargs) -> Dict[str, Any]:
        """实际执行转录的逻辑"""
        import io

        try:

            def _do_transcribe():
                # 使用C++ VAD预处理：去除静音段
                audio_input = io.BytesIO(audio_data)
                if _HAS_CPP_AUDIO and audio_processor_py is not None:
                    try:
                        from pydub import AudioSegment
                        import numpy as np
                        audio_segment = AudioSegment.from_file(io.BytesIO(audio_data))
                        audio_segment = audio_segment.set_frame_rate(16000).set_channels(1).set_sample_width(2)
                        samples = np.array(audio_segment.get_array_of_samples(), dtype=np.int16)
                        vad = audio_processor_py.AudioVAD(sample_rate=16000, energy_threshold=0.05)
                        cleaned = vad.remove_silence(samples, frame_ms=30)
                        if len(cleaned) > 0:
                            audio_input = io.BytesIO(cleaned.tobytes())
                    except Exception:
                        pass

                segments, info = self.model.transcribe(
                    audio_input,
                    beam_size=5,
                    language=kwargs.get("language", "zh"),
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=500),
                )
                segments = list(segments)
                text = "".join([s.text for s in segments])
                return text, info.language

            loop = asyncio.get_running_loop()
            text, lang = await loop.run_in_executor(None, _do_transcribe)

            return {"text": text.strip(), "language": lang, "success": True}
        except Exception as e:
            logger.error(f"Faster-Whisper 转录错误: {e}")
            return {"text": "", "error": str(e)}

    async def unload_model(self):
        """完全卸载模型以释放显存"""
        async with self._lock:
            if self.model:
                logger.info("正在卸载 Faster-Whisper 模型...")
                # CTranslate2 模型卸载
                self.model = None
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                import gc

                gc.collect()
                self.initialized = False
                logger.info("Faster-Whisper 模型已卸载")

    async def move_to_cpu(self):
        """将模型移动到 CPU 以节省显存"""
        async with self._lock:
            await self._move_to_cpu_impl()

    async def _move_to_cpu_impl(self):
        """内部实现，不带锁"""
        if self.device == "cpu":
            return

        logger.info("正在将 Faster-Whisper 移动到 CPU...")
        self.device = "cpu"
        self.compute_type = "int8"
        await self._load_model()
        logger.info("Faster-Whisper 已成功移动到 CPU (int8)")

    async def move_to_gpu(self):
        """将模型移动到 GPU 以提高速度"""
        async with self._lock:
            await self._move_to_gpu_impl()

    async def _move_to_gpu_impl(self):
        """内部实现，不带锁"""
        if self.device == "cuda":
            return

        try:
            import torch

            if not torch.cuda.is_available():
                logger.warning("Faster-Whisper 请求移动到 GPU 但 CUDA 不可用")
                return

            logger.info("正在将 Faster-Whisper 移动到 GPU...")
            self.device = "cuda"
            # GPU 下使用 float16 性能更好，显存占用也适中
            self.compute_type = "float16"
            await self._load_model()
            logger.info("Faster-Whisper 已成功移动到 GPU (float16)")
        except Exception as e:
            logger.error(f"Failed to move Faster-Whisper to GPU: {e}")
            self.device = "cpu"
            self.compute_type = "int8"


class CloudSTTEngine(STTEngine):
    """
    Cloud STT Engine (OpenAI Compatible)
    Supports OpenAI, SiliconFlow, Groq, etc.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "whisper-1",
    ):
        super().__init__()
        self.api_key = (
            api_key or os.getenv("SILICONFLOW_API_KEY") or os.getenv("OPENAI_API_KEY")
        )
        self.base_url = base_url or os.getenv(
            "STT_API_BASE", "https://api.siliconflow.cn/v1/audio/transcriptions"
        )
        self.model = model

        if not self.api_key:
            logger.warning(
                "Cloud STT API Key not found. Please set SILICONFLOW_API_KEY or OPENAI_API_KEY."
            )

    async def initialize(self):
        if self.initialized:
            return
        self.initialized = True
        logger.info(f"Cloud STT Engine initialized (Model: {self.model})")

    async def transcribe(self, audio_data: bytes, **kwargs) -> Dict[str, Any]:
        if not self.api_key:
            return {"text": "", "error": "API Key missing"}

        import aiohttp

        # Determine endpoint if base_url is just base (not full path)
        url = self.base_url
        if not url.endswith("transcriptions"):
            # Simple heuristic adjustment if user provided root base
            if url.endswith("/v1"):
                url += "/audio/transcriptions"
            elif not url.endswith("/"):
                url += "/v1/audio/transcriptions"

        headers = {"Authorization": f"Bearer {self.api_key}"}

        # Prepare multipart form data
        form_data = aiohttp.FormData()
        # Create a file-like object with a name, as APIs usually require a filename
        form_data.add_field(
            "file", audio_data, filename="audio.wav", content_type="audio/wav"
        )
        form_data.add_field("model", self.model)

        # Add optional params
        if "language" in kwargs:
            form_data.add_field("language", kwargs["language"])

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, data=form_data, headers=headers
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return {
                            "text": result.get("text", ""),
                            "segments": result.get(
                                "segments", []
                            ),  # Some APIs might return segments
                            "language": kwargs.get("language", "auto"),
                        }
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Cloud STT Error: {response.status} - {error_text}"
                        )
                        return {"text": "", "error": f"API Error: {response.status}"}
        except Exception as e:
            logger.error(f"Cloud STT Exception: {e}")
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

        # 1. 优先使用新的配置结构
        stt_config = self.settings.voice.stt
        provider = stt_config.provider

        # 兼容旧配置：如果新配置是默认的 local，但旧配置设置了 cloud
        legacy_engine = getattr(self.settings.voice, "stt_engine", "faster_whisper")
        if provider == "local" and legacy_engine in ["cloud", "siliconflow", "openai"]:
            provider = legacy_engine

        # 2. 根据 Provider 初始化引擎
        if provider == "local":
            # 策略优化：如果显存资源紧张（8G环境）或用户要求动态卸载，
            # 优先使用 HuggingFaceSTTEngine，因为它支持真正的权重搬移 (model.to)，
            # 而 FasterWhisper 在切换 CPU/GPU 时需要重新加载模型，速度极慢。

            # 优先尝试加载本地 HF 模型
            hf_model_path = str(
                Path(__file__).resolve().parents[2] / "models" / "whisper-small"
            )
            if os.path.exists(hf_model_path):
                logger.info(
                    f"检测到本地 HF 模型 {hf_model_path}，优先启用 HuggingFaceSTTEngine 以支持动态权重搬移"
                )
                try:
                    self.engine = HuggingFaceSTTEngine(
                        model_path=hf_model_path, device="cpu"
                    )
                    await self.engine.initialize()
                    self.initialized = True
                    self._register_resource_manager()
                    return
                except Exception as e:
                    logger.warning(f"初始化 HF Whisper 失败，尝试备选方案: {e}")

            # 如果 HF 不可用，再尝试 FasterWhisper
            try:
                device = "cpu"  # 初始放在 CPU
                compute_type = "int8"

                logger.info(
                    f"正在初始化 FasterWhisperSTTEngine 作为备选 (Device: {device})..."
                )
                self.engine = FasterWhisperSTTEngine(
                    model_size=stt_config.model or "small",
                    device=device,
                    compute_type=compute_type,
                )
                await self.engine.initialize()
                self.initialized = True
                self._register_resource_manager()
                return
            except Exception as e:
                logger.warning(f"Failed to initialize FasterWhisper: {e}")

        if provider in ["cloud", "siliconflow", "openai", "custom"]:
            logger.info(f"Selected CloudSTTEngine (Provider: {provider})")

            # Determine defaults if not explicitly set in stt_config
            model = stt_config.model
            base_url = stt_config.base_url
            api_key = stt_config.api_key

            # Fallbacks for specific providers if config is missing details
            if provider == "siliconflow":
                if not model or model == "default":
                    model = "FunAudioLLM/SenseVoiceSmall"
                if not base_url:
                    base_url = "https://api.siliconflow.cn/v1/audio/transcriptions"
            elif provider == "openai":
                if not model or model == "default":
                    model = "whisper-1"
                if not base_url:
                    base_url = "https://api.openai.com/v1/audio/transcriptions"

            self.engine = CloudSTTEngine(
                api_key=api_key, base_url=base_url, model=model
            )
            await self.engine.initialize()
            self.initialized = True
        else:
            # Default to Dummy if no local model found and not cloud
            logger.info(
                f"No suitable engine found for provider: {provider}, falling back to Dummy"
            )
            self.engine = DummySTTEngine()
            await self.engine.initialize()
            self.initialized = True

    def _register_resource_manager(self):
        """注册资源管理器回调"""
        if get_resource_manager:
            try:
                rm = get_resource_manager()
                # 注册为模型资源，方便 Dashboard 显示和统一调度
                # 注意：明确区分 offload_func 和 unload_func
                rm.register_model(
                    model_id="stt_engine",
                    model_type="stt",
                    priority=ResourcePriority.MEDIUM,
                    load_func=self.initialize,  # 彻底加载
                    unload_func=self.shutdown,  # 彻底销毁
                    offload_func=self.move_to_cpu,  # 搬移至 CPU
                    instance=self,
                )
                try:
                    rm.register_resource_handler(
                        "gpu_memory",
                        ResourcePriority.MEDIUM,
                        self.handle_resource_pressure,
                    )
                except Exception:
                    pass
                logger.info(
                    "Registered STTManager with ResourceManager (Priority: MEDIUM)"
                )
            except Exception as e:
                logger.error(f"Failed to register with ResourceManager: {e}")

    async def handle_resource_pressure(self, action: str):
        """处理资源压力通知，由 ResourceManager 或 C++ 调度器触发"""
        act = str(action or "").strip().lower()
        if act == "release":
            logger.info(
                "收到资源释放请求 (release)，正在将 STT 移动到 CPU 以释放显存..."
            )
            await self.move_to_cpu()
        elif act in {"recover", "restore"}:
            logger.info("收到资源恢复请求，但本地直连 GPU 已禁用，保持在 CPU 运行")

    async def unload_model(self):
        """卸载底层模型以释放资源"""
        if self.engine and hasattr(self.engine, "unload_model"):
            await self.engine.unload_model()
            self.initialized = False
            logger.info("STTManager: 底层模型已卸载")

    async def move_to_cpu(self):
        """将模型搬移至 CPU"""
        if self.engine and hasattr(self.engine, "move_to_cpu"):
            await self.engine.move_to_cpu()
            logger.info("STTManager: 模型已搬移至 CPU")

    async def move_to_gpu(self):
        """将模型搬移至 GPU"""
        if self.engine and hasattr(self.engine, "move_to_gpu"):
            await self.engine.move_to_gpu()
            logger.info("STTManager: 模型已搬移至 GPU")

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
