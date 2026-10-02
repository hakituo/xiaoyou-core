#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
错误处理模块

负责网络错误分类、瞬时错误判断和错误格式化，
以及 HTTP 非 200 响应的统一判定（是否可重试、是否需要重建 payload）。
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.llm.openai_compat.message_utils import (
    is_system_order_error,
    rebuild_payload_for_system_order,
    roles_preview,
)


# 认证 / 计费 / 内容策略类状态码：上层拿同一 payload 重试没有意义
NON_RETRYABLE_STATUS = (401, 402, 403, 422)

# 400 调试落盘文件名（MiniMax "group chat" 400 复盘用）
DEBUG_PAYLOAD_FILENAME = "minimax_400_payload.json"


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


def is_sensitive_input_rejection(status: Any, error_text: str) -> bool:
    """识别上游内容策略拒绝；它不可重试，也不应当作传输故障刷 ERROR。"""
    return int(status) == 422 and "new_sensitive" in str(error_text or "").lower()


def dump_debug_payload(
    payload: Optional[Dict[str, Any]],
    filename: str = DEBUG_PAYLOAD_FILENAME,
) -> None:
    """把触发 400 的 payload 落盘便于复盘；纯调试用途，任何失败都吞掉。"""
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


@dataclass
class ApiErrorInfo:
    """非 200 响应的统一判定结果

    Attributes:
        status: HTTP 状态码
        body: 响应体原文
        retry_payload: 非 None 表示需要立刻用它重建请求并重试（system-order 400）
        non_retryable: 认证 / 计费 / 内容策略类拒绝，上层不应再重试
    """

    status: int
    body: str
    retry_payload: Optional[Dict[str, Any]] = None
    non_retryable: bool = False


def classify_error_response(
    status: Any,
    error_text: str,
    payload: Optional[Dict[str, Any]] = None,
    attempt: int = 0,
    max_attempts: int = 3,
    logger: Optional[Any] = None,
) -> ApiErrorInfo:
    """判定一次非 200 响应该怎么处理，并顺带完成落盘与日志。

    chat / stream_chat 的差异只在「怎么把结果交给调用方」（字符串 vs dict），
    判定部分（调试落盘、system-order 重建、敏感输入 / 不可重试日志）完全一致，
    因此收敛在这里，避免两处各写一遍。
    """
    code = int(status)
    body = str(error_text or "")

    if code == 400 and "group chat" in body:
        dump_debug_payload(payload)

    if code == 400 and is_system_order_error(body) and attempt < max_attempts - 1:
        # 第一次尝试只重排 system 位置，第二次再退一步合并成单条 system
        rebuilt = rebuild_payload_for_system_order(
            payload or {}, keep_single_system=(attempt > 0)
        )
        if logger is not None:
            logger.warning(
                "Retrying after system-order 400. roles=%s",
                roles_preview(rebuilt.get("messages")),
            )
        return ApiErrorInfo(status=code, body=body, retry_payload=rebuilt)

    non_retryable = code in NON_RETRYABLE_STATUS
    if logger is not None:
        if is_sensitive_input_rejection(code, body):
            logger.warning("API 拒绝敏感输入 (%d)，本次请求不重试", code)
        elif non_retryable:
            logger.error("API 不可重试错误 (%d): %s", code, body[:200])
        else:
            logger.error("API Error (%d): %s", code, body)
    return ApiErrorInfo(status=code, body=body, non_retryable=non_retryable)
