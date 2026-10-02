#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek 客户端

继承 OpenAIClient，提供 DeepSeek API 的默认配置
支持思考模式（thinking mode）和 reasoning_effort 参数
"""

from typing import Dict, Any, Optional

from config.settings_model import PROVIDER_BASE_URLS
from core.llm.openai_compat.client import OpenAIClient


# 从统一常量读取，保留兜底默认值避免常量未加载时崩溃
DEEPSEEK_BASE_URL = PROVIDER_BASE_URLS.get(
    "deepseek", "https://api.deepseek.com/chat/completions"
)
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"


class DeepSeekClient(OpenAIClient):
    """DeepSeek 专用客户端
    
    支持 DeepSeek 特有的思考模式功能：
    - thinking: 控制思考模式开关
    - reasoning_effort: 控制思考强度 (high/max)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        thinking_enabled: bool = True,  # 默认启用思考模式
        reasoning_effort: str = "high",  # 思考强度：high 或 max
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url or DEEPSEEK_BASE_URL,
            model=model or DEEPSEEK_DEFAULT_MODEL,
        )
        # DeepSeek 特有参数
        self.thinking_enabled = thinking_enabled
        self.reasoning_effort = reasoning_effort

    def get_status(self) -> Dict[str, Any]:
        return self._build_base_status(
            provider="DeepSeek",
            thinking_enabled=self.thinking_enabled,
            reasoning_effort=self.reasoning_effort,
        )

    def _build_payload(self, messages: list, stream: bool, **kwargs) -> Dict[str, Any]:
        """构建 DeepSeek API 请求 Payload，自动注入思考模式参数"""
        if self.thinking_enabled:
            extra_body = kwargs.get("extra_body", {})
            extra_body["thinking"] = {"type": "enabled"}
            kwargs["extra_body"] = extra_body

            if self.reasoning_effort:
                kwargs["reasoning_effort"] = self.reasoning_effort

        payload = super()._build_payload(messages, stream, **kwargs)

        # 流式请求要求服务端在最后一个 chunk 返回 usage
        # （含 prompt_cache_hit_tokens / prompt_cache_miss_tokens，供缓存命中率统计）。
        # DeepSeek v4 流式默认不带 usage，必须显式开启 include_usage。
        if stream:
            payload.setdefault("stream_options", {"include_usage": True})

        return payload
