#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket 适配器工具函数
"""

from core.utils.logger import get_logger
import os

logger = get_logger(__name__)


def env_flag_enabled(name: str) -> bool:
    """检查环境变量是否启用"""
    value = str(os.getenv(name, "") or "").strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def normalize_audio_src(src: str) -> str:
    """规范化音频源 URL"""
    if not src:
        return ""
    src = src.strip()
    if src.startswith("data:audio"):
        return src
    if src.startswith("http://") or src.startswith("https://"):
        return src
    if src.startswith("/"):
        return src
    return f"/audio/{src}"


def strip_emotion_markers(text: str) -> str:
    """去除情绪标记，保留纯文本"""
    if not text:
        return ""
    import re

    # 去除 [*情绪*] 格式的标记
    text = re.sub(r"\[[\*\s]*([^\]]+?)[\*\s]*\]", r"\1", text)
    return text.strip()


def resolve_ws_message_id(msg: dict, fallback_id: str = None) -> str:
    """从 WebSocket 消息中提取消息 ID"""
    msg_id = msg.get("message_id") or msg.get("messageId")
    if msg_id:
        return str(msg_id)
    return fallback_id or str(id(msg))
