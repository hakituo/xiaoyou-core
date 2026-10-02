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
    strip_tool_mark_residue,
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


def test_drift_container_alias_and_whitespace():
    """测试漂移形态：容器丢了 tool_ 前缀（<｜｜｜DSML｜｜｜ calls>）+ 开闭标签空白不一致

    2026-09-29 实测泄漏：模型吐出的容器名是 ``calls`` 而非 ``tool_calls``，
    且前缀与标签名之间多了空格、开闭标签空白不一致。这类形态必须能被
    识别成真工具调用，否则原始 token 会当正文发给用户。
    """
    text = (
        '<\uff5c\uff5cDSML\uff5c\uff5c calls>'
        '<\uff5c\uff5cDSML\uff5c\uff5c invoke name="search_chat_history">'
        '<\uff5c\uff5cDSML\uff5c\uff5c parameter name="query" string="true">骂 说教 莫名其妙</\uff5c\uff5cDSML\uff5c\uff5c parameter>'
        '<\uff5c\uff5cDSML\uff5c\uff5c parameter name="limit" string="true">30</\uff5c\uff5cDSML\uff5c\uff5c parameter>'
        '</\uff5c\uff5cDSML\uff5c\uff5c invoke>'
        '</\uff5c\uff5cDSML\uff5c\uff5c calls>'
    )
    assert detect_dsml_format(text) == "v4"

    cleaned, calls = parse_dsml_tool_calls(text)
    assert len(calls) == 1, f"期望1个工具调用，实际{len(calls)}"
    assert calls[0]["function"]["name"] == "search_chat_history"
    args = json.loads(calls[0]["function"]["arguments"])
    assert args["query"] == "骂 说教 莫名其妙"
    assert args["limit"] == "30"
    assert cleaned == "", f"清理后应为空，实际: {cleaned}"
    print("✅ 漂移形态（calls 别名 + 空白不一致）解析通过")


def test_strip_residue_complete_drift_block():
    """通用清洗：完整漂移块应被完全剥掉"""
    text = (
        "我先看看记录。"
        '<\uff5c\uff5cDSML\uff5c\uff5c calls>'
        '<\uff5c\uff5cDSML\uff5c\uff5c invoke name="search_chat_history">'
        '<\uff5c\uff5cDSML\uff5c\uff5c parameter name="query" string="true">念叨 唠叨</\uff5c\uff5cDSML\uff5c\uff5c parameter>'
        '</\uff5c\uff5cDSML\uff5c\uff5c invoke>'
        '</\uff5c\uff5cDSML\uff5c\uff5c calls>'
    )
    cleaned = strip_tool_mark_residue(text)
    assert "DSML" not in cleaned
    assert "\uff5c" not in cleaned
    assert cleaned == "我先看看记录。", f"实际: {cleaned!r}"
    print("✅ 通用清洗：完整漂移块剥离通过")


def test_strip_residue_unclosed_block():
    """通用清洗：未闭合（被截断）的块也要能剥掉"""
    text = "晚安。<\uff5c\uff5cDSML\uff5c\uff5c calls><\uff5c\uff5cDSML\uff5c\uff5c invoke name=\"search\""
    cleaned = strip_tool_mark_residue(text)
    assert "DSML" not in cleaned
    assert "\uff5c" not in cleaned
    assert cleaned.startswith("晚安。")
    print("✅ 通用清洗：未闭合块剥离通过")


def test_strip_residue_split_fragments():
    """通用清洗：被拆到多条消息里的裸标签残片也要剥掉"""
    text = "稍等</\uff5c\uff5cDSML\uff5c\uff5cinvoke>\n\n好的"
    cleaned = strip_tool_mark_residue(text)
    assert "DSML" not in cleaned
    assert "稍等" in cleaned
    assert "好的" in cleaned
    print("✅ 通用清洗：拆散残片剥离通过")


def test_strip_residue_bare_prefix():
    """通用清洗：只剩裸前缀 ｜｜｜DSML｜｜｜ 也要剥掉"""
    cleaned = strip_tool_mark_residue("马上<\uff5c\uff5cDSML\uff5c\uff5c")
    assert "\uff5c" not in cleaned
    assert "DSML" not in cleaned
    print("✅ 通用清洗：裸前缀剥离通过")


def test_strip_residue_no_false_positive():
    """通用清洗：正常文本零误伤"""
    for text in ["晚安", "（轻轻揉了揉眼睛）困了", "这首歌来自QQ音乐", "用了 | 分隔"]:
        assert strip_tool_mark_residue(text) == text, f"误伤: {text!r}"
    print("✅ 通用清洗：正常文本零误伤通过")


if __name__ == "__main__":
    test_v4_format()
    test_v4_format_with_prefix_text()
    test_v3_format()
    test_plain_format()
    test_multiple_tool_calls()
    test_no_dsml()
    test_tool_calls_structure()
    test_drift_container_alias_and_whitespace()
    test_strip_residue_complete_drift_block()
    test_strip_residue_unclosed_block()
    test_strip_residue_split_fragments()
    test_strip_residue_bare_prefix()
    test_strip_residue_no_false_positive()
    print("\n🎉 所有DSML解析器测试通过！")
