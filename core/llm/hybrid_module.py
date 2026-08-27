#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
混合 LLM 模块（HybridLLMModule）

组合 LocalLLMAdapter 与 CloudRouterLLMModule，按 model_path / default_provider
在本地与云端之间路由请求。
特性：
- 后台异步预加载本地模型，不阻塞启动
- 云端失败时可降级到本地（fallback_local）
- 聚合本地+云端状态，输出统一 init_state 摘要
"""

import asyncio
import time
from typing import Dict, Any, Optional

from core.utils.debug_markers import ensure_debug_error_prefix
from core.utils.logger import get_logger
from core.contracts import LLMModuleType, ModuleInitState

from .base import LLMModule

logger = get_logger("LLM")


class HybridLLMModule(LLMModule):
    def __init__(
        self,
        local_module: Optional[LLMModule],
        cloud_module: Optional[LLMModule],
        preload_local: bool = True,
        default_provider: str = "local",
        lazy_local_factory: Optional[callable] = None,
    ):
        self.local_module = local_module
        self.cloud_module = cloud_module
        self.preload_local = preload_local
        self.default_provider = default_provider
        self.default_model_name = None
        self._lazy_local_factory = lazy_local_factory
        self._local_initialized = False

    _CLOUD_PREFIX_MAP = {
        "siliconflow": "cloud:siliconflow:",
        "deepseek": "cloud:deepseek:",
        "dashscope": "cloud:dashscope:",
        "aveline": "cloud:aveline:",
        "ark": "cloud:ark:",
        "minimax": "cloud:minimax:",
        "zhipu": "cloud:zhipu:",
        "openai": "cloud:openai:",
        "custom": "cloud:custom:",
    }

    def _resolve_cloud_model_path(self, model_path: str, kwargs: dict) -> dict:
        raw_model_path = str(model_path or "").strip()
        if not raw_model_path.startswith("cloud:"):
            if not kwargs.get("model") and self.default_model_name:
                kwargs["model"] = self.default_model_name
            return kwargs

        parts = raw_model_path.split(":")
        resolved_model = ""
        if len(parts) >= 4:
            resolved_model = ":".join(parts[3:]).strip()
        elif len(parts) >= 3:
            resolved_model = ":".join(parts[2:]).strip()

        current_model = str(kwargs.get("model") or "").strip()
        if resolved_model and (not current_model or current_model.startswith("cloud:")):
            kwargs["model"] = resolved_model

        if not kwargs.get("model") and self.default_model_name:
            kwargs["model"] = self.default_model_name
        return kwargs

    async def reload(self):
        """重新加载混合模块配置"""
        logger.info("Reloading HybridLLMModule...")
        from config.integrated_config import get_settings
        from config.model_config import get_default_chat_model

        settings = get_settings()

        # 更新路由偏好
        self.default_provider = settings.model.llm.provider
        default_chat_model = get_default_chat_model()
        if default_chat_model and ":" in default_chat_model:
            self.default_model_name = default_chat_model.split(":")[-1]
        else:
            self.default_model_name = settings.model.llm.model or "deepseek-v4-flash"
        allow_preload = bool(getattr(settings.model, "llm_preload_on_startup", True))
        self.preload_local = (self.default_provider == "local") and allow_preload

        logger.info(
            f"HybridLLMModule reloaded. Default provider: {self.default_provider}, Default model: {self.default_model_name}"
        )

        # 重新加载子模块
        if self.local_module and hasattr(self.local_module, "reload"):
            await self.local_module.reload()

        if self.cloud_module and hasattr(self.cloud_module, "reload"):
            if asyncio.iscoroutinefunction(self.cloud_module.reload):
                await self.cloud_module.reload()

    async def initialize(self):
        started_at = time.perf_counter()
        # 1. 初始化云端模块
        if self.cloud_module:
            try:
                await self.cloud_module.initialize()
                logger.info("Cloud Module initialized in Hybrid.")
            except Exception as e:
                logger.error(f"Failed to initialize Cloud Module in Hybrid: {e}")

        # 2. 延迟创建本地适配器 + 后台初始化（不阻塞启动）
        if self.local_module is None and self._lazy_local_factory and not self._local_initialized:
            if self.preload_local:
                # 先抢占标志，避免重复调度后台任务；
                # 但若后台任务失败需在回调里重置，允许下次 initialize() 重试。
                self._local_initialized = True

                async def _lazy_create_and_init():
                    try:
                        local = await asyncio.to_thread(self._lazy_local_factory)
                    except Exception as e:
                        # 工厂失败：重置标志以便下次重试，且 local_module 仍为 None
                        self._local_initialized = False
                        logger.error(
                            "HybridLLMModule: Local lazy factory failed: %s", e
                        )
                        return
                    if local is None:
                        # 工厂返回 None：同样重置标志，允许重试
                        self._local_initialized = False
                        logger.warning(
                            "HybridLLMModule: Local lazy factory returned None."
                        )
                        return
                    self.local_module = local
                    try:
                        await self.local_module.initialize()
                    except Exception as e:
                        # 初始化失败：保留 local_module 引用但记录错误，
                        # 不重置 _local_initialized（避免反复重试一个会失败的 init）
                        logger.error(
                            "HybridLLMModule: Local initialize failed: %s", e
                        )
                    logger.info(
                        "HybridLLMModule: Local lazy create+init completed (%.2fs).",
                        time.perf_counter() - started_at,
                    )

                self._local_init_task = asyncio.create_task(_lazy_create_and_init())
                logger.info("HybridLLMModule: Scheduling local lazy create+init in background...")
            else:
                # 非预加载路径：同步创建并立即初始化本地模块
                # 之前这里只创建不初始化，导致 local_module.initialized 一直为 False
                try:
                    self.local_module = await asyncio.to_thread(self._lazy_local_factory)
                    self._local_initialized = True
                    if self.local_module and hasattr(self.local_module, "initialize"):
                        await self.local_module.initialize()
                except Exception as e:
                    self._local_initialized = False
                    logger.error(
                        "HybridLLMModule: Local lazy factory/init failed: %s", e
                    )

        elif self.local_module and self.preload_local:
            task = getattr(self, "_local_init_task", None)
            if task is None or getattr(task, "done", lambda: True)():
                logger.info(
                    "HybridLLMModule: Scheduling local preload in background..."
                )
                self._local_init_task = asyncio.create_task(
                    self.local_module.initialize()
                )

                def _log_result(t: asyncio.Task):
                    try:
                        exc = t.exception()
                    except asyncio.CancelledError:
                        logger.warning("HybridLLMModule: Local preload cancelled.")
                        return
                    except Exception as e:
                        logger.error(
                            "HybridLLMModule: Failed to read preload result: %s", e
                        )
                        return

                    if exc:
                        logger.error("HybridLLMModule: Local preload failed: %s", exc)
                    else:
                        logger.info(
                            "HybridLLMModule: Local preload completed (%.2fs).",
                            time.perf_counter() - started_at,
                        )

                self._local_init_task.add_done_callback(_log_result)
            else:
                logger.info("HybridLLMModule: Local preload already running.")

        logger.info(
            "HybridLLMModule.initialize finished (%.2fs).",
            time.perf_counter() - started_at,
        )

    async def chat(self, messages: list, **kwargs):
        if "max_tokens" not in kwargs and "max_new_tokens" in kwargs:
            kwargs["max_tokens"] = kwargs.pop("max_new_tokens")

        model_path = str(kwargs.get("model_path") or "")
        fallback_local = bool(kwargs.pop("fallback_local", False))
        # 检查路由
        # 如果未指定model_path，使用默认提供者
        target_provider = self.default_provider

        if str(model_path).startswith("cloud:"):
            target_provider = "cloud"  # 通用云端
        elif model_path and not str(model_path).startswith("cloud:"):
            # 如果指定了明确的本地模型路径，强制使用本地
            target_provider = "local"

        # 如果model_path为空，依赖default_provider
        # 如果default_provider是local，使用local_module
        # 如果default_provider是其他值（如siliconflow），使用cloud_module

        if target_provider != "local" or str(model_path).startswith("cloud:"):
            if self.cloud_module:
                self._resolve_cloud_model_path(model_path, kwargs)

                logger.info(
                    "HybridLLM routing to cloud. provider=%s model=%s",
                    target_provider,
                    kwargs.get("model") or self.default_model_name or "?",
                )
                result = await self.cloud_module.chat(messages, **kwargs)
                # 日志预览时排除 reasoning_content，防止推理内容泄露到日志
                _preview = dict(result) if isinstance(result, dict) else result
                if isinstance(_preview, dict):
                    _preview.pop("reasoning_content", None)
                    _preview.pop("reasoning_text", None)
                logger.info(
                    "HybridLLM cloud result type=%s len=%d preview=%s",
                    type(result).__name__,
                    len(str(result or "")),
                    str(_preview or "")[:200],
                )
                result_text = result.get("response", "") if isinstance(result, dict) else str(result)
                if (
                    fallback_local
                    and self.local_module
                    and isinstance(result_text, str)
                    and result_text.strip().startswith("Error:")
                ):
                    logger.info("HybridLLM cloud returned error, falling back to local")
                    return await self.local_module.chat(messages, **kwargs)
                return result
            else:
                return ensure_debug_error_prefix(
                    "Error: Cloud model requested but Cloud Module not initialized."
                )
        else:
            if self.local_module:
                return await self.local_module.chat(messages, **kwargs)
            else:
                # 回退到云端（如果没有本地模块且没有明确路径？）
                # 或者直接报错。
                if self.cloud_module and not model_path:
                    logger.info(
                        "No local module and no model path, falling back to cloud."
                    )
                    return await self.cloud_module.chat(messages, **kwargs)
                return ensure_debug_error_prefix(
                    "Error: Local model requested but Local Module not initialized."
                )

    async def stream_chat(self, messages: list, **kwargs):
        if "max_tokens" not in kwargs and "max_new_tokens" in kwargs:
            kwargs["max_tokens"] = kwargs.pop("max_new_tokens")

        model_path = str(kwargs.get("model_path") or "")
        fallback_local = bool(kwargs.pop("fallback_local", False))
        logger.info(
            f"HybridLLMModule.stream_chat: model_path={model_path}, default_provider={self.default_provider}"
        )

        # 检查路由
        target_provider = self.default_provider
        if str(model_path).startswith("cloud:"):
            target_provider = "cloud"
        elif model_path and not str(model_path).startswith("cloud:"):
            # 如果指定了明确的本地模型路径，强制使用本地
            target_provider = "local"

        if target_provider != "local" or str(model_path).startswith("cloud:"):
            if self.cloud_module:
                self._resolve_cloud_model_path(model_path, kwargs)

                if fallback_local and self.local_module:
                    aiter = self.cloud_module.stream_chat(messages, **kwargs)
                    try:
                        first = await aiter.__anext__()
                    except StopAsyncIteration:
                        return
                    except Exception:
                        async for chunk in self.local_module.stream_chat(
                            messages, **kwargs
                        ):
                            yield chunk
                        return

                    if isinstance(first, dict) and first.get("error"):
                        async for chunk in self.local_module.stream_chat(
                            messages, **kwargs
                        ):
                            yield chunk
                        return

                    yield first
                    async for chunk in aiter:
                        yield chunk
                else:
                    async for chunk in self.cloud_module.stream_chat(
                        messages, **kwargs
                    ):
                        yield chunk
            else:
                yield {
                    "error": "Cloud model requested but Cloud Module not initialized."
                }
        else:
            if self.local_module:
                async for chunk in self.local_module.stream_chat(messages, **kwargs):
                    yield chunk
            else:
                if self.cloud_module and not model_path:
                    logger.info(
                        "No local module and no model path, falling back to cloud."
                    )
                    async for chunk in self.cloud_module.stream_chat(
                        messages, **kwargs
                    ):
                        yield chunk
                else:
                    yield {
                        "error": "Local model requested but Local Module not initialized."
                    }

    def get_status(self) -> Dict[str, Any]:
        status: Dict[str, Any] = {
            "type": LLMModuleType.HYBRID.value,
            "module_type": LLMModuleType.HYBRID.value,
            "default_provider": self.default_provider,
        }

        local = self.local_module.get_status() if self.local_module else None
        cloud = self.cloud_module.get_status() if self.cloud_module else None
        if local is not None:
            status["local"] = local
        if cloud is not None:
            status["cloud"] = cloud

        # 汇总 llm_status.instances_count（供上层检查是否有可用实例）
        instances_count = 0
        for child in (local, cloud):
            if isinstance(child, dict):
                instances_count += child.get("llm_status", {}).get("instances_count", 0)
        status["llm_status"] = {"instances_count": instances_count}

        # 路由模块本身的规范init_state摘要。
        # 如果任何子模块已初始化，则认为路由器已初始化。
        child_states = []
        for child in (local, cloud):
            if isinstance(child, dict):
                child_states.append(str(child.get("init_state") or child.get("status") or ""))
        if any(s == ModuleInitState.INITIALIZED.value for s in child_states):
            status["init_state"] = ModuleInitState.INITIALIZED.value
        elif any(s == ModuleInitState.ERROR.value for s in child_states):
            status["init_state"] = ModuleInitState.ERROR.value
        elif child_states:
            status["init_state"] = ModuleInitState.NOT_INITIALIZED.value
        else:
            status["init_state"] = ModuleInitState.UNKNOWN.value

        return status

    def get_current_model_name(self):
        # 遵循路由偏好
        if self.default_provider != "local":
            if self.cloud_module and hasattr(
                self.cloud_module, "get_current_model_name"
            ):
                return self.cloud_module.get_current_model_name()

        # 如果默认是本地或云端不可用，回退到本地
        if self.local_module and hasattr(self.local_module, "get_current_model_name"):
            return self.local_module.get_current_model_name()

        # 最后手段：如果因为本地存在而跳过了云端，但默认是云端……
        # 实际上第一个代码块已经处理了default!=local的情况。

        return "unknown"

    async def shutdown(self):
        try:
            if self.cloud_module and hasattr(self.cloud_module, "shutdown"):
                fn = getattr(self.cloud_module, "shutdown")
                if asyncio.iscoroutinefunction(fn):
                    await fn()
                else:
                    fn()
        except Exception:
            pass
        try:
            if self.local_module and hasattr(self.local_module, "unload_model"):
                await self.local_module.unload_model()
        except Exception:
            pass
