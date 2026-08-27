#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云端 TTS 引擎模块
支持 OpenAI、SiliconFlow 等兼容接口
"""

import asyncio
import os
import aiohttp
import numpy as np
from typing import Optional

try:
    import soundfile as sf
except ImportError:
    sf = None

from core.voice.cloud_tts_helpers import (
    shutdown_cloud_tts,
    synthesize_cloud_tts_bytes,
)
from core.utils.logger import get_logger
from core.voice.engines.base import TTSEngine

logger = get_logger("CLOUD_TTS_ENGINE")


class CloudTTSEngine(TTSEngine):
    """
    Cloud TTS Engine (OpenAI Compatible)
    Supports OpenAI, SiliconFlow, etc.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "tts-1",
    ):
        super().__init__()
        self.api_key = (
            api_key or os.getenv("SILICONFLOW_API_KEY") or os.getenv("OPENAI_API_KEY")
        )
        self.base_url = base_url or os.getenv(
            "TTS_API_BASE", "https://api.siliconflow.cn/v1/audio/speech"
        )
        self.model = model
        self.voice = "alloy"  # Default voice
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_loop = None
        self._session_lock = None

        if not self.api_key:
            logger.warning(
                "Cloud TTS API Key not found. Please set SILICONFLOW_API_KEY or OPENAI_API_KEY."
            )

    async def _get_session(self) -> aiohttp.ClientSession:
        loop = asyncio.get_running_loop()
        if self._session and not self._session.closed and self._session_loop is loop:
            return self._session

        if self._session_lock is None or self._session_loop is not loop:
            self._session_lock = asyncio.Lock()

        async with self._session_lock:
            if (
                self._session
                and not self._session.closed
                and self._session_loop is loop
            ):
                return self._session

            if (
                self._session
                and not self._session.closed
                and self._session_loop is not loop
            ):
                try:
                    await self._session.close()
                except Exception:
                    pass

            connector = aiohttp.TCPConnector(
                limit=32,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
            )
            timeout = aiohttp.ClientTimeout(total=300)
            self._session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            self._session_loop = loop
            return self._session

    async def initialize(self):
        if self.initialized:
            return
        self.initialized = True
        logger.info(f"Cloud TTS Engine initialized (Model: {self.model})")

    async def synthesize(self, text: str, **kwargs) -> np.ndarray:
        audio_bytes = await self.synthesize_bytes(text, **kwargs)
        if not audio_bytes or not sf:
            return np.array([], dtype=np.float32)

        import io

        try:
            data, _samplerate = sf.read(io.BytesIO(audio_bytes))
            return data.astype(np.float32)
        except Exception:
            return np.array([], dtype=np.float32)

    async def synthesize_bytes(self, text: str, **kwargs) -> Optional[bytes]:
        return await synthesize_cloud_tts_bytes(self, text, **kwargs)

    async def shutdown(self):
        await shutdown_cloud_tts(self)
        await super().shutdown()
