#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按 provider 自动注入 prompt caching 标记

依据 OpenRouter 官方说明（https://openrouter.ai/docs/guides/best-practices/prompt-caching）：

- **自动生效、不能塞标记**：OpenAI / DeepSeek / Grok(x-ai) / Moonshot / Groq / Z.AI，
  以及 Gemini 的隐式缓存。这些上游会自动放断点，请求体里出现 `cache_control`
  属于未知字段，轻则被忽略、重则直接 400——所以一律不加。
- **Anthropic**：支持两种。请求级 `cache_control`（自动缓存，官方推荐多轮对话，
  断点自动往前推进）与块级 `cache_control`（最多 4 个，精细控制）。
- **Google Gemini**：需要块级 `cache_control` 断点；OpenRouter 只取最后一个断点。
  注意 Gemini 的 systemInstruction 视为不可变，被缓存的 system 消息后面不能再挂动态尾巴
  （本项目 system 是纯静态人设，动态内容都在最后一条 user，天然满足）。
- **Alibaba Qwen**：需要块级 `cache_control`，且只有白名单里的模型支持。

另外 OpenRouter 的 sticky routing 默认要等到观测到 cache hit 才启用，
显式传 `session_id` 后第一条请求就把后续请求钉在同一 provider 上，
对**所有**模型（含自动缓存的 DeepSeek/Grok）都有收益，因此与标记分开处理。

本模块对外只暴露三个函数：
    resolve_cache_strategy(base_url, model)  判定加不加、加哪种
    mark_cache_breakpoints(messages, ttl)    块级断点
    apply_cache_markers(payload, ...)        写进 payload（含 session_id）
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger


logger = get_logger("cache_markers")


# 上游 host 判定
OPENROUTER_HOST = "openrouter.ai"
ANTHROPIC_HOST = "api.anthropic.com"

# 标记风格
STYLE_NONE = "none"          # 上游自动缓存，不要加任何字段
STYLE_TOP_LEVEL = "top_level"  # 请求级 cache_control（Anthropic 自动缓存）
STYLE_BLOCK = "block"        # 消息块级 cache_control（显式断点）

# Anthropic 只支持两种 TTL：默认 5 分钟与 1 小时
TTL_5M = ""
TTL_1H = "1h"

# 默认 TTL 取 1 小时（只对 Anthropic 生效，Gemini / Qwen 上游固定 5 分钟）。
# 代价：写缓存从 1.25x 变 2x 输入价；收益：多角色轮流对话时，切去跟别的角色聊
# 超过 5 分钟再回来不用重写缓存（5 分钟 TTL 且 Gemini 明确写了"不刷新"）。
# 按本项目的用法（几个角色共用一个模型、来回切），少重写几次比多付 0.75x 写成本划算。
# 单次调用仍可用 cache_ttl="5m" / "" 覆盖。
DEFAULT_CACHE_TTL = TTL_1H

# OpenRouter 模型名里需要块级断点的 vendor 前缀
BLOCK_VENDOR_PREFIXES = ("google/",)
TOP_LEVEL_VENDOR_PREFIXES = ("anthropic/",)

# Alibaba 显式缓存只支持这些模型（OpenRouter 文档列举，快照端点不支持）
QWEN_CACHEABLE_MODELS = (
    "deepseek/deepseek-v3.2",
    "qwen/qwen3-max",
    "qwen/qwen-plus",
    "qwen/qwen3.6-plus",
    "qwen/qwen3-coder-plus",
    "qwen/qwen3-coder-flash",
)

# 一条请求最多打几个断点（Anthropic 上限 4，够用且省 token）
MAX_BREAKPOINTS = 2

# 可打断点的角色：system/developer 是静态人设，user/assistant 是历史
CACHEABLE_PREFIX_ROLES = ("system", "developer")


@dataclass(frozen=True)
class CacheStrategy:
    """某个 (base_url, model) 组合的缓存标记决策

    Attributes:
        provider: 命中的厂商（anthropic / google / alibaba / ""）
        style: STYLE_* 之一
        ttl: ""（默认 5 分钟）或 "1h"
        reason: 决策依据，进日志便于复盘
    """

    provider: str = ""
    style: str = STYLE_NONE
    ttl: str = TTL_5M
    reason: str = ""

    @property
    def needs_marker(self) -> bool:
        return self.style != STYLE_NONE


def normalize_model_key(model: Any) -> str:
    """把模型名规整成 vendor/model 形式的小写串。

    兼容 `cloud:openrouter:anthropic/claude-opus-4.6`、`Pro/moonshotai/Kimi-K2.6`
    这类带协议头或路径前缀的写法：只取用于判定 vendor 的部分。
    """
    raw = str(model or "").strip().lower()
    if raw.startswith("cloud:"):
        rest = raw[len("cloud:"):]
        # openrouter 的模型名自带冒号（minimax/minimax-m3:free），按路径重建
        segs = rest.split(":", 1)
        raw = segs[1] if len(segs) == 2 else rest
    return raw


def build_cache_control(ttl: str = TTL_5M) -> Dict[str, Any]:
    """生成 cache_control 对象；ttl 只支持空串（默认 5 分钟）与 "1h"。"""
    marker: Dict[str, Any] = {"type": "ephemeral"}
    if ttl == TTL_1H:
        marker["ttl"] = TTL_1H
    return marker


def normalize_ttl(ttl: Optional[str]) -> str:
    """TTL 只允许 5 分钟（空串）与 1 小时，其它值一律退化为默认，不把脏值发给上游。"""
    return TTL_1H if str(ttl or "").strip().lower() == TTL_1H else TTL_5M


def resolve_cache_strategy(
    base_url: Optional[str],
    model: Any,
    ttl: Optional[str] = None,
) -> CacheStrategy:
    """按上游 host + 模型名判定要不要加缓存标记、加哪种、用什么 TTL。

    ttl 为 None 时取 DEFAULT_CACHE_TTL（当前是 1 小时），但只对 Anthropic 生效：
    Gemini 固定 5 分钟 TTL 且"不刷新"，Alibaba Qwen 的显式缓存也只有 5 分钟，
    给它们发 ttl=1h 没有意义，还可能被当成非法值。
    """
    host = str(base_url or "").lower()
    model_key = normalize_model_key(model)
    requested_ttl = normalize_ttl(DEFAULT_CACHE_TTL if ttl is None else ttl)
    # 非 Anthropic 上游的 TTL 由上游自己定，一律按 5 分钟发
    effective_ttl = requested_ttl
    block_ttl = TTL_5M

    if ANTHROPIC_HOST in host:
        return CacheStrategy(
            provider="anthropic",
            style=STYLE_TOP_LEVEL,
            ttl=effective_ttl,
            reason="Anthropic 直连：请求级自动缓存",
        )

    if OPENROUTER_HOST not in host:
        return CacheStrategy(
            reason=f"非 OpenRouter/Anthropic 上游（{host or '未知'}）：上游自动缓存或格式不同，不注入",
        )

    for prefix in TOP_LEVEL_VENDOR_PREFIXES:
        if model_key.startswith(prefix):
            return CacheStrategy(
                provider="anthropic",
                style=STYLE_TOP_LEVEL,
                ttl=effective_ttl,
                reason="Anthropic 多轮对话用请求级自动缓存，断点自动前移",
            )

    for prefix in BLOCK_VENDOR_PREFIXES:
        if model_key.startswith(prefix):
            return CacheStrategy(
                provider="google",
                style=STYLE_BLOCK,
                ttl=block_ttl,
                reason="Gemini 需要块级断点（OpenRouter 只取最后一个），TTL 上游固定 5 分钟",
            )

    if model_key in QWEN_CACHEABLE_MODELS:
        return CacheStrategy(
            provider="alibaba",
            style=STYLE_BLOCK,
            ttl=block_ttl,
            reason="Alibaba Qwen 显式缓存白名单模型：块级断点，TTL 只有 5 分钟",
        )

    return CacheStrategy(reason=f"OpenRouter 上游自动缓存（{model_key or '未知模型'}），不注入")


def _content_as_blocks(content: Any) -> Optional[List[Dict[str, Any]]]:
    """把消息 content 规整成块列表；无法承载断点时返回 None。"""
    if isinstance(content, str):
        if not content.strip():
            return None
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        blocks = [dict(item) for item in content if isinstance(item, dict)]
        return blocks or None
    return None


def _mark_message(message: Dict[str, Any], ttl: str) -> Optional[Dict[str, Any]]:
    """给单条消息的最后一个块打断点，返回新消息；不适用时返回 None。"""
    blocks = _content_as_blocks(message.get("content"))
    if blocks is None:
        return None
    last = blocks[-1]
    if not isinstance(last, dict):
        return None
    last["cache_control"] = build_cache_control(ttl)
    marked = dict(message)
    marked["content"] = blocks
    return marked


def pick_breakpoint_indices(messages: List[Any]) -> List[int]:
    """挑选断点落在哪几条消息上。

    项目的消息布局是 `[system(静态人设)] + [历史...] + [最后一条 user(当前时间/环境/记忆/用户消息)]`，
    动态内容全在最后一条，所以断点打在：

    1. 首条 system/developer —— 缓存静态人设（历史很短时也能命中）
    2. 倒数第二条 —— 缓存整段历史，只把最后一条留给动态内容
    """
    if not messages:
        return []

    indices: List[int] = []
    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip().lower()
        if role in CACHEABLE_PREFIX_ROLES:
            indices.append(idx)
            break

    # 倒数第二条：历史末尾（若它已经是 system 就不重复）
    if len(messages) >= 2:
        second_last = len(messages) - 2
        if second_last not in indices:
            indices.append(second_last)

    return indices[:MAX_BREAKPOINTS]


def mark_cache_breakpoints(
    messages: List[Any],
    ttl: str = TTL_5M,
) -> List[Any]:
    """给消息列表打块级缓存断点（返回新列表，不改动入参）。"""
    if not messages:
        return list(messages)

    targets = pick_breakpoint_indices(messages)
    marked: List[Any] = []
    for idx, msg in enumerate(messages):
        if idx in targets and isinstance(msg, dict):
            new_msg = _mark_message(msg, ttl)
            marked.append(new_msg if new_msg is not None else msg)
        else:
            marked.append(msg)
    return marked


def sticky_session_id(messages: List[Any], limit: int = 256) -> str:
    """生成 OpenRouter sticky routing 用的稳定会话 ID。

    OpenRouter 的默认会话键是"首条 system + 首条非 system"的哈希，**按会话粒度**
    把请求钉在同一个 provider 上：不同会话（首条 system 不同）天然落到不同 provider，
    各自保暖、互不挤占。

    这里**只取首条 system/developer** 作为指纹，与默认口径的差别是有意的：
    本项目 `system` 之后紧跟的那条 user 是 working_set（资料召回结果），
    每轮都可能变；按默认口径算会让同一个角色的 sticky 绑定反复漂移，
    等于每换一轮就可能被丢到没缓存的 provider 上。
    只用静态人设当键，绑定就稳定在"一个角色 = 一个 provider"。

    显式传 session_id 的另一个收益：sticky routing 从**第一条**请求就生效
    （否则要等观测到 cache hit 才钉住 provider）。
    """
    fingerprint = ""
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip().lower()
        if role not in CACHEABLE_PREFIX_ROLES:
            continue
        content = msg.get("content")
        fingerprint = content if isinstance(content, str) else str(content or "")
        break

    if not fingerprint:  # 没有 system/developer 时退回首条消息，保证仍有稳定键
        first = next((m for m in messages or [] if isinstance(m, dict)), None)
        if first is not None:
            content = first.get("content")
            fingerprint = content if isinstance(content, str) else str(content or "")

    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    return digest[:limit]


def apply_cache_markers(
    payload: Dict[str, Any],
    *,
    base_url: Optional[str] = None,
    ttl: Optional[str] = None,
    markers: bool = True,
    session_id: bool = True,
) -> Dict[str, Any]:
    """把缓存标记写进 payload（原地修改并返回）。

    Args:
        payload: build_payload 产出的请求体
        base_url: 上游地址，用于判定是不是 OpenRouter / Anthropic
        ttl: "1h" 用 1 小时 TTL，其余按默认 5 分钟
        markers: 是否写 cache_control（False 时只保留 session_id）
        session_id: 是否给 OpenRouter 补 sticky routing 的会话 ID
    """
    if not isinstance(payload, dict):
        return payload

    messages = payload.get("messages")
    host = str(base_url or "").lower()

    if markers:
        strategy = resolve_cache_strategy(base_url, payload.get("model"), ttl)
        if strategy.style == STYLE_TOP_LEVEL:
            payload["cache_control"] = build_cache_control(strategy.ttl)
        elif strategy.style == STYLE_BLOCK and isinstance(messages, list):
            payload["messages"] = mark_cache_breakpoints(messages, ttl=strategy.ttl)
        if strategy.needs_marker:
            logger.debug(
                "prompt cache 标记: provider=%s style=%s ttl=%s (%s)",
                strategy.provider,
                strategy.style,
                strategy.ttl or "5m",
                strategy.reason,
            )

    if session_id and OPENROUTER_HOST in host and isinstance(messages, list):
        payload["session_id"] = sticky_session_id(messages)

    return payload
