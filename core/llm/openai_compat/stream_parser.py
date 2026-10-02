#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流式响应解析器模块

负责解析SSE格式的流式响应，提取content和reasoning
"""

import json
from typing import AsyncGenerator, Dict, Any, Optional


async def parse_sse_stream(
    response_content,
    logger=None
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    异步解析SSE流式响应

    Args:
        response_content: aiohttp响应内容流
        logger: 可选的logger实例

    Yields:
        包含content或error的字典
    """
    buffer = b""
    pending_json = b""
    reasoning_mode = False

    async for chunk in response_content.iter_any():
        if not chunk:
            continue
        buffer += chunk

        while b"\n" in buffer:
            raw_line, buffer = buffer.split(b"\n", 1)
            line = raw_line.strip()
            if not line:
                continue

            if not line.startswith(b"data:"):
                if pending_json:
                    pending_json += b"\n" + line
                    content = _try_parse_single_content(pending_json, logger)
                    if content is not None:
                        pending_json = b""
                        yield {"content": content}
                continue

            data_bytes = line[5:].strip()
            if data_bytes == b"[DONE]":
                return

            if pending_json:
                if logger:
                    logger.warning(f"Discarding corrupted pending_json: {pending_json}")
                pending_json = b""

            try:
                decoded_line = data_bytes.decode("utf-8", errors="replace")
                data = json.loads(decoded_line, strict=False)

                if isinstance(data, dict) and data.get("completed"):
                    return

                # _extract_sse_content 永远返回 (parsed_items, new_reasoning_mode)
                # 只要 JSON 解析成功就不放入 pending_json（避免首包 role-only 块被误判为损坏）
                parsed_items, reasoning_mode = _extract_sse_content(data, reasoning_mode, logger)
                for parsed in parsed_items:
                    # Handle different types of content
                    if parsed["type"] == "content":
                        yield {"content": parsed["data"]}
                    elif parsed["type"] == "reasoning":
                        yield {"reasoning": parsed["data"]}
                    elif parsed["type"] == "tool_calls":
                        yield {"tool_calls": parsed["data"]}
                    elif parsed["type"] == "usage":
                        yield {"usage": parsed["data"]}
                    elif parsed["type"] == "finish":
                        yield {"finish_reason": parsed["data"]}
            except Exception:
                pending_json = data_bytes


def _extract_sse_content(
    data: Dict[str, Any],
    reasoning_mode: bool,
    logger=None
) -> tuple:
    """
    从 SSE 数据中提取 content、reasoning_content、tool_calls、usage、finish_reason

    Returns:
        (list_of_parsed_items, new_reasoning_mode) 元组，永远返回不会为 None。
        JSON 解析成功但没有可提取内容时，list 为空。
        每个 parsed_item 格式: {"type": ..., "data": ...}
        type 可以是: "content", "reasoning", "tool_calls", "usage", "finish"

    注意：DeepSeek 的 usage 可能出现在最后一个 chunk，和 choices（带 finish_reason）共存，
    因此必须无论 choices 是否为空都检查 usage。
    """
    try:
        parsed_items = []
        new_reasoning_mode = reasoning_mode

        # 先取 usage（可能与 choices 共存，如 DeepSeek 的最后一个 finish chunk）
        usage = data.get("usage")
        if isinstance(usage, dict) and usage:
            parsed_items.append({"type": "usage", "data": usage})

        choices = data.get("choices") or []
        if not choices:
            return parsed_items, new_reasoning_mode

        delta = (choices[0] or {}).get("delta") or {}

        # 优先处理 tool_calls（DeepSeek v4 原生工具调用）
        tool_calls = delta.get("tool_calls")
        if tool_calls:
            parsed_items.append({"type": "tool_calls", "data": tool_calls})

        # 处理 reasoning_content（DeepSeek 思考模式）
        reasoning = delta.get("reasoning_content")
        if reasoning:
            parsed_items.append({"type": "reasoning", "data": reasoning})
            new_reasoning_mode = True

        # 处理 MiniMax reasoning_details（reasoning_split 模式）
        reasoning_details = delta.get("reasoning_details")
        if isinstance(reasoning_details, list) and reasoning_details:
            reasoning_text = ""
            for detail in reasoning_details:
                if isinstance(detail, dict) and detail.get("text"):
                    reasoning_text += detail["text"]
            if reasoning_text:
                parsed_items.append({"type": "reasoning", "data": reasoning_text})
                new_reasoning_mode = True

        # 提取正常回复内容
        content = delta.get("content")
        if content:
            parsed_items.append({"type": "content", "data": content})
            new_reasoning_mode = False

        # 处理 finish_reason
        finish_reason = (choices[0] or {}).get("finish_reason")
        if finish_reason:
            parsed_items.append({"type": "finish", "data": finish_reason})

        return parsed_items, new_reasoning_mode
    except Exception as e:
        if logger:
            logger.error(f"Chunk processing error: {e}")
        return [], reasoning_mode


def _try_parse_single_content(pending_data: bytes, logger=None) -> Optional[str]:
    """
    尝试解析单个content（用于非data:开头的行）

    Returns:
        content字符串，None表示解析失败
    """
    try:
        decoded_line = pending_data.decode("utf-8", errors="replace")
        data = json.loads(decoded_line, strict=False)
        choices = data.get("choices") or []
        if choices:
            delta = (choices[0] or {}).get("delta") or {}
            content = delta.get("content")
            if content:
                return content
    except Exception:
        pass
    return None
