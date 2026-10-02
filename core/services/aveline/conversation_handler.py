#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
会话入口与状态管理模块。

负责会话级别的入口编排与状态管理：
- handle_conversation：非流式会话主入口（幂等缓存 + inflight 锁 + 媒体增强）
- normalize_conversation_id：规范化会话 ID（纯函数）
- normalize_request_id：规范化请求 ID（纯函数）
- get_inflight_lock：获取会话级 inflight 锁

带 service 参数的函数为模块级函数，第一参数为 `service`（AvelineService 实例），
与 stream_orchestrator.py 风格保持一致。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, Optional


def normalize_conversation_id(conversation_id: Optional[str]) -> str:
    cid = str(conversation_id or "").strip()
    return cid if cid else "default"


def normalize_request_id(request_id: Optional[str], fallback: str) -> str:
    rid = str(request_id or "").strip()
    return rid if rid else fallback


async def get_inflight_lock(service: Any, cache_key: str) -> asyncio.Lock:
    async with service._conversation_inflight_lock:
        lock = service._conversation_inflight.get(cache_key)
        if lock is None:
            lock = asyncio.Lock()
            service._conversation_inflight[cache_key] = lock
        return lock


async def handle_conversation(
    service: Any,
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
    cid = normalize_conversation_id(conversation_id)
    mid = str(message_id or uuid.uuid4())
    rid = normalize_request_id(request_id, fallback=mid)
    cache_key = f"{cid}:{rid}"

    requested_voice_id = voice_id
    allow_model_voice_tag = False
    try:
        from core.core_engine.config_manager import get_config_manager

        allow_model_voice_tag = bool(
            get_config_manager().get("voice.allow_model_voice_tag", False)
        )
    except Exception:
        allow_model_voice_tag = False

    if service._conversation_idempotency_cache is not None:
        cached = await service._conversation_idempotency_cache.get(cache_key)
        if isinstance(cached, dict):
            return dict(cached)

    lock = await get_inflight_lock(service, cache_key)
    try:
        async with lock:
            if service._conversation_idempotency_cache is not None:
                cached = await service._conversation_idempotency_cache.get(cache_key)
                if isinstance(cached, dict):
                    return dict(cached)

            response_text, metadata = await service.generate_response(
                user_input=user_input,
                conversation_id=cid,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                model_hint=model_hint,
                save_history=save_history,
                user_name=user_name,
                length_preference=length_preference,
            )

            effective_voice_id = requested_voice_id
            if allow_model_voice_tag:
                effective_voice_id = metadata.get("voice_id") or requested_voice_id

            result: Dict[str, Any] = {
                "status": "success",
                "response": response_text,
                "conversation_id": cid,
                "request_id": rid,
                "message_id": mid,
                "timestamp": time.time(),
                "model": metadata.get("model") or model_hint,
                "tokens_used": metadata.get("tokens_used"),
                "emotion": metadata.get("emotion"),
                "voice_id": effective_voice_id,
                "image_prompt": metadata.get("image_prompt"),
                "message_type": metadata.get("message_type"),
            }
            result = {k: v for k, v in result.items() if v is not None}

            if enable_auto_media:
                from core.services.aveline.response_media import enrich_result_with_auto_media
                result = await enrich_result_with_auto_media(
                    service=service,
                    result=result,
                    metadata=metadata,
                    response_text=response_text,
                    voice_id=voice_id,
                    conversation_id=cid,
                )

            if service._conversation_idempotency_cache is not None:
                try:
                    await service._conversation_idempotency_cache.set(
                        cache_key, dict(result)
                    )
                except Exception:
                    pass
            return result
    finally:
        # 清理已完成的 inflight 锁，避免 _conversation_inflight 字典无限增长
        async with service._conversation_inflight_lock:
            if not lock.locked():
                service._conversation_inflight.pop(cache_key, None)
