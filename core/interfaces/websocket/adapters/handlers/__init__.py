#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
消息处理器模块
将原来的 handlers.py 拆分为多个子模块
"""

from .connection_handlers import ConnectionHandlers
from .settings_handlers import SettingsHandlers
from .chat_handlers import ChatHandlers

__all__ = ["ConnectionHandlers", "SettingsHandlers", "ChatHandlers"]