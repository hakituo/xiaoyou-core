#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 QQ 消息发送前的思考过程剥离
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from clients.bots.qq.utils import _strip_think_for_qq  # noqa: E402


def test_strip_thinking_process_block():
    """带分隔线的 Thinking Process 段落整块剥离，只保留正文"""
    text = """> **Thinking Process:**
> 这是一个思考过程
> 多行思考内容

---

这是实际回复内容。"""

    result = _strip_think_for_qq(text)

    assert "Thinking Process" not in result, "应该过滤掉 Thinking Process"
    assert "这是一个思考过程" not in result, "不应该残留思考正文"
    assert result == "这是实际回复内容。"


def test_strip_thinking_process_without_separator():
    """没有分隔线时同样剥离思考段"""
    text = """> **Thinking Process:**
> 思考内容

实际内容"""

    result = _strip_think_for_qq(text)

    assert "Thinking Process" not in result
    assert result == "实际内容"


def test_strip_thinking_only_returns_empty():
    """只有思考没有正文时返回空串"""
    text = """> **Thinking Process:**
> 只有思考没有实际回复"""

    assert _strip_think_for_qq(text) == ""


def test_normal_content_unchanged():
    """正常内容不受影响"""
    text = "这是正常的回复内容，没有任何思考过程。"
    assert _strip_think_for_qq(text) == text


def test_strip_chinese_reasoning_marker():
    """中文"思考过程："写法同样剥离"""
    text = "思考过程：先确认一下她说的是哪天的事。\n\n那就明天见吧。"

    assert _strip_think_for_qq(text) == "那就明天见吧。"


def test_strip_think_tag():
    """<think/> 标签也要过滤"""
    text = """<think/>
这是思考内容
</think/>

这是实际回复。"""

    result = _strip_think_for_qq(text)

    assert "<think" not in result
    assert "这是思考内容" not in result
    assert result == "这是实际回复。"


def test_strip_think_store_tag():
    """[THINK_STORE: ...] 内部标记不进入气泡"""
    text = "[THINK_STORE: 她可能只是随口一说]好的，我知道了"

    assert _strip_think_for_qq(text) == "好的，我知道了"
