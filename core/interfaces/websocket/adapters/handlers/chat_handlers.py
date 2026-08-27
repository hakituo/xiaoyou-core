#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聊天处理器（兼容入口）

实际的实现已解耦到同级的 ``chat/`` 子包。本文件仅做再导出，
保证 `from .chat_handlers import ChatHandlers` 等既有 import 仍可工作。
"""

from core.interfaces.websocket.adapters.handlers.chat import ChatHandlers

__all__ = ["ChatHandlers"]
