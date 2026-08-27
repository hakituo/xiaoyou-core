#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
F5-TTS 引擎模块
基于流匹配(Flow Matching)的非自回归TTS模型
特点：速度快(RTF 0.15)、GPU利用率高、支持零样本语音克隆
参考：https://github.com/SWivid/F5-TTS
"""

import asyncio
import os
import numpy as np
from typing import Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

try:
    import soundfile as sf
except ImportError:
    sf = None

from config.integrated_config import get_settings
from core.utils.logger import get_logger
from core.utils.common import get_project_root
from core.utils.async_locks import LazyAsyncLock
from core.voice.engines.base import TTSEngine

try:
    from core.utils.resource_lock import get_resource_lock
except Exception:
    get_resource_lock = None
try:
    from core.resource_manager import get_resource_manager, ResourcePriority
except ImportError:
    get_resource_manager = None
    ResourcePriority = None

logger = get_logger("F5_TTS_ENGINE")


class F5TTSEngine(TTSEngine):
    """
    F5-TTS引擎
    基于流匹配(Flow Matching)的非自回归TTS模型
    特点：速度快(RTF 0.15)、GPU利用率高、支持零样本语音克隆
    参考：https://github.com/SWivid/F5-TTS
    """

    def __init__(self, model_path: str = None):
        super().__init__()
        self.model_path = model_path
        self._model = None
        self.current_device = "cpu"
        self._load_lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._is_generating = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="f5_tts")

    def _resolve_model_path(self):
        """解析模型路径"""
        if self.model_path:
            return Path(self.model_path), Path(self.model_path).exists()
        base_path = Path(str(get_project_root()))
        default_path = base_path / "models" / "voice" / "F5-TTS"
        if default_path.exists():
            return default_path, True
        return default_path, False

    async def initialize(self):
        if self.initialized:
            return

        self.model_path, path_exists = self._resolve_model_path()
        if not path_exists:
            logger.warning(f"F5-TTS model path not found: {self.model_path}")

        async with self._load_lock:

            def _load():
                try:
                    from f5_tts.api import F5TTS
                    import torch

                    device = "cuda" if torch.cuda.is_available() else "cpu"
                    logger.info(f"Loading F5-TTS on {device}...")

                    self._model = F5TTS(
                        model="F5TTS_v1_Base",
                        ckpt_file="",
                        vocab_file="",
                        ode_method="euler",
                        use_ema=True,
                        device=device,
                        hf_cache_dir=str(self.model_path),
                    )
                    self.current_device = device
                    logger.info("F5-TTS loaded successfully")
                except Exception as e:
                    logger.error(f"Failed to load F5-TTS: {e}")
                    raise

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _load)

        if get_resource_manager:
            rm = get_resource_manager()
            rm.register_resource_handler(
                "gpu_memory", ResourcePriority.MEDIUM, self.handle_resource_pressure
            )
            logger.info("Registered F5-TTS with ResourceManager (Priority: MEDIUM)")

        self.initialized = True

    async def synthesize_bytes(self, text: str, **kwargs) -> Optional[bytes]:
        if not self._model:
            await self.initialize()

        settings = get_settings()
        default_ref_audio = settings.voice.reference_audio
        base_path = str(get_project_root())
        if not default_ref_audio:
            default_ref_audio = os.path.join(
                base_path, "ref_audio", "female", "ref_calm.wav"
            )
        elif not os.path.isabs(default_ref_audio):
            default_ref_audio = os.path.join(base_path, default_ref_audio)

        ref_audio = (
            kwargs.get("ref_audio_path")
            or kwargs.get("reference_audio")
            or default_ref_audio
        )

        def _infer():
            try:
                # F5-TTS的infer方法参数
                wav, sr, _ = self._model.infer(
                    ref_file=str(ref_audio),
                    ref_text="",  # F5-TTS不需要ref_text
                    gen_text=text,
                    speed=kwargs.get("speed", 1.0),
                )

                import io
                import soundfile as sf

                buf = io.BytesIO()
                sf.write(buf, wav, sr, format="WAV")
                return buf.getvalue()
            except Exception as e:
                logger.error(f"F5-TTS inference failed: {e}")
                raise

        loop = asyncio.get_running_loop()
        if get_resource_lock:
            async with get_resource_lock().acquire("TTS", reject_if_full=True):
                return await loop.run_in_executor(self._executor, _infer)
        return await loop.run_in_executor(self._executor, _infer)

    async def synthesize(self, text: str, **kwargs) -> np.ndarray:
        if sf is None:
            return np.zeros(0, dtype=np.float32)
        audio_bytes = await self.synthesize_bytes(text, **kwargs)
        if not audio_bytes:
            return np.zeros(0, dtype=np.float32)
        import io

        data, _sr = sf.read(io.BytesIO(audio_bytes))
        return data.astype(np.float32)

    async def shutdown(self):
        self._model = None
        if self._executor is not None:
            self._executor.shutdown(wait=False)
        await super().shutdown()
