#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAI兼容客户端模块

提供所有基于OpenAI兼容API的客户端实现，包括：
- OpenAIClient: 通用OpenAI兼容客户端
- AvelineClient: Aveline专用客户端
- DeepSeekClient: DeepSeek客户端
- MiniMaxClient: MiniMax客户端
- ArkClient: 火山方舟客户端
- ZhiPuClient: 智谱AI客户端
"""

from core.llm.openai_compat.client import OpenAIClient
from core.llm.openai_compat.aveline_client import AvelineClient
from core.llm.openai_compat.deepseek_client import DeepSeekClient
from core.llm.openai_compat.minimax_client import MiniMaxClient
from core.llm.openai_compat.ark_client import ArkClient
from core.llm.openai_compat.zhipu_client import ZhiPuClient

__all__ = [
    "OpenAIClient",
    "AvelineClient",
    "DeepSeekClient",
    "MiniMaxClient",
    "ArkClient",
    "ZhiPuClient",
]
