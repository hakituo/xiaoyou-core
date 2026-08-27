#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试 QQ Adapter 导入是否正常
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_imports():
    """测试所有相关导入"""
    try:
        from clients.bots.qq.utils import _normalize_qq_face_position
        print("✓ _normalize_qq_face_position 导入成功")
        assert _normalize_qq_face_position is not None, "_normalize_qq_face_position 导入后不应为 None"
    except ImportError as e:
        print(f"✗ _normalize_qq_face_position 导入失败: {e}")
        assert False, f"_normalize_qq_face_position 导入失败: {e}"
        return False

    try:
        from clients.bots.qq.main import QQAdapter
        print("✓ QQAdapter 导入成功")
        assert QQAdapter is not None, "QQAdapter 导入后不应为 None"
    except ImportError as e:
        print(f"✗ QQAdapter 导入失败: {e}")
        assert False, f"QQAdapter 导入失败: {e}"
        return False

    try:
        from clients.bots.qq.transport import NapcatTransport
        print("✓ NapcatTransport 导入成功")
        assert NapcatTransport is not None, "NapcatTransport 导入后不应为 None"
    except ImportError as e:
        print(f"✗ NapcatTransport 导入失败: {e}")
        assert False, f"NapcatTransport 导入失败: {e}"
        return False

    return True

def test_normalize_function():
    """测试 _normalize_qq_face_position 函数"""
    from clients.bots.qq.utils import _normalize_qq_face_position

    test_cases = [
        ('你好 [微笑]', '你好 [微笑]'),
        ('[微笑] 你好', '你好 [微笑]'),
        ('你好 [微笑] 世界 [难过]', '你好世界 [微笑] [难过]'),
        ('没有表情的消息', '没有表情的消息'),
    ]

    print("\n测试 _normalize_qq_face_position 函数:")
    for input_text, expected in test_cases:
        result = _normalize_qq_face_position(input_text)
        status = "✓" if result == expected else "✗"
        print(f"{status} 输入: {input_text!r} -> 输出: {result!r}")
        if result != expected:
            print(f"  期望: {expected!r}")
        assert result == expected, f"输入 {input_text!r}: 期望 {expected!r}, 得到 {result!r}"

    return True

if __name__ == "__main__":
    print("测试 QQ Adapter 导入修复...")
    print("=" * 50)
    
    if test_imports():
        print("\n" + "=" * 50)
        test_normalize_function()
        print("\n" + "=" * 50)
        print("所有测试通过！")
    else:
        print("\n导入测试失败！")
        sys.exit(1)