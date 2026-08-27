#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 QQ 前端过滤 Thinking Process
"""

import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from clients.bots.qq.utils import _strip_think_for_qq


def test_strip_thinking_process():
    print("=" * 60)
    print("测试: QQ 前端过滤 Thinking Process")
    print("=" * 60)
    
    # 测试用例 1: 标准格式
    test1 = """> **Thinking Process:**
> 这是一个思考过程
> 多行思考内容

---

这是实际回复内容。"""

    result1 = _strip_think_for_qq(test1)
    print("\n[测试 1] 标准格式:")
    print(f"输入:\n{test1}")
    print(f"\n输出:\n{result1}")
    assert "Thinking Process" not in result1, "应该过滤掉 Thinking Process"
    assert "这是实际回复内容" in result1, "应该保留实际内容"
    print("[OK] 通过")
    
    # 测试用例 2: 没有分隔线
    test2 = """> **Thinking Process:**
> 思考内容

实际内容"""

    result2 = _strip_think_for_qq(test2)
    print("\n[测试 2] 没有分隔线:")
    print(f"输入:\n{test2}")
    print(f"\n输出:\n{result2}")
    assert "Thinking Process" not in result2, "应该过滤掉 Thinking Process"
    assert "实际内容" in result2, "应该保留实际内容"
    print("[OK] 通过")
    
    # 测试用例 3: 只有 thinking process
    test3 = """> **Thinking Process:**
> 只有思考没有实际回复"""

    result3 = _strip_think_for_qq(test3)
    print("\n[测试 3] 只有 thinking process:")
    print(f"输入:\n{test3}")
    print(f"\n输出: '{result3}'")
    assert result3 == "", "应该返回空字符串"
    print("[OK] 通过")
    
    # 测试用例 4: 正常内容不受影响
    test4 = "这是正常的回复内容，没有任何思考过程。"
    result4 = _strip_think_for_qq(test4)
    print("\n[测试 4] 正常内容:")
    print(f"输入: {test4}")
    print(f"输出: {result4}")
    assert result4 == test4, "正常内容不应被修改"
    print("[OK] 通过")
    
    # 测试用例 5: <think/> 标签也要过滤
    test5 = """<think/>
这是思考内容
</think/>

这是实际回复。"""
    result5 = _strip_think_for_qq(test5)
    print("\n[测试 5] <think/> 标签:")
    print(f"输入:\n{test5}")
    print(f"\n输出:\n{result5}")
    assert "<think" not in result5, "应该过滤掉 think 标签"
    assert "这是实际回复" in result5, "应该保留实际内容"
    print("[OK] 通过")
    
    print("\n" + "=" * 60)
    print("[PASS] 所有测试通过")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = test_strip_thinking_process()
    sys.exit(0 if success else 1)
