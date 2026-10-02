#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aveline专用客户端

继承OpenAIClient，提供Aveline API的默认配置
"""

from typing import Dict, Any, Optional

from core.llm.openai_compat.client import OpenAIClient


class AvelineClient(OpenAIClient):
    """Aveline专用客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        aveline_url = "https://www.gpt4novel.com/api/xiaoshuoai/ext/v1/chat/completions"
        super().__init__(
            api_key=api_key,
            base_url=base_url or aveline_url,
            model=model
        )
        self.default_model = model or self.default_model
        self.default_max_tokens = None
        self.default_top_p = 0.35
        self.default_repetition_penalty = 1.05

    def get_status(self) -> Dict[str, Any]:
        return self._build_base_status(provider="Aveline")
