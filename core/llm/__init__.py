#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 模块入口（仅做 re-export，保持向后兼容）

实际实现已按职责拆分：
- base.py            : LLMConfig / LLMModule 抽象基类
- local_adapter.py   : LocalLLMAdapter（本地 GGUF 模型封装）
- cloud_router.py    : CloudRouterLLMModule（云端多 provider 路由）
- hybrid_module.py   : HybridLLMModule（本地+云端混合 + fallback 降级）
- factory.py         : get_llm_module() 工厂与实例管理
"""

from .base import LLMConfig, LLMModule
from .local_adapter import LocalLLMAdapter
from .cloud_router import CloudRouterLLMModule
from .hybrid_module import HybridLLMModule
from .factory import (
    get_llm_module,
    create_instance,
    get_instance,
    list_instances,
)

__all__ = [
    "LLMConfig",
    "LLMModule",
    "LocalLLMAdapter",
    "CloudRouterLLMModule",
    "HybridLLMModule",
    "get_llm_module",
    "create_instance",
    "get_instance",
    "list_instances",
]
