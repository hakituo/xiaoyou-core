#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AvelineService 薄壳门面。

本文件仅保留 AvelineService 类的核心生命周期方法与状态字段，
具体业务逻辑已按职责拆分到同目录下的兄弟模块：
- proactive_messaging.py：主动消息生成/分发/历史追加
- vision_service.py：视觉/图像服务
- response_generator.py：回复生成核心
- conversation_handler.py：会话入口与状态管理
- stream_orchestrator.py：流式会话编排（已有）
- control_intent.py / command_handler.py / prompt_policy.py / response_media.py / response_postprocess.py（已有）

外部 API 完全兼容：所有原方法保留签名，内部通过延迟导入委托给对应模块级函数。
"""
from __future__ import annotations

import asyncio
import time
import traceback
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional, Tuple, Union

from core.utils.common import get_project_root
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time
from core.utils.async_locks import LazyAsyncLock
from config.integrated_config import get_settings

logger = get_logger("AVELINE_SERVICE")


class AvelineService:
    """
    Aveline Character Service
    Handles all character logic including context management, persona generation, and response generation.
    Replaces the legacy fallback_service.py.
    """

    def __init__(self):
        """轻量初始化，重操作延迟到 initialize() 中异步执行"""
        self._initialized = False
        self._async_initialized = False
        self._chat_agent_init_task: Optional[asyncio.Task] = None
        self.chat_agent = None
        self.memory_manager = None
        self._conversation_idempotency_cache = None
        self._conversation_idempotency_lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._conversation_inflight: Dict[str, asyncio.Lock] = {}
        self._conversation_inflight_lock = LazyAsyncLock()

        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._active_tasks_lock = LazyAsyncLock()

        self.settings = None
        self._resource_monitor = None
        self.character_config = {"name": "Aveline", "max_history_length": 5}
        self.cache_manager = None
        self.performance_stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "avg_processing_time": 0,
            "last_reset_time": time.time(),
        }

        self._initialized = True
        logger.info("AvelineService 轻量构造完成（重操作延迟到 initialize）")

    async def _ensure_chat_agent_ready(self):
        if self._chat_agent_init_task is not None:
            try:
                await self._chat_agent_init_task
            except Exception:
                pass
            self._chat_agent_init_task = None
        if self.chat_agent and not getattr(self.chat_agent, "is_initialized", True):
            try:
                await self.chat_agent.initialize()
            except Exception as e:
                logger.error(f"ChatAgent 初始化失败: {e}")

    def _friendly_stream_error_message(self, exc: Exception) -> str:
        # 使用统一的错误消息转换
        try:
            from core.api.error_response import get_friendly_error_message

            return get_friendly_error_message(exc)
        except ImportError:
            # Fallback if import fails
            try:
                raw = str(exc or "").strip()
            except Exception:
                raw = ""
            if "timeout" in raw.lower():
                return "请求超时，请稍后重试。"
            return "系统处理消息时遇到错误"

    async def initialize(self):
        if self._async_initialized:
            return
        self._async_initialized = True

        try:
            logger.info("AvelineService 开始异步初始化...")
            _t0 = time.perf_counter()

            self.settings = get_settings()

            try:
                from core.services.monitoring.resource_monitor import get_resource_monitor
                self._resource_monitor = get_resource_monitor()
            except Exception:
                self._resource_monitor = None

            try:
                from core.async_cache import get_cache_manager
                self.cache_manager = get_cache_manager()
                self._conversation_idempotency_cache = self.cache_manager.get_cache(
                    name="conversation_idempotency",
                    max_size=2000,
                    default_ttl=600,
                )
            except Exception:
                self.cache_manager = None
                self._conversation_idempotency_cache = None

            async def _bg_init_heavy():
                try:
                    # 等启动完成后再执行重操作，避免 GIL 阻塞其他服务初始化
                    await asyncio.sleep(2)

                    self.character_config = await asyncio.to_thread(self._load_character_config)

                    from memory.weighted_memory_manager import get_weighted_memory_manager
                    self.memory_manager = await asyncio.to_thread(get_weighted_memory_manager)

                    from core.agents.chat_agent import get_default_chat_agent
                    self.chat_agent = await asyncio.to_thread(get_default_chat_agent)

                    if self.chat_agent:
                        await self.chat_agent.initialize()

                    logger.info("AvelineService 后台初始化完成 (%.3fs)", time.perf_counter() - _t0)
                except Exception as e:
                    logger.error(f"AvelineService 后台初始化失败: {e}")
                    traceback.print_exc()

            self._chat_agent_init_task = asyncio.create_task(_bg_init_heavy())

            logger.info("AvelineService 异步初始化完成 (%.3fs)", time.perf_counter() - _t0)
        except Exception as e:
            logger.error(f"AvelineService 异步初始化失败: {e}")
            traceback.print_exc()

    async def shutdown(self):
        """Shutdown service and release resources"""
        logger.info("Shutting down AvelineService...")

        # 取消后台初始化 task（如果在运行中），避免资源泄漏
        if self._chat_agent_init_task is not None:
            if not self._chat_agent_init_task.done():
                self._chat_agent_init_task.cancel()
                try:
                    await self._chat_agent_init_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.warning("AvelineService: 后台初始化 task 取消时异常: %s", e)
            self._chat_agent_init_task = None

        try:
            if self.chat_agent and getattr(self.chat_agent, "llm_module", None):
                llm = self.chat_agent.llm_module
                if hasattr(llm, "shutdown"):
                    fn = getattr(llm, "shutdown")
                    if asyncio.iscoroutinefunction(fn):
                        await fn()
                    else:
                        fn()
        except Exception:
            pass
        logger.info("AvelineService shutdown complete")

    def _load_character_config(self):
        try:
            from core.character.managers.persona_manager import get_persona_manager

            pm = get_persona_manager()
            return pm.get_current_persona()
        except Exception as e:
            logger.warning(f"Failed to load character config via PersonaManager: {e}")
        return {"name": "Aveline", "max_history_length": 10}

    def _get_project_root(self) -> Path:
        return Path(get_project_root())

    def _get_dynamic_context(self) -> str:
        """Get dynamic context including user status and daily activity summary"""
        context = []
        try:
            now_dt = get_current_time()
            context.append(
                f"【时间锚点】当前本地时间：{now_dt.strftime('%Y-%m-%d %H:%M:%S')}。"
                "如果你不确定具体钟点，请不要编造具体时间。"
            )
        except Exception:
            pass

        # 1. User Status (Persistent)
        try:
            from core.services.workspace.status_manager import get_user_status_manager

            status_summary = get_user_status_manager().get_status_summary()
            if status_summary and "当前无特殊状态" not in status_summary:
                context.append(status_summary)
        except Exception as e:
            logger.warning(f"Failed to get user status: {e}")

        # 2. Daily Activity Summary (Today's Portrait)
        try:
            from core.services.daily.manager import get_daily_manager

            daily_summary = get_daily_manager().get_today_summary()
            if daily_summary:
                context.append(daily_summary)
        except Exception as e:
            logger.warning(f"Failed to get daily summary: {e}")

        return "\n\n".join(context)

    # ===== 以下为委托方法（延迟导入避免循环依赖，保持外部 API 完全兼容）=====

    async def _check_control_intent(
        self, user_input: str, conversation_id: str
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        from core.services.aveline.control_intent import check_control_intent
        return await check_control_intent(self, user_input, conversation_id)

    async def _check_llm_control_intent(
        self, user_input: str, conversation_id: str
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        from core.services.aveline.control_intent import check_llm_control_intent
        return await check_llm_control_intent(self, user_input, conversation_id)

    async def _handle_command(
        self, user_input: str, conversation_id: str
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        from core.services.aveline.command_handler import handle_system_command
        return await handle_system_command(self, user_input, conversation_id)

    # --- 主动消息相关委托 ---
    async def generate_proactive_message(
        self,
        conversation_id: Optional[str] = None,
        save_to_history: bool = False,
        user_name: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from core.services.aveline.proactive_messaging import generate_proactive_message
        async for chunk in generate_proactive_message(
            self, conversation_id, save_to_history, user_name
        ):
            yield chunk

    async def dispatch_proactive_message(
        self,
        target_conversation_id: str,
        content: str,
        thought: str = "",
        message_type: str = "text",
        tts_text: str = "",
        client_type: str = "",
        requested_client_type: str = "",
        hardware_payload: Optional[Dict[str, Any]] = None,
        original_primary_conversation_id: str = "",
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from core.services.aveline.proactive_messaging import dispatch_proactive_message
        return await dispatch_proactive_message(
            self,
            target_conversation_id,
            content,
            thought=thought,
            message_type=message_type,
            tts_text=tts_text,
            client_type=client_type,
            requested_client_type=requested_client_type,
            hardware_payload=hardware_payload,
            original_primary_conversation_id=original_primary_conversation_id,
            extra_payload=extra_payload,
        )

    async def _dispatch_to_qq_official(
        self, target_conversation_id: str, content: str, client_type: str
    ) -> bool:
        from core.services.aveline.proactive_messaging import _dispatch_to_qq_official
        return await _dispatch_to_qq_official(
            self, target_conversation_id, content, client_type
        )

    async def append_proactive_message(
        self, conversation_id: str, content: str, thought: str = "",
        is_peer_script: bool = False,
        peer_speaker: str = "",
    ):
        from core.services.aveline.proactive_messaging import append_proactive_message
        await append_proactive_message(
            self,
            conversation_id=conversation_id,
            content=content,
            thought=thought,
            is_peer_script=is_peer_script,
            peer_speaker=peer_speaker,
        )

    # --- 视觉/图像服务委托 ---
    async def analyze_screen(
        self, image_data: Union[str, bytes], prompt: str = "描述屏幕上的内容", **kwargs
    ) -> Dict[str, Any]:
        from core.services.aveline.vision_service import analyze_screen
        return await analyze_screen(self, image_data, prompt, **kwargs)

    def _process_image_data(self, image_data: Union[str, bytes]):
        from core.services.aveline.vision_service import _process_image_data
        return _process_image_data(image_data)

    async def _execute_vision_task(self, image, prompt):
        from core.services.aveline.vision_service import _execute_vision_task
        return await _execute_vision_task(self, image, prompt)

    async def _execute_multimodal_llm_task(self, image, prompt):
        from core.services.aveline.vision_service import _execute_multimodal_llm_task
        return await _execute_multimodal_llm_task(self, image, prompt)

    async def _generate_image_task(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        vae_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        from core.services.aveline.vision_service import _generate_image_task
        return await _generate_image_task(self, prompt, model_name, vae_name)

    # --- 回复生成委托 ---
    async def stream_generate_response(
        self,
        user_input: str,
        conversation_id: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        model_hint: Optional[str] = None,
        save_history: bool = True,
        user_name: Optional[str] = None,
        length_preference: Optional[str] = None,
        persona_filename: Optional[str] = None,
        service_dynamic_context: Optional[str] = None,
        api_key_env: Optional[str] = None,
        platform: Optional[str] = None,
        history_override: Optional[list[Dict[str, str]]] = None,
    ):
        from core.services.aveline.response_generator import stream_generate_response
        async for chunk in stream_generate_response(
            self,
            user_input,
            conversation_id,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            model_hint=model_hint,
            save_history=save_history,
            user_name=user_name,
            length_preference=length_preference,
            persona_filename=persona_filename,
            service_dynamic_context=service_dynamic_context,
            api_key_env=api_key_env,
            platform=platform,
            history_override=history_override,
        ):
            yield chunk

    async def generate_response(
        self,
        user_input: str,
        conversation_id: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        timeout: Optional[float] = None,
        model_hint: Optional[str] = None,
        save_history: bool = True,
        user_name: Optional[str] = None,
        length_preference: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        from core.services.aveline.response_generator import generate_response
        return await generate_response(
            self,
            user_input,
            conversation_id,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            model_hint=model_hint,
            save_history=save_history,
            user_name=user_name,
            length_preference=length_preference,
        )

    # --- 会话入口与状态管理委托 ---
    def _normalize_conversation_id(self, conversation_id: Optional[str]) -> str:
        from core.services.aveline.conversation_handler import normalize_conversation_id
        return normalize_conversation_id(conversation_id)

    def _normalize_request_id(self, request_id: Optional[str], fallback: str) -> str:
        from core.services.aveline.conversation_handler import normalize_request_id
        return normalize_request_id(request_id, fallback)

    async def _get_inflight_lock(self, cache_key: str) -> asyncio.Lock:
        from core.services.aveline.conversation_handler import get_inflight_lock
        return await get_inflight_lock(self, cache_key)

    async def handle_conversation(
        self,
        *,
        user_input: str,
        conversation_id: Optional[str],
        request_id: Optional[str] = None,
        message_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        model_hint: Optional[str] = None,
        voice_id: Optional[str] = None,
        save_history: bool = True,
        enable_auto_media: bool = True,
        user_name: Optional[str] = None,
        length_preference: Optional[str] = None,
    ) -> Dict[str, Any]:
        from core.services.aveline.conversation_handler import handle_conversation
        return await handle_conversation(
            self,
            user_input=user_input,
            conversation_id=conversation_id,
            request_id=request_id,
            message_id=message_id,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            model_hint=model_hint,
            voice_id=voice_id,
            save_history=save_history,
            enable_auto_media=enable_auto_media,
            user_name=user_name,
            length_preference=length_preference,
        )

    async def stream_conversation(
        self,
        *,
        user_input: str,
        conversation_id: Optional[str],
        request_id: Optional[str] = None,
        message_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        model_hint: Optional[str] = None,
        save_history: bool = True,
        user_name: Optional[str] = None,
        length_preference: Optional[str] = None,
        persona_filename: Optional[str] = None,
        service_dynamic_context: Optional[str] = None,
        api_key_env: Optional[str] = None,
        skip_active_care: bool = False,
        platform: Optional[str] = None,
        history_override: Optional[list[Dict[str, str]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        # [DEBUG] 关键日志：追踪 persona_filename 在 service 层的传递
        from core.utils.logger import get_logger as _get_logger
        _svc_logger = _get_logger("AvelineService")
        _svc_logger.info(
            f"[stream_conversation] conversation_id={conversation_id}, "
            f"persona_filename={persona_filename!r}, model_hint={model_hint!r}"
        )
        from core.services.aveline.stream_orchestrator import stream_conversation_events
        async for event in stream_conversation_events(
            self,
            user_input=user_input,
            conversation_id=conversation_id,
            request_id=request_id,
            message_id=message_id,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            model_hint=model_hint,
            save_history=save_history,
            user_name=user_name,
            length_preference=length_preference,
            persona_filename=persona_filename,
            service_dynamic_context=service_dynamic_context,
            api_key_env=api_key_env,
            skip_active_care=skip_active_care,
            platform=platform,
            history_override=history_override,
        ):
            yield event
