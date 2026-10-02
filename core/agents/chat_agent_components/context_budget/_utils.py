# -*- coding: utf-8 -*-
"""共享工具函数。"""

from typing import Any


def safe_float(v: Any, default: float) -> float:
    """安全转 float，失败或非正返回 default。"""
    try:
        x = float(v)
        if x > 0:
            return x
    except Exception:
        return float(default)
    return float(default)


def safe_int(v: Any, default: int) -> int:
    """安全转 int，失败或非正返回 default。"""
    try:
        x = int(v)
        if x > 0:
            return x
    except Exception:
        return int(default)
    return int(default)
