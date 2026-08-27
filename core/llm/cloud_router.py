#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云端路由 LLM 模块（CloudRouterLLMModule）

管理多个云端 provider 客户端（SiliconFlow / DeepSeek / DashScope / Aveline /
Ark / Zhipu / OpenAI 等），按 model_path 路由到对应客户端。
支持：
- 延迟创建非默认 provider 客户端（lazy_providers）
- 多 API key 格式：cloud:provider:key_alias:model
- 默认 provider 自动回退选择
"""

import asyncio
from typing import Dict, Any, Optional, AsyncGenerator, Tuple

from core.utils.debug_markers import ensure_debug_error_prefix
from core.utils.logger import get_logger
from core.contracts import LLMModuleType

from .base import LLMModule

logger = get_logger("LLM")


class CloudRouterLLMModule(LLMModule):
    def __init__(self, clients: Dict[str, LLMModule], default_provider: str = "local", lazy_providers: Dict[str, callable] = None):
        self._clients = dict(clients or {})
        self._default_provider = str(default_provider or "local")
        self._lazy_providers: Dict[str, callable] = dict(lazy_providers or {})
        self._lazy_initialized: set = set()
        # P1-2: 跟踪延迟初始化的 fire-and-forget 任务，防止被 GC 后客户端未初始化
        self._pending_init_tasks: set = set()

    def _ensure_client(self, provider: str):
        """延迟创建非默认provider的客户端

        同步创建客户端实例，初始化由客户端在首次调用时自动完成
        （chat/stream_chat 内部有 initialized 检查）。
        避免使用 fire-and-forget task，防止与首次调用的 initialize() 竞态导致重复初始化。
        """
        if provider in self._clients or provider not in self._lazy_providers:
            return
        if provider in self._lazy_initialized:
            return
        self._lazy_initialized.add(provider)
        try:
            factory = self._lazy_providers[provider]
            client = factory()
            if client is not None:
                self._clients[provider] = client
                logger.info("延迟创建云端客户端: %s（初始化将在首次调用时完成）", provider)
            else:
                # 工厂返回 None：重置标志，允许下次重试
                self._lazy_initialized.discard(provider)
        except Exception as e:
            # 创建失败：重置标志，允许下次重试
            self._lazy_initialized.discard(provider)
            logger.warning("延迟创建云端客户端 %s 失败: %s", provider, e)

    def _ensure_all_clients(self):
        """创建所有延迟客户端"""
        for provider in list(self._lazy_providers.keys()):
            self._ensure_client(provider)

    async def reload(self):
        """重新加载配置"""
        from config.integrated_config import get_settings

        settings = get_settings()
        self._default_provider = settings.model.llm.provider
        logger.info(
            f"CloudRouterLLMModule reloaded. Default provider: {self._default_provider}"
        )

    async def initialize(self):
        async def _init_one(client):
            try:
                await client.initialize()
            except Exception:
                pass
        await asyncio.gather(*[_init_one(c) for c in self._clients.values()])

    async def shutdown(self):
        async def _shutdown_one(client):
            try:
                if hasattr(client, "shutdown"):
                    fn = getattr(client, "shutdown")
                    if asyncio.iscoroutinefunction(fn):
                        await fn()
                    else:
                        fn()
            except Exception:
                pass
        await asyncio.gather(*[_shutdown_one(c) for c in self._clients.values()])

    def _pick_default_provider(self) -> Optional[str]:
        if self._default_provider in self._clients:
            return self._default_provider
        for name in ["siliconflow", "dashscope", "aveline", "ark", "zhipu", "openai", "custom"]:
            if name in self._clients:
                return name
        return next(iter(self._clients.keys()), None)

    def _select_client(
        self, model_path: Any, kwargs: Dict[str, Any]
    ) -> Tuple[Optional[LLMModule], Dict[str, Any]]:
        """选择客户端

        支持两种模型路径格式：
        1. cloud:provider:model（传统格式）
        2. cloud:provider:key_alias:model（多API key格式）
        """
        mp = str(model_path or "")
        provider = None
        key_alias = None
        model = kwargs.get("model")

        if mp.startswith("cloud:"):
            parts = mp.split(":")
            if len(parts) >= 2:
                provider = parts[1].strip().lower() or None
            if len(parts) >= 3:
                # 判断是传统格式还是多API key格式
                # 传统格式: cloud:deepseek:model (3段)
                # 多API key格式: cloud:deepseek:qqbot1:model (4段)
                if len(parts) == 3:
                    # 传统格式
                    if not model:
                        model = parts[2]
                elif len(parts) >= 4:
                    # 多API key格式
                    key_alias = parts[2].strip().lower() or None
                    if not model:
                        model = ":".join(parts[3:])  # 模型名可能包含冒号

        # 构建客户端key
        client_key = provider
        if key_alias:
            client_key = f"{provider}:{key_alias}"

        if client_key and client_key not in self._clients:
            self._ensure_client(client_key)
            if client_key not in self._clients:
                # 回退到不带key_alias的客户端
                if key_alias:
                    self._ensure_client(provider)
                    if provider in self._clients:
                        client_key = provider
                    else:
                        provider = None
                else:
                    provider = None

        if not provider:
            provider = self._pick_default_provider()
            client_key = provider

        client = self._clients.get(client_key) if client_key else None
        if not client:
            return None, kwargs

        new_kwargs = dict(kwargs)
        if model:
            new_kwargs["model"] = model
        return client, new_kwargs

    async def chat(self, messages: list, **kwargs):
        client, new_kwargs = self._select_client(kwargs.get("model_path"), kwargs)
        if not client:
            return ensure_debug_error_prefix("Error: Cloud Module not initialized.")
        return await client.chat(messages, **new_kwargs)

    async def stream_chat(
        self, messages: list, **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        client, new_kwargs = self._select_client(kwargs.get("model_path"), kwargs)
        if not client:
            yield {"error": "Cloud Module not initialized."}
            return

        async for chunk in client.stream_chat(messages, **new_kwargs):
            yield chunk

    def get_status(self) -> Dict[str, Any]:
        """
        获取所有客户端的状态
        """
        status = {
            "type": LLMModuleType.CLOUD_ROUTER.value,
            "module_type": LLMModuleType.CLOUD_ROUTER.value,
            "default_provider": self._default_provider,
            "active_clients": list(self._clients.keys()),
            "llm_status": {"instances_count": len(self._clients)},
        }
        for name, client in self._clients.items():
            if hasattr(client, "get_status"):
                status[name] = client.get_status()
        return status

    def get_current_model_name(self):
        """
        根据默认提供者获取当前活跃模型名称
        """
        provider = self._pick_default_provider()
        if not provider:
            return "cloud:unknown"

        # 优先从客户端获取
        client = self._clients.get(provider)
        if client and hasattr(client, "get_current_model_name"):
            name = client.get_current_model_name()
            if str(name).startswith("cloud:"):
                return name
            return f"cloud:{provider}:{name}"

        # 回退到配置查找
        try:
            from config.integrated_config import get_settings
            from config.model_config import get_default_chat_model

            settings = get_settings()
            model_name = settings.model.llm.model
            if not model_name:
                # 从 model_routing 获取默认模型名
                default_model = get_default_chat_model()
                if default_model and ":" in default_model:
                    model_name = default_model.split(":")[-1]
                else:
                    model_name = "deepseek-v4-flash"
            return f"cloud:{provider}:{model_name}"
        except Exception:
            return f"cloud:{provider}:default"
