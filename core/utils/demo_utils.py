#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from core.utils.logger import get_logger
import asyncio
import time
from typing import List, Dict, Any

logger = get_logger(__name__)

# 全局演示日志缓存
_demo_logs: List[Dict[str, Any]] = []
_max_logs = 100


def add_demo_log(message: str, level: str = "info"):
    """
    添加演示日志到全局缓存
    """
    # P1-1: 使用 try/except asyncio.get_running_loop() 替代 get_event_loop().is_running()
    # 避免 Python 3.10+ 弃用警告
    try:
        asyncio.get_running_loop()
        log_time = time.monotonic()
    except RuntimeError:
        log_time = 0
    log_entry = {
        "text": message,
        "level": level,
        "time": log_time,
    }
    _demo_logs.append(log_entry)

    # 保持长度
    if len(_demo_logs) > _max_logs:
        _demo_logs.pop(0)

    logger.debug(f"Demo Log added: {message}")


def get_demo_logs(start_index: int = 0) -> List[Dict[str, Any]]:
    """
    获取增量演示日志
    """
    return _demo_logs[start_index:]


def clear_demo_logs():
    """
    清空演示日志
    """
    _demo_logs.clear()
