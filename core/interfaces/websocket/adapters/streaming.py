#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket 流式消息处理
处理 LLM 流式输出并通过 WebSocket 发送
"""

from core.utils.logger import get_logger
import asyncio

import re
import time
from typing import Optional, Any
from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

from .utils import env_flag_enabled


logger = get_logger(__name__)

_BASE64_CHUNK_PATTERN = re.compile(r'[A-Za-z0-9+/]{80,}={0,2}')

# 媒体标签正则（用于剥离 chunk 文本中的标签，避免前端显示 [MEME] 字样）
_MEDIA_TAG_STRIP_RE = re.compile(
    r"[\[［](?:MEME|IMG|BM|VOICE)(?:[：:][^\]］]*)?[\]］]",
    re.IGNORECASE,
)


class StreamingHandler:
    """处理流式对话输出"""

    def __init__(self, adapter):
        self.adapter = adapter

    async def handle_stream(
        self,
        websocket: WebSocket,
        svc,
        content: str,
        msg_id: str,
        conversation_id: str,
        request_id: str,
        model: Optional[str] = None,
        user_name: Optional[str] = None,
        persona_filename: Optional[str] = None,
        service_dynamic_context: Optional[str] = None,
        api_key_env: Optional[str] = None,
        platform: Optional[str] = None,
    ):
        """
        处理流式对话并发送 chunk

        Args:
            websocket: WebSocket 连接
            svc: AvelineService 实例
            content: 用户输入内容
            msg_id: 消息 ID
            conversation_id: 对话 ID
            request_id: 请求 ID
            model: 模型提示
            user_name: 用户名
            persona_filename: 人设文件名
            api_key_env: API key 环境变量名（用于QQ官方机器人独立缓存）
        """
        user_id = getattr(websocket, "user_id", "unknown")

        # [DEBUG] 关键日志：追踪 persona_filename 传递
        logger.info(
            f"[handle_stream] conversation_id={conversation_id}, "
            f"persona_filename={persona_filename!r}, model={model!r}"
        )

        from config.integrated_config import get_settings
        _cfg_max_tokens = getattr(get_settings().model, "max_new_tokens", None)

        if _cfg_max_tokens and _cfg_max_tokens > 0:
            max_tokens = _cfg_max_tokens
        else:
            max_tokens = None

        temperature = float(getattr(get_settings().model, "temperature", 0.7) or 0.7)
        t_stream_start = time.time()
        chunk_count = 0
        last_emotion = None
        done_sent = False
        accumulated_text = ""  # 累积完整响应文本，用于响应结束时解析媒体标签

        try:
            async for chunk in svc.stream_conversation(
                user_input=content,
                conversation_id=conversation_id,
                request_id=request_id,
                message_id=msg_id,
                model_hint=model,
                save_history=True,
                max_tokens=max_tokens,
                temperature=temperature,
                user_name=user_name,
                persona_filename=persona_filename,
                service_dynamic_context=service_dynamic_context,
                api_key_env=api_key_env,
                platform=platform,
            ):
                t_chunk = time.time()
                if chunk_count == 0:
                    logger.info(
                        f"[{t_chunk * 1000:.0f}ms] First chunk generated for {user_id}, "
                        f"TTFT: {(t_chunk - t_stream_start) * 1000:.0f}ms"
                    )
                chunk_count += 1

                # 处理图片触发器
                if isinstance(chunk, dict) and chunk.get("type") == "image_trigger":
                    await self._handle_image_trigger(
                        websocket, chunk, msg_id, conversation_id
                    )
                    continue

                # 处理普通 chunk
                if isinstance(chunk, dict):
                    chunk_type = str(chunk.get("type") or "")
                    chunk_subtype = str(chunk.get("subtype") or "")
                    if chunk_type == "message" and chunk_subtype == "response_done":
                        if chunk.get("emotion") and not last_emotion:
                            last_emotion = {
                                "primary_emotion": chunk.get("emotion"),
                                "sub_emotions": chunk.get("emotion_internal"),
                            }
                        await websocket.send_json(jsonable_encoder(chunk))
                        done_sent = True
                        break
                    if chunk_type == "done":
                        done_sent = True
                        break
                    await self._handle_chunk(
                        websocket, chunk, msg_id, conversation_id, request_id,
                        chunk_index=chunk_count,
                    )

                    # 记录情绪
                    if chunk.get("emotion"):
                        last_emotion = chunk.get("emotion")

                    # 累积文本用于响应结束时的媒体标签解析
                    if chunk_type == "token" or (
                        chunk_type == "message" and chunk_subtype == "response_chunk"
                    ):
                        text_piece = str(chunk.get("content") or chunk.get("data") or "")
                        if text_piece:
                            accumulated_text += text_piece

                    # 检查是否完成
                    if chunk.get("done"):
                        done_sent = True
                        break
                    continue

                # 处理纯文本 chunk
                content_text = str(chunk or "")
                if content_text:
                    accumulated_text += content_text
                    await self._send_chunk(
                        websocket, content_text, msg_id, conversation_id, request_id,
                        chunk_index=chunk_count,
                    )

            # 响应完成：解析累积文本里的 [MEME]/[IMG]/[BM] 标签，选图推回前端
            if accumulated_text:
                try:
                    await self._process_media_tags_in_response(
                        websocket, accumulated_text, msg_id, conversation_id, request_id
                    )
                except Exception as e:
                    logger.warning(f"媒体标签处理失败（不影响主流程）: {e}")

            # 发送完成消息
            if not done_sent:
                await self._send_done(
                    websocket, msg_id, conversation_id, request_id, last_emotion
                )

        except Exception as e:
            logger.error(f"Stream handling error: {e}")
            await self._send_error(
                websocket, f"流式处理失败: {e}", msg_id, conversation_id, request_id
            )

    async def _handle_image_trigger(
        self,
        websocket: WebSocket,
        chunk: dict,
        msg_id: str,
        conversation_id: str,
    ):
        """处理图片生成触发器"""
        platform = getattr(websocket, "platform", None)
        is_demo = (platform == "web_demo") or env_flag_enabled("XIAOYOU_DEMO_MODE")

        if not env_flag_enabled("XIAOYOU_DISABLE_IMAGE"):
            asyncio.create_task(
                self.adapter._generate_image_and_send(
                    websocket=websocket,
                    raw_prompt=chunk.get("data", ""),
                    message_id=msg_id,
                    conversation_id=conversation_id,
                )
            )
        else:
            logger.info(
                f"Image trigger skipped (demo={is_demo}, disable_image=True): "
                f"{str(chunk.get('data') or '')[:80]}"
            )
        await websocket.send_json(jsonable_encoder(chunk))

    async def _handle_chunk(
        self,
        websocket: WebSocket,
        chunk: dict,
        msg_id: str,
        conversation_id: str,
        request_id: str,
        chunk_index: int = 0,
    ):
        """处理单个 chunk"""
        ctype = chunk.get("type")
        subtype = chunk.get("subtype")

        logger.debug(
            f"[WS_HANDLE] Chunk type={ctype}, subtype={subtype}, content={str(chunk.get('content', ''))[:30]}"
        )

        # 响应 chunk
        if ctype == "token" or (ctype == "message" and subtype == "response_chunk"):
            content_text = str(chunk.get("content") or chunk.get("data") or "")
            if content_text:
                logger.debug(
                    f"[WS_HANDLE] Calling _send_chunk with content: {content_text[:30]}"
                )
                await self._send_chunk(
                    websocket,
                    content_text,
                    msg_id,
                    conversation_id,
                    request_id,
                    backchannel=bool(chunk.get("backchannel")),
                    chunk_index=chunk_index,
                )
            else:
                logger.warning("[WS_HANDLE] Empty content in token chunk")
            return

        # 错误
        if ctype == "error":
            error_text = str(
                chunk.get("message") or chunk.get("error") or "处理消息失败"
            )
            await self._send_error(
                websocket, error_text, msg_id, conversation_id, request_id
            )
            return

        # 其他类型直接转发
        await websocket.send_json(jsonable_encoder(chunk))

    async def _send_chunk(
        self,
        websocket: WebSocket,
        content: str,
        msg_id: str,
        conversation_id: str,
        request_id: str,
        backchannel: bool = False,
        chunk_index: int = 0,
    ):
        """发送响应 chunk"""
        # 剥离 [MEME]/[IMG]/[BM]/[VOICE] 媒体标签，避免前端显示 "[MEME]" 字样
        # 媒体标签的图通过 _process_media_tags_in_response 单独走 image_result 推送
        clean_content = _MEDIA_TAG_STRIP_RE.sub("", str(content or ""))
        if not clean_content.strip():
            # 注意：流式输出是逐字符发送 token 的，单个空格/换行也会作为独立
            # chunk 到达这里。若仅凭 .strip() 判空就跳过，英文单词间的空格和
            # 换行会被全部吞掉（表现为 LLM 英文回复发出去没空格）。
            # 只有"剥掉媒体标签后无任何可见内容"（纯标签/空 chunk）才应跳过。
            if content and not str(content).strip():
                # 纯空白 chunk（空格/换行等）：原样转发，保留空白
                clean_content = str(content)
            else:
                logger.debug(f"chunk 全部为媒体标签，跳过发送 (index={chunk_index})")
                return

        if _BASE64_CHUNK_PATTERN.search(clean_content):
            logger.warning(f"拦截含裸 base64 的流式 chunk (index={chunk_index}): {str(content)[:60]}...")
            return

        t_send = time.time()
        logger.debug(f"[WS_SEND] Sending chunk: {clean_content[:30]}...")
        await websocket.send_json(
            {
                "type": "message",
                "subtype": "response_chunk",
                "content": clean_content,
                "timestamp": t_send,
                "message_id": msg_id,
                "conversation_id": conversation_id,
                "request_id": request_id,
                "backchannel": backchannel,
                "chunk_index": chunk_index,
            }
        )

        dt_send = time.time() - t_send
        if dt_send > 0.5:
            logger.warning(f"Slow WebSocket send (response_chunk): {dt_send:.3f}s")

    async def _send_done(
        self,
        websocket: WebSocket,
        msg_id: str,
        conversation_id: str,
        request_id: str,
        emotion: Any = None,
    ):
        """发送完成消息"""
        emotion_value = None
        if isinstance(emotion, dict):
            emotion_value = emotion.get("primary_emotion")

        await websocket.send_json(
            {
                "type": "message",
                "subtype": "response_done",
                "timestamp": time.time(),
                "message_id": msg_id,
                "conversation_id": conversation_id,
                "request_id": request_id,
                "emotion": emotion_value,
            }
        )

    async def _send_error(
        self,
        websocket: WebSocket,
        error: str,
        msg_id: str,
        conversation_id: str,
        request_id: str,
    ):
        """发送错误消息"""
        await websocket.send_json(
            {
                "type": "message",
                "subtype": "response",
                "content": error,
                "timestamp": time.time(),
                "message_id": msg_id,
                "conversation_id": conversation_id,
                "request_id": request_id,
            }
        )

    async def _process_media_tags_in_response(
        self,
        websocket: WebSocket,
        full_text: str,
        msg_id: str,
        conversation_id: str,
        request_id: str,
    ):
        """响应完成后，解析 [MEME] 标签，选表情包并通过 image_result 推回前端

        与 QQ adapter 不同（QQ 用 CQ:image 码发本地文件），websocket/Android 链路
        拿不到本地文件——所以把图片转 base64（限制到 1024x1024 JPEG，平衡清晰度和
        websocket 消息体积），通过 image_result 推回去，Android 端按现有 ImageResult
        渲染逻辑展示。

        支持的标签：
        - [MEME] / [MEME:分类]：从 data/memes/ 选表情包
        - [VOICE:xxx]：本方法不处理（语音走另外通道），仅作文本剥离

        注意：WebSocket/Android 前端为通用公开接口，只处理普通表情包，
        不承载敏感图库（[IMG]/[BM]）内容。

        发送格式（与 _generate_image_and_send 一致）：
            {
                "type": "image_result",
                "data": {
                    "success": True,
                    "source": "meme",
                    "image_url": "data:image/jpeg;base64,...",
                    "thumbnail_base64": "data:image/jpeg;base64,...",
                },
                "timestamp": ...,
                "message_id": msg_id,
                "conversation_id": conversation_id,
                "request_id": request_id,
            }
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

        # 是否有媒体标签需要处理（避免无标签时也走 IO 路径）
        has_media = any(seg.meme_categories for seg in segments)
        if not has_media:
            return

        logger.info(
            f"[media_tags] 处理响应中的媒体标签 cid={conversation_id} "
            f"segments={len(segments)}"
        )

        for seg in segments:
            # 表情包
            for cat in seg.meme_categories:
                try:
                    picked = await asyncio.to_thread(pick_meme_image, cat)
                    if picked is None:
                        logger.info(f"表情包无候选图: cat={cat}")
                        continue
                    await self._send_media_image_result(
                        websocket, picked, source="meme",
                        msg_id=msg_id, conversation_id=conversation_id,
                        request_id=request_id,
                    )
                except Exception as e:
                    logger.warning(f"表情处理失败 cat={cat}: {e}")

    async def _send_media_image_result(
        self,
        websocket: WebSocket,
        image_path,
        *,
        source: str,
        msg_id: str,
        conversation_id: str,
        request_id: str,
    ):
        """把本地图片转 base64（限 1024x1024 JPEG）后通过 image_result 推给前端

        与 _generate_image_and_send 的 image_result 格式一致，让 Android 端
        现有的 ImageResult 渲染逻辑能直接显示。
        """
        import base64
        import io
        import os
        from PIL import Image

        path_str = str(image_path)
        if not os.path.exists(path_str):
            logger.warning(f"媒体图片文件不存在: {path_str}")
            return

        def _encode() -> Optional[str]:
            try:
                with Image.open(path_str) as img:
                    # 限制到 1024x1024（平衡清晰度和 websocket 消息体积）
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

        data_url = await asyncio.to_thread(_encode)
        if not data_url:
            return

        await websocket.send_json(
            {
                "type": "image_result",
                "data": {
                    "success": True,
                    "source": source,
                    "image_url": data_url,
                    "thumbnail_base64": data_url,  # Android 端用同一份
                },
                "timestamp": time.time(),
                "message_id": msg_id,
                "conversation_id": conversation_id,
                "request_id": request_id,
            }
        )
        logger.info(
            f"[media_tags] 推送图片 source={source} cid={conversation_id} "
            f"path={os.path.basename(path_str)}"
        )
