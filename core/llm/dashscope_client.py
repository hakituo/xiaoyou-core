#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DashScope API Client (dashscope_client.py)

Provides integration with Alibaba Cloud's DashScope API (e.g. Qwen-Max).
"""

import json
import os
from typing import List, Dict, Optional, Any, AsyncGenerator

# Import logger
from core.utils.logger import get_logger
from core.utils.debug_markers import ensure_debug_error_prefix
from . import LLMModule
from core.llm.openai_compat.client import LLMSessionMixin

logger = get_logger("dashscope_client")


class DashScopeClient(LLMSessionMixin, LLMModule):
    """
    Client for interacting with DashScope API (Qwen models)
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize DashScope Client

        Args:
            api_key: DashScope API Key
            model: Default model name (e.g. qwen-plus, qwen-max)
        """
        super().__init__()
        # Priority:
        # 1. Passed arg (仅允许 qwen3.5-plus)
        # 2. 固定使用 qwen3.5-plus
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        # 固定使用 Qwen 3.5 Plus，不支持其他模型
        self.default_model = "qwen3.5-plus"
        # 注意：此处使用的是 DashScope 原生 API URL（text-generation/generation），
        # 与 config.settings_model.PROVIDER_BASE_URLS["dashscope"] 中的 OpenAI 兼容模式 URL
        # （compatible-mode/v1/chat/completions）不同，故不复用该常量。
        # 如需切换为 OpenAI 兼容模式，请改用 OpenAIClient + PROVIDER_BASE_URLS["dashscope"]。
        self.base_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        self.timeout = 60
        self.session = None
        self.initialized = False

        if not self.api_key:
            logger.warning(
                "DashScope API Key not found. Please set DASHSCOPE_API_KEY in .env or config."
            )
        else:
            logger.info("DashScope Client initialized with API Key.")

    async def initialize(self):
        if not self.initialized:
            await self._get_session()
            self.initialized = True
            logger.info("DashScope Client initialized")

    async def chat(self, messages: list, **kwargs) -> dict:
        """
        Chat generation

        Args:
            messages: List of chat messages
            **kwargs: Additional parameters

        Returns:
            包含 response 和 finish_reason 的字典，或错误字符串
        """
        if not self.initialized:
            await self.initialize()

        history = messages[:-1] if len(messages) > 1 else []
        prompt = messages[-1]["content"] if messages else ""

        result = await self.generate(prompt, history, **kwargs)
        if result["status"] == "success":
            return {"response": result["text"], "finish_reason": result.get("finish_reason")}
        else:
            logger.error(f"Chat failed: {result.get('error')}")
            return ensure_debug_error_prefix(f"Error: {result.get('error')}")

    async def stream_chat(self, messages: list, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        """
        真流式对话补全。

        通过 DashScope 原生 SSE 接口（X-DashScope-SSE: enable）逐块返回内容，
        不再先调用 chat() 再假装 yield 一次。

        Args:
            messages: 消息列表
            **kwargs: 其他参数（max_tokens / temperature / top_p / repetition_penalty / model）

        Yields:
            包含 content / finish_reason / error 的字典
        """
        if not self.initialized:
            await self.initialize()

        if not self.api_key:
            yield {"error": "DashScope API Key missing"}
            return

        # 构造与 generate() 一致的 payload，但开启流式
        target_model = kwargs.pop("model", None) or self.default_model
        max_tokens = kwargs.pop("max_tokens", 4096)
        temperature = kwargs.pop("temperature", 0.8)
        top_p = kwargs.pop("top_p", 0.8)
        repetition_penalty = kwargs.pop("repetition_penalty", 1.1)

        # 直接使用传入的 messages，不再重新拼接（避免与 chat() 路径重复处理）
        payload = {
            "model": target_model,
            "input": {"messages": messages},
            "parameters": {
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "repetition_penalty": repetition_penalty,
                "result_format": "message",
                # 增量输出，避免每个 chunk 都是完整文本
                "incremental_output": True,
            },
        }

        # DashScope 原生流式必须通过 X-DashScope-SSE: enable 头开启
        stream_headers = {"X-DashScope-SSE": "enable"}

        try:
            session = await self._get_session()
            async with session.post(
                self.base_url, json=payload, headers=stream_headers
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.error(f"DashScope stream API Error {response.status}: {text}")
                    yield {"error": f"HTTP {response.status}: {text}"}
                    return

                # 解析 SSE 流
                async for chunk in self._parse_dashscope_sse(response.content):
                    if chunk:
                        yield chunk
        except Exception as e:
            logger.error(f"DashScope stream request failed: {e}")
            yield {"error": str(e)}

    async def _parse_dashscope_sse(
        self, response_content
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """解析 DashScope 原生 SSE 流。

        DashScope 原生流式响应格式（开启 incremental_output 后）：
            data:{"output":{"choices":[{"message":{"content":"增量文本","role":"assistant"},"finish_reason":"null"}]},"usage":{}}
            ...
            data:{"output":{"choices":[{"message":{"content":"","role":"assistant"},"finish_reason":"stop"}]},"usage":{...}}
            data:[DONE]

        与 OpenAI 兼容格式的区别：
        - 用 message.content（不是 delta.content）
        - finish_reason 字符串 "null" 表示未结束，"stop" 表示结束
        """
        buffer = b""
        async for raw_chunk in response_content.iter_any():
            if not raw_chunk:
                continue
            buffer += raw_chunk
            # SSE 事件以空行分隔，但 DashScope 实际可能用单换行分隔 data: 行
            while b"\n" in buffer:
                raw_line, buffer = buffer.split(b"\n", 1)
                line = raw_line.strip()
                if not line:
                    continue
                if not line.startswith(b"data:"):
                    continue

                data_bytes = line[5:].strip()
                if data_bytes == b"[DONE]":
                    return

                try:
                    data = json.loads(data_bytes.decode("utf-8", errors="replace"))
                except Exception as e:
                    logger.warning(f"DashScope SSE 解析失败: {e}, raw={data_bytes!r}")
                    continue

                # 错误响应
                if "code" in data and "output" not in data:
                    yield {"error": f"DashScope Error: {data.get('message')}"}
                    return

                output = data.get("output") or {}
                choices = output.get("choices") or []
                if not choices:
                    continue

                choice = choices[0] or {}
                message = choice.get("message") or {}
                content = message.get("content")
                finish_reason_raw = choice.get("finish_reason")

                # DashScope 用字符串 "null" 表示未结束
                finish_reason: Optional[str] = None
                if finish_reason_raw and str(finish_reason_raw).lower() != "null":
                    finish_reason = str(finish_reason_raw)

                if content:
                    yield {"content": content}

                if finish_reason:
                    yield {"finish_reason": finish_reason, "usage": data.get("usage", {})}

    def get_status(self) -> Dict[str, Any]:
        return self._build_base_status(provider="DashScope", llm_status={"instances_count": 1})

    async def generate(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.8,
        top_p: float = 0.8,
        repetition_penalty: float = 1.1,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Generate text using DashScope API
        """
        if not self.api_key:
            return {"status": "error", "error": "DashScope API Key missing"}

        target_model = model or self.default_model

        # Construct messages from history + prompt
        messages = []
        if history:
            for msg in history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                messages.append({"role": role, "content": content})

        # Append current prompt as user message if not already in history (usually it isn't)
        # Check if the last message is the same as prompt to avoid duplication if caller handled it
        if not messages or messages[-1]["content"] != prompt:
            messages.append({"role": "user", "content": prompt})

        payload = {
            "model": target_model,
            "input": {"messages": messages},
            "parameters": {
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "repetition_penalty": repetition_penalty,
                "result_format": "message",
            },
        }

        try:
            session = await self._get_session()
            async with session.post(self.base_url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    if "output" in data and "choices" in data["output"]:
                        choice = data["output"]["choices"][0]
                        content = choice["message"]["content"]
                        finish_reason = choice.get("finish_reason")
                        return {
                            "status": "success",
                            "text": content,
                            "usage": data.get("usage", {}),
                            "finish_reason": finish_reason,
                        }
                    elif "code" in data:
                        return {
                            "status": "error",
                            "error": f"DashScope Error: {data.get('message')}",
                            "code": data.get("code"),
                        }
                    else:
                        return {
                            "status": "error",
                            "error": "Unknown response format",
                            "raw": data,
                        }
                else:
                    text = await response.text()
                    logger.error(f"DashScope API Error {response.status}: {text}")
                    return {
                        "status": "error",
                        "error": f"HTTP {response.status}: {text}",
                    }
        except Exception as e:
            logger.error(f"DashScope Request Failed: {e}")
            return {"status": "error", "error": str(e)}


# Global instance
_dashscope_client = None


def get_dashscope_client():
    global _dashscope_client
    if _dashscope_client is None:
        _dashscope_client = DashScopeClient()
    return _dashscope_client
