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


def extract_match_tokens(text: str) -> set[str]:
    """从文本中提取关键词集合，用于历史相关性打分。"""
    import re

    s = str(text or "").strip().lower()
    if not s:
        return set()
    tokens = re.findall(r"[\u4e00-\u9fa5]{2,}|[a-z0-9_]{2,}", s)
    stop = {
        "的", "了", "和", "是", "在", "我", "你", "他", "她", "它",
        "this", "that", "the", "and", "for", "with", "from", "have", "will",
    }
    return {t for t in tokens if t and t not in stop}
