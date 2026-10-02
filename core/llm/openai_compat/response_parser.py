#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""非流式响应解析模块

从 client.py 拆出，负责解析 OpenAI 兼容 API 的非流式响应。
包含 reasoning 泄漏检测、DSML 工具调用兜底解析、MiniMax TOOL_CALL 格式提取等逻辑。
"""

import re
from typing import Any, Dict

from core.utils.logger import get_logger

from .dsml_parser import parse_dsml_tool_calls, has_dsml_tokens
from .stream_parser import parse_sse_stream

logger = get_logger("openai_client")

# 推理内容泄漏标记：当 content 中出现这些短语时，判定为推理泄漏
_REASONING_LEAK_MARKERS = [
    "规则说", "指令说", "约束说", "要求我",
    "按照规则", "根据指令", "根据约束", "根据要求",
    "我应该", "我需要先", "我决定",
    "优先顺着", "优先选择", "优先考虑",
    "【核心指令", "【核心约束", "【主动发起模式",
    "【强制字数限制", "【句式多样性",
]


def looks_like_reasoning_leak(text: str) -> bool:
    """检测文本是否包含推理泄漏标记"""
    raw = str(text or "").strip()
    if not raw:
        return False
    for marker in _REASONING_LEAK_MARKERS:
        if marker in raw:
            return True
    return False


def _attach_usage(result: Dict[str, Any], data: Any) -> Dict[str, Any]:
    """把原始响应里的 usage 附到解析结果上（供上层记录 prompt 缓存命中率）"""
    usage = data.get("usage") if isinstance(data, dict) else None
    if isinstance(usage, dict) and usage:
        result["usage"] = usage
    return result


async def parse_non_stream_response(response: Any) -> Dict[str, Any]:
    """解析非流式响应，返回包含 content、finish_reason 和 tool_calls 的字典

    纯函数，无 self 依赖。调用方传入 aiohttp response 对象即可。
    """
    content_type = response.headers.get("Content-Type", "")

    # 某些 API 在非流式请求时返回 event-stream，按流式解析
    if "text/event-stream" in content_type:
        logger.warning(
            "API returned stream for non-stream request. Parsing stream buffer..."
        )
        full_content = ""
        async for chunk in parse_sse_stream(response.content, logger):
            if "content" in chunk:
                full_content += chunk["content"]
        return {"content": full_content if full_content else "Error: Stream parsing failed", "finish_reason": None}

    data = await response.json()
    if "choices" in data and len(data["choices"]) > 0:
        msg = (data["choices"][0] or {}).get("message") or {}
        content = msg.get("content")
        reasoning = msg.get("reasoning_content") or msg.get("reasoning")
        reasoning_details = msg.get("reasoning_details")
        tool_calls = msg.get("tool_calls")
        finish_reason = (data["choices"][0] or {}).get("finish_reason")

        # 优先处理 tool_calls（原生函数调用）
        if finish_reason == "tool_calls" and tool_calls:
            logger.info(
                "API returned tool_calls. count=%d model=%s",
                len(tool_calls),
                data.get("model"),
            )
            result = {
                "content": content or "",
                "finish_reason": finish_reason,
                "tool_calls": tool_calls,
            }
            if reasoning and isinstance(reasoning, str) and reasoning.strip():
                result["reasoning_content"] = reasoning
            return _attach_usage(result, data)

        if isinstance(content, str) and content.strip():
            has_reasoning_details = isinstance(reasoning_details, list) and reasoning_details
            if has_reasoning_details and looks_like_reasoning_leak(content):
                reasoning_text = content
                for detail in reasoning_details:
                    if isinstance(detail, dict) and detail.get("text"):
                        reasoning_text += "\n" + detail["text"]
                logger.info(
                    "MiniMax reasoning_split: content含推理语言且有reasoning_details，"
                    "content长度=%d，推理长度=%d，模型=%s",
                    len(content),
                    len(reasoning_text),
                    data.get("model"),
                )
                return _attach_usage({
                    "content": "",
                    "finish_reason": finish_reason,
                    "reasoning_only": True,
                    "reasoning_text": reasoning_text,
                }, data)
            result = {"content": content, "finish_reason": finish_reason}
            if reasoning and isinstance(reasoning, str) and reasoning.strip():
                result["reasoning_content"] = reasoning
            if tool_calls:
                result["tool_calls"] = tool_calls
            elif has_dsml_tokens(content):
                cleaned, dsml_calls = parse_dsml_tool_calls(content)
                if dsml_calls:
                    logger.info(
                        "DSML兜底解析: 从content中提取到%d个工具调用, 模型=%s",
                        len(dsml_calls),
                        data.get("model"),
                    )
                    result["content"] = cleaned
                    result["tool_calls"] = dsml_calls
                    if not finish_reason:
                        result["finish_reason"] = "tool_calls"
            # MiniMax-M2.5 等模型有时输出 [TOOL_CALL]...[/TOOL_CALL] 格式
            # 这是模型训练数据中自带的工具调用格式，项目未注册这些工具
            # 尝试提取 --text 参数中的实际文本，避免原始格式泄露给用户
            if "[TOOL_CALL]" in content and "[/TOOL_CALL]" in content:
                _tc_pattern = re.compile(r"\[TOOL_CALL\](.*?)\[/TOOL_CALL\]", re.DOTALL)
                _extracted = []
                for _m in _tc_pattern.finditer(content):
                    _text_match = re.search(r'--text\s+["\u201c](.+?)["\u201d]', _m.group(1), re.DOTALL)
                    if _text_match:
                        _extracted.append(_text_match.group(1).strip())
                _cleaned = _tc_pattern.sub("", content).strip()
                if _extracted:
                    result["content"] = " ".join(_extracted)
                    logger.info(
                        "MiniMax TOOL_CALL提取: 从[TOOL_CALL]中提取到文本，长度=%d，模型=%s",
                        len(result["content"]),
                        data.get("model"),
                    )
                elif _cleaned:
                    result["content"] = _cleaned
            return _attach_usage(result, data)

        if isinstance(reasoning_details, list) and reasoning_details:
            reasoning_text = ""
            for detail in reasoning_details:
                if isinstance(detail, dict) and detail.get("text"):
                    reasoning_text += detail["text"]
            if reasoning_text.strip():
                logger.info(
                    "MiniMax reasoning_split: content为空但有reasoning_details，"
                    "推理长度=%d，模型=%s",
                    len(reasoning_text),
                    data.get("model"),
                )
                return _attach_usage({
                    "content": "",
                    "finish_reason": finish_reason,
                    "reasoning_only": True,
                    "reasoning_text": reasoning_text,
                }, data)

        if isinstance(reasoning, str) and reasoning.strip():
            return _attach_usage({
                "content": "",
                "finish_reason": finish_reason,
                "reasoning_content": reasoning,
                "reasoning_only": True,
            }, data)
        if isinstance(content, str):
            logger.warning(
                "OpenAI-compatible API returned empty content. finish_reason=%s model=%s",
                finish_reason,
                data.get("model"),
            )
            return _attach_usage(
                {"content": "Error: Empty response content", "finish_reason": finish_reason},
                data,
            )
        return _attach_usage(
            {"content": "Error: No response content", "finish_reason": finish_reason},
            data,
        )
    return _attach_usage({"content": "Error: No response content", "finish_reason": None}, data)
