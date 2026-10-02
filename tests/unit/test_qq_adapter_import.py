#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试 QQ Adapter 导入是否正常
"""

import os
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_imports():
    """测试所有相关导入"""
    from clients.bots.qq.utils import _normalize_qq_face_position
    from clients.bots.qq.main import QQAdapter
    from clients.bots.qq.transport import NapcatTransport

    assert callable(_normalize_qq_face_position)
    assert isinstance(QQAdapter, type)
    assert isinstance(NapcatTransport, type)


def test_normalize_function():
    """测试 _normalize_qq_face_position 函数"""
    from clients.bots.qq.utils import _normalize_qq_face_position

    test_cases = [
        ("你好 [微笑]", "你好 [微笑]"),
        ("[微笑] 你好", "你好 [微笑]"),
        ("你好 [微笑] 世界 [难过]", "你好世界 [微笑] [难过]"),
        ("没有表情的消息", "没有表情的消息"),
    ]

    for input_text, expected in test_cases:
        result = _normalize_qq_face_position(input_text)
        assert result == expected, (
            f"输入 {input_text!r}: 期望 {expected!r}, 得到 {result!r}"
        )
