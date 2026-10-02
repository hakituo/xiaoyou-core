#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSML 流式兜底过滤器

DeepSeek 的 DSML 工具调用 token 常常跨多个 SSE chunk 到达，客户端需要把它们
缓冲成一个完整块再解析，避免原始 DSML 文本泄漏到上层（streaming.py / 前端）。

本模块把「缓冲 → 找闭合 → 解析 → 吐 remainder」的状态机收敛成一个
DSMLStreamFilter：

- 纯同步、无 IO，便于单测；
- 每次流式调用新建一个实例，缓冲状态不再挂在 client 上，
  同一 client 并发两次流式调用时 DSML 分块不会互相串；
- 起止标记复用 ``dsml_parser`` 的**容错正则**，标签名与空白漂移（如
  ``<｜｜DSML｜｜ calls>``）同样会被扣留；尾部疑似被截断的开标签也会先攒住。
"""

import re
from typing import Any, Dict, List, Optional

from core.llm.openai_compat.dsml_parser import (
    DSML_CLOSE_RE,
    DSML_START_RE,
    parse_dsml_tool_calls,
)

#: 尾部可能是不完整开标签的起始字符集（``<`` / 全角竖线 / 空白 / 标签名字母）
_PARTIAL_OPENER_CHARS_RE = re.compile(r"[<\uff5c\sA-Za-z_]*")


def _partial_opener_index(text: str) -> int:
    """返回尾部一个「可能是不完整 DSML 开标签」的起始下标，没有则 -1。

    只认已经出现 DSML 线索（``DSML`` 字样或全角竖线）且尚未闭合的 ``<...``，
    避免把普通文本里孤立的 ``<`` 也长期扣留。
    """
    idx = text.rfind("<")
    if idx < 0:
        return -1
    tail = text[idx:]
    if ">" in tail:
        return -1
    if not _PARTIAL_OPENER_CHARS_RE.fullmatch(tail):
        return -1
    if "DSML" in tail or "\uff5c" in tail:
        return idx
    return -1


class DSMLStreamFilter:
    """拦截流式 content 中的 DSML token，解析成结构化 tool_calls。

    用法（每次流式调用一个实例）：

        dsml_filter = DSMLStreamFilter(logger)
        for out_chunk in dsml_filter.filter_chunk(chunk):
            yield out_chunk
        for out_chunk in dsml_filter.flush():
            yield out_chunk
    """

    def __init__(self, logger: Optional[Any] = None):
        self._logger = logger
        self._buffer = ""
        self._active = False
        self._pending = ""

    @property
    def active(self) -> bool:
        """是否正在缓冲一个尚未闭合的 DSML 块"""
        return self._active

    def filter_chunk(self, chunk: Dict[str, Any]) -> List[Dict[str, Any]]:
        """把上游 chunk 转成下发 chunk 列表。

        返回空列表表示本 chunk 还在 DSML 块内部（或疑似被截断的开标签）、
        需要继续缓冲。不含 content 的 chunk（如 usage / finish_reason）原样透传。
        """
        if "content" not in chunk:
            return [chunk]

        text = chunk["content"]
        if self._pending:
            text = self._pending + text
            self._pending = ""

        if self._active:
            self._buffer += text
            return self._flush_if_closed()

        start_match = DSML_START_RE.search(text)
        if start_match:
            out: List[Dict[str, Any]] = []
            before = text[: start_match.start()]
            if before.strip():
                out.append({"content": before})
            self._active = True
            self._buffer = text[start_match.start():]
            out.extend(self._flush_if_closed())
            return out

        # 未见到完整开标签：若尾部像被截断的开标签，先攒着等下一个 chunk
        idx = _partial_opener_index(text)
        if idx >= 0:
            self._pending = text[idx:]
            head = text[:idx]
            return [{"content": head}] if head.strip() else []
        return [chunk]

    def flush(self) -> List[Dict[str, Any]]:
        """流结束时收尾：把仍未闭合的缓冲按可见文本吐出，避免整段内容被吞掉。"""
        chunks: List[Dict[str, Any]] = []
        leftover = self._pending + self._buffer
        self._pending = ""
        self._buffer = ""
        self._active = False
        if leftover:
            chunks.append({"content": leftover})
        return chunks

    def _flush_if_closed(self) -> List[Dict[str, Any]]:
        """缓冲区里已出现闭合标记时解析整块，否则继续缓冲"""
        close_match = DSML_CLOSE_RE.search(self._buffer)
        if not close_match:
            return []

        dsml_block = self._buffer[: close_match.end()]
        remainder = self._buffer[close_match.end():]
        self._active = False
        self._buffer = ""

        out: List[Dict[str, Any]] = []
        _, dsml_calls = parse_dsml_tool_calls(dsml_block)
        if dsml_calls:
            if self._logger is not None:
                self._logger.info("DSML流式兜底: 解析到%d个工具调用", len(dsml_calls))
            out.append({"tool_calls": dsml_calls})
            out.append({"finish_reason": "tool_calls"})

        if remainder.strip():
            out.append({"content": remainder})
        return out