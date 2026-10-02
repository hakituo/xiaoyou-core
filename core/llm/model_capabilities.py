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
#   - 模型名不带 vl 字样也可能是原生多模态(如 deepseek-v4-flash/pro),确认后按型号写进来
#   - 纯文本模型(如 qwen3-max / minimax-m2.5 / deepseek-v3.2)不要写进来
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
    "minimax-m3",       # MiniMax M3 原生多模态(文本+图片输入),发图走一阶段直通,不触发 VL 中转
    "minimax-m3:free",  # OpenRouter 托管的免费 M3 同样是多模态
    # ===== OpenAI / 兼容厂商 =====
    "gpt-4o",         # gpt-4o / gpt-4o-mini
    "gpt-4-vision",
    "gpt-4-turbo",    # 多模态版
    "gpt-5",          # 假设 GPT-5 默认多模态
    # ===== DeepSeek 系列 =====
    # v4 flash/pro 已升级为原生多模态,虽不带 vl 字样也按型号列入
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "deepseek-vl",
    # ===== OpenRouter 托管的多模态模型 =====
    # 命中后消息含图片会走一阶段直通(自带视觉),不再经 VL 模型描述
    "muse",              # meta/muse-* 家族(muse-spark-1.3-contributor 等)原生多模态
    "gemini-3.5-flash",  # google/gemini-3.5-flash
    "gemini-3.8-flash",  # google/gemini-3.8-flash
    "grok-4.20",         # x-ai/grok-4.20(含 -multi-agent 变体),text+image+file 输入
    # ===== SiliconFlow 平台托管的视觉模型 =====
    # 注:SiliconFlow 上的非视觉模型(如 Pro/moonshotai/Kimi-K2.6 也会命中上面的 kimi-k2.6)
    # 所以这里不重复加 SiliconFlow 路径前缀
    "claude-opus-4.6",
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

    # 去掉 cloud: 协议头与 provider 段,保留完整 model 路径。
    # 注意:OpenRouter 免费模型形如 cloud:openrouter:minimax/minimax-m3:free,
    # 模型名本身含冒号(:free 后缀),不能用固定 4 段切分,否则会把模型名截断为 "free"。
    # 故只去掉 "cloud:" 头与 provider 段,保留其后全部内容(可能含 key_alias 与 :free 后缀)。
    raw = str(model_name).strip()
    if raw.startswith("cloud:"):
        rest = raw[len("cloud:"):]
        segs = rest.split(":", 1)  # 仅去掉 provider 段
        raw = segs[1] if len(segs) == 2 else rest

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
