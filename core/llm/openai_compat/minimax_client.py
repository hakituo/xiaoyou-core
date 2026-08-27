#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniMax客户端

继承OpenAIClient，提供MiniMax API的默认配置
支持 reasoning_split=True 将推理内容分离到 reasoning_details 字段
"""

from typing import Dict, Any, Optional

from core.llm.openai_compat.client import OpenAIClient
from core.utils.logger import get_logger

logger = get_logger("minimax_client")


MINIMAX_BASE_URL = "https://api.minimax.chat/v1/chat/completions"
MINIMAX_DEFAULT_MODEL = "MiniMax-M2.5"


class MiniMaxClient(OpenAIClient):
    """MiniMax专用客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url or MINIMAX_BASE_URL,
            model=model or MINIMAX_DEFAULT_MODEL,
        )

    def _strip_names(self, messages):
        """MiniMax 不支持 group chat，强制移除所有的 name 字段"""
        for msg in messages:
            if "name" in msg:
                del msg["name"]

    def _build_payload(self, messages: list, stream: bool, **kwargs) -> Dict[str, Any]:
        payload = super()._build_payload(messages, stream, **kwargs)
        payload["reasoning_split"] = True
        payload.pop("max_tokens", None)
        return payload

    async def chat(self, messages, **kwargs):
        self._strip_names(messages)
        return await super().chat(messages, **kwargs)

    async def stream_chat(self, messages, **kwargs):
        self._strip_names(messages)
        async for chunk in super().stream_chat(messages, **kwargs):
            yield chunk

    def get_status(self) -> Dict[str, Any]:
        return self._build_base_status(provider="MiniMax")
