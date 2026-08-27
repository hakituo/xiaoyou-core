#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 模块工厂与实例管理

提供：
- get_llm_module()：构建并返回全局 HybridLLMModule 实例
  （组合 LocalLLMAdapter + CloudRouterLLMModule，按 provider 配置注册多个云端客户端）
- create_instance() / get_instance() / list_instances()：基于 LLMConfig 的实例管理

依赖 base / local_adapter / cloud_router / hybrid_module 四个模块。
"""

import os
import threading
import time
from typing import Dict, Optional

from core.utils.logger import get_logger
from core.utils.config_accessor import get_config

from .base import LLMModule, LLMConfig
from .local_adapter import LocalLLMAdapter
from .cloud_router import CloudRouterLLMModule
from .hybrid_module import HybridLLMModule

logger = get_logger("LLM")


def _load_provider_defaults():
    """延迟加载 PROVIDER_BASE_URLS / PROVIDER_DEFAULT_MODELS 并派生默认值

    放在函数内部 import 是为了规避循环导入：
    `core.llm.__init__` 顶层 import 本模块，若本模块顶层 import `config.settings_model`，
    会在 `config/__init__.py` 执行期间触发 `ModelSettings()` 实例化，
    而 `ModelSettings.default_factory` 又依赖 `config.model_config`（尚未加载完成），
    从而报 "partially initialized module 'config' has no attribute 'model_config'"。
    """
    from config.settings_model import PROVIDER_BASE_URLS, PROVIDER_DEFAULT_MODELS

    defaults = {
        "model_deepseek": (PROVIDER_DEFAULT_MODELS.get("deepseek") or ["deepseek-v4-flash"])[0],
        "model_siliconflow": (PROVIDER_DEFAULT_MODELS.get("siliconflow") or ["Pro/moonshotai/Kimi-K2.6"])[0],
        "model_dashscope": (PROVIDER_DEFAULT_MODELS.get("dashscope") or ["qwen3-max-2025-09-23"])[0],
        "model_minimax": (PROVIDER_DEFAULT_MODELS.get("minimax") or ["MiniMax-M2.5"])[0],
        "model_ark": (PROVIDER_DEFAULT_MODELS.get("ark") or ["doubao-seed-2-0-lite-260215"])[0],
        "model_zhipu": (PROVIDER_DEFAULT_MODELS.get("zhipu") or ["glm-4.5-air"])[0],
        "ark_base_url": PROVIDER_BASE_URLS.get("ark") or "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
    }
    return defaults


# 全局LLM模块实例
# P0-21: 使用 threading.Lock + double-check 保护单例初始化，
# 防止多线程并发导致重复加载本地 LLM 模型（显存翻倍）和 ResourceManager 重复注册
_llm_module_instance = None
_llm_module_lock = threading.Lock()
_llm_instances = {}
_llm_instances_lock = threading.Lock()


def get_llm_module() -> LLMModule:
    """
    获取全局LLM模块实例

    线程安全：使用 double-check locking 防止多线程并发初始化导致：
    1. 本地 LLM 模型重复加载（显存翻倍）
    2. 多个 HybridLLMModule 实例（资源浪费）
    3. ResourceManager 重复注册（状态不一致）
    """
    global _llm_module_instance
    if _llm_module_instance is None:
        with _llm_module_lock:
            # double-check：拿到锁后再次确认，避免重复初始化
            if _llm_module_instance is not None:
                return _llm_module_instance
            _do_initialize_llm_module()
    return _llm_module_instance


def _do_initialize_llm_module() -> None:
    """实际执行 LLM 模块初始化（在 _llm_module_lock 内调用）"""
    global _llm_module_instance
    _t0 = time.perf_counter()
    from config.integrated_config import get_settings

    settings = get_settings()

    # 延迟加载供应商默认值（避免顶层 import 触发循环导入）
    _defaults = _load_provider_defaults()
    _DEFAULT_MODEL_DEEPSEEK = _defaults["model_deepseek"]
    _DEFAULT_MODEL_SILICONFLOW = _defaults["model_siliconflow"]
    _DEFAULT_MODEL_DASHSCOPE = _defaults["model_dashscope"]
    _DEFAULT_MODEL_MINIMAX = _defaults["model_minimax"]
    _DEFAULT_MODEL_ARK = _defaults["model_ark"]
    _DEFAULT_MODEL_ZHIPU = _defaults["model_zhipu"]
    _DEFAULT_ARK_BASE_URL = _defaults["ark_base_url"]

    local_adapter = None
    cloud_client = None

    llm_settings = settings.model.llm
    provider = llm_settings.provider
    logger.info(f"Initializing LLM Module with provider: {provider}")

    # 提取 VL 中转配置(所有 OpenAIClient 子类共享)
    # 用途:当主模型是纯文本 + 消息含图片时,用这套配置调 VL 模型描述图片
    vision_settings = getattr(settings.model, "vision", None)
    _vision_api_key = getattr(vision_settings, "api_key", None) if vision_settings else None
    _vision_base_url = getattr(vision_settings, "base_url", None) if vision_settings else None
    _vision_model = getattr(vision_settings, "model", None) if vision_settings else None
    if _vision_model:
        logger.info(
            "VL 中转配置已加载: model=%s, base_url=%s",
            _vision_model, _vision_base_url,
        )

    def _inject_vision_config(client):
        """给 OpenAIClient 子类实例注入 VL 中转配置(供两阶段路径使用)"""
        if client is None:
            return client
        try:
            # 直接赋值,基类 __init__ 已初始化这些属性
            if _vision_model:
                client._vision_model = _vision_model
            if _vision_api_key:
                client._vision_api_key = _vision_api_key
            if _vision_base_url:
                client._vision_base_url = _vision_base_url
        except Exception as e:
            logger.warning(f"注入 VL 配置失败: {e}")
        return client

    # 1. 本地适配器延迟创建（避免 import torch ~1.5s）
    def _make_local_adapter():
        try:
            adapter = LocalLLMAdapter()
            if getattr(adapter, "is_available", False):
                logger.info("LocalLLMAdapter created (lazy).")
                return adapter
        except Exception as e:
            logger.error(f"Failed to create LocalLLMAdapter: {e}")
        return None

    local_adapter = None
    _lazy_local_adapter_factory = _make_local_adapter

    clients: Dict[str, LLMModule] = {}
    lazy_providers: Dict[str, callable] = {}

    def _make_siliconflow(api_key, model_name):
        from .siliconflow_client import SiliconFlowClient
        client = SiliconFlowClient(api_key=api_key, model=model_name)
        # SiliconFlowClient 自带 VISION_MODEL 字段,但优先用全局 vision 配置覆盖
        if _vision_model:
            client.VISION_MODEL = _vision_model
        return client

    def _make_deepseek(api_key, model_name, thinking_enabled, reasoning_effort, key_id=None):
        from .openai_compat import DeepSeekClient
        client = _inject_vision_config(DeepSeekClient(api_key=api_key, base_url=None, model=model_name, thinking_enabled=thinking_enabled, reasoning_effort=reasoning_effort))
        client.key_id = key_id
        return client

    def _make_dashscope(api_key, model_name):
        from .dashscope_client import DashScopeClient
        return DashScopeClient(api_key=api_key, model=model_name)

    def _make_openai(api_key, base_url, model_name):
        from .openai_compat import OpenAIClient
        return _inject_vision_config(OpenAIClient(api_key=api_key, base_url=base_url, model=model_name))

    def _make_aveline(api_key, base_url, model_name):
        from .openai_compat import AvelineClient
        return _inject_vision_config(AvelineClient(api_key=api_key, base_url=base_url, model=model_name))

    def _make_ark(api_key, base_url, model_name):
        from .openai_compat import ArkClient
        return _inject_vision_config(ArkClient(api_key=api_key, base_url=base_url, model=model_name))

    def _make_minimax(api_key, model_name):
        from .openai_compat import MiniMaxClient
        return _inject_vision_config(MiniMaxClient(api_key=api_key, base_url=None, model=model_name))

    def _make_zhipu(api_key, model_name, thinking_enabled, web_search_enabled):
        from .openai_compat import ZhiPuClient
        return _inject_vision_config(ZhiPuClient(api_key=api_key, base_url=None, model=model_name, thinking_enabled=thinking_enabled, web_search_enabled=web_search_enabled))

    if provider == "siliconflow" or os.getenv("SILICONFLOW_API_KEY"):
        try:
            api_key = llm_settings.api_key if provider == "siliconflow" else None
            api_key = api_key or os.getenv("SILICONFLOW_API_KEY")
            if api_key:
                if provider == "siliconflow":
                    model_name = llm_settings.model
                else:
                    try:
                        from config.model_config import get_provider_default_model
                        model_name = get_provider_default_model("siliconflow", _DEFAULT_MODEL_SILICONFLOW)
                    except Exception:
                        model_name = _DEFAULT_MODEL_SILICONFLOW
                if provider == "siliconflow":
                    clients["siliconflow"] = _make_siliconflow(api_key, model_name)
                else:
                    lazy_providers["siliconflow"] = lambda _k=api_key, _m=model_name: _make_siliconflow(_k, _m)
        except ImportError:
            pass

    if provider == "deepseek" or os.getenv("DEEPSEEK_API_KEY"):
        try:
            api_key = llm_settings.api_key if provider == "deepseek" else None
            api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
            if api_key:
                if provider == "deepseek":
                    model_name = llm_settings.model
                else:
                    try:
                        from config.model_config import get_provider_default_model
                        model_name = get_provider_default_model("deepseek", _DEFAULT_MODEL_DEEPSEEK)
                    except Exception:
                        model_name = _DEFAULT_MODEL_DEEPSEEK
                thinking_enabled = getattr(llm_settings, 'thinking_enabled', True)
                reasoning_effort = getattr(llm_settings, 'reasoning_effort', 'high')
                if provider == "deepseek":
                    clients["deepseek"] = _make_deepseek(api_key, model_name, thinking_enabled, reasoning_effort, key_id="deepseek")
                else:
                    lazy_providers["deepseek"] = lambda _k=api_key, _m=model_name, _t=thinking_enabled, _r=reasoning_effort, _id="deepseek": _make_deepseek(_k, _m, _t, _r, key_id=_id)
        except ImportError:
            pass

    if provider == "dashscope" or os.getenv("DASHSCOPE_API_KEY"):
        try:
            api_key = llm_settings.api_key if provider == "dashscope" else None
            api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
            if api_key:
                if provider == "dashscope":
                    model_name = llm_settings.model
                else:
                    try:
                        from config.model_config import get_provider_default_model
                        model_name = get_provider_default_model("dashscope", _DEFAULT_MODEL_DASHSCOPE)
                    except Exception:
                        model_name = _DEFAULT_MODEL_DASHSCOPE
                if provider == "dashscope":
                    clients["dashscope"] = _make_dashscope(api_key, model_name)
                else:
                    lazy_providers["dashscope"] = lambda _k=api_key, _m=model_name: _make_dashscope(_k, _m)
        except ImportError:
            pass

    if provider in ["openai", "custom"]:
        try:
            clients[provider] = _make_openai(
                llm_settings.api_key, llm_settings.base_url, llm_settings.model,
            )
        except ImportError:
            pass

    if provider == "aveline" or os.getenv("AVELINE_API_KEY"):
        try:
            api_key = llm_settings.api_key if provider == "aveline" else None
            api_key = api_key or os.getenv("AVELINE_API_KEY")
            if api_key:
                base_url = llm_settings.base_url if provider == "aveline" else None
                base_url = base_url or os.getenv("AVELINE_BASE_URL")
                model_name = llm_settings.model if provider == "aveline" else None
                model_name = (
                    model_name or os.getenv("AVELINE_MODEL") or "nalang-xl-0826-16k"
                )
                if "," in model_name:
                    model_name = model_name.split(",")[0].strip()
                if provider == "aveline":
                    clients["aveline"] = _make_aveline(api_key, base_url, model_name)
                else:
                    lazy_providers["aveline"] = lambda _k=api_key, _b=base_url, _m=model_name: _make_aveline(_k, _b, _m)
        except ImportError:
            pass

    if provider == "ark" or os.getenv("ARK_API_KEY"):
        try:
            api_key = llm_settings.api_key if provider == "ark" else None
            api_key = api_key or os.getenv("ARK_API_KEY")
            if api_key:
                base_url = llm_settings.base_url if provider == "ark" else None
                base_url = base_url or _DEFAULT_ARK_BASE_URL
                model_name = llm_settings.model if provider == "ark" else None
                model_name = model_name or _DEFAULT_MODEL_ARK
                if provider == "ark":
                    clients["ark"] = _make_ark(api_key, base_url, model_name)
                else:
                    lazy_providers["ark"] = lambda _k=api_key, _b=base_url, _m=model_name: _make_ark(_k, _b, _m)
        except ImportError:
            pass

    if provider == "minimax" or os.getenv("MINIMAX_API_KEY"):
        try:
            api_key = llm_settings.api_key if provider == "minimax" else None
            api_key = api_key or os.getenv("MINIMAX_API_KEY")
            if api_key:
                model_name = llm_settings.model if provider == "minimax" else None
                model_name = model_name or _DEFAULT_MODEL_MINIMAX
                if provider == "minimax":
                    clients["minimax"] = _make_minimax(api_key, model_name)
                else:
                    lazy_providers["minimax"] = lambda _k=api_key, _m=model_name: _make_minimax(_k, _m)
        except ImportError:
            pass

    if provider == "zhipu" or os.getenv("ZHIPU_API_KEY"):
        try:
            api_key = llm_settings.api_key if provider == "zhipu" else None
            api_key = api_key or os.getenv("ZHIPU_API_KEY")
            if api_key:
                model_name = llm_settings.model if provider == "zhipu" else None
                model_name = model_name or _DEFAULT_MODEL_ZHIPU
                thinking_enabled = getattr(llm_settings, 'thinking_enabled', True)
                web_search_enabled = getattr(llm_settings, 'web_search_enabled', False)
                if provider == "zhipu":
                    clients["zhipu"] = _make_zhipu(api_key, model_name, thinking_enabled, web_search_enabled)
                else:
                    lazy_providers["zhipu"] = lambda _k=api_key, _m=model_name, _t=thinking_enabled, _w=web_search_enabled: _make_zhipu(_k, _m, _t, _w)
        except ImportError:
            pass

    # 2.5 多API key支持：为每个供应商的每个key创建独立的客户端
    try:
        cloud_provider_keys = getattr(settings.model, 'cloud_provider_keys', {})
        if cloud_provider_keys:
            logger.info(f"加载多API key配置: {list(cloud_provider_keys.keys())}")

            for prov, key_configs in cloud_provider_keys.items():
                for key_alias, key_config in key_configs.items():
                    # 生成客户端key（格式: provider:key_alias）
                    client_key = f"{prov}:{key_alias}"

                    # 跳过已存在的客户端
                    if client_key in clients or client_key in lazy_providers:
                        continue

                    # 获取API key（优先使用配置中的api_key，其次从环境变量读取）
                    api_key = key_config.api_key
                    if not api_key and key_config.api_key_env:
                        api_key = os.getenv(key_config.api_key_env)

                    if not api_key:
                        logger.warning(f"跳过 {client_key}: 未找到API key")
                        continue

                    base_url = key_config.base_url
                    thinking_enabled = key_config.thinking_enabled
                    reasoning_effort = key_config.reasoning_effort

                    # 根据供应商类型创建客户端
                    try:
                        if prov == "deepseek":
                            model_name = key_config.models[0] if key_config.models else _DEFAULT_MODEL_DEEPSEEK
                            lazy_providers[client_key] = lambda _k=api_key, _m=model_name, _t=thinking_enabled, _r=reasoning_effort, _id=client_key: _make_deepseek(_k, _m, _t, _r, key_id=_id)
                        elif prov == "siliconflow":
                            model_name = key_config.models[0] if key_config.models else _DEFAULT_MODEL_SILICONFLOW
                            lazy_providers[client_key] = lambda _k=api_key, _m=model_name: _make_siliconflow(_k, _m)
                        elif prov == "dashscope":
                            model_name = key_config.models[0] if key_config.models else _DEFAULT_MODEL_DASHSCOPE
                            lazy_providers[client_key] = lambda _k=api_key, _m=model_name: _make_dashscope(_k, _m)
                        elif prov == "minimax":
                            model_name = key_config.models[0] if key_config.models else _DEFAULT_MODEL_MINIMAX
                            lazy_providers[client_key] = lambda _k=api_key, _m=model_name: _make_minimax(_k, _m)
                        elif prov == "ark":
                            model_name = key_config.models[0] if key_config.models else _DEFAULT_MODEL_ARK
                            lazy_providers[client_key] = lambda _k=api_key, _b=base_url, _m=model_name: _make_ark(_k, _b, _m)
                        elif prov == "zhipu":
                            model_name = key_config.models[0] if key_config.models else _DEFAULT_MODEL_ZHIPU
                            web_search_enabled = getattr(key_config, 'web_search_enabled', False)
                            lazy_providers[client_key] = lambda _k=api_key, _m=model_name, _t=thinking_enabled, _w=web_search_enabled: _make_zhipu(_k, _m, _t, _w)
                        elif prov == "aveline":
                            model_name = key_config.models[0] if key_config.models else "nalang-xl-0826-16k"
                            lazy_providers[client_key] = lambda _k=api_key, _b=base_url, _m=model_name: _make_aveline(_k, _b, _m)
                        else:
                            # 默认使用OpenAI兼容客户端
                            model_name = key_config.models[0] if key_config.models else "default"
                            lazy_providers[client_key] = lambda _k=api_key, _b=base_url, _m=model_name: _make_openai(_k, _b, _m)

                        logger.info(f"注册多API key客户端: {client_key} (models={key_config.models})")
                    except Exception as e:
                        logger.warning(f"创建多API key客户端 {client_key} 失败: {e}")
    except Exception as e:
        logger.warning(f"加载多API key配置失败: {e}")

    if clients or lazy_providers:
        cloud_client = CloudRouterLLMModule(clients, default_provider=provider, lazy_providers=lazy_providers)

    # 3. 构建混合模块
    allow_preload = bool(getattr(settings.model, "llm_preload_on_startup", True))
    # provider 为云端时不需要本地模块，避免触发 torch/llama_cpp 等重模块冷导入（~30s）
    # 只有 provider == "local" 时才延迟创建 LocalLLMAdapter 作为本地路由
    needs_local_adapter = (provider == "local")
    _lazy_factory = (
        _lazy_local_adapter_factory
        if (needs_local_adapter and local_adapter is None)
        else None
    )
    _llm_module_instance = HybridLLMModule(
        local_module=local_adapter,
        cloud_module=cloud_client,
        preload_local=needs_local_adapter and allow_preload,
        default_provider=provider,
        lazy_local_factory=_lazy_factory,
    )
    # 保存 settings 引用
    _llm_module_instance.settings = settings

    try:
        from core.resource_manager import get_resource_manager, ResourcePriority
        from core.services.scheduler.cpp_scheduler_engine import (
            get_scheduler_engine,
        )

        scheduler_settings = getattr(settings, "scheduler", None)
        use_cpp = bool(getattr(scheduler_settings, "use_cpp", False))
        use_cpp_for_llm = bool(
            getattr(scheduler_settings, "use_cpp_for_llm", False)
        )

        text_path = get_config("model.text_path", default=None, settings=settings)
        is_gguf = bool(text_path and str(text_path).lower().endswith(".gguf"))
        _engine = get_scheduler_engine()
        cpp_llm_configured = (
            bool(getattr(_engine, "enabled", False))
            and use_cpp
            and use_cpp_for_llm
            and is_gguf
        )

        if not cpp_llm_configured and local_adapter:
            rm = get_resource_manager()
            existing = rm.get_model("llm_engine")
            if not (existing and existing.unload_func):
                instance = getattr(local_adapter, "local_module", None)
                rm.register_model(
                    model_id="llm_engine",
                    model_type="llm",
                    priority=ResourcePriority.HIGH,
                    load_func=local_adapter.initialize,
                    unload_func=local_adapter.shutdown,
                    instance=instance,
                )
    except Exception as e:
        logger.error(f"Failed to register LLM Module with Resource Manager: {e}")

    logger.info(
        "get_llm_module() 完成 (%.3fs), 默认provider=%s, 即时客户端=%s, 延迟客户端=%s",
        time.perf_counter() - _t0, provider, list(clients.keys()), list(lazy_providers.keys()),
    )


def create_instance(instance_name: str, config: LLMConfig) -> None:
    """
    创建LLM实例
    """
    global _llm_instances
    # P0-21: 加锁保护并发写入
    with _llm_instances_lock:
        # 这里简化实现，实际应该根据配置创建不同类型的LLM实例
        _llm_instances[instance_name] = config
    logger.info(f"创建LLM实例: {instance_name}, 模型: {config.model_name}")


def get_instance(instance_name: str) -> Optional[LLMConfig]:
    """
    获取指定名称的LLM实例
    """
    global _llm_instances
    # P0-21: 加锁保护并发读取
    with _llm_instances_lock:
        return _llm_instances.get(instance_name)


def list_instances() -> Dict[str, LLMConfig]:
    """
    列出所有LLM实例
    """
    global _llm_instances
    # P0-21: 加锁保护并发读取
    with _llm_instances_lock:
        return _llm_instances.copy()
