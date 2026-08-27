#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聊天消息处理子包（从庞大的 chat_handlers.py 解耦而来）。"""

from core.interfaces.websocket.adapters.handlers.chat.facade import ChatHandlers

__all__ = ["ChatHandlers"]
