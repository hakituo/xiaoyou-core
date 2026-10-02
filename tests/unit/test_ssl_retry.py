#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SSL / 网络瞬时错误识别测试

重试策略已收敛到 client 内部（最多 3 次尝试，仅对瞬时错误重试、且流式场景
在已吐出内容后不再重试），客户端不再暴露 max_retries / retry_delay 等参数。
这里只验证错误分类本身——它决定"要不要重试"以及返回给用户的错误码。
"""

import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from core.llm.openai_compat.error_handling import (  # noqa: E402
    SSL_ERROR_CODE,
    format_network_error,
    is_transient_error,
    is_transient_ssl_error,
)


def test_ssl_error_detection():
    """SSL 告警类错误识别为瞬时错误"""
    ssl_cases = [
        "sslv3 alert bad record mac",
        "bad record mac",
        "SSL alert certificate expired",
    ]
    for error_msg in ssl_cases:
        assert is_transient_ssl_error(Exception(error_msg)), (
            f"{error_msg} 应识别为瞬时 SSL 错误"
        )


def test_non_transient_errors_are_not_ssl():
    """超时、鉴权等错误不参与重试"""
    normal_cases = [
        "Connection timeout",
        "Invalid API key",
        "",
    ]
    for error_msg in normal_cases:
        assert not is_transient_ssl_error(Exception(error_msg)), (
            f"{error_msg} 不应识别为瞬时 SSL 错误"
        )


def test_transient_error_includes_network_markers():
    """网络瞬时错误同样进入重试判定"""
    assert is_transient_error(Exception("Response payload is not completed"))
    assert not is_transient_error(Exception("Invalid API key"))


def test_format_network_error_maps_ssl_code():
    """SSL 错误返回用户可读文案与错误码，不暴露底层细节"""
    formatted = format_network_error(Exception("bad record mac"))

    assert formatted["error_code"] == SSL_ERROR_CODE
    assert "SSL" in formatted["error"]
    assert "bad record mac" not in formatted["error"]
