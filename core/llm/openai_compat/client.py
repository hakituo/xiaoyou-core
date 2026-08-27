#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用OpenAI兼容API客户端

提供与OpenAI兼容API的集成，支持流式和非流式对话
"""

import asyncio
import inspect
import os
from typing import Dict, Optional, Any, AsyncGenerator

import aiohttp

from core.llm import LLMModule
from core.utils.logger import get_logger
from core.utils.debug_markers import ensure_debug_error_prefix
from core.contracts import ModuleInitState
from core.llm.llm_logger import (
    log_api_call,
    log_llm_call_stats,
    log_prompt_cache_usage,
)
from core.llm.openai_compat.message_utils import (
    build_payload,
    extract_prompt_preview,
    roles_preview,
    rebuild_payload_for_system_order,
    is_system_order_error,
    normalize_messages,
)
from core.llm.openai_compat.error_handling import is_transient_error, format_network_error
from core.llm.openai_compat.stream_parser import parse_sse_stream
from core.llm.openai_compat.dsml_parser import parse_dsml_tool_calls, has_dsml_tokens
from core.llm.openai_compat.response_parser import parse_non_stream_response
from core.llm.openai_compat.vision_router import route_vision_if_needed


logger = get_logger("openai_client")

# 调用栈来源标签：跳过这些框架层，取真正的业务任务函数名
_SOURCE_SKIP = {
    "_caller_source", "stream_chat", "chat", "_do_chat", "_raw_chat",
    "build_payload", "rebuild_payload_for_system_order", "submit_llm_task",
}
# 这些目录/文件属于框架层（LLM 客户端、调度器、日志器），不作为来源
_FRAMEWORK_DIRS = ("openai_compat", "/llm/", "scheduler", "llm_logger.py")


def _caller_source() -> Optional[str]:
    """从调用栈提取业务层函数名（如 task_runner.py::distill_memories_async），用于缓存日志定位请求来源。"""
    try:
        for frame in inspect.stack()[1:]:
            name = frame.function
            if name in _SOURCE_SKIP:
                continue
            mod = (frame.filename or "")
            if any(d in mod for d in _FRAMEWORK_DIRS):
                continue
            base = mod.replace("\\", "/").split("/")[-1]
            return f"{base}::{name}"
    except Exception:
        return None
    return None


class LLMSessionMixin:
    """LLM 客户端公共 session 管理和状态报告混入类"""

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self.session

    async def _close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
        if self._vision_session and self._vision_session.closed is False:
            await self._vision_session.close()
            self._vision_session = None

    async def shutdown(self):
        await self._close_session()

    def _build_base_status(self, provider: str = "", **extra) -> Dict[str, Any]:
        init_state = (
            ModuleInitState.INITIALIZED
            if bool(self.initialized)
            else ModuleInitState.NOT_INITIALIZED
        )
        status = {
            "status": init_state.value,
            "init_state": init_state.value,
            "api_key_configured": bool(self.api_key),
            "session_active": self.session is not None and not self.session.closed,
            "model": self.default_model,
        }
        if provider:
            status["provider"] = provider
        if getattr(self, "base_url", None):
            status["base_url"] = self.base_url
        status.update(extra)
        return status


class OpenAIClient(LLMSessionMixin, LLMModule):
    """
    通用OpenAI兼容API客户端

    所有基于OpenAI兼容接口的客户端（DeepSeek、MiniMax、Ark等）都继承此类
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        vision_api_key: Optional[str] = None,
        vision_base_url: Optional[str] = None,
        vision_model: Optional[str] = None,
    ):
        """
        初始化OpenAI兼容客户端

        Args:
            api_key: API密钥
            base_url: API基础URL
            model: 默认模型名称
            vision_api_key: VL 中转模型专用 API Key(纯文本主模型走两阶段时使用)
            vision_base_url: VL 中转模型专用 base_url
            vision_model: VL 中转模型名(如 Qwen/Qwen3-VL-32B-Instruct)
        """
        super().__init__()
        self.api_key = api_key
        # 缓存命中率日志按 API key 区分（如 deepseek:qqbot1），由 factory 注入
        self.key_id = None
        self.base_url = base_url or "https://api.openai.com/v1/chat/completions"
        # 默认模型可由环境变量 OPENAI_DEFAULT_MODEL 覆盖，否则使用 gpt-3.5-turbo
        self.default_model = model or os.getenv("OPENAI_DEFAULT_MODEL", "gpt-3.5-turbo")
        self.default_max_tokens: Optional[int] = None
        self.default_top_p: Optional[float] = None
        self.default_repetition_penalty: Optional[float] = None
        self.timeout = 180
        self.session: Optional[aiohttp.ClientSession] = None
        self.initialized = False
        self._dsml_buffer: str = ""
        self._dsml_active: bool = False

        # 视觉路由配置:仅当主模型是纯文本模型、消息含图片时,用这套配置调 VL 模型描述图片
        # 多模态主模型自带视觉,不需要这套配置,直接走一阶段
        self._vision_api_key = vision_api_key or api_key
        self._vision_base_url = vision_base_url or base_url
        self._vision_model = vision_model
        self._vision_session: Optional[aiohttp.ClientSession] = None

        if not self.api_key:
            logger.warning("OpenAI API Key not provided.")

        logger.info(
            f"OpenAI Client configured with URL: {self.base_url}, Model: {self.default_model}"
        )

    def get_status(self) -> Dict[str, Any]:
        return self._build_base_status(type="openai_compatible")

    async def initialize(self):
        if not self.initialized:
            await self._get_session()
            self.initialized = True
            logger.info("OpenAI Client initialized")

    # ============================================================
    # 视觉路由(核心)
    # ============================================================
    # 决策依据:模型能力 + 消息内容
    #   - 主模型是多模态(is_vision_model=True) → 一阶段:把含 image_url 的消息原样发给主模型
    #   - 主模型是纯文本 + 消息含图片 → 两阶段:先调 VL 模型把图片描述成文字,替换进消息,再发给主模型
    #   - 消息无图片 → 走默认路径
    # 多模态判断见 core/llm/model_capabilities.py 的 is_vision_model()
    # ============================================================

    async def _get_vision_session(self) -> aiohttp.ClientSession:
        """获取 VL 中转专用 session(若未配置则回退主 session)"""
        # 没配置独立 vision session 时,直接用主 session(共用同一个 API 端点/key)
        if not self._vision_base_url or self._vision_base_url == self.base_url:
            return await self._get_session()
        if self._vision_session is None or self._vision_session.closed:
            self._vision_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={
                    "Authorization": f"Bearer {self._vision_api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._vision_session

    async def _route_vision_if_needed(self, messages: list, **kwargs) -> tuple[list, str]:
        """视觉路由前置处理（委托给 vision_router 模块）"""
        model_name = kwargs.get("model", self.default_model)
        return await route_vision_if_needed(
            messages=messages,
            model_name=model_name,
            vision_model=self._vision_model,
            vision_base_url=self._vision_base_url,
            get_session_fn=self._get_vision_session,
        )

    async def chat(self, messages: list, **kwargs) -> dict:
        """
        对话补全

        Args:
            messages: 消息列表
            **kwargs: 其他参数（temperature, max_tokens, api_key等）

        Returns:
            包含 response 和 finish_reason 的字典，或错误字符串
        """
        if not self.initialized:
            await self.initialize()

        # 视觉路由:多模态主模型直通,纯文本主模型走 VL 中转
        messages, _route_desc = await self._route_vision_if_needed(messages, **kwargs)

        # 支持动态API key
        api_key = kwargs.pop("api_key", None) or self.api_key

        payload = self._build_payload(messages, stream=False, **kwargs)
        prompt_preview = extract_prompt_preview(messages)

        last_error: Optional[Exception] = None

        for attempt in range(3):
            log_api_call(provider="openai_compat", prompt_preview=prompt_preview, is_retry=(attempt > 0), model=payload.get("model", ""))

            # 判断是否使用临时 session（动态 api_key 场景）
            _temp_session = None
            try:
                if api_key != self.api_key:
                    # 动态 key：创建临时 session，请求后关闭
                    _temp_session = aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(total=self.timeout),
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                    )
                    session = _temp_session
                else:
                    session = await self._get_session()

                async with session.post(self.base_url, json=payload) as response:
                    if response.status != 200:
                        err_result = await self._handle_error_response(response, payload, attempt)
                        if err_result is None:
                            continue
                        return err_result

                    parsed = await self._parse_non_stream_response(response)
                    if isinstance(parsed, dict) and "content" in parsed:
                        # 记录 prompt 缓存命中率（usage 不进下游 result，避免污染）
                        usage = parsed.pop("usage", None)
                        if usage:
                            log_prompt_cache_usage(
                                "openai_compat",
                                payload.get("model", ""),
                                usage,
                                extra={"mode": "sync"},
                                key_id=getattr(self, "key_id", None),
                                source=_caller_source(),
                            )
                        result = {"response": parsed["content"], "finish_reason": parsed.get("finish_reason")}
                        if parsed.get("reasoning_only"):
                            result["reasoning_only"] = True
                            result["reasoning_text"] = parsed.get("reasoning_text", "")
                        if parsed.get("reasoning_content"):
                            result["reasoning_content"] = parsed["reasoning_content"]
                        if parsed.get("tool_calls"):
                            result["tool_calls"] = parsed["tool_calls"]
                        return result
                    return parsed

            except Exception as e:
                last_error = e
                if attempt < 2 and is_transient_error(e):
                    logger.warning(f"Transient transport error detected, retrying: {e}")
                    # 不关闭主 session：aiohttp 连接池会自动丢弃坏连接并在下次请求时重建
                    # 关闭整个 session 会丢弃所有 TCP 连接和 TLS 握手，增加 200-800ms 延迟
                    await asyncio.sleep(0.25 * (attempt + 1))
                    continue
                logger.error(f"Request failed: {e}")
                err_obj = format_network_error(e)
                return ensure_debug_error_prefix(
                    f"Error: {err_obj['error']} [{err_obj['error_code']}] ({e})"
                )
            finally:
                # 关闭临时 session
                if _temp_session and not _temp_session.closed:
                    await _temp_session.close()

        if last_error is not None:
            logger.error(f"Request failed: {last_error}")
            return ensure_debug_error_prefix(f"Error: {last_error}")
        return ensure_debug_error_prefix("Error: Unknown failure")

    async def _handle_error_response(self, response, payload, attempt):
        """处理错误响应"""
        error_text = await response.text()
        if response.status == 400 and "group chat" in error_text:
            try:
                import json
                with open("minimax_400_payload.json", "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        if response.status == 400 and is_system_order_error(error_text) and attempt < 2:
            if attempt == 0:
                payload = rebuild_payload_for_system_order(payload, keep_single_system=False)
            else:
                payload = rebuild_payload_for_system_order(payload, keep_single_system=True)
            logger.warning(
                "Retrying after system-order 400. roles=%s",
                roles_preview(payload.get("messages")),
            )
            return None

        logger.error(f"API Error ({response.status}): {error_text}")
        detail = (error_text or "").strip()
        error_msg = f"Error: API returned {response.status}"
        if detail:
            error_msg = f"Error: API returned {response.status}: {detail}"
        return ensure_debug_error_prefix(error_msg)

    async def _parse_non_stream_response(self, response) -> dict:
        """解析非流式响应（委托给 response_parser 模块）"""
        return await parse_non_stream_response(response)

    async def stream_chat(
        self, messages: list, **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式对话补全

        Args:
            messages: 消息列表
            **kwargs: 其他参数

        Yields:
            包含content或error的字典
        """
        if not self.initialized:
            await self.initialize()

        # 视觉路由:多模态主模型直通,纯文本主模型走 VL 中转
        # 注:两阶段中转里 VL 描述本身是非流式调用,描述完成后再把替换后的消息流式发给主模型
        messages, _route_desc = await self._route_vision_if_needed(messages, **kwargs)

        payload = self._build_payload(messages, stream=True, **kwargs)
        prompt_preview = extract_prompt_preview(messages)
        last_error: Optional[Exception] = None

        for attempt in range(3):
            log_api_call(provider="openai_compat", prompt_preview=prompt_preview, is_retry=(attempt > 0), model=payload.get("model", ""))
            emitted_any_content = False

            try:
                session = await self._get_session()
                async with session.post(self.base_url, json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        if response.status == 400 and "group chat" in error_text:
                            try:
                                import json
                                with open("minimax_400_payload.json", "w", encoding="utf-8") as f:
                                    json.dump(payload, f, ensure_ascii=False, indent=2)
                            except Exception:
                                pass
                        if response.status == 400 and is_system_order_error(error_text) and attempt < 2:
                            if attempt == 0:
                                payload = rebuild_payload_for_system_order(payload, keep_single_system=False)
                            else:
                                payload = rebuild_payload_for_system_order(payload, keep_single_system=True)
                            logger.warning(
                                "Retrying stream after system-order 400. roles=%s",
                                roles_preview(payload.get("messages")),
                            )
                            continue
                        # 401/402/403 属于认证/计费类错误，重试无意义，快速失败
                        # 并打 non_retryable 标识，让上层跳过重试，避免刷屏日志与浪费配额
                        if response.status in (401, 402, 403):
                            logger.error(
                                "API 不可重试错误 (%d): %s",
                                response.status,
                                error_text[:200],
                            )
                            yield {
                                "error": f"API returned {response.status}",
                                "error_code": "non_retryable",
                                "non_retryable": True,
                                "details": {
                                    "status": response.status,
                                    "body": error_text[:200],
                                },
                            }
                            return
                        logger.error(f"API Error ({response.status}): {error_text}")
                        yield {"error": f"API returned {response.status}"}
                        return

                    async for chunk in parse_sse_stream(response.content, logger):
                        emitted_any_content = True
                        # 流式结束块携带 usage：记录缓存命中率，不向下游转发
                        if "usage" in chunk:
                            log_prompt_cache_usage(
                                "openai_compat",
                                payload.get("model", ""),
                                chunk.get("usage") or {},
                                extra={"mode": "stream"},
                                key_id=getattr(self, "key_id", None),
                                source=_caller_source(),
                            )
                            continue
                        async for processed in self._process_stream_chunk(chunk):
                            yield processed
                    return

            except Exception as e:
                last_error = e
                if attempt < 2 and not emitted_any_content and is_transient_error(e):
                    logger.warning(f"Transient transport error detected, retrying stream: {e}")
                    # 不关闭主 session：aiohttp 连接池会自动丢弃坏连接并在下次请求时重建
                    await asyncio.sleep(0.25 * (attempt + 1))
                    continue
                logger.error(f"Stream request failed: {e}")
                err_obj = format_network_error(e)
                yield {
                    "error": err_obj["error"],
                    "error_code": err_obj["error_code"],
                    "details": {"raw": str(e)},
                }
                return

        if last_error is not None:
            logger.error(f"Stream request failed: {last_error}")
            err_obj = format_network_error(last_error)
            yield {
                "error": err_obj["error"],
                "error_code": err_obj["error_code"],
                "details": {"raw": str(last_error)},
            }

    async def _process_stream_chunk(self, chunk: Dict[str, Any]):
        """
        处理流式chunk，拦截DSML token泄漏

        当DeepSeek API未正确解析DSML token时，它们会作为content泄漏。
        此方法在LLM客户端层拦截DSML token，将其解析为结构化tool_calls，
        防止原始DSML文本流到上层（streaming.py/前端）。
        """
        if "content" not in chunk:
            yield chunk
            return

        text = chunk["content"]

        if self._dsml_active:
            self._dsml_buffer += text
            close_patterns = [
                "</\uff5c\uff5cDSML\uff5c\uff5ctool_calls>",
                "</\uff5c\uff5cDSML\uff5c\uff5cfunction_calls>",
                "</\uff5cDSML\uff5ctool_calls>",
                "</\uff5cDSML\uff5cfunction_calls>",
                "</tool_calls>",
                "</function_calls>",
            ]
            for close_pat in close_patterns:
                close_idx = self._dsml_buffer.find(close_pat)
                if close_idx >= 0:
                    dsml_block = self._dsml_buffer[:close_idx + len(close_pat)]
                    remainder = self._dsml_buffer[close_idx + len(close_pat):]
                    self._dsml_active = False
                    self._dsml_buffer = ""

                    _, dsml_calls = parse_dsml_tool_calls(dsml_block)
                    if dsml_calls:
                        logger.info(
                            "DSML流式兜底: 解析到%d个工具调用",
                            len(dsml_calls),
                        )
                        yield {"tool_calls": dsml_calls}
                        yield {"finish_reason": "tool_calls"}

                    if remainder.strip():
                        yield {"content": remainder}
                    break
            else:
                pass
            return

        if has_dsml_tokens(text):
            start_markers = [
                "<\uff5c\uff5cDSML\uff5c\uff5ctool_calls>",
                "<\uff5c\uff5cDSML\uff5c\uff5cfunction_calls>",
                "<\uff5cDSML\uff5ctool_calls>",
                "<\uff5cDSML\uff5cfunction_calls>",
            ]
            for marker in start_markers:
                idx = text.find(marker)
                if idx >= 0:
                    before = text[:idx]
                    after = text[idx:]

                    if before.strip():
                        yield {"content": before}

                    self._dsml_active = True
                    self._dsml_buffer = after

                    close_patterns = [
                        "</\uff5c\uff5cDSML\uff5c\uff5ctool_calls>",
                        "</\uff5c\uff5cDSML\uff5c\uff5cfunction_calls>",
                        "</\uff5cDSML\uff5ctool_calls>",
                        "</\uff5cDSML\uff5cfunction_calls>",
                        "</tool_calls>",
                        "</function_calls>",
                    ]
                    for close_pat in close_patterns:
                        close_idx = self._dsml_buffer.find(close_pat)
                        if close_idx >= 0:
                            dsml_block = self._dsml_buffer[:close_idx + len(close_pat)]
                            remainder = self._dsml_buffer[close_idx + len(close_pat):]
                            self._dsml_active = False
                            self._dsml_buffer = ""

                            _, dsml_calls = parse_dsml_tool_calls(dsml_block)
                            if dsml_calls:
                                logger.info(
                                    "DSML流式兜底: 解析到%d个工具调用",
                                    len(dsml_calls),
                                )
                                yield {"tool_calls": dsml_calls}
                                yield {"finish_reason": "tool_calls"}

                            if remainder.strip():
                                yield {"content": remainder}
                            break
                    return

        yield chunk

    def _build_payload(self, messages: list, stream: bool, **kwargs) -> Dict[str, Any]:
        """构建 API 请求 Payload"""
        model = kwargs.pop("model", self.default_model)
        temperature = kwargs.pop("temperature", 0.7)
        max_tokens = kwargs.pop("max_tokens", self.default_max_tokens)
        top_p = kwargs.pop("top_p", self.default_top_p)
        repetition_penalty = kwargs.pop("repetition_penalty", self.default_repetition_penalty)
        # 支持 extra_body 参数（用于 DeepSeek 思考模式等）
        extra_body = kwargs.pop("extra_body", None)
        # 支持 tools 参数（用于原生工具调用）
        tools = kwargs.pop("tools", None)
        tool_choice = kwargs.pop("tool_choice", None)
        # 移除客户端特有参数，避免泄漏到API请求体
        kwargs.pop("web_search_enabled", None)
        kwargs.pop("thinking_enabled", None)

        normalized_messages = normalize_messages(messages)

        log_llm_call_stats(
            provider="openai_compat",
            model=model,
            messages=normalized_messages,
            stream=stream,
            extra={"temperature": temperature, "max_tokens": max_tokens},
        )

        payload = build_payload(
            messages=normalized_messages,
            model=model,
            stream=stream,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
            default_max_tokens=self.default_max_tokens,
            **kwargs
        )

        # 添加 extra_body 参数（如果提供）
        if extra_body:
            payload["extra_body"] = extra_body

        # 添加 tools 参数（如果提供）
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice

        return payload
