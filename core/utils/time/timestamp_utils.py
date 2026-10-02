#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
时间戳工具函数
统一处理时间戳的解析、转换、格式化
"""
from datetime import datetime
from typing import Any, Optional


def safe_timestamp(value: Any, default: float = 0.0) -> float:
    """
    安全地将值转换为时间戳（秒级）
    
    自动处理：
    - None 值
    - 毫秒级时间戳（>1e12）
    - 字符串数字
    - 无效值
    
    Args:
        value: 时间戳值（可能是毫秒、秒、字符串、None等）
        default: 转换失败时的默认值
        
    Returns:
        float: 秒级时间戳
        
    Examples:
        >>> safe_timestamp(1700000000000)  # 毫秒
        1700000000.0
        >>> safe_timestamp(1700000000)    # 秒
        1700000000.0
        >>> safe_timestamp(None)
        0.0
        >>> safe_timestamp("invalid", default=100.0)
        100.0
    """
    try:
        ts = float(value or 0.0)
        # 毫秒级时间戳转换
        if ts > 1e12:
            ts = ts / 1000.0
        return ts
    except (TypeError, ValueError):
        return float(default)


def is_plausible_timestamp(ts: float, now: Optional[float] = None) -> bool:
    """
    检查时间戳是否合理
    
    合理的时间戳应该：
    - 大于 0
    - 不在未来（允许 5 分钟误差）
    - 不在太久以前（30天内）
    
    Args:
        ts: 待检查的时间戳
        now: 当前时间戳，默认使用当前时间
        
    Returns:
        bool: 时间戳是否合理
    """
    if ts <= 0:
        return False
    
    current = now or datetime.now().timestamp()
    
    # 不在未来（允许 5 分钟误差）
    if ts > current + 300:
        return False
    
    # 不在 30 天前
    if (current - ts) > 30 * 24 * 3600:
        return False
    
    return True


def format_message_age(msg_ts: Any, now: Optional[float] = None) -> str:
    """
    格式化消息年龄（多久之前）

    Args:
        msg_ts: 消息时间戳
        now: 当前时间戳

    Returns:
        str: 年龄字符串，如 "（约5分钟前）"、"（约2天3小时前）"
    """
    ts = safe_timestamp(msg_ts)
    if ts <= 0:
        return ""

    current = now or datetime.now().timestamp()
    if current < ts:
        return ""

    age_seconds = int(current - ts)

    if age_seconds < 60:
        return f"（约{age_seconds}秒前）"
    elif age_seconds < 3600:
        return f"（约{age_seconds // 60}分钟前）"
    elif age_seconds < 86400:
        return f"（约{age_seconds // 3600}小时前）"
    else:
        days = age_seconds // 86400
        hours = (age_seconds % 86400) // 3600
        if hours > 0:
            return f"（约{days}天{hours}小时前）"
        return f"（约{days}天前）"


# 为了向后兼容，提供别名
_safe_ts = safe_timestamp
