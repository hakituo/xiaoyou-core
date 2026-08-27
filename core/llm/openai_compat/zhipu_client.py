#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智谱AI(ZhiPu)客户端

继承OpenAIClient，提供智谱AI API的默认配置
支持思考模式（thinking mode）、联网搜索（web_search）和视觉模型
"""

import base64
from typing import Dict, Any, Optional

from config.settings_model import PROVIDER_BASE_URLS
from core.llm.openai_compat.client import OpenAIClient
from core.llm.model_capabilities import is_vision_model
from core.utils.logger import get_logger

logger = get_logger("zhipu_client")

# 从统一常量读取，保留兜底默认值避免常量未加载时崩溃
ZHIPU_BASE_URL = PROVIDER_BASE_URLS.get(
    "zhipu", "https://open.bigmodel.cn/api/paas/v4/chat/completions"
)
ZHIPU_DEFAULT_MODEL = "glm-4.5-air"

ZHIPU_SUPPORTED_MODELS = {
    "glm-5.1",
    "glm-5-turbo",
    "glm-5",
    "glm-4.7",
    "glm-4.6",
    "glm-4.6v",
    "glm-4.5",
    "glm-4.5-air",
    "glm-4.5-airx",
    "glm-4.5-flash",
    "glm-4-flash-250414",
    "glm-4-flashx-250414",
}

VISION_MODELS = {"glm-4.6v", "glm-4.5v", "glm-5v-turbo"}

THINKING_MODELS = {
    "glm-5.1", "glm-5-turbo", "glm-5",
    "glm-4.7", "glm-4.6", "glm-4.6v",
    "glm-4.5", "glm-4.5-air", "glm-4.5-airx", "glm-4.5-flash",
}

SERVER_SIDE_SEARCH_MODELS = {
    "glm-4.5", "glm-4.5-air", "glm-4.5-airx", "glm-4.5-flash",
    "glm-4.6", "glm-4.6v", "glm-4.7",
    "glm-5", "glm-5-turbo", "glm-5.1",
}


class ZhiPuClient(OpenAIClient):
    """智谱AI专用客户端

    支持智谱AI特有功能：
    - thinking: 思考模式（深度推理），GLM-4.5及以上模型支持
    - web_search: 服务端联网搜索，通过tools参数注入
    - 视觉模型: glm-4.6v 等支持图片输入

    web_search有两种模式：
    - server_side: 智谱服务端搜索，在API请求中注入tools参数，搜索由智谱执行
    - client_side: 客户端搜索（如Bocha），由本地WebSearchTool执行后注入上下文

    当web_search_enabled=True且模型支持服务端搜索时，自动使用服务端搜索；
    否则回退到客户端搜索（由上层ChatAgent通过WebSearchTool处理）。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        thinking_enabled: bool = True,
        web_search_enabled: bool = False,
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url or ZHIPU_BASE_URL,
            model=model or ZHIPU_DEFAULT_MODEL,
        )
        self.thinking_enabled = thinking_enabled
        self.web_search_enabled = web_search_enabled
        self.default_max_tokens = 4096
        self.default_top_p = 0.95

    def get_status(self) -> Dict[str, Any]:
        return self._build_base_status(
            provider="ZhiPu",
            thinking_enabled=self.thinking_enabled,
            web_search_enabled=self.web_search_enabled,
        )

    def _is_vision_model(self, model: str) -> bool:
        """判断是否为视觉模型(委托给统一检测模块,兼容全局多模态名单)"""
        return is_vision_model(model)

    def _is_thinking_model(self, model: str) -> bool:
        return any(tm in model.lower() for tm in THINKING_MODELS)

    def _supports_server_side_search(self, model: str) -> bool:
        """判断模型是否支持智谱服务端web_search"""
        return any(sm in model.lower() for sm in SERVER_SIDE_SEARCH_MODELS)

    def _build_payload(self, messages: list, stream: bool, **kwargs) -> Dict[str, Any]:
        """构建智谱AI API请求Payload，自动注入思考模式和搜索工具参数"""
        model = kwargs.get("model", self.default_model)

        # 支持运行时动态覆盖web_search_enabled
        web_search_enabled = kwargs.pop("web_search_enabled", self.web_search_enabled)

        if self.thinking_enabled and self._is_thinking_model(model):
            extra_body = kwargs.get("extra_body", {})
            extra_body["thinking"] = {"type": "enabled"}
            kwargs["extra_body"] = extra_body

        if web_search_enabled and self._supports_server_side_search(model):
            tools = kwargs.get("tools", [])
            has_web_search = any(
                isinstance(t, dict) and t.get("type") == "web_search"
                for t in tools
            )
            if not has_web_search:
                tools.append({
                    "type": "web_search",
                    "web_search": {"enable": True},
                })
                kwargs["tools"] = tools
                logger.info(f"智谱服务端web_search已注入, model={model}")

        return super()._build_payload(messages, stream, **kwargs)

    @staticmethod
    def build_image_message(image_path: str, text: str = "请描述这张图片") -> Dict[str, Any]:
        """构建视觉模型的多模态消息

        Args:
            image_path: 图片文件路径
            text: 附带的文本提示

        Returns:
            包含图片和文本的user消息
        """
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        ext = image_path.lower().split(".")[-1]
        mime_map = {
            "jpg": "jpeg", "jpeg": "jpeg",
            "png": "png", "gif": "gif",
            "webp": "webp", "bmp": "bmp",
        }
        mime_ext = mime_map.get(ext, "jpeg")

        return {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": text,
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/{mime_ext};base64,{image_data}"
                    },
                },
            ],
        }
