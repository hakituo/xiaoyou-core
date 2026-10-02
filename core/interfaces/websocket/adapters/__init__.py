#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket 适配器模块
重构后的 FastAPI WebSocket 适配器
"""

from .adapter import (
    FastAPIWebSocketAdapter,
    get_fastapi_websocket_adapter,
    initialize_websocket_adapter,
    shutdown_websocket_adapter,
)
from .utils import env_flag_enabled, normalize_audio_src, strip_emotion_markers
from .handlers.main_handlers import MessageHandlers
from .streaming import StreamingHandler
from .demo import DemoHandler

__all__ = [
    "FastAPIWebSocketAdapter",
    "get_fastapi_websocket_adapter",
    "initialize_websocket_adapter",
    "shutdown_websocket_adapter",
    "env_flag_enabled",
    "normalize_audio_src",
    "strip_emotion_markers",
    "MessageHandlers",
    "StreamingHandler",
    "DemoHandler",
]
