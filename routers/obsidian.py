# -*- coding: utf-8 -*-
"""Obsidian 专用端点。

独立挂在 /obsidian/v1 前缀下，与通用 OpenAI 兼容层 (/v1) 解耦：
- /obsidian/v1/models：只列出 obsidian/ 目录下的人设
- /obsidian/v1/chat/completions：走完整人设/记忆流程，但：
  * 使用 Obsidian 专用 DeepSeek API Key（DEEPSEEK_API_KEY_OBSIDIAN）
  * 跳过 Active Care（Obsidian 是被动场景，不触发 QQ 端主动关怀）
  * 历史存储标记 platform="obsidian"（注入上下文时加平台标记）

Copilot for Obsidian 配置：
  Provider: 3rd party (openai-format)
  Base URL: http://localhost:8000/obsidian/v1
  API Key:  <后端安全 token>
  Model:    persona:obsidian/Aveline_Obsidian          （默认 pro）
            persona:obsidian/Aveline_Obsidian:flash     （切换 flash）
"""

import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(prefix="/obsidian/v1", tags=["Obsidian专用"])

# Obsidian 专用 DeepSeek API Key 的环境变量名
_OBSIDIAN_API_KEY_ENV = "DEEPSEEK_API_KEY_OBSIDIAN"

# Obsidian 人设目录
_OBSIDIAN_CONFIGS_SUBDIR = "obsidian"

# 模型切换后缀 → model_hint 映射
# model 名格式：persona:obsidian/<persona_name>[:flash]
# 不带后缀默认 pro，带 :flash 切 flash
# model_hint 必须用 cloud:deepseek:obsidian:<model> 格式，让 HybridLLMModule 走 openai_compat provider
# 否则裸模型名会走本地 provider，导致卡住无输出
_MODEL_SUFFIX_MAP = {
    "flash": "cloud:deepseek:obsidian:deepseek-v4-flash",
}
_DEFAULT_MODEL_HINT = "cloud:deepseek:obsidian:deepseek-v4-pro"

# 默认共享 QQ 主会话记忆（同一个人在 QQ/Obsidian 两端聊天，记忆应共享）
# 历史消息通过 sanitize_history_messages 在末尾标注（来自Obsidian）区分来源
# QQ 号从环境变量 XIAOYOU_QQ_MASTER_ID 读取，避免硬编码隐私数据
_DEFAULT_QQ_ID = os.getenv("XIAOYOU_QQ_MASTER_ID", "")
_DEFAULT_CONVERSATION_ID = (
    f"private_{_DEFAULT_QQ_ID}__persona__aveline_qq_master" if _DEFAULT_QQ_ID else ""
)


# ========== 响应构建工具函数（与 openai_compat 保持一致格式） ==========

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


def _build_chunk(model: str, delta_content: str, finish_reason: Optional[str] = None) -> str:
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


def _build_models_response(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "object": "list",
        "data": items,
    }


# ========== 人设列表 ==========

def _list_obsidian_persona_models() -> List[Dict[str, Any]]:
    """扫描 character/configs/obsidian/ 目录，列出 Obsidian 专用人设。

    model_id 格式：persona:obsidian/<相对路径不含.json>
    例如：persona:obsidian/Aveline_Obsidian
    """
    configs_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "core", "character", "configs", _OBSIDIAN_CONFIGS_SUBDIR,
    )
    if not os.path.isdir(configs_dir):
        return []

    items: List[Dict[str, Any]] = []
    for fname in sorted(os.listdir(configs_dir)):
        if not fname.endswith(".json"):
            continue
        if fname in {"playsets.json", "reference_examples.json"}:
            continue
        persona_id = f"persona:{_OBSIDIAN_CONFIGS_SUBDIR}/{fname[:-5]}"
        display_name = fname[:-5]
        items.append({
            "id": persona_id,
            "object": "model",
            "owned_by": "obsidian",
            "display_name": display_name,
        })
    return items


# ========== model 名解析 ==========

def _parse_obsidian_model(model: str) -> Dict[str, Any]:
    """解析 Obsidian 端的 model 字段。

    支持格式：
      persona:obsidian/Aveline_Obsidian
      persona:obsidian/Aveline_Obsidian:flash
      persona:obsidian/Aveline_Obsidian:user=<conversation_id>
      persona:obsidian/Aveline_Obsidian:flash:user=<conversation_id>

    返回：
      {
        "persona_filename": "obsidian/Aveline_Obsidian.json",
        "model_hint": "deepseek-v4-pro" | "deepseek-v4-flash",
        "conversation_id": Optional[str],
      }
    """
    # 剥离 "persona:" 前缀
    rest = model[len("persona:"):]

    # 提取 :user= 后缀（跨端共享记忆）
    conversation_id: Optional[str] = None
    if ":user=" in rest:
        rest, conv_part = rest.split(":user=", 1)
        conversation_id = conv_part.strip() or None

    # 提取模型切换后缀（:flash）
    model_hint = _DEFAULT_MODEL_HINT
    # 检查是否带已知后缀
    for suffix, hint in _MODEL_SUFFIX_MAP.items():
        if rest.endswith(f":{suffix}"):
            rest = rest[: -(len(suffix) + 1)]
            model_hint = hint
            break

    # 补回 .json
    persona_filename = rest if rest.endswith(".json") else rest + ".json"

    return {
        "persona_filename": persona_filename,
        "model_hint": model_hint,
        "conversation_id": conversation_id,
    }


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


# ========== 端点 ==========

@router.get("/models", summary="Obsidian 专用的人设列表")
async def list_models():
    items = _list_obsidian_persona_models()
    return _build_models_response(items)


@router.post("/chat/completions", summary="Obsidian 专用的对话补全")
async def chat_completions(payload: Dict[str, Any] = Body(...)):
    model = str(payload.get("model") or "").strip()
    messages = payload.get("messages")
    stream = bool(payload.get("stream", False))

    if not model:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "model 不能为空"},
        )
    if not isinstance(messages, list) or not messages:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "messages 不能为空"},
        )
    # 必须是 persona:obsidian/ 前缀
    if not model.startswith("persona:obsidian/"):
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "Obsidian 端点只接受 persona:obsidian/ 前缀的 model 名",
            },
        )

    parsed = _parse_obsidian_model(model)
    persona_filename = parsed["persona_filename"]
    model_hint = parsed["model_hint"]
    # 默认共享 QQ 主会话记忆：同一个人在 QQ / Obsidian 两端聊天，记忆应共享
    # 历史消息通过 sanitize_history_messages 在末尾标注（来自Obsidian）区分来源
    conversation_id = parsed["conversation_id"] or str(
        payload.get("user") or payload.get("user_name") or ""
    ) or _DEFAULT_CONVERSATION_ID

    user_input = _extract_last_user_message(messages)
    if not user_input:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "messages 中没有 user 消息"},
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
            _stream_obsidian_chat(
                svc, user_input, conversation_id, persona_filename,
                model, user_name, max_tokens, temperature, model_hint,
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
    _debug_chunk_types = []
    try:
        async for chunk in svc.stream_conversation(
            user_input=user_input,
            conversation_id=conversation_id,
            persona_filename=persona_filename,
            user_name=user_name or None,
            max_tokens=max_tokens,
            temperature=temperature,
            model_hint=model_hint,
            save_history=True,
            api_key_env=_OBSIDIAN_API_KEY_ENV,
            skip_active_care=True,
            platform="obsidian",
        ):
            if isinstance(chunk, dict):
                _t = chunk.get("type", "")
                _sub = chunk.get("subtype", "")
                _done = chunk.get("done", False)
                _ctype = f"{_t}/{_sub}/done={_done}"
                if _ctype not in _debug_chunk_types:
                    _debug_chunk_types.append(_ctype)
                # 收集所有可能包含文本的 chunk
                if _t == "message":
                    content = chunk.get("content")
                    if isinstance(content, str) and content:
                        full_text += content
                elif _done:
                    # done 事件可能携带最终内容
                    content = chunk.get("content") or chunk.get("thought") or ""
                    if isinstance(content, str) and content and not full_text:
                        full_text = content
            elif isinstance(chunk, str) and chunk:
                full_text += chunk
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error": f"人设流程异常: {e}",
                "debug_chunk_types": _debug_chunk_types,
            },
        )

    if not full_text:
        return JSONResponse(
            status_code=502,
            content={
                "success": False,
                "error": "stream_conversation 未返回任何内容",
                "debug_chunk_types": _debug_chunk_types,
            },
        )

    return _build_chat_completion(model, full_text)


async def _stream_obsidian_chat(
    svc,
    user_input: str,
    conversation_id: str,
    persona_filename: str,
    model: str,
    user_name: str,
    max_tokens,
    temperature: float,
    model_hint: str,
):
    """Obsidian 模式流式输出：走完整人设流程，跳过 Active Care。"""
    try:
        async for chunk in svc.stream_conversation(
            user_input=user_input,
            conversation_id=conversation_id,
            persona_filename=persona_filename,
            user_name=user_name or None,
            max_tokens=max_tokens,
            temperature=temperature,
            model_hint=model_hint,
            save_history=True,
            api_key_env=_OBSIDIAN_API_KEY_ENV,
            skip_active_care=True,
            platform="obsidian",
        ):
            if not isinstance(chunk, dict):
                continue
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
