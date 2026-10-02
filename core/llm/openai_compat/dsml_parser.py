#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek DSML 工具调用解析器

当 DeepSeek API 未正确解析内部 DSML token 时，这些 token 会以原始文本形式
泄漏到 content 字段中。本模块负责检测并解析这些泄漏的 DSML token，将其转换为
OpenAI 兼容的 tool_calls 格式。

支持的格式（**标签名与空白容错**，模型实测会漂移出各种写法）：

  - DeepSeek V4 DSML 格式: ``<｜｜DSML｜｜tool_calls>``
  - DeepSeek V3.2 DSML 格式: ``<｜DSML｜｜function_calls>``
  - Plain 格式: ``<tool_calls>``
  - 漂移形态：``<｜｜DSML｜｜ calls>``（前缀后多一个空格、且丢了 ``tool_`` 前缀），
    开闭标签空白不一致（``<｜｜DSML｜｜ parameter ...>`` / ``</｜｜DSML｜｜ parameter>``）等。

容错口径：前缀与标签名之间允许任意空白；容器名接受 ``tool_calls`` /
``function_calls`` / ``calls``；开闭标签各自独立容忍空白。

另提供 :func:`strip_tool_mark_residue`：面向**所有客户端输出侧**的通用清洗，
既剥离已解析的完整块，也兜住未闭合块、被拆散到多条消息的裸标签残片。
"""

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

_DSML_V4_PREFIX = "\uff5c\uff5cDSML\uff5c\uff5c"
_DSML_V3_PREFIX = "\uff5cDSML\uff5c"

#: 前缀交替（V4 必须排在 V3 前面：V3 前缀是 V4 前缀的子串）
_PREFIX_ALT = "(?:%s|%s)" % (re.escape(_DSML_V4_PREFIX), re.escape(_DSML_V3_PREFIX))

#: 容器名容错：漂移形态会丢 ``tool_`` 前缀，只写 ``calls``
_CONTAINER_ALT = r"(?:tool_calls|function_calls|calls)"

# 带 DSML 前缀的标签：开闭各自容忍「前缀与标签名之间的空白」
_DSML_OPEN = r"<\s*" + _PREFIX_ALT + r"\s*"
_DSML_CLOSE = r"</\s*" + _PREFIX_ALT + r"\s*"

# Plain 变体（无 DSML 前缀）保持原有严格口径，不给 ``calls`` 别名
_PLAIN_CONTAINER_ALT = r"(?:tool_calls|function_calls)"

_PLAIN_OPEN = r"<\s*"
_PLAIN_CLOSE = r"</\s*"

# 完整块：容器 → 容器
_DSML_CALLS_RE = re.compile(
    rf"{_DSML_OPEN}{_CONTAINER_ALT}\s*>(.*?){_DSML_CLOSE}{_CONTAINER_ALT}\s*>",
    re.DOTALL,
)
_PLAIN_CALLS_RE = re.compile(
    rf"{_PLAIN_OPEN}{_PLAIN_CONTAINER_ALT}\s*>(.*?)"
    rf"{_PLAIN_CLOSE}{_PLAIN_CONTAINER_ALT}\s*>",
    re.DOTALL,
)
#: 单个 plain 容器标签（未闭合也算命中，保持与旧 detect 口径一致）
_PLAIN_TAG_RE = re.compile(rf"</?\s*{_PLAIN_CONTAINER_ALT}\s*>")

# 块内元素：invoke / parameter（同样容忍空白漂移）
_DSML_INVOKE_RE = re.compile(
    rf'{_DSML_OPEN}invoke\s+name="([^"]+)"\s*>(.*?){_DSML_CLOSE}invoke\s*>',
    re.DOTALL,
)
_DSML_PARAM_RE = re.compile(
    rf'{_DSML_OPEN}parameter\s+name="([^"]+)"\s+string="(?:true|false)"\s*>'
    rf"(.*?){_DSML_CLOSE}parameter\s*>",
    re.DOTALL,
)
_PLAIN_INVOKE_RE = re.compile(
    rf'{_PLAIN_OPEN}invoke\s+name="([^"]+)"\s*>(.*?){_PLAIN_CLOSE}invoke\s*>',
    re.DOTALL,
)
_PLAIN_PARAM_RE = re.compile(
    rf'{_PLAIN_OPEN}parameter\s+name="([^"]+)"\s+string="(?:true|false)"\s*>'
    rf"(.*?){_PLAIN_CLOSE}parameter\s*>",
    re.DOTALL,
)

#: 流式兜底用的旧版字符串标记（保留兼容；流式过滤已改用下面的正则）
DSML_START_MARKERS = [
    f"<{_DSML_V4_PREFIX}tool_calls>",
    f"<{_DSML_V4_PREFIX}function_calls>",
    f"<{_DSML_V3_PREFIX}tool_calls>",
    f"<{_DSML_V3_PREFIX}function_calls>",
]
DSML_CLOSE_MARKERS = [m.replace("<", "</", 1) for m in DSML_START_MARKERS] + [
    "</tool_calls>",
    "</function_calls>",
]

#: 流式兜底用的容错起止正则（空白与标签名漂移都能命中）
DSML_START_RE = re.compile(rf"{_DSML_OPEN}{_CONTAINER_ALT}\s*>", re.IGNORECASE)
DSML_CLOSE_RE = re.compile(rf"{_DSML_CLOSE}{_CONTAINER_ALT}\s*>", re.IGNORECASE)

#: 任意 DSML 标签残片（未闭合块、被拆到多条消息里的裸标签）
_DSML_TAG_FRAGMENT_RE = re.compile(
    rf"</?\s*{_PREFIX_ALT}\s*[A-Za-z_]*(?:\s+[^<>]*)?>",
)
#: 收尾处被截断、连 ``>`` 都没吐出来的半个标签（``<｜｜｜DSML｜｜｜ invoke name="search"``）。
#: 限定在字符串末尾，且属性段有长度上限，避免把标签之后的正常正文一起吃掉。
_DSML_TAIL_FRAGMENT_RE = re.compile(
    rf"</?\s*{_PREFIX_ALT}\s*[A-Za-z_]*(?:\s+[^<>]{{0,200}})?$",
)
#: 裸前缀（只剩 ``｜｜｜DSML｜｜｜`` 而没有标签名），连同其可能的前导 ``<`` 一起剥掉
_BARE_PREFIX_RE = re.compile(rf"</?\s*{_PREFIX_ALT}")


def detect_dsml_format(text: str) -> Optional[str]:
    """
    检测文本中是否包含 DSML 格式的工具调用

    Returns:
        "v4" / "v3" / "plain" / None
    """
    if _DSML_V4_PREFIX in text:
        return "v4"
    if _DSML_V3_PREFIX in text:
        return "v3"
    if _PLAIN_CALLS_RE.search(text) or _PLAIN_TAG_RE.search(text):
        return "plain"
    return None


def has_dsml_tokens(text: str) -> bool:
    """快速检查文本是否包含 DSML token（含残片）"""
    return detect_dsml_format(text) is not None


def _extract_calls(
    text: str,
    calls_regex: re.Pattern,
    invoke_regex: re.Pattern,
    param_regex: re.Pattern,
) -> List[Dict[str, Any]]:
    """按给定的一组正则抽出 OpenAI 兼容的 tool_calls。"""
    tool_calls: List[Dict[str, Any]] = []
    for calls_match in calls_regex.finditer(text):
        for invoke_match in invoke_regex.finditer(calls_match.group(1)):
            func_name = invoke_match.group(1)
            params = {
                m.group(1): m.group(2).strip()
                for m in param_regex.finditer(invoke_match.group(2))
            }
            tool_calls.append(
                {
                    "id": f"dsml_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": func_name,
                        "arguments": json.dumps(params, ensure_ascii=False),
                    },
                }
            )
    return tool_calls


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

    if fmt == "plain":
        calls_regex, invoke_regex, param_regex = (
            _PLAIN_CALLS_RE,
            _PLAIN_INVOKE_RE,
            _PLAIN_PARAM_RE,
        )
    else:
        calls_regex, invoke_regex, param_regex = (
            _DSML_CALLS_RE,
            _DSML_INVOKE_RE,
            _DSML_PARAM_RE,
        )

    tool_calls = _extract_calls(text, calls_regex, invoke_regex, param_regex)
    cleaned = calls_regex.sub("", text).strip()
    return cleaned, tool_calls


def strip_tool_mark_residue(text: str) -> str:
    """剥离输出里残留的工具调用标记（**所有客户端共用**的通用清洗）。

    与 :func:`parse_dsml_tool_calls` 的分工：后者面向「能还原成真工具调用」的
    完整块；这里面向**输出侧安全网**，处理解析阶段漏掉的形态：

    - 完整但形态漂移的块（``<｜｜DSML｜｜ calls>...</｜｜DSML｜｜ calls>``）；
    - 未闭合就被截断的块；
    - 标签被拆散到多条消息里的裸残片（``</｜｜DSML｜｜invoke>`` 单独一条）；
    - 只剩前缀 ``｜｜DSML｜｜``。

    没有命中任何标记时原样返回，便于调用方用 ``after == before`` 判断是否记日志。
    """
    original = str(text or "")
    if not original or not has_dsml_tokens(original):
        return original

    cleaned, _ = parse_dsml_tool_calls(original)
    # 安全网：完整块剥掉后，清掉剩余的任何 DSML 标签残片与裸前缀
    cleaned = _DSML_TAG_FRAGMENT_RE.sub("", cleaned)
    cleaned = _DSML_TAIL_FRAGMENT_RE.sub("", cleaned)
    cleaned = _BARE_PREFIX_RE.sub("", cleaned)
    # 残片清理常留下空行与多余空白
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return cleaned.strip()