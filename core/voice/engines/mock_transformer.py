#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MockTransformer 模块
模拟 sox 以避免外部依赖（Qwen3-TTS需求绕过）
"""

import sys
import types
import numpy as np

from core.utils.logger import get_logger

logger = get_logger("MOCK_TRANSFORMER")


class MockTransformer:
    """模拟 sox.Transformer 的实现"""

    def __init__(self):
        self.db_level = 0

    def norm(self, db_level=0):
        self.db_level = db_level

    def build_array(self, input_array, sample_rate_in):
        if len(input_array) == 0:
            return input_array
        arr = np.array(input_array, dtype=np.float32)
        peak = np.max(np.abs(arr))
        if peak == 0:
            return arr
        target_peak = 10 ** (self.db_level / 20.0)
        return arr * (target_peak / peak)


def _ensure_sox_mock():
    """确保 sox 模块可用；若未安装则注入 Mock 实现（仅影响当前进程）"""
    if "sox" in sys.modules:
        return
    try:
        import sox as _sox_check
        _sox_check.Transformer
    except (ImportError, AttributeError):
        mock_sox = types.ModuleType("sox")
        mock_sox.Transformer = MockTransformer
        sys.modules["sox"] = mock_sox
        logger.debug("sox 未安装，已注入 MockTransformer 替代")
