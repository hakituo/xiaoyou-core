#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI WebSocket 适配器

注意：此文件已重构，代码已迁移到 adapters/ 目录
保留此文件以保持向后兼容
"""

# 从新的模块化位置导入所有内容
from core.interfaces.websocket.adapters import (
    FastAPIWebSocketAdapter,
    get_fastapi_websocket_adapter,
    initialize_websocket_adapter,
    shutdown_websocket_adapter,
    env_flag_enabled,
)

# 保持向后兼容的导出
__all__ = [
    "FastAPIWebSocketAdapter",
    "get_fastapi_websocket_adapter",
    "initialize_websocket_adapter",
    "shutdown_websocket_adapter",
    "env_flag_enabled",
]
