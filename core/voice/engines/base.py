#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TTS引擎基类模块
"""

import numpy as np
from typing import Optional

from core.utils.logger import get_logger

logger = get_logger("TTS_ENGINE_BASE")


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

    async def synthesize_bytes(self, text: str, **kwargs) -> Optional[bytes]:
        return None

    async def shutdown(self):
        """
        关闭引擎
        """
        self.initialized = False