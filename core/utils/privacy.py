#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
隐私隔离开关的统一判定

历史实现里"读 settings.chat.privacy_isolation 再决定是否排除 sensitive"这段逻辑
在记忆搜索、聊天记录搜索、上下文预算与主动关心四处各写了一遍，且判定条件略有差异，
改动一处容易漏掉其他。这里收敛为两个函数，保持各调用点原有语义不变。
"""

from typing import Optional


def get_privacy_isolation_enabled() -> bool:
    """读取隐私隔离开关，配置不可用时按关闭处理（不阻断主流程）"""
    try:
        from config.integrated_config import get_settings

        return bool(
            getattr(getattr(get_settings(), "chat", None), "privacy_isolation", False)
        )
    except Exception:
        return False


def should_exclude_sensitive(
    *, scope: Optional[str] = None, is_sensitive_mode: bool = False
) -> bool:
    """
    判断当前请求是否应排除 sensitive 记忆/事件

    Args:
        scope: 记忆作用域。传入时只有 sfw 作用域才排除；
              不传表示调用点不按作用域区分（上下文预算等内部路径）。
        is_sensitive_mode: 当前会话处于敏感模式时不排除，
              否则用户主动使用的内容会被自己隔离掉。

    Returns:
        True 表示应排除 sensitive 内容
    """
    if is_sensitive_mode:
        return False
    if scope is not None and str(scope).strip().lower() != "sfw":
        return False
    return get_privacy_isolation_enabled()


__all__ = ["get_privacy_isolation_enabled", "should_exclude_sensitive"]
