#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用OpenAI兼容API客户端

提供与OpenAI兼容API的集成，支持流式和非流式对话。

本文件只做编排：payload 构造 → 重试 → 错误判定 → 解析 / 转发。
可复用细节住在同目录的专职模块里：

    message_utils    消息规范化与 payload 构建
    error_handling   传输错误分类 + HTTP 非 200 判定
    retry            重试次数与退避
    session_mixin    常驻 / 临时 session 管理
    caller_source    业务调用来源提取
    stream_parser    SSE 流解析
    dsml_stream      DSML token 流式兜底（跨 chunk 缓冲）
    dsml_parser      DSML 工具调用解析
    response_parser  非流式响应解析
    vision_router    纯文本主模型的两阶段视觉路由

兼容说明：LLMSessionMixin 与 _is_sensitive_input_rejection 历史上从本模块导出
（core/llm/siliconflow_client.py、tests/scripts/monitoring 都在用），
实现搬走后这里保留 re-export。
"""

import os
from typing import Any, Dict, Optional, AsyncGenerator

import aiohttp

from core.llm import LLMModule
from core.utils.logger import get_logger
from core.utils.debug_markers import ensure_debug_error_prefix
from core.llm.llm_logger import (
    log_api_call,
    log_llm_call_stats,
    log_prompt_cache_usage,
)
from core.llm.openai_compat.caller_source import caller_source
from core.llm.openai_compat.cache_markers import apply_cache_markers
from core.llm.openai_compat.dsml_stream import DSMLStreamFilter
from core.llm.openai_compat.error_handling import (
    classify_error_response,
    format_network_error,
    is_sensitive_input_rejection as _is_sensitive_input_rejection,
)
from core.llm.openai_compat.message_utils import (
    build_payload,
    extract_prompt_preview,
    normalize_messages,
)
from core.llm.openai_compat.retry import RetryPolicy
from core.llm.openai_compat.session_mixin import (
    LLMSessionMixin,
    create_session,
    request_session,
)
from core.llm.openai_compat.stream_parser import parse_sse_stream
from core.llm.openai_compat.response_parser import parse_non_stream_response
from core.llm.openai_compat.vision_router import route_vision_if_needed


logger = get_logger("openai_client")

# 兼容旧导入路径：实现已搬到 session_mixin / error_handling，符号仍从本模块导出
__all__ = ["OpenAIClient", "LLMSessionMixin", "_is_sensitive_input_rejection"]


class OpenAIClient(LLMSessionMixin, LLMModule):
    """
    通用OpenAI兼容API客户端

    所有基于OpenAI兼容接口的客户端（DeepSeek、MiniMax、Ark等）都继承此类
    """

    # 传输层瞬时错误的重试策略（次数 + 退避），子类可整体替换
    retry_policy = RetryPolicy()

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        vision_api_key: Optional[str] = None,
        vision_base_url: Optional[str] = None,
        vision_model: Optional[str] = None,
        proxy: Optional[str] = None,
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

        # 视觉路由配置:仅当主模型是纯文本模型、消息含图片时,用这套配置调 VL 模型描述图片
        # 多模态主模型自带视觉,不需要这套配置,直接走一阶段
        self._vision_api_key = vision_api_key or api_key
        self._vision_base_url = vision_base_url or base_url
        self._vision_model = vision_model
        self._vision_session: Optional[aiohttp.ClientSession] = None

        # 可选 HTTP 代理（如国内访问受限的 OpenAI 兼容服务，如 OpenRouter 的 gemini）。
        # 默认 None 表示不走代理，不影响其它 provider。
        self.proxy = proxy

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
            self._vision_session = create_session(
                self._vision_api_key, self.timeout, getattr(self, "proxy", None)
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

    def _log_call_stats(self, payload: Dict[str, Any], stream: bool) -> None:
        """发送前记录调用统计。

        放在编排层而不是 _build_payload 里：_build_payload 是子类的扩展点，
        统计塞在里面会变成构造器副作用，子类一旦不调 super() 就漏统计。
        """
        log_llm_call_stats(
            provider="openai_compat",
            model=payload.get("model", ""),
            messages=payload.get("messages") or [],
            stream=stream,
            extra={
                "temperature": payload.get("temperature"),
                "max_tokens": payload.get("max_tokens"),
            },
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
        api_key = kwargs.pop("api_key", None)

        payload = self._build_payload(messages, stream=False, **kwargs)
        self._log_call_stats(payload, stream=False)
        prompt_preview = extract_prompt_preview(messages)

        last_error: Optional[Exception] = None

        for attempt in range(self.retry_policy.max_attempts):
            log_api_call(provider="openai_compat", prompt_preview=prompt_preview, is_retry=(attempt > 0), model=payload.get("model", ""))

            try:
                async with request_session(self, api_key) as session:
                    async with session.post(self.base_url, json=payload) as response:
                        if response.status != 200:
                            info = classify_error_response(
                                response.status,
                                await response.text(),
                                payload=payload,
                                attempt=attempt,
                                max_attempts=self.retry_policy.max_attempts,
                                logger=logger,
                            )
                            if info.retry_payload is not None:
                                payload = info.retry_payload
                                continue
                            detail = info.body.strip()
                            error_msg = f"Error: API returned {info.status}"
                            if detail:
                                error_msg = f"{error_msg}: {detail}"
                            return ensure_debug_error_prefix(error_msg)

                        parsed = await parse_non_stream_response(response)
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
                                    source=caller_source(),
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
                if self.retry_policy.should_retry(e, attempt):
                    logger.warning(f"Transient transport error detected, retrying: {e}")
                    await self.retry_policy.backoff(attempt)
                    continue
                logger.error(f"Request failed: {e}")
                err_obj = format_network_error(e)
                return ensure_debug_error_prefix(
                    f"Error: {err_obj['error']} [{err_obj['error_code']}] ({e})"
                )

        if last_error is not None:
            logger.error(f"Request failed: {last_error}")
            return ensure_debug_error_prefix(f"Error: {last_error}")
        return ensure_debug_error_prefix("Error: Unknown failure")

    async def stream_chat(
        self, messages: list, **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式对话补全

        Args:
            messages: 消息列表
            **kwargs: 其他参数（temperature、max_tokens、api_key 等）

        Yields:
            包含content或error的字典
        """
        if not self.initialized:
            await self.initialize()

        # 视觉路由:多模态主模型直通,纯文本主模型走 VL 中转
        # 注:两阶段中转里 VL 描述本身是非流式调用,描述完成后再把替换后的消息流式发给主模型
        messages, _route_desc = await self._route_vision_if_needed(messages, **kwargs)

        # 支持动态API key（与 chat 一致：非默认 key 走临时 session）
        api_key = kwargs.pop("api_key", None)

        payload = self._build_payload(messages, stream=True, **kwargs)
        self._log_call_stats(payload, stream=True)
        prompt_preview = extract_prompt_preview(messages)
        last_error: Optional[Exception] = None
        # 每次流式调用一个过滤器：缓冲不挂实例，避免并发调用互相串
        dsml_filter = DSMLStreamFilter(logger)

        for attempt in range(self.retry_policy.max_attempts):
            log_api_call(provider="openai_compat", prompt_preview=prompt_preview, is_retry=(attempt > 0), model=payload.get("model", ""))
            emitted_any_content = False

            try:
                async with request_session(self, api_key) as session:
                    async with session.post(self.base_url, json=payload) as response:
                        if response.status != 200:
                            info = classify_error_response(
                                response.status,
                                await response.text(),
                                payload=payload,
                                attempt=attempt,
                                max_attempts=self.retry_policy.max_attempts,
                                logger=logger,
                            )
                            if info.retry_payload is not None:
                                payload = info.retry_payload
                                continue
                            # 401/402/403 属于认证/计费类错误；422 表示输入已被明确
                            # 拒绝。它们都不应由上层拿同一 payload 再重试。
                            # 并打 non_retryable 标识，让上层跳过重试，避免刷屏日志与浪费配额
                            if info.non_retryable:
                                yield {
                                    "error": f"API returned {info.status}",
                                    "error_code": "non_retryable",
                                    "non_retryable": True,
                                    "details": {
                                        "status": info.status,
                                        "body": info.body[:200],
                                    },
                                }
                                return
                            yield {"error": f"API returned {info.status}"}
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
                                    source=caller_source(),
                                )
                                continue
                            for processed in dsml_filter.filter_chunk(chunk):
                                yield processed
                        # 收尾：未闭合的 DSML 缓冲按可见文本吐出，避免整段内容被吞掉
                        for processed in dsml_filter.flush():
                            yield processed
                        return

            except Exception as e:
                last_error = e
                if self.retry_policy.should_retry(e, attempt, not emitted_any_content):
                    logger.warning(f"Transient transport error detected, retrying stream: {e}")
                    # 不关闭主 session：aiohttp 连接池会自动丢弃坏连接并在下次请求时重建
                    await self.retry_policy.backoff(attempt)
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
        # prompt caching 开关：默认开，单次调用可用 cache_markers=False / cache_ttl="1h" 覆盖
        cache_markers = kwargs.pop("cache_markers", True)
        cache_ttl = kwargs.pop("cache_ttl", None)
        cache_session_id = kwargs.pop("cache_session_id", True)

        normalized_messages = normalize_messages(messages)

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

        # 按上游 provider 注入 prompt caching 标记：
        # 只对需要显式断点的厂商（Anthropic / Gemini / Qwen）写 cache_control，
        # 其余上游自动缓存，写了反而可能被当成未知字段；OpenRouter 另补 session_id 打开 sticky routing
        apply_cache_markers(
            payload,
            base_url=self.base_url,
            ttl=cache_ttl,
            markers=cache_markers,
            session_id=cache_session_id,
        )

        return payload
