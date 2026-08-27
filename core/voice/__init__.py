#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语音模块入口
"""

from core.utils.logger import get_logger
import asyncio

from typing import List
from dataclasses import dataclass

logger = get_logger(__name__)

# 全局TTs管理器实例
_tts_manager_instance = None
_stt_manager_instance = None
# P0-23: 使用 asyncio.Lock + double-check 保护 async 单例初始化，
# 防止协程并发导致重复创建 TTSManager/STTManager 实例（引擎重复加载、显存翻倍）
_tts_manager_lock = asyncio.Lock()
_stt_manager_lock = asyncio.Lock()


@dataclass
class TTSSpeaker:
    """
    TTS说话人信息
    """

    id: str
    name: str
    language: str = "zh"
    description: str = ""


async def get_tts_manager():
    """
    获取TTS管理器实例
    """
    global _tts_manager_instance
    if _tts_manager_instance is None:
        async with _tts_manager_lock:
            # double-check：拿到锁后再次确认，避免重复初始化
            if _tts_manager_instance is not None:
                return _tts_manager_instance
            # 创建默认TTS管理器实例
            from .tts_engine import TTSManager

            _tts_manager_instance = TTSManager()
    return _tts_manager_instance


async def get_speakers() -> List[str]:
    """
    获取可用说话人列表
    """
    try:
        await get_tts_manager()
        # 简化实现，返回默认说话人列表
        return ["default", "female", "male", "child"]
    except Exception as e:
        logger.error(f"获取说话人列表失败: {e}")
        return ["default"]


async def get_stt_manager():
    """
    获取STT管理器实例
    """
    global _stt_manager_instance
    if _stt_manager_instance is None:
        async with _stt_manager_lock:
            # double-check：拿到锁后再次确认，避免重复初始化
            if _stt_manager_instance is not None:
                return _stt_manager_instance
            # 创建默认STT管理器实例
            from .stt_engine import STTManager

            _stt_manager_instance = STTManager()
    return _stt_manager_instance


async def shutdown_tts():
    """
    关闭TTS服务
    """
    global _tts_manager_instance
    async with _tts_manager_lock:
        if _tts_manager_instance:
            try:
                await _tts_manager_instance.shutdown()
            except Exception as e:
                logger.error(f"关闭TTS服务失败: {e}")
            _tts_manager_instance = None


async def shutdown_stt():
    """
    关闭STT服务
    """
    global _stt_manager_instance
    async with _stt_manager_lock:
        if _stt_manager_instance:
            try:
                await _stt_manager_instance.shutdown()
            except Exception as e:
                logger.error(f"关闭STT服务失败: {e}")
            _stt_manager_instance = None
