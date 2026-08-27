#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
消息规范化工具模块

负责消息格式标准化、角色映射和Payload构建
"""

import json
from typing import Dict, Any, Iterable, List, Optional


ALLOWED_ROLES = {"system", "user", "assistant", "tool"}


def normalize_role(role: str) -> str:
    """
    规范化角色名称

    Args:
        role: 原始角色字符串

    Returns:
        标准化后的角色
    """
    role = str(role or "user").strip().lower()
    if role in ALLOWED_ROLES:
        return role
    if role.startswith("system") or role in {"developer", "instruction"}:
        return "system"
    if role in {"bot", "model"}:
        return "assistant"
    return "user"


def normalize_content(content: Any) -> Any:
    """
    规范化消息内容

    Args:
        content: 原始内容

    Returns:
        规范化后的内容（字符串或多模态消息列表）
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    # 如果是列表且包含字典（多模态格式），保留原样
    if isinstance(content, list) and len(content) > 0 and isinstance(content[0], dict):
        return content
    if isinstance(content, (dict, list)):
        try:
            return json.dumps(content, ensure_ascii=False)
        except Exception:
            return str(content)
    return str(content)


def normalize_message(msg: Any) -> Optional[Dict[str, Any]]:
    """
    规范化单条消息

    Args:
        msg: 原始消息

    Returns:
        规范化后的消息字典，如果消息无效则返回None
    """
    if not isinstance(msg, dict):
        return {"role": "user", "content": str(msg)}

    role = normalize_role(msg.get("role", "user"))
    # 当有 tool_calls 时，content 必须为 None（DeepSeek/OpenAI API 要求）
    has_tool_calls = role == "assistant" and msg.get("tool_calls")
    if has_tool_calls and msg.get("content") is None:
        content = None
    else:
        content = normalize_content(msg.get("content", ""))

    result = {"role": role, "content": content}

    # Preserve tool_calls for assistant messages (DeepSeek v4 native function calling)
    if role == "assistant" and msg.get("tool_calls"):
        result["tool_calls"] = msg["tool_calls"]

    # Preserve reasoning_content for assistant messages (DeepSeek v4 thinking mode)
    if role == "assistant" and msg.get("reasoning_content"):
        result["reasoning_content"] = msg["reasoning_content"]

    # Preserve tool_call_id for tool messages
    if role == "tool" and msg.get("tool_call_id"):
        result["tool_call_id"] = msg["tool_call_id"]

    # Preserve name field if present
    if msg.get("name"):
        result["name"] = msg["name"]

    return result


def normalize_messages(messages: Iterable[Any]) -> List[Dict[str, Any]]:
    """
    规范化消息列表

    【缓存优化】保持消息的原始顺序，不再将 system 消息重排到最前面。
    DeepSeek Prompt Caching 基于前缀匹配，消息顺序必须稳定。
    上游代码（assembler.py）已经按缓存友好顺序构建消息列表，
    此处只需规范化格式，不做顺序调整。

    Args:
        messages: 原始消息迭代器

    Returns:
        规范化后的消息列表（保持原始顺序）
    """
    normalized: List[Dict[str, Any]] = []

    for msg in messages or []:
        normalized_msg = normalize_message(msg)
        if normalized_msg is None:
            continue
        normalized.append(normalized_msg)

    return normalized


def build_payload(
    messages: list,
    model: str,
    stream: bool,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    top_p: Optional[float] = None,
    repetition_penalty: Optional[float] = None,
    default_max_tokens: Optional[int] = 2048,
    **kwargs
) -> Dict[str, Any]:
    """
    构建API请求Payload

    Args:
        messages: 消息列表
        model: 模型名称
        stream: 是否流式
        temperature: 温度参数
        max_tokens: 最大token数
        top_p: top_p参数
        repetition_penalty: 重复惩罚参数
        default_max_tokens: 默认最大token数
        **kwargs: 其他API参数

    Returns:
        构建好的Payload字典
    """
    normalized_messages = normalize_messages(messages)

    try:
        if max_tokens is not None and max_tokens > 0:
            effective_max_tokens = max_tokens
        else:
            effective_max_tokens = None
    except (ValueError, TypeError):
        effective_max_tokens = None

    payload: Dict[str, Any] = {
        "model": model,
        "messages": normalized_messages,
        "temperature": temperature,
        "stream": stream,
    }
    if effective_max_tokens is not None:
        payload["max_tokens"] = effective_max_tokens

    for key in ["frequency_penalty", "presence_penalty", "stop", "prefix_caching",
                "reasoning_effort"]:
        if key in kwargs and kwargs[key] is not None:
            payload[key] = kwargs[key]

    if top_p is not None:
        payload["top_p"] = top_p
    if repetition_penalty is not None:
        payload["repetition_penalty"] = repetition_penalty

    return payload


def extract_prompt_preview(messages: list) -> str:
    """
    从消息列表中提取最后一条用户消息的预览

    Args:
        messages: 消息列表

    Returns:
        提示词预览字符串
    """
    if not messages:
        return ""
    last_msg = messages[-1]
    if isinstance(last_msg, dict):
        return str(last_msg.get("content", "") or "")
    return str(last_msg)


def roles_preview(messages: Any) -> str:
    """
    生成消息角色序列预览

    Args:
        messages: 消息列表

    Returns:
        角色预览字符串，如 "system -> user -> assistant"
    """
    roles: List[str] = []
    if isinstance(messages, list):
        for item in messages[:8]:
            if isinstance(item, dict):
                roles.append(str(item.get("role") or "user"))
            else:
                roles.append("user")
    return " -> ".join(roles)


def rebuild_payload_for_system_order(
    payload: Dict[str, Any],
    keep_single_system: bool = False
) -> Dict[str, Any]:
    """
    重新构建Payload以修复系统消息顺序问题

    Args:
        payload: 原始Payload
        keep_single_system: 是否只保留第一个系统消息

    Returns:
        修复后的Payload
    """
    new_payload = dict(payload or {})
    raw_messages = new_payload.get("messages") or []
    normalized = normalize_messages(raw_messages)

    if keep_single_system:
        kept: List[Dict[str, Any]] = []
        system_kept = False
        for msg in normalized:
            role = str((msg or {}).get("role") or "").strip().lower()
            if role == "system":
                if system_kept:
                    continue
                system_kept = True
            kept.append(msg)
        normalized = kept

    new_payload["messages"] = normalized
    return new_payload


def is_system_order_error(error_text: str) -> bool:
    """
    判断是否为系统消息顺序错误

    Args:
        error_text: 错误文本

    Returns:
        是否为系统消息顺序错误
    """
    return "system message must be at the beginning" in str(error_text or "").lower()
