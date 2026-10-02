#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SiliconFlow API Client (siliconflow_client.py)

Provides integration with SiliconFlow API (OpenAI-compatible).
"""

import os
import json
import asyncio
import time
import random
from typing import List, Dict, Optional, Any

from config.settings_model import PROVIDER_BASE_URLS
from core.utils.logger import get_logger
from core.utils.debug_markers import ensure_debug_error_prefix
from core.utils.async_locks import LazyAsyncLock
from . import LLMModule
from core.llm.openai_compat.client import LLMSessionMixin
from core.llm.llm_logger import log_llm_call_stats, log_api_call
from core.llm.model_capabilities import (
    is_vision_model,
    has_image_content,
    describe_routing,
)

logger = get_logger("siliconflow_client")

# 从统一常量读取 siliconflow base_url，保留兜底默认值
SILICONFLOW_BASE_URL = PROVIDER_BASE_URLS.get(
    "siliconflow", "https://api.siliconflow.cn/v1/chat/completions"
)

class SiliconFlowClient(LLMSessionMixin, LLMModule):
    """
    Client for interacting with SiliconFlow API

    视觉路由策略(与 OpenAIClient 基类一致):
    - 主模型是多模态(is_vision_model=True) → 一阶段:直接用主模型处理含图消息
    - 主模型是纯文本 + 消息含图片 → 两阶段:先用 VL 中转模型描述图片,再用主模型回复
    - 消息无图片 → 走默认 generate / _stream_generate
    """

    VISION_MODEL = "Qwen/Qwen3-VL-235B-A22B-Thinking"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        vision_model: Optional[str] = None,
    ):
        """
        Initialize SiliconFlow Client

        Args:
            api_key: SiliconFlow API Key
            model: Default model name
            vision_model: VL 中转模型名(仅当主模型是纯文本 + 消息含图片时使用)
        """
        super().__init__()
        self.api_key = api_key or os.getenv("SILICONFLOW_API_KEY")
        self.default_model = model or "Pro/moonshotai/Kimi-K2.6"
        self.VISION_MODEL = vision_model or "Qwen/Qwen3-VL-235B-A22B-Thinking"
        self.base_url = SILICONFLOW_BASE_URL
        self.timeout = 60
        self.session = None
        self.initialized = False
        self._rate_lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._last_request_at = 0.0
        self._min_interval_sec = float(os.getenv("SILICONFLOW_MIN_INTERVAL_SEC", "1.2"))
        self._max_retries = int(os.getenv("SILICONFLOW_MAX_RETRIES", "3"))
        self._retry_base_sec = float(os.getenv("SILICONFLOW_RETRY_BASE_SEC", "1.5"))

        if not self.api_key:
            logger.warning(
                "SiliconFlow API Key not found. Please set SILICONFLOW_API_KEY in .env."
            )
        else:
            logger.info("SiliconFlow Client initialized with API Key")

    def _sanitize_messages(self, messages: list) -> list:
        """
        规范化messages中的role字段，确保符合SiliconFlow要求
        """
        allowed_roles = {"system", "user", "assistant", "tool"}
        sanitized = []
        for msg in messages:
            if not isinstance(msg, dict):
                sanitized.append(msg)
                continue
            role = msg.get("role", "user")
            if role not in allowed_roles:
                role = "system"
            new_msg = dict(msg)
            new_msg["role"] = role
            sanitized.append(new_msg)
        return sanitized

    def _has_image_content(self, messages: list) -> bool:
        """
        检测消息列表中是否包含图片内容(委托给统一模块)
        """
        return has_image_content(messages)

    async def _describe_images_via_vl(self, messages: list) -> Optional[list]:
        """用 VL 中转模型把消息里的图片描述成文字,返回替换后的新消息列表

        仅当主模型是纯文本 + 消息含图片时调用。
        与 OpenAIClient._describe_images_via_vl 等效,但走 SiliconFlow 自己的速率限制和重试。
        """
        vl_messages: list = []
        image_descriptions: List[str] = []
        vl_prompt = "请详细描述这张图片的内容,包括场景、人物、动作、文字、色彩氛围等。描述要自然,像你在亲眼看到这张图一样。"

        for msg in messages:
            if not isinstance(msg, dict):
                vl_messages.append(msg)
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                vl_messages.append(msg)
                continue
            text_parts: List[str] = []
            image_items: List[dict] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "image_url":
                        image_items.append(item)
                    elif item.get("type") == "text" and item.get("text"):
                        text_parts.append(str(item["text"]))
            if not image_items:
                vl_messages.append(msg)
                continue

            for idx, img_item in enumerate(image_items):
                vl_payload_msg = {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": vl_prompt},
                        img_item,
                    ],
                }
                result = await self._vision_inference(
                    [vl_payload_msg], max_tokens=1024, temperature=0.5
                )
                if result.get("status") == "success":
                    image_descriptions.append(result.get("text", "").strip() or f"[图片{idx+1}描述为空]")
                else:
                    logger.error("VL 中转失败: %s", result.get("error"))
                    image_descriptions.append(f"[图片{idx+1}描述失败]")

            new_content_parts: List[dict] = []
            if text_parts:
                new_content_parts.append({"type": "text", "text": "\n".join(text_parts)})
            img_desc_text = "【你看到了一张图片:" + "\n".join(image_descriptions) + "】"
            new_content_parts.append({"type": "text", "text": img_desc_text})
            vl_messages.append({"role": msg.get("role", "user"), "content": new_content_parts})

        return vl_messages

    async def _vision_inference(self, messages: list, **kwargs) -> Dict[str, Any]:
        """
        调用 VL 中转模型处理含图消息,返回模型生成的文字
        用途:在两阶段中转路径里,把图片描述成文字
        """
        if not self.api_key:
            return {"status": "error", "error": "SiliconFlow API Key missing"}

        max_tokens = int(kwargs.get("max_tokens", 4096))
        temperature = float(kwargs.get("temperature", 0.7))
        top_p = float(kwargs.get("top_p", 0.9))

        payload = {
            "model": self.VISION_MODEL,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
        }

        try:
            session = await self._get_session()
            for attempt in range(max(1, self._max_retries)):
                await self._throttle()
                log_llm_call_stats(
                    provider="siliconflow",
                    model=self.VISION_MODEL,
                    messages=messages,
                    stream=False,
                )
                async with session.post(self.base_url, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "choices" in data and len(data["choices"]) > 0:
                            msg = data["choices"][0].get("message", {})
                            content = msg.get("content") or ""
                            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
                            if not content.strip() and reasoning.strip():
                                content = reasoning
                            logger.info(f"VL模型直接回复: {content[:200]}...")
                            return {
                                "status": "success",
                                "text": content,
                                "usage": data.get("usage", {}),
                            }
                        return {
                            "status": "error",
                            "error": "No choices in vision response",
                            "raw": data,
                        }

                    text = await response.text()
                    if self._is_retryable_http_error(
                        response.status, text
                    ) and attempt < (self._max_retries - 1):
                        delay = self._retry_delay_sec(
                            attempt, response.headers.get("Retry-After")
                        )
                        logger.warning(
                            f"Vision API Error {response.status}: {text} | retry in {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.error(f"Vision API Error {response.status}: {text}")
                    return {
                        "status": "error",
                        "error": f"HTTP {response.status}: {text}",
                    }
        except Exception as e:
            logger.error(f"Vision Request Failed: {e}")
            return {"status": "error", "error": str(e)}

    async def initialize(self):
        """
        Initialize LLM module
        """
        if not self.initialized:
            await self._get_session()
            self.initialized = True
            logger.info("SiliconFlow Client initialized")

    async def _throttle(self):
        async with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_at
            if elapsed < self._min_interval_sec:
                await asyncio.sleep(self._min_interval_sec - elapsed)
            self._last_request_at = time.monotonic()

    def _is_retryable_http_error(self, status: int, body_text: str) -> bool:
        if status in {429, 500, 502, 503, 504}:
            return True
        if status == 403:
            t = (body_text or "").lower()
            if any(
                k in t for k in ["rpm", "rate", "limit", "too many", "频率", "限流"]
            ):
                return True
        return False

    def _retry_delay_sec(self, attempt_index: int, retry_after: Optional[str]) -> float:
        if retry_after:
            try:
                ra = float(str(retry_after).strip())
                if ra >= 0:
                    return min(ra, 60.0)
            except Exception:
                pass
        base = self._retry_base_sec * (2**attempt_index)
        jitter = random.random() * 0.4
        return min(base + jitter, 60.0)

    async def chat(self, messages: list, **kwargs) -> dict:
        """
        Chat generation
        视觉路由:
        - 主模型是多模态 → 直接用主模型处理含图消息(一阶段)
        - 主模型是纯文本 + 含图片 → 先走 VL 中转描述图片,再调主模型(两阶段)
        - 无图片 → 走默认 generate
        """
        if not self.initialized:
            await self.initialize()

        messages = self._sanitize_messages(messages)

        if self._has_image_content(messages):
            model_name = kwargs.get("model", self.default_model)
            route_desc = describe_routing(model_name, True)
            logger.info("SiliconFlow 视觉路由: %s", route_desc)

            if is_vision_model(model_name):
                # 主模型自带视觉,一阶段直通
                result = await self.generate(messages, **kwargs)
            else:
                # 纯文本主模型,两阶段中转
                replaced = await self._describe_images_via_vl(messages)
                if replaced is None:
                    # VL 中转失败,回退到原消息(主模型可能报错,但保留原有行为)
                    replaced = messages
                result = await self.generate(replaced, **kwargs)

            if result["status"] == "success":
                return {"response": result["text"], "finish_reason": result.get("finish_reason")}
            else:
                logger.error(f"Chat failed: {result.get('error')}")
                return ensure_debug_error_prefix(f"Error: {result.get('error')}")

        result = await self.generate(messages, **kwargs)
        if result["status"] == "success":
            return {"response": result["text"], "finish_reason": result.get("finish_reason")}
        else:
            logger.error(f"Chat failed: {result.get('error')}")
            return ensure_debug_error_prefix(f"Error: {result.get('error')}")

    async def stream_chat(self, messages: list, **kwargs) -> Any:
        """
        Stream chat generation
        视觉路由:
        - 主模型是多模态 → 直接用主模型流式处理含图消息(一阶段)
        - 主模型是纯文本 + 含图片 → 先走 VL 中转描述图片(非流式),再用主模型流式输出(两阶段)
        - 无图片 → 走默认 _stream_generate
        """
        if not self.initialized:
            await self.initialize()

        messages = self._sanitize_messages(messages)

        if self._has_image_content(messages):
            model_name = kwargs.get("model", self.default_model)
            route_desc = describe_routing(model_name, True)
            logger.info("SiliconFlow 视觉路由(stream): %s", route_desc)

            if is_vision_model(model_name):
                # 主模型自带视觉,一阶段直通
                async for chunk in self._stream_generate(messages, **kwargs):
                    yield chunk
                return

            # 纯文本主模型,两阶段中转:先 VL 描述(非流式),再主模型流式输出
            replaced = await self._describe_images_via_vl(messages)
            if replaced is None:
                replaced = messages
            async for chunk in self._stream_generate(replaced, **kwargs):
                yield chunk
            return

        async for chunk in self._stream_generate(messages, **kwargs):
            yield chunk

    async def _stream_generate(self, messages: list, **kwargs) -> Any:
        """
        内部流式生成方法
        """
        model = kwargs.get("model", self.default_model)
        try:
            max_tokens = int(kwargs.get("max_tokens", 4096))
        except (ValueError, TypeError):
            max_tokens = 4096

        temperature = kwargs.get("temperature", 0.7)
        top_p = kwargs.get("top_p", 0.9)

        stop = kwargs.get("stop", None)

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
        }
        if stop:
            valid_stop = [s for s in stop if s and len(s) >= 2]
            if valid_stop:
                payload["stop"] = valid_stop

        try:
            session = await self._get_session()
            for attempt in range(max(1, self._max_retries)):
                await self._throttle()
                log_llm_call_stats(
                    provider="siliconflow",
                    model=model,
                    messages=messages,
                    stream=True,
                    extra={"temperature": temperature, "max_tokens": max_tokens, "top_p": top_p},
                )
                log_api_call(
                    provider="siliconflow",
                    model=model,
                    prompt_preview=str(messages[-1].get("content", ""))[:100] if messages else "",
                    is_retry=(attempt > 0),
                )
                async with session.post(self.base_url, json=payload) as response:
                    if response.status != 200:
                        text = await response.text()
                        if self._is_retryable_http_error(
                            response.status, text
                        ) and attempt < (self._max_retries - 1):
                            delay = self._retry_delay_sec(
                                attempt, response.headers.get("Retry-After")
                            )
                            logger.warning(
                                f"Stream Error {response.status}: {text} | retry in {delay:.1f}s"
                            )
                            await asyncio.sleep(delay)
                            continue
                        logger.error(f"Stream Error {response.status}: {text}")
                        yield {"error": f"HTTP {response.status}: {text}"}
                        return

                    buffer = b""
                    async for chunk in response.content.iter_any():
                        buffer += chunk
                        while b"\n" in buffer:
                            line_bytes, buffer = buffer.split(b"\n", 1)
                            line = line_bytes.decode("utf-8", errors="replace").strip()
                            if not line:
                                continue

                            if line == "data: [DONE]":
                                continue

                            if line.startswith("data: "):
                                try:
                                    data = json.loads(line[6:])
                                    if "choices" in data and len(data["choices"]) > 0:
                                        delta = data["choices"][0].get("delta", {})

                                        # 处理 reasoning_content（DeepSeek 思考模式）
                                        reasoning = delta.get("reasoning_content")
                                        if reasoning:
                                            yield {"reasoning": reasoning}
                                            continue

                                        content = delta.get("content", "")
                                        if content:
                                            yield {"content": content}
                                except Exception as e:
                                    logger.error(
                                        f"JSON Parse Error: {e} | Line: {line}"
                                    )
                                    continue
                    return
        except Exception as e:
            logger.error(f"Stream Request Failed: {e}")
            yield {"error": str(e)}

    def get_status(self) -> Dict[str, Any]:
        return self._build_base_status(provider="SiliconFlow")

    def get_current_model_name(self):
        """
        Get current model name
        """
        return f"cloud:siliconflow:{self.default_model}"

    async def generate(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_p: float = 0.9,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Generate text using SiliconFlow API
        """
        if not self.api_key:
            return {"status": "error", "error": "SiliconFlow API Key missing"}

        model = model or self.default_model

        messages = self._sanitize_messages(messages)

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
        }

        try:
            session = await self._get_session()
            for attempt in range(max(1, self._max_retries)):
                await self._throttle()
                log_llm_call_stats(
                    provider="siliconflow",
                    model=model,
                    messages=messages,
                    stream=False,
                    extra={"temperature": temperature, "max_tokens": max_tokens, "top_p": top_p},
                )
                async with session.post(self.base_url, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "choices" in data and len(data["choices"]) > 0:
                            msg = data["choices"][0].get("message", {})
                            content = msg.get("content") or ""
                            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
                            if not content.strip() and reasoning.strip():
                                content = reasoning
                            finish_reason = (data["choices"][0] or {}).get("finish_reason")
                            return {
                                "status": "success",
                                "text": content,
                                "usage": data.get("usage", {}),
                                "finish_reason": finish_reason,
                            }
                        return {
                            "status": "error",
                            "error": "No choices in response",
                            "raw": data,
                        }

                    text = await response.text()
                    if self._is_retryable_http_error(
                        response.status, text
                    ) and attempt < (self._max_retries - 1):
                        delay = self._retry_delay_sec(
                            attempt, response.headers.get("Retry-After")
                        )
                        logger.warning(
                            f"API Error {response.status}: {text} | retry in {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.error(f"API Error {response.status}: {text}")
                    return {
                        "status": "error",
                        "error": f"HTTP {response.status}: {text}",
                    }
        except Exception as e:
            logger.error(f"Request Failed: {e}")
            return {"status": "error", "error": str(e)}


_siliconflow_client = None


def get_siliconflow_client():
    global _siliconflow_client
    if _siliconflow_client is None:
        _siliconflow_client = SiliconFlowClient()
    return _siliconflow_client
