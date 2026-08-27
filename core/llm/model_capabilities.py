#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 模型能力检测模块

提供统一的"模型是否支持视觉(多模态)"判断,供所有 LLM 客户端复用。

设计原则:
- 模型名模糊匹配(子串匹配),兼容 `kimi-k3` / `Pro/moonshotai/Kimi-K2.6` / `Qwen/Qwen3-VL-32B-Instruct` 等带前缀的路径
- 名单集中维护,新增多模态模型只需改一处
- 大小写不敏感
"""

from __future__ import annotations

from typing import Iterable

from core.utils.logger import get_logger

logger = get_logger("model_capabilities")


# 支持视觉(图片输入)的模型关键词名单
# 命中任一关键词(子串、忽略大小写)即视为多模态模型
# 维护规则:
#   - 关键词尽量短而通用,覆盖一个模型家族
#   - 纯文本模型(如 deepseek-v4-flash / qwen3-max / minimax-m2.5)不要写进来
#   - 不确定时不写,让纯文本路径兜底(更安全)
VISION_MODEL_KEYWORDS: tuple[str, ...] = (
    # ===== Qwen 系列 =====
    "qwen2-vl",
    "qwen2.5-vl",
    "qwen3-vl",
    "qwen-vl",
    "qvq",  # QVQ 思考型视觉模型
    # ===== Kimi 系列(Moonshot) =====
    "kimi-k3",        # K3 自带视觉
    "kimi-k2.6",      # K2.6 自带视觉
    "kimi-k2.7",      # K2.7 Code 自带视觉
    # ===== 智谱 GLM 系列 =====
    "glm-4.6v",
    "glm-4.5v",
    "glm-5v",
    "glm-6v",
    # ===== Doubao / Ark 系列 =====
    "doubao-vision",
    "doubao-1.5-vision",
    # ===== MiniMax 系列 =====
    "minimax-vl",
    "abab-vl",
    # ===== OpenAI / 兼容厂商 =====
    "gpt-4o",         # gpt-4o / gpt-4o-mini
    "gpt-4-vision",
    "gpt-4-turbo",    # 多模态版
    "gpt-5",          # 假设 GPT-5 默认多模态
    # ===== DeepSeek(若未来支持) =====
    "deepseek-vl",
    # ===== SiliconFlow 平台托管的视觉模型 =====
    # 注:SiliconFlow 上的非视觉模型(如 Pro/moonshotai/Kimi-K2.6 也会命中上面的 kimi-k2.6)
    # 所以这里不重复加 SiliconFlow 路径前缀
)


def is_vision_model(model_name: str) -> bool:
    """判断给定模型名是否支持视觉(图片输入)

    Args:
        model_name: 模型名,可能是纯名(`kimi-k3`)、带前缀路径(`Pro/moonshotai/Kimi-K2.6`)
                    或带 cloud: 协议头(`cloud:siliconflow:Qwen/Qwen3-VL-32B-Instruct`)

    Returns:
        True 表示该模型支持图片输入,可直接走一阶段多模态路径
        False 表示纯文本模型,图片需先经 VL 模型描述
    """
    if not model_name:
        return False

    # 去掉 cloud:provider:key_alias:model 这种 4 段协议头的协议部分,
    # 只保留最后的 model 部分(可能含厂商路径前缀如 "Pro/moonshotai/Kimi-K2.6")
    raw = str(model_name).strip()
    if raw.startswith("cloud:"):
        parts = raw.split(":", 3)
        if len(parts) == 4:
            raw = parts[3]
        elif len(parts) == 3:
            raw = parts[2]

    # 取最后一段(/后的部分)和完整名一起做匹配,
    # 例如 "Pro/moonshotai/Kimi-K2.6" 同时匹配 "Pro/moonshotai/Kimi-K2.6" 和 "Kimi-K2.6"
    candidates = [raw.lower()]
    if "/" in raw:
        candidates.append(raw.rsplit("/", 1)[-1].lower())

    for keyword in VISION_MODEL_KEYWORDS:
        kw = keyword.lower()
        for cand in candidates:
            if kw in cand:
                return True

    return False


def has_image_content(messages: Iterable) -> bool:
    """检测消息列表中是否包含图片内容(OpenAI 多模态格式)

    用于决定是否触发视觉路由。检测两种格式:
    - 标准 OpenAI 多模态:content 为 list,含 {"type": "image_url", ...}
    - 兜底:content 字符串里含 "data:image"(部分上游会直接塞 base64 文本)

    Args:
        messages: 消息列表

    Returns:
        True 表示消息含图片
    """
    if not messages:
        return False

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    return True
        elif isinstance(content, str) and "data:image" in content:
            return True
    return False


def describe_routing(model_name: str, has_image: bool) -> str:
    """生成路由决策的可读描述(用于日志/调试)"""
    if not has_image:
        return "纯文本路径(无图片)"
    if is_vision_model(model_name):
        return f"一阶段多模态路径(主模型 {model_name} 自带视觉)"
    return f"两阶段中转路径(主模型 {model_name} 纯文本,先经 VL 模型描述图片)"
