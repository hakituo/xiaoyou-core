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
    r"[\[［](?:MEME|IMG|BM|VOICE|VIDEO)(?:[：:][^\]］]*)?[\]］]",
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
        # 媒体标签缓冲：还没发出去的尾部正文（可能含"半个标签"，等下一个 token 补全）。
        # 正文与媒体事件的下发顺序由它决定 —— 标签之前的话先发，图紧跟其后。
        pending_media = ""
        last_emotion = None
        done_sent = False
        start_time = time.time()
        first_token_time = None

        async def _flush_media_buffer(
            new_text: Optional[str] = None, *, final: bool = False
        ) -> list[Dict[str, Any]]:
            """把新到的正文追加进媒体缓冲，按标签位置切分后返回要下发的事件。"""
            nonlocal pending_media
            if new_text:
                pending_media += new_text
            events, pending_media = await _drain_media_stream(
                service, pending_media, cid, rid, mid, final=final
            )
            return events

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
                        for evt in await _flush_media_buffer(tail):
                            yield evt
                if not done_sent:
                    # 收尾：把缓冲里剩下的正文全部发出去（此后再不会插入媒体）
                    for evt in await _flush_media_buffer(final=True):
                        yield evt
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

                # collected 累积原文（含 [MEME] 标签，供缓存与收尾解析）
                collected += content_chunk
                # 按标签位置下发：标签之前的正文先发，图紧跟在那句话之后，
                # 标签之后的内容留给后续 chunk（实现"句中插图"，与 QQ 段感知发送一致）
                for evt in await _flush_media_buffer(content_chunk):
                    yield evt

        if not done_sent:
            # 流自然结束（没收到 done 标记）也要把缓冲里的正文吐出去
            for evt in await _flush_media_buffer(final=True):
                yield evt
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


def _chunk_event(content: str, cid: str, rid: str, mid: str) -> Dict[str, Any]:
    """构造一个正文 response_chunk 事件（字段与既有实现保持一致）。"""
    return {
        "type": "message",
        "subtype": "response_chunk",
        "content": content,
        "timestamp": time.time(),
        "message_id": mid,
        "conversation_id": cid,
        "request_id": rid,
    }


async def _build_image_result_event(
    service: Any,
    category: str,
    cid: str,
    rid: str,
    mid: str,
) -> Optional[Dict[str, Any]]:
    """选一张表情包并构造 image_result 事件；没有候选图/转换失败时返回 None。

    HTTP SSE 通道复用 WebSocket 适配器的媒体标签语义：
    - 只处理普通表情包 [MEME]/[MEME:分类]，不承载敏感图库（[IMG]/[BM]）内容
    - 优先下发静态 URL（体积小、保留 GIF 动图、前端可走 HTTP 缓存），
      转 URL 失败时回退到 base64 data URI（限 1024x1024 JPEG），保证图还能发出去
    """
    try:
        from clients.bots.qq.media_tags import meme_path_to_url, pick_meme_image
    except Exception as e:
        logger.debug(f"媒体标签模块不可用（无 QQ 适配器依赖）: {e}")
        return None

    try:
        picked = await asyncio.to_thread(pick_meme_image, category)
        if picked is None:
            logger.info(f"表情包无候选图: cat={category}")
            return None
        image_url = await asyncio.to_thread(meme_path_to_url, picked)
        if not image_url:
            image_url = await asyncio.to_thread(_encode_image_to_data_url, picked)
        if not image_url:
            return None
        logger.info(f"[media_tags] 推送图片 source=meme cid={cid}")
        return {
            "type": "image_result",
            "data": {
                "success": True,
                "source": "meme",
                "image_url": image_url,
            },
            "timestamp": time.time(),
            "message_id": mid,
            "conversation_id": cid,
            "request_id": rid,
        }
    except Exception as e:
        logger.warning(f"表情处理失败 cat={category}: {e}")
        return None


async def _build_video_result_events(
    service: Any,
    count: int,
    cid: str,
    rid: str,
    mid: str,
) -> list[Dict[str, Any]]:
    """选 count 个敏感视频并构造 video_result 事件（受 private_video_push_enabled 开关控制）。

    与 WebSocket 适配器行为一致，且共用 media_tags.private_video_push_enabled 这一个
    开关（默认开启，设 XIAOYOU_PUSH_PRIVATE_VIDEO=0 可关）。

    与图片不同，视频没有 base64 兜底——一段几十 MB 的视频塞进 SSE 事件既不现实
    也必然超时，拿不到静态 URL 就整条跳过。
    """
    try:
        from clients.bots.qq.media_tags import (
            pick_videos,
            private_video_push_enabled,
            video_path_to_url,
        )
    except Exception as e:
        logger.debug(f"媒体标签模块不可用（无 QQ 适配器依赖）: {e}")
        return []

    if not private_video_push_enabled():
        return []

    events: list[Dict[str, Any]] = []
    try:
        videos = await asyncio.to_thread(pick_videos, count)
        for video in videos:
            video_url = await asyncio.to_thread(video_path_to_url, video)
            if not video_url:
                logger.info(f"视频转静态 URL 失败，跳过: {video}")
                continue
            events.append({
                "type": "video_result",
                "data": {
                    "success": True,
                    "source": "video",
                    "video_url": video_url,
                },
                "timestamp": time.time(),
                "message_id": mid,
                "conversation_id": cid,
                "request_id": rid,
            })
            logger.info(f"[media_tags] 推送视频 source=video cid={cid}")
    except Exception as e:
        logger.warning(f"视频处理失败 count={count}: {e}")
    return events


async def _emit_tag_media(
    service: Any,
    tag_text: str,
    cid: str,
    rid: str,
    mid: str,
) -> list[Dict[str, Any]]:
    """把**单个**媒体标签解析成要下发的媒体事件。

    - [MEME]/[MEME:分类] → image_result（表情包）
    - [VIDEO]/[VIDEO:3]  → video_result（敏感视频，受开关控制）
    - [IMG]/[BM]/[VOICE] → 本通道不下发媒体，仅作文本剥离（与既有行为一致）

    标签参数怎么解析交给 media_tags.extract_media_segments：把单个标签喂进去，
    拿到的那一条 MediaSegment 就是它自己，避免在流式通道里再写一套解析。
    """
    try:
        from clients.bots.qq.media_tags import extract_media_segments
    except Exception as e:
        logger.debug(f"媒体标签模块不可用（无 QQ 适配器依赖）: {e}")
        return []

    segments = extract_media_segments(tag_text)
    if not segments:
        return []

    segment = segments[0]
    events: list[Dict[str, Any]] = []
    for category in segment.meme_categories:
        event = await _build_image_result_event(service, category, cid, rid, mid)
        if event:
            events.append(event)
    if segment.video_count:
        events.extend(
            await _build_video_result_events(service, segment.video_count, cid, rid, mid)
        )
    return events


async def _drain_media_stream(
    service: Any,
    buffer: str,
    cid: str,
    rid: str,
    mid: str,
    *,
    final: bool = False,
) -> tuple[list[Dict[str, Any]], str]:
    """把流式缓冲里已经闭合的媒体标签切出来，按"正文 → 图 → 正文 → 图"的顺序产出事件。

    这是"表情包按标签位置给"的实现：标签挂在哪句话末尾，图就紧跟在那句话之后下发，
    而不是等整段文字都发完再统一补发。人设提示词（persona_system/prompt/qq_integration.py）
    对模型的承诺就是前者——「图片在它所在那句话之后立即发出（不是全部文字发完才补图），
    所以可以在任意句末插入标签，实现句中插图的效果」；QQ 端的段感知发送
    （clients/bots/qq/session/message.py）也是这么兑现的。

    切分本身由 media_tags.split_stream_media_tags 负责（它还会把"半个标签"留在
    缓冲里等下一个 token），这里只负责把切出来的东西变成事件。

    Returns:
        (events, pending)：events 是要下发的事件；pending 是还不能下发的尾巴。
    """
    try:
        from clients.bots.qq.media_tags import split_stream_media_tags
    except Exception as e:
        # 媒体模块不可用时退化成"照原样发正文"，绝不能把回复吞掉
        logger.debug(f"媒体标签模块不可用（无 QQ 适配器依赖）: {e}")
        if not buffer:
            return [], ""
        if final:
            return [_chunk_event(buffer, cid, rid, mid)], ""
        return [_chunk_event(buffer, cid, rid, mid)], ""

    pieces, pending = split_stream_media_tags(buffer, final=final)
    events: list[Dict[str, Any]] = []
    for text, tag in pieces:
        if text:
            # 收尾时再兜底剥一次：模型偶尔吐出畸形标签（如参数里有换行），
            # 正常路径下 split_stream_media_tags 已经切干净，这里是最后一道保险
            events.append(_chunk_event(_MEDIA_TAG_STRIP_RE.sub("", text) if final else text, cid, rid, mid))
        if tag:
            events.extend(await _emit_tag_media(service, tag, cid, rid, mid))
    return events, pending


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
    # 缓存回放同样按标签位置切分（"图在它那句话之后"），与实时流式路径表现一致；
    # 这里整段文本一次性喂进去，final=True 表示没有后续内容了
    cached_events, _ = await _drain_media_stream(
        service, cached_response, cid, rid, mid, final=True
    )
    for evt in cached_events:
        yield evt
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
