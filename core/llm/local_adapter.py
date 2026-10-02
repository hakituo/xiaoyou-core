#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地 LLM 适配器（LocalLLMAdapter）

封装 `core.modules.llm.module.LLMModule`，对外暴露统一的 LLMModule 接口。
负责：
- 本地 GGUF 模型的加载、卸载、状态查询
- 与 C++ 调度器（cpp_scheduler_engine）协同判断是否跳过本地预加载
- 与资源管理器（resource_manager）联动注册/标记模型加载状态
"""

import asyncio
import time
from typing import Dict, Any

from core.utils.debug_markers import ensure_debug_error_prefix
from core.utils.logger import get_logger
from core.utils.config_accessor import get_config
from core.contracts import LLMModuleType, ModuleInitState

from .base import LLMModule

logger = get_logger("LLM")


class LocalLLMAdapter(LLMModule):
    def __init__(self):
        try:
            from core.modules.llm.module import LLMModule as LocalLLMModuleImpl

            self.local_module = LocalLLMModuleImpl()
            self.is_available = True
        except ImportError as e:
            logger.error(f"Failed to import LocalLLMModule: {e}")
            self.local_module = None
            self.is_available = False

    async def initialize(self):
        if not self.is_available:
            return

        started_at = time.perf_counter()

        try:
            from config.integrated_config import get_settings
            from core.services.scheduler.cpp_scheduler_engine import (
                cpp_scheduler_engine,
            )

            settings = get_settings()
            scheduler_settings = getattr(settings, "scheduler", None)
            use_cpp = bool(getattr(scheduler_settings, "use_cpp", False))
            use_cpp_for_llm = bool(
                getattr(scheduler_settings, "use_cpp_for_llm", False)
            )

            text_path = get_config("model.text_path", default=None, settings=settings)
            engine_model_path = None
            try:
                gpu_cfg = getattr(cpp_scheduler_engine, "_gpu_config", None)
                if isinstance(gpu_cfg, dict):
                    engine_model_path = gpu_cfg.get("model_path") or gpu_cfg.get("path")
            except Exception as e:
                logger.debug("LocalLLMAdapter: 获取 C++ 调度器 GPU 配置失败: %s", e)
                engine_model_path = None

            is_gguf = bool(
                (text_path and str(text_path).lower().endswith(".gguf"))
                or (
                    engine_model_path
                    and str(engine_model_path).lower().endswith(".gguf")
                )
            )

            cpp_llm_configured = (
                bool(getattr(cpp_scheduler_engine, "enabled", False))
                and use_cpp
                and use_cpp_for_llm
                and is_gguf
            )
            if cpp_llm_configured:
                if getattr(self.local_module, "is_loaded", False):
                    try:
                        await self.local_module.unload_model()
                    except Exception as e:
                        logger.warning("LocalLLMAdapter: 卸载已加载模型失败: %s", e)
                logger.info(
                    "LocalLLMAdapter: Skipping local preload (C++ scheduler LLM enabled)."
                )
                return
        except Exception as e:
            logger.warning("LocalLLMAdapter: 检查 C++ 调度器配置失败，回退到本地加载: %s", e)

        # 安全初始化，使用锁防止与stream_chat的竞态条件
        # 并确保不会无限阻塞（虽然在后台调用）
        try:
            logger.info("LocalLLMAdapter: Acquiring lock for initialization...")
            async with self.local_module._lock:
                if not self.local_module.is_loaded:
                    logger.info("LocalLLMAdapter: Loading model...")

                    timeout_seconds = 60.0
                    try:
                        from config.integrated_config import get_settings

                        settings = get_settings()
                        timeout_seconds = float(
                            getattr(settings.model, "model_load_timeout", 60)
                        )
                    except Exception as e:
                        logger.debug("LocalLLMAdapter: 读取 model_load_timeout 失败，使用默认值 60s: %s", e)
                        timeout_seconds = 60.0

                    await asyncio.wait_for(
                        self.local_module._load_model(), timeout=timeout_seconds
                    )
                    logger.info(
                        "LocalLLMAdapter: Model loaded successfully (%.2fs).",
                        time.perf_counter() - started_at,
                    )

                    try:
                        from core.resource_manager import (
                            get_resource_manager,
                            ResourcePriority,
                        )

                        rm = get_resource_manager()
                        rm.register_model(
                            model_id="llm_engine",
                            model_type="llm",
                            priority=ResourcePriority.HIGH,
                            load_func=self.local_module._load_model,
                            unload_func=self.local_module.unload_model,
                            offload_func=getattr(
                                self.local_module, "offload_to_cpu", None
                            ),
                            instance=self.local_module,
                        )
                        rm.mark_model_loaded("llm_engine", True)
                    except Exception as e:
                        logger.warning("LocalLLMAdapter: 注册资源管理器失败，尝试降级标记: %s", e)
                        try:
                            from core.resource_manager import get_resource_manager

                            get_resource_manager().mark_model_loaded("llm_engine", True)
                        except Exception as e2:
                            logger.warning("LocalLLMAdapter: 降级标记也失败: %s", e2)
                else:
                    logger.info("LocalLLMAdapter: Model already loaded.")
                    try:
                        from core.resource_manager import (
                            get_resource_manager,
                            ResourcePriority,
                        )

                        rm = get_resource_manager()
                        rm.register_model(
                            model_id="llm_engine",
                            model_type="llm",
                            priority=ResourcePriority.HIGH,
                            load_func=self.local_module._load_model,
                            unload_func=self.local_module.unload_model,
                            offload_func=getattr(
                                self.local_module, "offload_to_cpu", None
                            ),
                            instance=self.local_module,
                        )
                        rm.mark_model_loaded("llm_engine", True)
                    except Exception as e:
                        logger.warning("LocalLLMAdapter: 注册资源管理器失败，尝试降级标记: %s", e)
                        try:
                            from core.resource_manager import get_resource_manager

                            get_resource_manager().mark_model_loaded("llm_engine", True)
                        except Exception as e2:
                            logger.warning("LocalLLMAdapter: 降级标记也失败: %s", e2)
        except asyncio.TimeoutError:
            logger.error(
                "Local model load timed out (%.2fs).", time.perf_counter() - started_at
            )
        except Exception as e:
            logger.error(
                "Local model load failed after %.2fs: %s",
                time.perf_counter() - started_at,
                e,
            )

    async def chat(self, messages: list, **kwargs):
        if not self.is_available:
            return ensure_debug_error_prefix("Error: Local LLM module not available.")

        local_kwargs = {}
        if "max_tokens" in kwargs and kwargs.get("max_tokens") is not None:
            local_kwargs["max_tokens"] = kwargs.get("max_tokens")
        if "temperature" in kwargs and kwargs.get("temperature") is not None:
            local_kwargs["temperature"] = kwargs.get("temperature")
        if "model_path" in kwargs and kwargs.get("model_path") is not None:
            local_kwargs["model_path"] = kwargs.get("model_path")
        if "conversation_id" in kwargs and kwargs.get("conversation_id") is not None:
            local_kwargs["conversation_id"] = kwargs.get("conversation_id")

        result = await self.local_module.chat(messages, **local_kwargs)
        if result.get("status") == "success":
            return result.get("response")
        else:
            return ensure_debug_error_prefix(f"Error: {result.get('error')}")

    async def stream_chat(self, messages: list, **kwargs):
        if not self.is_available:
            yield {"error": "Local LLM module not available."}
            return

        logger.info("LocalLLMAdapter.stream_chat called.")
        local_kwargs = {}
        if "max_tokens" in kwargs and kwargs.get("max_tokens") is not None:
            local_kwargs["max_tokens"] = kwargs.get("max_tokens")
        if "temperature" in kwargs and kwargs.get("temperature") is not None:
            local_kwargs["temperature"] = kwargs.get("temperature")
        if "model_path" in kwargs and kwargs.get("model_path") is not None:
            local_kwargs["model_path"] = kwargs.get("model_path")
        if (
            "first_token_timeout" in kwargs
            and kwargs.get("first_token_timeout") is not None
        ):
            local_kwargs["first_token_timeout"] = kwargs.get("first_token_timeout")
        if "conversation_id" in kwargs and kwargs.get("conversation_id") is not None:
            local_kwargs["conversation_id"] = kwargs.get("conversation_id")

        async for chunk in self.local_module.stream_chat(messages, **local_kwargs):
            yield chunk
        logger.info("LocalLLMAdapter.stream_chat finished.")

    async def shutdown(self):
        if not self.is_available:
            return
        try:
            if hasattr(self.local_module, "unload_model"):
                await self.local_module.unload_model()
                # 同步状态到资源管理器
                try:
                    from core.resource_manager import get_resource_manager

                    get_resource_manager().mark_model_loaded("llm_engine", False)
                except Exception:
                    pass
        except Exception:
            pass

    async def reload(self):
        """重新加载底层本地模块"""
        if not self.is_available:
            return
        if hasattr(self.local_module, "reload"):
            if asyncio.iscoroutinefunction(self.local_module.reload):
                await self.local_module.reload()
            else:
                self.local_module.reload()

    def get_status(self) -> Dict[str, Any]:
        if not self.is_available:
            return {
                "status": ModuleInitState.ERROR.value,
                "init_state": ModuleInitState.ERROR.value,
                "type": LLMModuleType.LOCAL.value,
                "module_type": LLMModuleType.LOCAL.value,
                "error": "Import failed",
            }

        init_state = (
            ModuleInitState.INITIALIZED
            if bool(self.local_module.is_loaded)
            else ModuleInitState.NOT_INITIALIZED
        )
        return {
            # 旧版键（保留以兼容）
            "status": init_state.value,
            # Canonical key
            "init_state": init_state.value,
            "type": LLMModuleType.LOCAL.value,
            "module_type": LLMModuleType.LOCAL.value,
            "model_path": self.local_module.get_current_model_name(),
            "llm_status": {"instances_count": 1},
        }

    def get_current_model_name(self):
        if self.is_available:
            return self.local_module.get_current_model_name()
        return "unknown"
