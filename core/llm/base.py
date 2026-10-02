#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 模块抽象基类与配置定义

本文件定义 LLM 模块的统一接口（LLMModule 抽象基类）和配置数据类（LLMConfig），
供 local_adapter / cloud_router / hybrid_module 等具体实现继承使用。
"""

from typing import Dict, Any, AsyncGenerator
from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class LLMConfig:
    """
    LLM配置类
    """

    model_name: str
    device: str = "auto"
    max_context_length: int = 2048
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 50


class LLMModule(ABC):
    """
    LLM模块抽象基类
    """

    @abstractmethod
    async def initialize(self):
        """
        初始化LLM模块
        """
        pass

    @abstractmethod
    async def chat(self, messages: list, **kwargs):
        """
        聊天生成
        """
        pass

    @abstractmethod
    async def stream_chat(
        self, messages: list, **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式聊天生成
        """
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """
        获取模块状态
        """
        pass
