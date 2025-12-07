#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语音模块入口
"""
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 全局TTs管理器实例
_tts_manager_instance = None
_stt_manager_instance = None

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
        # 创建默认TTS管理器实例
        from .tts_engine import TTSManager
        _tts_manager_instance = TTSManager()
    return _tts_manager_instance

async def get_speakers() -> List[str]:
    """
    获取可用说话人列表
    """
    try:
        manager = await get_tts_manager()
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
        # 创建默认STT管理器实例
        from .stt_engine import STTManager
        _stt_manager_instance = STTManager()
    return _stt_manager_instance

async def shutdown_tts():
    """
    关闭TTS服务
    """
    global _tts_manager_instance
    if _tts_manager_instance:
        try:
            await _tts_manager_instance.shutdown()
            _tts_manager_instance = None
        except Exception as e:
            logger.error(f"关闭TTS服务失败: {e}")

async def shutdown_stt():
    """
    关闭STT服务
    """
    global _stt_manager_instance
    if _stt_manager_instance:
        try:
            await _stt_manager_instance.shutdown()
            _stt_manager_instance = None
        except Exception as e:
            logger.error(f"关闭STT服务失败: {e}")
