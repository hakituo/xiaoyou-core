#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSML解析器验证脚本

验证DeepSeek V4 DSML token泄漏时的兜底解析功能是否正常工作。
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.llm.openai_compat.dsml_parser import (
    parse_dsml_tool_calls,
    has_dsml_tokens,
    detect_dsml_format,
)


def test_v4_format():
    """测试DeepSeek V4 DSML格式（双全角竖线）"""
    text = (
        '<\uff5c\uff5cDSML\uff5c\uff5ctool_calls>'
        '<\uff5c\uff5cDSML\uff5c\uff5cinvoke name="aveline_daily_data">'
        '<\uff5c\uff5cDSML\uff5c\uff5cparameter name="action" string="true">list</\uff5c\uff5cDSML\uff5c\uff5cparameter>'
        '<\uff5c\uff5cDSML\uff5c\uff5cparameter name="path" string="true">us </\uff5c\uff5cDSML\uff5c\uff5cparameter>'
        '</\uff5c\uff5cDSML\uff5c\uff5cinvoke>'
        '</\uff5c\uff5cDSML\uff5c\uff5ctool_calls>'
    )
    fmt = detect_dsml_format(text)
    assert fmt == "v4", f"期望v4，实际{fmt}"

    cleaned, calls = parse_dsml_tool_calls(text)
    assert len(calls) == 1, f"期望1个工具调用，实际{len(calls)}"
    assert calls[0]["function"]["name"] == "aveline_daily_data"
    args = json.loads(calls[0]["function"]["arguments"])
    assert args["action"] == "list"
    assert args["path"] == "us"
    assert cleaned == "", f"清理后应为空，实际: {cleaned}"
    print("✅ V4格式解析通过")


def test_v4_format_with_prefix_text():
    """测试V4格式前有普通文本"""
    text = (
        "好的，我来帮你查询数据。"
        '<\uff5c\uff5cDSML\uff5c\uff5ctool_calls>'
        '<\uff5c\uff5cDSML\uff5c\uff5cinvoke name="get_weather">'
        '<\uff5c\uff5cDSML\uff5c\uff5cparameter name="city" string="true">北京</\uff5c\uff5cDSML\uff5c\uff5cparameter>'
        '</\uff5c\uff5cDSML\uff5c\uff5cinvoke>'
        '</\uff5c\uff5cDSML\uff5c\uff5ctool_calls>'
    )
    cleaned, calls = parse_dsml_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "get_weather"
    args = json.loads(calls[0]["function"]["arguments"])
    assert args["city"] == "北京"
    assert "好的" in cleaned
    assert "DSML" not in cleaned
    print("✅ V4格式+前缀文本解析通过")


def test_v3_format():
    """测试DeepSeek V3.2 DSML格式（单全角竖线）"""
    text = (
        '<\uff5cDSML\uff5cfunction_calls>'
        '<\uff5cDSML\uff5cinvoke name="get_weather">'
        '<\uff5cDSML\uff5cparameter name="location" string="true">杭州</\uff5cDSML\uff5cparameter>'
        '<\uff5cDSML\uff5cparameter name="date" string="true">2024-01-16</\uff5cDSML\uff5cparameter>'
        '</\uff5cDSML\uff5cinvoke>'
        '</\uff5cDSML\uff5cfunction_calls>'
    )
    fmt = detect_dsml_format(text)
    assert fmt == "v3", f"期望v3，实际{fmt}"

    cleaned, calls = parse_dsml_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "get_weather"
    args = json.loads(calls[0]["function"]["arguments"])
    assert args["location"] == "杭州"
    assert args["date"] == "2024-01-16"
    print("✅ V3格式解析通过")


def test_plain_format():
    """测试Plain格式（无DSML前缀）"""
    text = (
        '<function_calls>'
        '<invoke name="search">'
        '<parameter name="query" string="true">test</parameter>'
        '</invoke>'
        '</function_calls>'
    )
    fmt = detect_dsml_format(text)
    assert fmt == "plain", f"期望plain，实际{fmt}"

    cleaned, calls = parse_dsml_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "search"
    print("✅ Plain格式解析通过")


def test_multiple_tool_calls():
    """测试多个工具调用"""
    text = (
        '<\uff5c\uff5cDSML\uff5c\uff5ctool_calls>'
        '<\uff5c\uff5cDSML\uff5c\uff5cinvoke name="tool_a">'
        '<\uff5c\uff5cDSML\uff5c\uff5cparameter name="x" string="true">1</\uff5c\uff5cDSML\uff5c\uff5cparameter>'
        '</\uff5c\uff5cDSML\uff5c\uff5cinvoke>'
        '<\uff5c\uff5cDSML\uff5c\uff5cinvoke name="tool_b">'
        '<\uff5c\uff5cDSML\uff5c\uff5cparameter name="y" string="true">2</\uff5c\uff5cDSML\uff5c\uff5cparameter>'
        '</\uff5c\uff5cDSML\uff5c\uff5cinvoke>'
        '</\uff5c\uff5cDSML\uff5c\uff5ctool_calls>'
    )
    cleaned, calls = parse_dsml_tool_calls(text)
    assert len(calls) == 2, f"期望2个工具调用，实际{len(calls)}"
    assert calls[0]["function"]["name"] == "tool_a"
    assert calls[1]["function"]["name"] == "tool_b"
    print("✅ 多工具调用解析通过")


def test_no_dsml():
    """测试无DSML token的普通文本"""
    text = "这是一段普通的回复文本，没有任何工具调用。"
    assert not has_dsml_tokens(text)
    cleaned, calls = parse_dsml_tool_calls(text)
    assert len(calls) == 0
    assert cleaned == text
    print("✅ 普通文本不误判通过")


def test_tool_calls_structure():
    """测试输出的tool_calls结构是否符合OpenAI格式"""
    text = (
        '<\uff5c\uff5cDSML\uff5c\uff5ctool_calls>'
        '<\uff5c\uff5cDSML\uff5c\uff5cinvoke name="aveline_daily_data">'
        '<\uff5c\uff5cDSML\uff5c\uff5cparameter name="action" string="true">list</\uff5c\uff5cDSML\uff5c\uff5cparameter>'
        '</\uff5c\uff5cDSML\uff5c\uff5cinvoke>'
        '</\uff5c\uff5cDSML\uff5c\uff5ctool_calls>'
    )
    _, calls = parse_dsml_tool_calls(text)
    tc = calls[0]
    assert "id" in tc, "tool_call缺少id字段"
    assert tc["type"] == "function", f"type应为function，实际{tc['type']}"
    assert "function" in tc, "tool_call缺少function字段"
    assert "name" in tc["function"], "function缺少name字段"
    assert "arguments" in tc["function"], "function缺少arguments字段"
    args = json.loads(tc["function"]["arguments"])
    assert isinstance(args, dict), f"arguments应为dict，实际{type(args)}"
    print("✅ OpenAI格式结构验证通过")


if __name__ == "__main__":
    test_v4_format()
    test_v4_format_with_prefix_text()
    test_v3_format()
    test_plain_format()
    test_multiple_tool_calls()
    test_no_dsml()
    test_tool_calls_structure()
    print("\n🎉 所有DSML解析器测试通过！")
