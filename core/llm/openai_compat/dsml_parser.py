#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek DSML 工具调用解析器

当 DeepSeek V4 API 未正确解析内部 DSML token 时，
这些 token 会以原始文本形式泄漏到 content 字段中。
本模块负责检测并解析这些泄漏的 DSML token，
将其转换为 OpenAI 兼容的 tool_calls 格式。

支持的格式：
  - DeepSeek V4 DSML 格式: <｜｜DSML｜｜tool_calls>
  - DeepSeek V3.2 DSML 格式: <｜DSML｜function_calls>
  - Plain 格式: <function_calls>
"""

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple


_DSML_V4_PREFIX = "\uff5c\uff5cDSML\uff5c\uff5c"
_DSML_V3_PREFIX = "\uff5cDSML\uff5c"

_V4_START_TOKENS = [
    f"<{_DSML_V4_PREFIX}tool_calls>",
    f"<{_DSML_V4_PREFIX}function_calls>",
]
_V3_START_TOKENS = [
    f"<{_DSML_V3_PREFIX}tool_calls>",
    f"<{_DSML_V3_PREFIX}function_calls>",
]
_PLAIN_START_TOKENS = [
    "<tool_calls>",
    "<function_calls>",
]

_ALL_START_TOKENS = _V4_START_TOKENS + _V3_START_TOKENS + _PLAIN_START_TOKENS


def detect_dsml_format(text: str) -> Optional[str]:
    """
    检测文本中是否包含 DSML 格式的工具调用

    Returns:
        "v4" / "v3" / "plain" / None
    """
    for tok in _V4_START_TOKENS:
        if tok in text:
            return "v4"
    for tok in _V3_START_TOKENS:
        if tok in text:
            return "v3"
    for tok in _PLAIN_START_TOKENS:
        if tok in text:
            return "plain"
    return None


def _build_regexes(fmt: str) -> Tuple[re.Pattern, re.Pattern, re.Pattern]:
    """根据检测到的格式构建正则表达式"""
    if fmt == "v4":
        open_tag = re.escape(f"<{_DSML_V4_PREFIX}")
        close_body = re.escape(_DSML_V4_PREFIX)
    elif fmt == "v3":
        open_tag = re.escape(f"<{_DSML_V3_PREFIX}")
        close_body = re.escape(_DSML_V3_PREFIX)
    else:
        open_tag = "<"
        close_body = ""

    calls_pattern = rf"{open_tag}(?:tool_calls|function_calls)>(.*?)</{close_body}(?:tool_calls|function_calls)>"
    invoke_pattern = rf'{open_tag}invoke\s+name="([^"]+)"\s*>(.*?)</{close_body}invoke>'
    param_pattern = (
        rf'{open_tag}parameter\s+name="([^"]+)"\s+string="(?:true|false)"\s*>'
        rf"(.*?)</{close_body}parameter>"
    )

    return (
        re.compile(calls_pattern, re.DOTALL),
        re.compile(invoke_pattern, re.DOTALL),
        re.compile(param_pattern, re.DOTALL),
    )


def _parse_params(param_str: str, param_regex: re.Pattern) -> Dict[str, Any]:
    """解析参数列表"""
    params: Dict[str, Any] = {}
    for m in param_regex.finditer(param_str):
        name = m.group(1)
        raw_val = m.group(2).strip()
        params[name] = raw_val
    return params


def parse_dsml_tool_calls(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    从文本中解析 DSML 格式的工具调用

    Args:
        text: 可能包含 DSML token 的原始文本

    Returns:
        (cleaned_text, tool_calls) 元组:
        - cleaned_text: 移除 DSML token 后的干净文本
        - tool_calls: OpenAI 兼容格式的 tool_calls 列表
    """
    fmt = detect_dsml_format(text)
    if fmt is None:
        return text, []

    calls_regex, invoke_regex, param_regex = _build_regexes(fmt)

    tool_calls: List[Dict[str, Any]] = []

    for calls_match in calls_regex.finditer(text):
        calls_body = calls_match.group(1)

        for invoke_match in invoke_regex.finditer(calls_body):
            func_name = invoke_match.group(1)
            invoke_body = invoke_match.group(2)

            params = _parse_params(invoke_body, param_regex)

            tc_id = f"dsml_{uuid.uuid4().hex[:8]}"
            tool_calls.append(
                {
                    "id": tc_id,
                    "type": "function",
                    "function": {
                        "name": func_name,
                        "arguments": json.dumps(params, ensure_ascii=False),
                    },
                }
            )

    dsml_region_regex = _build_dsml_region_regex(fmt)
    cleaned = dsml_region_regex.sub("", text).strip()

    return cleaned, tool_calls


def _build_dsml_region_regex(fmt: str) -> re.Pattern:
    """构建匹配整个 DSML 区域的正则（用于清理）"""
    if fmt == "v4":
        open_tag = re.escape(f"<{_DSML_V4_PREFIX}")
        close_body = re.escape(_DSML_V4_PREFIX)
    elif fmt == "v3":
        open_tag = re.escape(f"<{_DSML_V3_PREFIX}")
        close_body = re.escape(_DSML_V3_PREFIX)
    else:
        open_tag = "<"
        close_body = ""

    return re.compile(
        rf"{open_tag}(?:tool_calls|function_calls)>.*?</{close_body}(?:tool_calls|function_calls)>",
        re.DOTALL,
    )


def has_dsml_tokens(text: str) -> bool:
    """快速检查文本是否包含 DSML token"""
    return detect_dsml_format(text) is not None
