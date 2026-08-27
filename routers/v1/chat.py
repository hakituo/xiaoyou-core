# -*- coding: utf-8 -*-
"""聊天核心（chat）域。

提供消息发送 / 重新生成、主动问候、角色配置查询等核心对话能力。
注意：生命状态 /status/life 已迁移至 life 域。
"""

import asyncio
import json
import logging
import time
import uuid
from collections import OrderedDict
from typing import Any, Dict, Optional

from core.utils.time_utils import get_current_time, now_iso

from fastapi import APIRouter, Body, Query
from fastapi.responses import StreamingResponse

from core.api.contract import error_response
from core.api.error_response import ErrorCode
from core.core_engine.config_manager import get_config_manager
from core.utils.async_locks import LazyAsyncLock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["聊天核心"])

MAX_CONVERSATION_ID_LENGTH = 64

config_manager = get_config_manager()

_http_request_cache_lock = LazyAsyncLock()
_http_request_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_http_request_cache_max_size = 1000


def get_aveline_service():
    from core.core_engine.service_singletons import (
        get_aveline_service as real_get_aveline_service,
    )
    return real_get_aveline_service()


async def _ensure_aveline_service(request_id: str = ""):
    aveline_service = get_aveline_service()
    if aveline_service is None:
        try:
            from core.core_engine.service_singletons import initialize_aveline_service
            aveline_service = await initialize_aveline_service()
        except Exception as e:
            logger.error(f"初始化Aveline服务失败: {e} 请求ID={request_id}")
    return aveline_service


def _extract_max_tokens(message: dict) -> int:
    max_tokens = 0
    try:
        if isinstance(message, dict):
            mt = message.get("max_tokens")
            if mt is not None:
                try:
                    max_tokens = int(mt)
                except (ValueError, TypeError):
                    pass
    except Exception:
        pass
    return max_tokens


def _extract_temperature(message: dict, default: float = 0.7) -> Optional[float]:
    try:
        if isinstance(message, dict):
            t = message.get("temperature")
            if t is not None:
                try:
                    return float(t)
                except (ValueError, TypeError):
                    pass
    except Exception:
        pass
    return None


def _resolve_max_tokens(raw_max_tokens: int) -> Optional[int]:
    cfg_max = config_manager.get("limits.max_tokens", 0)
    if not isinstance(cfg_max, int):
        cfg_max = 0
    if raw_max_tokens <= 0:
        raw_max_tokens = cfg_max if cfg_max > 0 else None
    return raw_max_tokens


def _fallback_http_cloud_model(settings, global_provider: str) -> str:
    """HTTP 聊天通道的全局云端模型兜底：从 model_routing 取默认模型。"""
    try:
        from config.model_config import get_default_chat_model
        default_model = get_default_chat_model()
        if default_model and default_model.startswith("cloud:"):
            return default_model
    except Exception:
        pass
    llm_model = getattr(settings.model.llm, "model", None)
    if llm_model:
        return f"cloud:{global_provider}:{llm_model}"
    return f"cloud:{global_provider}:deepseek-v4-pro"


def _build_response_data(response: dict, request_id: str, conversation_id: str, **extra) -> dict:
    if isinstance(response, str):
        response_text = response
        response = {}
    else:
        response_text = response.get("reply", response.get("response", ""))

    if not response_text:
        response_text = "（无回复内容）"

    data = {
        "status": "success",
        "response": response_text,
        "request_id": response.get("request_id", request_id),
        "timestamp": response.get("timestamp", time.time()),
        "message_id": response.get("message_id", str(uuid.uuid4())),
        "conversation_id": response.get("conversation_id", conversation_id),
    }
    data.update(extra)

    if not isinstance(response, str):
        for key in ("voice_id", "image_prompt", "image_base64", "image_path",
                     "audio_base64", "audio_path", "emotion", "tokens_used"):
            if key in response:
                data[key] = response[key]
        m_used = response.get("model")
        if m_used:
            data["model"] = m_used

    return data


@router.get("/persona", summary="获取当前角色配置")
async def get_persona():
    try:
        aveline_service = get_aveline_service()
        config = aveline_service.character_config
        return {
            "status": "success",
            "data": config,
            "timestamp": get_current_time().isoformat(),
        }
    except Exception as e:
        logger.error(f"获取角色配置失败: {str(e)}", exc_info=True)
        resp = error_response(
            ErrorCode.INTERNAL_ERROR,
            message="获取角色配置失败",
            details={"error_type": type(e).__name__},
        )
        resp["timestamp"] = get_current_time().isoformat()
        resp["retryable"] = True
        resp["retry_after_seconds"] = 5
        return resp


@router.get("/greeting", summary="生成主动问候")
async def get_greeting(
    conversation_id: Optional[str] = Query(None, description="会话ID"),
    user_name: Optional[str] = Query(None, description="用户名"),
):
    try:
        if conversation_id:
            conversation_id = str(conversation_id)[:MAX_CONVERSATION_ID_LENGTH]

        aveline_service = await _ensure_aveline_service()
        if not aveline_service:
            return error_response(
                ErrorCode.SERVICE_UNAVAILABLE,
                message="Service not ready",
                details={"greeting": "系统初始化中..."},
            )

        greeting = await aveline_service.generate_proactive_message(
            conversation_id=conversation_id,
            save_to_history=True,
            user_name=user_name,
        )

        return {
            "status": "success",
            "greeting": greeting,
            "timestamp": now_iso(),
        }
    except Exception as e:
        logger.error(f"获取问候失败: {str(e)}", exc_info=True)
        return error_response(
            ErrorCode.INTERNAL_ERROR, message=str(e), details={"greeting": "你好。"}
        )


@router.post("/message", summary="发送消息（核心对话）")
async def handle_message(
    message: Dict[str, Any] = Body(..., description="用户消息内容"),
    conversation_id: Optional[str] = Query(None, description="会话ID"),
    model: Optional[str] = Query(None, description="使用的模型"),
    voice_id: Optional[str] = Query(None, description="Voice ID"),
    stream: bool = Query(False, description="是否流式返回"),
    length: Optional[str] = Query(None, description="Response length preference"),
):
    request_id = str(uuid.uuid4())

    # 提取 persona_filename（用于按人设解析默认模型 + 跨平台共享 conversation_id 规范化）
    # 提前提取，使下方的模型同步逻辑能像 QQ 的 WebSocket 通道一样按人设自动选模型。
    persona_filename = message.get("persona_filename") or message.get("personaFilename")
    if isinstance(persona_filename, str):
        persona_filename = persona_filename.strip() or None

    # [Fix] Sync global model configuration for Mobile/HTTP requests
    try:
        from config.integrated_config import get_settings

        settings = get_settings()

        global_provider = settings.model.llm.provider
        should_override = False

        if not model:
            should_override = True
        else:
            is_client_cloud = str(model).startswith("cloud:")
            is_global_cloud = global_provider != "local"

            if is_global_cloud and not is_client_cloud:
                client_model_lower = str(model).lower().strip()
                if client_model_lower in ["default", "auto", ""]:
                    should_override = True
                    logger.info(
                        f"HTTP Chat: Override generic local request '{model}' with global cloud provider '{global_provider}'"
                    )
                else:
                    should_override = False
                    logger.info(
                        f"HTTP Chat: Respecting explicit local model request: {model}"
                    )

        if should_override:
            if global_provider == "local":
                if settings.model.text_path:
                    model = settings.model.text_path
                else:
                    model = "local"
            else:
                # 云端模型：优先按人设选模型（与 QQ 的 WS 通道 resolve_model_by_persona 对齐），
                # 让 App 端角色聊天像 QQ 一样按角色自动使用各自默认的模型。
                if persona_filename:
                    from core.interfaces.websocket.adapters.handlers.chat.model_pref import (
                        resolve_model_by_persona,
                    )
                    persona_model = resolve_model_by_persona(settings, persona_filename)
                    if persona_model:
                        model = persona_model
                        logger.info(
                            f"HTTP Chat: 按人设注入云端模型配置: {model} (persona={persona_filename})"
                        )
                    else:
                        _model = _fallback_http_cloud_model(
                            settings, global_provider
                        )
                        model = _model
                        logger.info(f"HTTP Chat: 注入全局云端模型配置: {model}")
                else:
                    _model = _fallback_http_cloud_model(settings, global_provider)
                    model = _model
                    logger.info(f"HTTP Chat: Injected global cloud model: {model}")
    except Exception as e:
        logger.warning(f"HTTP Chat: Failed to sync global model config: {e}")

    try:
        if not isinstance(stream, bool):
            stream = getattr(stream, "default", False)
            if not isinstance(stream, bool):
                stream = False

        if not isinstance(message, dict):
            resp = error_response(
                ErrorCode.INVALID_MESSAGE_FORMAT,
                message="消息格式无效，必须是JSON对象",
                request_id=request_id,
            )
            resp["timestamp"] = time.time()
            return resp

        client_request_id = message.get("request_id")
        if isinstance(client_request_id, str):
            client_request_id = client_request_id.strip()
            if 1 <= len(client_request_id) <= 128:
                request_id = client_request_id

        message_id = message.get("message_id")
        if isinstance(message_id, str):
            message_id = message_id.strip()
            if not (1 <= len(message_id) <= 128):
                message_id = None
        else:
            message_id = None

        content = ""
        for field in ["content", "message", "text"]:
            if field in message:
                content = str(message[field]).strip()
                break

        if not conversation_id and "conversation_id" in message:
            conversation_id = str(message["conversation_id"])

        user_name = message.get("user_name") or message.get("username")

        # persona_filename 已在函数开头提取（用于按人设解析默认模型），此处直接复用，
        # 客户端传过来后，后端用 shared__persona__{slug} 作为 cid，让同一 persona 跨平台共享历史

        length_preference = length
        if not length_preference and "length" in message:
            length_preference = str(message["length"])

        if not stream and "stream" in message:
            stream = bool(message["stream"])

        if not content or not isinstance(content, str):
            resp = error_response(
                ErrorCode.EMPTY_CONTENT,
                message="消息内容不能为空且必须是字符串",
                request_id=request_id,
            )
            resp["timestamp"] = time.time()
            return resp

        if len(content) > 10000:
            resp = error_response(
                ErrorCode.CONTENT_TOO_LARGE,
                message="消息内容过长，请减少内容后重试",
                request_id=request_id,
            )
            resp["timestamp"] = time.time()
            return resp

        history_override = None
        raw_history_override = message.get("history_override")
        if isinstance(raw_history_override, list):
            history_override = []
            for item in raw_history_override[-100:]:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "").strip().lower()
                item_content = str(item.get("content") or "").strip()
                if role in {"user", "assistant"} and item_content:
                    history_override.append(
                        {"role": role, "content": item_content[:10000]}
                    )

        # 跨平台共享 conversation_id 规范化：
        # 客户端传 persona_filename 时，用 shared__persona__{slug} 作为 cid
        # 没传则用客户端原始 conversation_id（兼容旧客户端）
        normalized_conversation_id = conversation_id or "default"
        if persona_filename:
            try:
                from core.utils.data_paths import build_shared_persona_conversation_id
                shared_cid = build_shared_persona_conversation_id(persona_filename)
                if shared_cid:
                    logger.info(
                        f"HTTP Chat: persona_filename={persona_filename} "
                        f"规范化 cid {conversation_id} -> {shared_cid}"
                    )
                    normalized_conversation_id = shared_cid
            except Exception as e:
                logger.warning(f"HTTP Chat: cid 规范化失败（继续用原值）: {e}")
        cache_key = f"{normalized_conversation_id}:{request_id}"
        if not stream:
            async with _http_request_cache_lock:
                cached = _http_request_cache.get(cache_key)
                if isinstance(cached, dict):
                    _http_request_cache.move_to_end(cache_key)
                    return cached

        logger.info(
            f"收到消息请求: 请求ID={request_id} 长度={len(content)} 会话ID={conversation_id or 'new'} Stream={stream}"
        )

        aveline_service = await _ensure_aveline_service(request_id)

        if aveline_service is None:
            logger.error(f"无法获取Aveline服务实例，请求ID={request_id}")
            resp = error_response(
                ErrorCode.SERVICE_UNAVAILABLE,
                message="核心服务暂时不可用，正在尝试恢复，请稍后重试",
                request_id=request_id,
            )
            resp["timestamp"] = time.time()
            return resp

        if stream:

            async def event_generator():
                try:
                    max_tokens_s = _resolve_max_tokens(_extract_max_tokens(message))
                    temperature_s = _extract_temperature(message) or 0.7

                    async for chunk in aveline_service.stream_conversation(
                        user_input=content,
                        conversation_id=normalized_conversation_id,
                        request_id=request_id,
                        message_id=message_id,
                        max_tokens=max_tokens_s,
                        temperature=temperature_s,
                        model_hint=model,
                        save_history=True,
                        user_name=user_name,
                        length_preference=length_preference,
                        persona_filename=persona_filename,
                        history_override=history_override,
                    ):
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                except Exception as e:
                    logger.error(f"Stream error: {e}")
                    err_resp = error_response(
                        ErrorCode.INTERNAL_ERROR,
                        message="流式响应出错，请稍后重试。",
                        request_id=request_id,
                    )
                    err_resp.update({"type": "error", "timestamp": time.time()})
                    yield f"data: {json.dumps(err_resp, ensure_ascii=False)}\n\n"

                yield "data: [DONE]\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")

        try:
            max_tokens_override = _resolve_max_tokens(_extract_max_tokens(message))
            temperature_override = _extract_temperature(message)

            task = asyncio.create_task(
                aveline_service.handle_conversation(
                    user_input=content,
                    conversation_id=normalized_conversation_id,
                    request_id=request_id,
                    message_id=message_id,
                    max_tokens=max_tokens_override,
                    temperature=(
                        temperature_override
                        if temperature_override is not None
                        else 0.7
                    ),
                    model_hint=model,
                    voice_id=voice_id,
                    save_history=True,
                    enable_auto_media=True,
                    user_name=user_name,
                    length_preference=length_preference,
                )
            )

            timeout_seconds = 300
            try:
                cfg_timeout = config_manager.get("limits.message_timeout")
                if cfg_timeout is not None:
                    timeout_seconds = int(cfg_timeout)
            except Exception:
                timeout_seconds = 300

            logger.info(
                f"开始处理消息任务，超时设置: {timeout_seconds}秒, request_id={request_id}"
            )
            start_time = time.time()
            try:
                response = await asyncio.wait_for(task, timeout=timeout_seconds)
                logger.info(
                    f"消息任务处理完成，耗时: {time.time() - start_time:.2f}秒, request_id={request_id}"
                )
            except asyncio.TimeoutError:
                logger.error(
                    f"消息任务超时，耗时: {time.time() - start_time:.2f}秒, request_id={request_id}"
                )
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                return {
                    "status": "success",
                    "response": "抱歉，我思考的时间有点久，请稍后再试或换个话题。",
                    "error": "Timeout",
                    "error_code": ErrorCode.TIMEOUT_ERROR.value,
                    "request_id": request_id,
                    "timestamp": time.time(),
                    "message_id": str(uuid.uuid4()),
                    "conversation_id": normalized_conversation_id,
                }
            except Exception as e:
                logger.error(f"消息任务执行异常: {e}", exc_info=True)
                resp = error_response(
                    ErrorCode.INTERNAL_ERROR,
                    message="处理消息时遇到错误，请稍后重试。",
                    request_id=request_id,
                    details={"error_type": type(e).__name__},
                )
                resp.update(
                    {
                        "timestamp": time.time(),
                        "message_id": str(uuid.uuid4()),
                        "conversation_id": normalized_conversation_id,
                    }
                )
                return resp

            response_data = _build_response_data(
                response, request_id, normalized_conversation_id
            )

            async with _http_request_cache_lock:
                _http_request_cache[cache_key] = response_data
                if len(_http_request_cache) > _http_request_cache_max_size:
                    _http_request_cache.popitem(last=False)

            return response_data

        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            logger.error(f"消息处理超时: 请求ID={request_id} 会话ID={conversation_id}")
            resp = error_response(
                ErrorCode.PROCESSING_TIMEOUT,
                message="消息处理超时，请稍后重试",
                request_id=request_id,
            )
            resp["timestamp"] = time.time()
            return resp

    except Exception as e:
        logger.error(f"处理消息时出错: 请求ID={request_id} {str(e)}", exc_info=True)
        resp = error_response(
            ErrorCode.INTERNAL_ERROR,
            message="服务器内部错误，请稍后重试",
            request_id=request_id,
            details={"error_type": type(e).__name__},
        )
        resp["timestamp"] = time.time()
        return resp


@router.post("/regenerate", summary="重新生成最后一条 AI 回复")
async def regenerate_message(
    message: Dict[str, Any] = Body(..., description="重新生成请求参数"),
    conversation_id: Optional[str] = Query(None, description="会话ID"),
    model: Optional[str] = Query(None, description="使用的模型"),
    stream: bool = Query(False, description="是否流式返回"),
):
    """重新生成最后一条AI回复消息。会先删除最后一条AI回复，再基于上下文重新生成。"""
    request_id = str(uuid.uuid4())

    try:
        if not conversation_id:
            conversation_id = message.get("conversation_id")

        if not conversation_id:
            resp = error_response(
                ErrorCode.MISSING_PARAMETER,
                message="缺少会话ID",
                request_id=request_id,
            )
            resp["timestamp"] = time.time()
            return resp

        normalized_conversation_id = str(conversation_id) or "default"

        logger.info(f"重新生成请求: 会话ID={normalized_conversation_id} 请求ID={request_id}")

        aveline_service = await _ensure_aveline_service(request_id)
        if aveline_service is None:
            resp = error_response(
                ErrorCode.SERVICE_UNAVAILABLE,
                message="核心服务暂时不可用",
                request_id=request_id,
            )
            resp["timestamp"] = time.time()
            return resp

        from memory.weighted_memory_manager import get_weighted_memory_manager
        mm = get_weighted_memory_manager(normalized_conversation_id)

        last_user_message = None
        last_ai_message_id = None

        with mm.lock:
            for msg in reversed(mm.short_term_memory):
                role = msg.get("role") or msg.get("source", "")
                if role == "assistant" and last_ai_message_id is None:
                    last_ai_message_id = msg.get("id") or msg.get("message_id")
                elif role == "user" and last_user_message is None:
                    last_user_message = msg.get("content")
                if last_ai_message_id and last_user_message:
                    break

        if not last_user_message:
            resp = error_response(
                ErrorCode.INVALID_REQUEST,
                message="没有找到可以重新生成的对话",
                request_id=request_id,
            )
            resp["timestamp"] = time.time()
            return resp

        if last_ai_message_id:
            deleted = mm.delete_message(last_ai_message_id)
            if deleted:
                logger.info(f"已删除最后一条AI回复: {last_ai_message_id}")
            else:
                logger.warning(f"删除AI回复失败: {last_ai_message_id}")

        user_input = last_user_message

        if stream:
            async def event_generator():
                try:
                    max_tokens_s = _resolve_max_tokens(_extract_max_tokens(message))

                    async for chunk in aveline_service.stream_conversation(
                        user_input=user_input,
                        conversation_id=normalized_conversation_id,
                        request_id=request_id,
                        max_tokens=max_tokens_s,
                        temperature=0.7,
                        model_hint=model,
                        save_history=True,
                    ):
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                except Exception as e:
                    logger.error(f"重新生成流式响应出错: {e}")
                    err_resp = error_response(
                        ErrorCode.INTERNAL_ERROR,
                        message="重新生成响应出错",
                        request_id=request_id,
                    )
                    err_resp.update({"type": "error", "timestamp": time.time()})
                    yield f"data: {json.dumps(err_resp, ensure_ascii=False)}\n\n"

                yield "data: [DONE]\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")

        try:
            max_tokens_override = _resolve_max_tokens(_extract_max_tokens(message))

            response = await asyncio.wait_for(
                aveline_service.handle_conversation(
                    user_input=user_input,
                    conversation_id=normalized_conversation_id,
                    request_id=request_id,
                    max_tokens=max_tokens_override,
                    temperature=0.7,
                    model_hint=model,
                    save_history=True,
                ),
                timeout=300,
            )

            response_data = _build_response_data(
                response, request_id, normalized_conversation_id,
                regenerated=True, deleted_message_id=last_ai_message_id,
            )

            return response_data

        except asyncio.TimeoutError:
            resp = error_response(
                ErrorCode.PROCESSING_TIMEOUT,
                message="重新生成超时，请稍后再试",
                request_id=request_id,
            )
            resp["timestamp"] = time.time()
            return resp

    except Exception as e:
        logger.error(f"重新生成消息时出错: {str(e)}", exc_info=True)
        resp = error_response(
            ErrorCode.INTERNAL_ERROR,
            message="重新生成消息失败",
            request_id=request_id,
            details={"error_type": type(e).__name__},
        )
        resp["timestamp"] = time.time()
        return resp
