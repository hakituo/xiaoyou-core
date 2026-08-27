# -*- coding: utf-8 -*-
"""OpenAI 兼容层。

提供与 OpenAI Chat Completions API 一致的接口，方便第三方工具 / SDK 直接接入。
保留标准 /v1/chat/completions 路径，独立挂在顶层，不纳入 /api/v1 业务前缀。
"""

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(prefix="/v1", tags=["OpenAI兼容"])


def _build_chat_completion(model: str, content: str) -> Dict[str, Any]:
    now = int(time.time())
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": now,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def _build_model_item(
    model_id: str,
    owned_by: str,
    *,
    display_name: str | None = None,
) -> Dict[str, Any]:
    item = {
        "id": model_id,
        "object": "model",
        "owned_by": owned_by,
    }
    if display_name and display_name != model_id:
        item["display_name"] = display_name
    return item


def _build_models_response(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "object": "list",
        "data": items,
    }


def _build_embeddings_response(
    model: str,
    vectors: List[List[float]],
) -> Dict[str, Any]:
    data = []
    for index, vector in enumerate(vectors):
        data.append(
            {
                "object": "embedding",
                "index": index,
                "embedding": vector,
            }
        )
    return {
        "object": "list",
        "data": data,
        "model": model,
        "usage": {
            "prompt_tokens": 0,
            "total_tokens": 0,
        },
    }


def _extract_cloud_model_id(model_path: str) -> str:
    parts = str(model_path or "").split(":")
    if len(parts) >= 4:
        return ":".join(parts[3:])
    if len(parts) >= 3:
        return ":".join(parts[2:])
    return str(model_path or "")


def _list_persona_models() -> List[Dict[str, Any]]:
    """扫描 character/configs 目录，为每个人设文件生成 persona: 虚拟模型。

    model_id 格式：persona:<相对路径不含.json>
    例如：persona:core_aveline、persona:qq/Aveline_QQ_Master、persona:sensitive/Ling_love
    调用时端点会自动补 .json 后缀并走 AvelineService.stream_conversation 完整人设流程。
    """
    import os

    configs_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "core", "character", "configs",
    )
    if not os.path.isdir(configs_dir):
        return []

    # 白名单：只暴露这些人设目录/文件，排除 playsets/reference_examples/evolution/extra 等非人设 json
    allowed_subdirs = {"qq", "sensitive", "study", "sfw"}
    # 非人设文件名黑名单（即使白名单目录内的也不暴露）
    excluded_filenames = {"playsets.json", "reference_examples.json"}
    items: List[Dict[str, Any]] = []

    for root, dirs, files in os.walk(configs_dir):
        rel_root = os.path.relpath(root, configs_dir).replace("\\", "/")
        for fname in sorted(files):
            if not fname.endswith(".json"):
                continue
            if fname in excluded_filenames:
                continue
            rel_path = f"{rel_root}/{fname}" if rel_root != "." else fname
            # 根目录只暴露 core_*.json
            if rel_root == ".":
                if not fname.startswith("core_"):
                    continue
            else:
                top_dir = rel_root.split("/")[0]
                if top_dir not in allowed_subdirs:
                    continue
            # model_id = persona:<相对路径不含.json>
            persona_id = "persona:" + rel_path[:-5]  # 去掉 .json
            display_name = fname[:-5]  # 显示名用文件名（不含后缀）
            items.append(
                _build_model_item(
                    persona_id,
                    "persona",
                    display_name=display_name,
                )
            )
    return items


def _list_openai_compat_models() -> List[Dict[str, Any]]:
    from config.integrated_config import get_settings
    from core.core_engine.model_manager import get_model_manager

    settings = get_settings()
    manager = get_model_manager()

    current_provider = str(settings.model.llm.provider or "local").strip().lower() or "local"
    current_model = str(settings.model.llm.model or "").strip()

    items: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    for info in manager.list_models(model_type="llm"):
        model_path = str(info.get("path") or "").strip()
        display_name = str(info.get("name") or info.get("id") or "").strip()

        if model_path.startswith("cloud:"):
            parts = model_path.split(":")
            provider = parts[1].strip().lower() if len(parts) >= 2 else ""
            if provider != current_provider:
                continue
            model_id = _extract_cloud_model_id(model_path).strip()
            owned_by = provider or "cloud"
        else:
            if current_provider != "local":
                continue
            model_id = display_name or model_path
            owned_by = "local"

        if not model_id or model_id in seen_ids:
            continue

        seen_ids.add(model_id)
        items.append(
            _build_model_item(
                model_id,
                owned_by,
                display_name=display_name or None,
            )
        )

    if current_model and current_model not in seen_ids:
        items.insert(
            0,
            _build_model_item(
                current_model,
                current_provider,
                display_name=current_model,
            ),
        )

    # 追加 persona 虚拟模型（走完整人设/记忆流程）
    items.extend(_list_persona_models())

    return items


def _resolve_openai_compat_model_path(model_id: str) -> str | None:
    """将 OpenAI 兼容层传入的裸模型名映射回内部真实模型路径。"""
    from config.integrated_config import get_settings
    from core.core_engine.model_manager import get_model_manager

    normalized_model_id = str(model_id or "").strip()
    if not normalized_model_id:
        return None

    settings = get_settings()
    manager = get_model_manager()
    current_provider = str(settings.model.llm.provider or "local").strip().lower() or "local"

    for info in manager.list_models(model_type="llm"):
        model_path = str(info.get("path") or "").strip()
        display_name = str(info.get("name") or info.get("id") or "").strip()
        info_id = str(info.get("id") or "").strip()

        if current_provider == "local":
            if normalized_model_id in {model_path, display_name, info_id} and model_path:
                return model_path
            continue

        if not model_path.startswith("cloud:"):
            continue

        parts = model_path.split(":")
        provider = parts[1].strip().lower() if len(parts) >= 2 else ""
        if provider != current_provider:
            continue

        extracted_model_id = _extract_cloud_model_id(model_path).strip()
        if normalized_model_id == extracted_model_id:
            return model_path

    if current_provider == "local":
        return None

    return f"cloud:{current_provider}:{normalized_model_id}"


def _build_chunk(model: str, delta_content: str, finish_reason: str | None = None) -> str:
    chunk = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": delta_content} if delta_content else {},
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


@router.get("/models", summary="OpenAI 兼容的模型列表接口")
async def list_models():
    items = _list_openai_compat_models()
    return _build_models_response(items)


@router.post("/embeddings", summary="OpenAI 兼容的向量嵌入接口")
async def create_embeddings(payload: Dict[str, Any] = Body(...)):
    model = str(payload.get("model") or "").strip() or "text-embedding-3-small"
    raw_input = payload.get("input")

    if isinstance(raw_input, str):
        inputs = [raw_input]
    elif isinstance(raw_input, list) and all(isinstance(item, str) for item in raw_input):
        inputs = raw_input
    else:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "input 必须是字符串或字符串列表"},
        )

    from memory.embedding_generator import get_embedding_generator

    generator = get_embedding_generator()
    vectors_np = await asyncio.to_thread(generator.generate_embeddings_batch, inputs)
    vectors = [vector.astype("float32").tolist() for vector in vectors_np]
    return _build_embeddings_response(model, vectors)


@router.post("/chat/completions", summary="OpenAI 兼容的对话补全接口")
async def chat_completions(payload: Dict[str, Any] = Body(...)):
    model = payload.get("model")
    messages = payload.get("messages")
    stream = bool(payload.get("stream", False))
    if not isinstance(model, str) or not model.strip():
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "model 不能为空"},
        )
    if not isinstance(messages, list) or not messages:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "messages 不能为空"},
        )

    # persona 模式：model 以 "persona:" 开头时走完整人设/记忆流程
    if model.startswith("persona:"):
        return await _handle_persona_chat(model, messages, payload, stream)

    kwargs: Dict[str, Any] = {"model": model}
    model_path = _resolve_openai_compat_model_path(model)
    if model_path:
        kwargs["model_path"] = model_path
    for key in [
        "max_tokens",
        "temperature",
        "top_p",
        "repetition_penalty",
        "frequency_penalty",
        "presence_penalty",
        "stop",
    ]:
        if key in payload:
            kwargs[key] = payload[key]

    from core.llm import get_llm_module
    llm = get_llm_module()

    if stream:
        return StreamingResponse(
            _stream_chat(llm, messages, model, kwargs),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    result = await llm.chat(messages, **kwargs)
    if isinstance(result, str) and result.strip().startswith("Error:"):
        return JSONResponse(
            status_code=502,
            content={"success": False, "error": result},
        )

    return _build_chat_completion(model, str(result))


def _extract_persona_filename(model: str) -> str:
    """从 model 字段提取 persona_filename（补回 .json 后缀）。

    支持两种格式：
      persona:qq/Aveline_QQ_Master
      persona:qq/Aveline_QQ_Master:user=private_xxx__persona__aveline

    输出：qq/Aveline_QQ_Master.json
    """
    persona_path = model[len("persona:"):]
    # 剥离 :user=xxx 后缀
    if ":user=" in persona_path:
        persona_path = persona_path.split(":user=", 1)[0]
    if not persona_path.endswith(".json"):
        persona_path += ".json"
    return persona_path


def _extract_conversation_id_from_model(model: str) -> str | None:
    """从 model 字段提取可选的 conversation_id（用于跨端共享记忆）。

    格式：persona:xxx:user=<conversation_id>
    返回 None 表示未指定，由调用方走默认逻辑。
    """
    if ":user=" not in model:
        return None
    return model.split(":user=", 1)[1].strip() or None


def _extract_last_user_message(messages: List[Dict[str, Any]]) -> str:
    """从 messages 提取最后一条 user 消息的文本内容。"""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            # OpenAI 多模态格式，拼接所有 text 部分
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
            if parts:
                return "\n".join(parts)
    return ""


async def _handle_persona_chat(
    model: str,
    messages: List[Dict[str, Any]],
    payload: Dict[str, Any],
    stream: bool,
):
    """走完整人设/记忆流程的对话处理。

    复用 AvelineService.stream_conversation，享受人设加载、记忆注入、
    system prompt 构建、模型路由等完整能力。
    """
    persona_filename = _extract_persona_filename(model)
    user_input = _extract_last_user_message(messages)
    if not user_input:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "messages 中没有 user 消息"},
        )

    # conversation_id 用作 user_id，影响记忆隔离；优先级：
    # 1. model 里 :user=xxx 后缀（用于跨端共享记忆，如 Obsidian 接 QQ 的会话）
    # 2. payload.user / payload.user_name
    # 3. 默认 "obsidian_user"
    conversation_id = (
        _extract_conversation_id_from_model(model)
        or str(payload.get("user") or payload.get("user_name") or "")
        or "obsidian_user"
    )
    user_name = str(payload.get("user_name") or "")
    max_tokens = payload.get("max_tokens")
    temperature = float(payload.get("temperature", 0.7))

    try:
        from core.core_engine.service_singletons import get_aveline_service
        svc = get_aveline_service()
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": f"AvelineService 未就绪: {e}"},
        )

    if stream:
        return StreamingResponse(
            _stream_persona_chat(
                svc, user_input, conversation_id, persona_filename,
                model, user_name, max_tokens, temperature,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # 非流式：聚合所有 chunk
    full_text = ""
    try:
        async for chunk in svc.stream_conversation(
            user_input=user_input,
            conversation_id=conversation_id,
            persona_filename=persona_filename,
            user_name=user_name or None,
            max_tokens=max_tokens,
            temperature=temperature,
            save_history=True,
        ):
            # chunk 是 dict，提取 type=message 的 content
            if not isinstance(chunk, dict):
                continue
            if chunk.get("type") == "message":
                content = chunk.get("content")
                if isinstance(content, str) and content:
                    full_text += content
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"success": False, "error": f"人设流程异常: {e}"},
        )

    return _build_chat_completion(model, full_text)


async def _stream_persona_chat(
    svc,
    user_input: str,
    conversation_id: str,
    persona_filename: str,
    model: str,
    user_name: str,
    max_tokens,
    temperature: float,
):
    """persona 模式的流式输出：把 stream_conversation 的 chunk 转成 OpenAI SSE 格式。"""
    try:
        async for chunk in svc.stream_conversation(
            user_input=user_input,
            conversation_id=conversation_id,
            persona_filename=persona_filename,
            user_name=user_name or None,
            max_tokens=max_tokens,
            temperature=temperature,
            save_history=True,
        ):
            if not isinstance(chunk, dict):
                continue
            # 只转发 type=message 的文本内容
            if chunk.get("type") == "message":
                content = chunk.get("content")
                if isinstance(content, str) and content:
                    yield _build_chunk(model, content)
    except Exception as e:
        yield _build_chunk(model, f"Error: {e}", finish_reason="stop")
        yield "data: [DONE]\n\n"
        return

    yield _build_chunk(model, "", finish_reason="stop")
    yield "data: [DONE]\n\n"


async def _stream_chat(llm, messages, model: str, kwargs: Dict[str, Any]):
    """真流式输出聊天结果"""
    try:
        # 使用 LLM 模块的真流式接口
        async for chunk in llm.stream_chat(messages, **kwargs):
            if isinstance(chunk, str):
                if chunk.startswith("Error:"):
                    yield _build_chunk(model, chunk, finish_reason="stop")
                    yield "data: [DONE]\n\n"
                    return
                yield _build_chunk(model, chunk)
            elif isinstance(chunk, dict):
                # 某些 LLM 可能返回字典格式
                content = chunk.get("content") or chunk.get("text") or ""
                if content:
                    yield _build_chunk(model, content)
    except AttributeError:
        # 如果 LLM 不支持 stream_chat，回退到伪流式
        try:
            result = await llm.chat(messages, **kwargs)
        except Exception as e:
            error_chunk = _build_chunk(model, f"Error: {e}", finish_reason="stop")
            yield error_chunk
            yield "data: [DONE]\n\n"
            return

        if isinstance(result, str) and result.strip().startswith("Error:"):
            error_chunk = _build_chunk(model, result, finish_reason="stop")
            yield error_chunk
            yield "data: [DONE]\n\n"
            return

        text = str(result)
        chunk_size = 4
        for i in range(0, len(text), chunk_size):
            yield _build_chunk(model, text[i : i + chunk_size])
    except Exception as e:
        error_chunk = _build_chunk(model, f"Error: {e}", finish_reason="stop")
        yield error_chunk
        yield "data: [DONE]\n\n"
        return

    yield _build_chunk(model, "", finish_reason="stop")
    yield "data: [DONE]\n\n"
