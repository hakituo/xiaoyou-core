#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视觉路由模块

从 client.py 拆出，负责纯文本主模型 + 图片消息的两阶段路由：
先用 VL 模型把图片描述成文字，替换进消息，再发给纯文本主模型。

多模态主模型自带视觉，不需要走此模块，直接一阶段原样发送。
"""

from typing import Any, List, Optional, Tuple

from core.utils.logger import get_logger

from ..model_capabilities import (
    is_vision_model,
    has_image_content,
    describe_routing,
)

logger = get_logger("openai_client")


async def describe_images_via_vl(
    messages: list,
    vision_model: str,
    vision_base_url: str,
    default_model: str,
    get_session_fn: Any,
) -> Optional[list]:
    """用 VL 模型把消息里的图片描述成文字，返回替换后的新消息列表

    仅当主模型是纯文本 + 消息含图片时调用。
    保留 system / assistant 等非图片消息原样，只把 user 消息里的 image_url 替换为文字描述。

    Args:
        messages: 原始消息列表（OpenAI 多模态格式）
        vision_model: VL 中转模型名
        vision_base_url: VL 中转 API 端点
        default_model: 主模型名（用于日志）
        get_session_fn: async callable，返回 aiohttp.ClientSession

    Returns:
        替换后的消息列表；若 VL 未配置返回 None，由调用方决定是否回退原消息
    """
    if not vision_model:
        logger.warning(
            "主模型 %s 是纯文本但未配置 vision_model，无法走 VL 中转，原样发给主模型(可能报错)",
            default_model,
        )
        return None

    vl_messages: list = []
    image_descriptions: List[str] = []
    vl_prompt = "请详细描述这张图片的内容，包括场景、人物、动作、文字、色彩氛围等。描述要自然，像你在亲眼看到这张图一样。"

    for msg in messages:
        if not isinstance(msg, dict):
            vl_messages.append(msg)
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            vl_messages.append(msg)
            continue
        # 提取图片项，保留文本项
        text_parts: List[str] = []
        image_items: List[dict] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "image_url":
                    image_items.append(item)
                elif item.get("type") == "text" and item.get("text"):
                    text_parts.append(str(item["text"]))
        if not image_items:
            vl_messages.append(msg)
            continue
        # 给每张图片单独调一次 VL 模型
        for idx, img_item in enumerate(image_items):
            vl_payload_msg = {
                "role": "user",
                "content": [
                    {"type": "text", "text": vl_prompt},
                    img_item,
                ],
            }
            payload = {
                "model": vision_model,
                "messages": [vl_payload_msg],
                "stream": False,
                "max_tokens": 1024,
                "temperature": 0.5,
            }
            try:
                session = await get_session_fn()
                async with session.post(vision_base_url, json=payload) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        logger.error(
                            "VL 中转调用失败 status=%d model=%s err=%s",
                            resp.status, vision_model, err_text[:200],
                        )
                        image_descriptions.append(f"[图片{idx+1}描述失败]")
                        continue
                    data = await resp.json()
                    choices = data.get("choices") or []
                    if choices:
                        desc = ((choices[0] or {}).get("message") or {}).get("content") or ""
                        desc = str(desc).strip()
                        if desc:
                            image_descriptions.append(desc)
                            continue
                    image_descriptions.append(f"[图片{idx+1}描述为空]")
            except Exception as e:
                logger.error("VL 中转异常: %s", e)
                image_descriptions.append(f"[图片{idx+1}描述异常]")

        # 把图片描述拼回原消息（替换 image_url，保留原文本）
        new_content_parts: List[dict] = []
        if text_parts:
            new_content_parts.append({"type": "text", "text": "\n".join(text_parts)})
        img_desc_text = "【你看到了一张图片:" + "\n".join(image_descriptions) + "】"
        new_content_parts.append({"type": "text", "text": img_desc_text})
        vl_messages.append({"role": msg.get("role", "user"), "content": new_content_parts})

    return vl_messages


async def route_vision_if_needed(
    messages: list,
    model_name: str,
    vision_model: str,
    vision_base_url: str,
    get_session_fn: Any,
) -> Tuple[list, str]:
    """视觉路由前置处理

    Returns:
        (processed_messages, route_desc)
        - processed_messages: 路由后的消息（可能原样、可能已替换图片为文字）
        - route_desc: 路由决策描述，用于日志
    """
    has_img = has_image_content(messages)
    route_desc = describe_routing(model_name, has_img)

    if not has_img:
        return messages, route_desc

    if is_vision_model(model_name):
        # 多模态主模型：原样发送（一阶段）
        logger.info("视觉路由:一阶段多模态，model=%s", model_name)
        return messages, route_desc

    # 纯文本主模型 + 含图片：走 VL 中转（两阶段）
    logger.info("视觉路由:两阶段中转，主模型=%s 纯文本，先用 VL 模型描述图片", model_name)
    replaced = await describe_images_via_vl(
        messages, vision_model, vision_base_url, model_name, get_session_fn
    )
    if replaced is None:
        return messages, route_desc + "(VL 未配置，回退原消息)"
    return replaced, route_desc
