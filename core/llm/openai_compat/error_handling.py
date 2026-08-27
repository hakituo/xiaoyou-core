#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
错误处理模块

负责网络错误分类、瞬时错误判断和错误格式化
"""

from typing import Dict


SSL_ERROR_MARKERS = [
    "sslv3_alert_bad_record_mac",
    "bad record mac",
]

SSL_ERROR_MSG = "网络或SSL连接异常，请检查网络后重试。"
SSL_ERROR_CODE = "SSL_ERROR"

NETWORK_ERROR_MARKERS = [
    "transferencodingerror",
    "response payload is not completed",
    "not enough data to satisfy transfer length header",
    "connection reset",
    "connectionreseterror",
    "server disconnected",
    "broken pipe",
    "指定的网络名不再可用",
    "network name is no longer available",
    "clientpayloaderror",
    "payload error",
    "connection aborted",
    "connection lost",
]

NETWORK_ERROR_MSG = "网络连接在传输中断开，请稍后重试。"
NETWORK_ERROR_CODE = "NETWORK_INTERRUPTED"

GENERIC_ERROR_MSG = "请求失败，请稍后重试。"
GENERIC_ERROR_CODE = "REQUEST_FAILED"


def is_transient_ssl_error(error: Exception) -> bool:
    """
    判断是否为瞬时SSL错误

    Args:
        error: 异常对象

    Returns:
        是否为瞬时SSL错误
    """
    try:
        msg = str(error or "").lower()
    except Exception:
        return False

    for marker in SSL_ERROR_MARKERS:
        if marker in msg:
            return True

    if "ssl" in msg and "alert" in msg:
        return True
    return False


def is_transient_network_error(error: Exception) -> bool:
    """
    判断是否为瞬时网络错误

    Args:
        error: 异常对象

    Returns:
        是否为瞬时网络错误
    """
    try:
        msg = str(error or "").lower()
    except Exception:
        return False

    return any(marker in msg for marker in NETWORK_ERROR_MARKERS)


def is_transient_error(error: Exception) -> bool:
    """
    判断是否为瞬时错误（可重试）

    Args:
        error: 异常对象

    Returns:
        是否为瞬时错误
    """
    return is_transient_ssl_error(error) or is_transient_network_error(error)


def format_network_error(error: Exception) -> Dict[str, str]:
    """
    格式化网络错误为标准错误响应

    Args:
        error: 异常对象

    Returns:
        包含error和error_code的字典
    """
    if is_transient_ssl_error(error):
        return {
            "error": SSL_ERROR_MSG,
            "error_code": SSL_ERROR_CODE,
        }
    if is_transient_network_error(error):
        return {
            "error": NETWORK_ERROR_MSG,
            "error_code": NETWORK_ERROR_CODE,
        }
    return {
        "error": GENERIC_ERROR_MSG,
        "error_code": GENERIC_ERROR_CODE,
    }
