from core.utils.logger import get_logger
import asyncio

import time
import uuid
import re
from typing import Any, AsyncGenerator, Dict, Optional

from config.debug_config import is_debug_enabled

logger = get_logger(__name__)

# 媒体标签正则（用于剥离 chunk 文本中的标签，避免前端显示 [MEME] 字样）
_MEDIA_TAG_STRIP_RE = re.compile(
    r"[\[［](?:MEME|IMG|BM|VOICE)(?:[：:][^\]］]*)?[\]］]",
    re.IGNORECASE,
)


async def stream_conversation_events(
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
    cid = service._normalize_conversation_id(conversation_id)
    mid = str(message_id or uuid.uuid4())
    rid = service._normalize_request_id(request_id, fallback=mid)
    cache_key = f"{cid}:{rid}"

    try:
        from core.services.life_simulation.service import get_life_simulation_service

        get_life_simulation_service().update_interaction()

        # Notify Active Care to reset wait time（Obsidian 等被动场景跳过）
        if not skip_active_care:
            try:
                from core.services.active_care.core.service import get_active_care_service

                active_care_service = get_active_care_service()
                try:
                    active_care_service.context.update_recent_user_message(
                        conversation_id=cid,
                        content=str(user_input or ""),
                        timestamp=time.time(),
                    )
                except Exception as cache_e:
                    if is_debug_enabled("aveline_stream"):
                        logger.info(f"Active Care recent user cache update failed: {cache_e}")

                await active_care_service.on_user_interaction(persona_filename=persona_filename)
            except Exception as e:
                logger.warning(f"Active Care on_user_interaction failed: {e}")

            # 更新用户交互时间戳（供提醒注入判断用户是否正在聊天）
            try:
                from core.services.active_care.shared.reminder_injection import get_reminder_injection_store
                get_reminder_injection_store().update_user_interaction()
            except Exception:
                pass

            # 标记用户活跃（供 PeerChatScheduler 感知）
            try:
                from core.services.active_care.peer_chat.peer_chat_scheduler import get_peer_chat_scheduler
                _pcs = get_peer_chat_scheduler()
                if _pcs:
                    _pcs.mark_user_activity(cid)
            except Exception:
                pass
    except Exception:
        pass

    if not hasattr(service, "_active_tasks_lock") or getattr(service, "_active_tasks_lock") is None:
        service._active_tasks_lock = asyncio.Lock()
    if not hasattr(service, "_active_tasks") or getattr(service, "_active_tasks") is None:
        service._active_tasks = {}

    current_task = asyncio.current_task()
    if current_task is not None:
        t_lock_start = time.time()
        async with service._active_tasks_lock:
            t_lock_acquired = time.time()
            prev_task = service._active_tasks.get(cid)
            if prev_task is not None and prev_task is not current_task and not prev_task.done():
                logger.info(f"stream_orchestrator: cancelling prev_task for cid={cid}")
                prev_task.cancel()
            service._active_tasks[cid] = current_task
        t_lock_wait = t_lock_acquired - t_lock_start
        if t_lock_wait > 1.0:
            logger.warning(f"stream_orchestrator: _active_tasks_lock wait={t_lock_wait:.2f}s for cid={cid}")

    try:
        t_cache_start = time.time()
        cached = await _get_cached_response(service, cache_key)
        t_cache_elapsed = time.time() - t_cache_start
        if t_cache_elapsed > 1.0:
            logger.warning(f"stream_orchestrator: cache lookup took {t_cache_elapsed:.2f}s for cid={cid}")
        if cached is not None:
            logger.info(f"stream_orchestrator: using cached response for cid={cid}")
            async for evt in _emit_cached_response(service, cached, cid, rid, mid):
                yield evt
            return

        collected = ""
        last_emotion = None
        done_sent = False
        start_time = time.time()
        first_token_time = None
        async for chunk in service.stream_generate_response(
            user_input=user_input,
            conversation_id=cid,
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
            if isinstance(chunk, dict) and (
                chunk.get("type") == "error" or chunk.get("status") == "error" or "error" in chunk
            ):
                if not done_sent:
                    async for evt in _emit_error_and_done(chunk, cid, rid, mid, last_emotion):
                        yield evt
                    done_sent = True
                return

            if isinstance(chunk, dict) and chunk.get("done"):
                final_content = str(chunk.get("content") or "")
                # 只有当 final_content 比 collected 更长时才计算 tail
                # 因为 stream_chat_impl 在 done 前会做清理（剥离时间戳、think标签等），
                # final_content 通常比 collected 短或相等，此时不应补发
                if final_content and len(final_content) > len(collected):
                    tail = _compute_done_tail(collected, final_content)
                    if tail:
                        collected += tail
                        clean_tail = _MEDIA_TAG_STRIP_RE.sub("", tail)
                        yield {
                            "type": "message",
                            "subtype": "response_chunk",
                            "content": clean_tail,
                            "timestamp": time.time(),
                            "message_id": mid,
                            "conversation_id": cid,
                            "request_id": rid,
                        }
                if not done_sent:
                    # 响应完成：解析累积文本里的 [MEME] 标签，选表情包推给前端
                    if collected.strip():
                        try:
                            async for evt in _emit_media_image_results(
                                service, collected, cid, rid, mid
                            ):
                                yield evt
                        except Exception as e:
                            logger.warning(f"媒体标签处理失败（不影响主流程）: {e}")
                    yield _build_done_event(
                        cid=cid,
                        rid=rid,
                        mid=mid,
                        last_emotion=last_emotion,
                        model_path=chunk.get("model_path"),
                        is_cloud=chunk.get("is_cloud"),
                        system_prompt=chunk.get("system_prompt"),
                        thought=chunk.get("thought"),
                    )
                    done_sent = True
                break

            if isinstance(chunk, dict) and chunk.get("type") and chunk.get("type") != "token":
                if chunk.get("type") == "emotion_update":
                    data = chunk.get("data", {})
                    if isinstance(data, dict):
                        last_emotion = data
                yield {
                    "type": chunk.get("type"),
                    "data": chunk.get("data", {}),
                    "timestamp": time.time(),
                    "message_id": mid,
                    "conversation_id": cid,
                    "request_id": rid,
                }
                continue

            if isinstance(chunk, dict):
                content_chunk = str(chunk.get("content") or "")
            else:
                content_chunk = str(chunk or "")

            if content_chunk:
                if first_token_time is None:
                    first_token_time = time.time()
                    ttft = first_token_time - start_time
                    try:
                        if service._resource_monitor:
                            service._resource_monitor.record_metric("llm_ttft", ttft, {"conversation_id": cid})
                    except Exception:
                        pass

                # collected 累积原文（含 [MEME] 标签，供响应结束时解析推送表情包）
                collected += content_chunk
                # 发送时剥离 [MEME]/[IMG]/[BM]/[VOICE] 标签，避免前端显示 "[MEME]" 字样
                clean_chunk = _MEDIA_TAG_STRIP_RE.sub("", content_chunk)
                yield {
                    "type": "message",
                    "subtype": "response_chunk",
                    "content": clean_chunk,
                    "timestamp": time.time(),
                    "message_id": mid,
                    "conversation_id": cid,
                    "request_id": rid,
                }

        if not done_sent:
            yield _build_done_event(cid=cid, rid=rid, mid=mid, last_emotion=last_emotion)

        if collected.strip():
            collected = re.sub(r"。\.{3,}", "......", collected)
            collected = re.sub(r"。…+", "……", collected)
            if not skip_active_care:
                try:
                    from core.services.active_care.core.service import get_active_care_service
                    await get_active_care_service().on_assistant_message_sent(timestamp=time.time())
                except Exception:
                    pass

        await _cache_stream_result(service, cache_key, collected, last_emotion, cid, rid, mid)
    finally:
        if current_task is not None:
            async with service._active_tasks_lock:
                if service._active_tasks.get(cid) is current_task:
                    del service._active_tasks[cid]


async def _get_cached_response(service: Any, cache_key: str) -> Optional[Dict[str, Any]]:
    if service._conversation_idempotency_cache is None:
        return None
    cached = await service._conversation_idempotency_cache.get(cache_key)
    if isinstance(cached, dict) and isinstance(cached.get("response"), str):
        return cached
    return None


async def _emit_media_image_results(
    service: Any,
    full_text: str,
    cid: str,
    rid: str,
    mid: str,
) -> AsyncGenerator[Dict[str, Any], None]:
    """响应完成后，解析 [MEME] 标签，选表情包并通过 image_result 事件推给前端。

    与 WebSocket 适配器的媒体标签处理逻辑一致（HTTP SSE 通道复用）：
    - 只处理普通表情包 [MEME]/[MEME:分类]，不承载敏感图库（[IMG]/[BM]）内容
    - 图片转 base64（限 1024x1024 JPEG）后作为 image_result 事件 yield，
      Android 端按现有 ImageResult 渲染逻辑展示
    """
    try:
        from clients.bots.qq.media_tags import (
            extract_media_segments,
            pick_meme_image,
        )
    except Exception as e:
        logger.debug(f"媒体标签模块不可用（无 QQ 适配器依赖）: {e}")
        return

    segments = extract_media_segments(full_text)
    if not segments:
        return

    has_media = any(seg.meme_categories for seg in segments)
    if not has_media:
        return

    logger.info(
        f"[media_tags] 处理响应中的媒体标签 cid={cid} segments={len(segments)}"
    )

    for seg in segments:
        for cat in seg.meme_categories:
            try:
                picked = await asyncio.to_thread(pick_meme_image, cat)
                if picked is None:
                    logger.info(f"表情包无候选图: cat={cat}")
                    continue
                data_url = await asyncio.to_thread(_encode_image_to_data_url, picked)
                if not data_url:
                    continue
                yield {
                    "type": "image_result",
                    "data": {
                        "success": True,
                        "source": "meme",
                        "image_url": data_url,
                        "thumbnail_base64": data_url,  # Android 端用同一份
                    },
                    "timestamp": time.time(),
                    "message_id": mid,
                    "conversation_id": cid,
                    "request_id": rid,
                }
                logger.info(f"[media_tags] 推送图片 source=meme cid={cid}")
            except Exception as e:
                logger.warning(f"表情处理失败 cat={cat}: {e}")


def _encode_image_to_data_url(image_path) -> Optional[str]:
    """把本地图片转 base64（限 1024x1024 JPEG），供 image_result 推送。"""
    import base64
    import io
    import os

    path_str = str(image_path)
    if not os.path.exists(path_str):
        logger.warning(f"媒体图片文件不存在: {path_str}")
        return None
    try:
        from PIL import Image

        with Image.open(path_str) as img:
            img.thumbnail((1024, 1024))
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG", quality=80)
            b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        logger.warning(f"图片转 base64 失败 path={path_str}: {e}")
        return None


async def _emit_cached_response(
    service: Any,
    cached: Dict[str, Any],
    cid: str,
    rid: str,
    mid: str,
) -> AsyncGenerator[Dict[str, Any], None]:
    cached_emotion = cached.get("emotion")
    cached_emotion_internal = cached.get("emotion_internal")
    if not cached_emotion:
        try:
            if service.chat_agent:
                service.chat_agent.emotion_manager.process_text(cid, str(cached.get("response") or ""))
                st = service.chat_agent.emotion_manager.get_effective_state(cid)
                if st and getattr(st, "primary_emotion", None):
                    cached_emotion = st.primary_emotion.value
                    cached_emotion_internal = getattr(st, "sub_emotions", None)
        except Exception:
            pass
    cached_response = str(cached.get("response", "") or "")
    # 发送时剥离 [MEME]/[IMG]/[BM]/[VOICE] 标签
    clean_response = _MEDIA_TAG_STRIP_RE.sub("", cached_response)
    yield {
        "type": "message",
        "subtype": "response_chunk",
        "content": clean_response,
        "timestamp": time.time(),
        "message_id": mid,
        "conversation_id": cid,
        "request_id": rid,
    }
    # 缓存命中时也解析 [MEME] 标签推送表情包
    if cached_response.strip():
        try:
            async for evt in _emit_media_image_results(
                service, cached_response, cid, rid, mid
            ):
                yield evt
        except Exception as e:
            logger.warning(f"媒体标签处理失败（不影响主流程）: {e}")
    yield {
        "type": "message",
        "subtype": "response_done",
        "timestamp": time.time(),
        "message_id": mid,
        "conversation_id": cid,
        "request_id": rid,
        "emotion": cached_emotion,
        "emotion_internal": cached_emotion_internal,
    }


async def _emit_error_and_done(
    chunk: Dict[str, Any],
    cid: str,
    rid: str,
    mid: str,
    last_emotion: Any,
) -> AsyncGenerator[Dict[str, Any], None]:
    err_code = str(chunk.get("error_code") or "SYSTEM_INTERNAL_ERROR")
    err_msg = str(chunk.get("message") or "").strip() or str(chunk.get("error") or "").strip() or "系统处理消息时遇到错误"
    err_details = chunk.get("details") if isinstance(chunk.get("details"), dict) else {}
    yield {
        "type": "error",
        "message": err_msg,
        "error": err_msg,
        "error_code": err_code,
        "details": err_details,
        "timestamp": time.time(),
        "message_id": mid,
        "conversation_id": cid,
        "request_id": rid,
    }
    yield _build_done_event(cid=cid, rid=rid, mid=mid, last_emotion=last_emotion)


def _strip_timestamps(text: str) -> str:
    """剥离 AI 输出中的时间戳前缀，如 [06-04 06:00]"""
    return re.sub(r"\[\d{2}-\d{2}\s+\d{2}:\d{2}\]\s*", "", str(text or ""))


def _normalize_overlap_text(text: str) -> str:
    raw = str(text or "")
    if not raw:
        return ""
    raw = _strip_timestamps(raw)
    raw = re.sub(r"\s+", "", raw)
    raw = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", raw)
    return raw


def _compute_done_tail(collected: str, final_content: str) -> str:
    final_text = str(final_content or "")
    if not final_text:
        return ""
    base = str(collected or "")
    if not base:
        return final_text
    # 先对两边都剥离时间戳后再比较，避免因时间戳导致误判差值
    base_stripped = _strip_timestamps(base)
    if final_text.startswith(base_stripped):
        return final_text[len(base_stripped):]
    if final_text == base_stripped or base_stripped.endswith(final_text):
        return ""
    if final_text.startswith(base):
        return final_text[len(base) :]
    if final_text in base or base.endswith(final_text):
        return ""
    norm_base = _normalize_overlap_text(base)
    norm_final = _normalize_overlap_text(final_text)
    if norm_final and norm_final in norm_base:
        return ""
    max_overlap = min(len(base), len(final_text))
    for k in range(max_overlap, 0, -1):
        if base.endswith(final_text[:k]):
            return final_text[k:]
    return final_text


def _build_done_event(
    *,
    cid: str,
    rid: str,
    mid: str,
    last_emotion: Any,
    model_path: Any = None,
    is_cloud: Any = None,
    system_prompt: Any = None,
    thought: Any = None,
) -> Dict[str, Any]:
    return {
        "type": "message",
        "subtype": "response_done",
        "timestamp": time.time(),
        "message_id": mid,
        "conversation_id": cid,
        "request_id": rid,
        "emotion": (last_emotion or {}).get("primary_emotion") if isinstance(last_emotion, dict) else None,
        "emotion_internal": (last_emotion or {}).get("sub_emotions") if isinstance(last_emotion, dict) else None,
        "model_path": model_path,
        "is_cloud": is_cloud,
        "system_prompt": system_prompt,
        "thought": thought,
    }


async def _cache_stream_result(
    service: Any,
    cache_key: str,
    collected: str,
    last_emotion: Any,
    cid: str,
    rid: str,
    mid: str,
) -> None:
    if not (service._conversation_idempotency_cache is not None and isinstance(collected, str) and collected):
        return
    try:
        await service._conversation_idempotency_cache.set(
            cache_key,
            {
                "status": "success",
                "response": collected,
                "emotion": (last_emotion or {}).get("primary_emotion") if isinstance(last_emotion, dict) else None,
                "emotion_internal": (last_emotion or {}).get("sub_emotions") if isinstance(last_emotion, dict) else None,
                "conversation_id": cid,
                "request_id": rid,
                "message_id": mid,
                "timestamp": time.time(),
            },
        )
    except Exception:
        pass
