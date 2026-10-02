#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
火山方舟(Ark)客户端

继承OpenAIClient，提供火山方舟API的默认配置
"""

from typing import Dict, Any, Optional

from config.settings_model import PROVIDER_BASE_URLS
from core.llm.openai_compat.client import OpenAIClient


# 从统一常量读取，保留兜底默认值避免常量未加载时崩溃
ARK_BASE_URL = PROVIDER_BASE_URLS.get(
    "ark", "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
)
ARK_DEFAULT_MODEL = "doubao-seed-2-0-lite-260215"


class ArkClient(OpenAIClient):
    """火山方舟(Ark)专用客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url or ARK_BASE_URL,
            model=model or ARK_DEFAULT_MODEL,
        )

    def get_status(self) -> Dict[str, Any]:
        return self._build_base_status(provider="Ark")
