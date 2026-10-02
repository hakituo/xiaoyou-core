import os
import time
import base64
import re
import mimetypes
import urllib.parse
import aiohttp
from typing import Tuple

from clients.bots.handlers.base import BaseHandler
from clients.bots.qq.settings import (
    STT_TIMEOUT_SECONDS,
    VISION_TIMEOUT_SECONDS,
    XIAOYOU_ACCESS_TOKEN,
    XIAOYOU_HTTP_BASE_URL,
    logger,
)

class MediaHandler(BaseHandler):
    """
    Handles media processing: Image recognition (Vision) and Audio transcription (STT).
    """

    def _extract_text_from_segments(self, segments) -> str:
        if not isinstance(segments, list):
            return ""
        parts = []
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            typ = str(seg.get("type") or "").strip().lower()
            data = seg.get("data") if isinstance(seg.get("data"), dict) else {}
            if typ in {"text", "plain"}:
                t = str(data.get("text") or "").strip()
                if t:
                    parts.append(t)
            elif typ == "image":
                parts.append("[图片]")
            elif typ == "record":
                parts.append("[语音]")
            elif typ == "video":
                parts.append("[视频]")
            elif typ == "file":
                parts.append("[文件]")
            elif typ == "at":
                qq = str(data.get("qq") or "").strip()
                if qq and qq != "all":
                    parts.append(f"@{qq}")
                elif qq == "all":
                    parts.append("@全体成员")
        return " ".join(p for p in parts if p).strip()

    async def _extract_forward_text(self, forward_id: str) -> str:
        fid = str(forward_id or "").strip()
        if not fid:
            return ""

        code, resp = await self.adapter.call_napcat_action("get_forward_msg", {"id": fid}, timeout_seconds=6.0)
        if code != 0:
            code, resp = await self.adapter.call_napcat_action("get_forward_msg", {"message_id": fid}, timeout_seconds=6.0)
        if code != 0 or not isinstance(resp, dict):
            return ""

        data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
        msgs = data.get("messages")
        if not isinstance(msgs, list):
            return ""

        lines = []
        for item in msgs[:5]:
            if not isinstance(item, dict):
                continue
            sender = item.get("sender") if isinstance(item.get("sender"), dict) else {}
            name = str(sender.get("nickname") or sender.get("card") or "").strip()
            content = item.get("content")
            text = self._extract_text_from_segments(content if isinstance(content, list) else [])
            if text:
                if name:
                    lines.append(f"{name}: {text}")
                else:
                    lines.append(text)
        return " | ".join(lines).strip()

    async def process_reply_in_message(self, raw_message: str, current_display_msg: str) -> str:
        reply_ids = re.findall(r"\[CQ:reply,id=(\d+)\]", str(raw_message or ""))
        if not reply_ids:
            return current_display_msg

        reply_id = str(reply_ids[0]).strip()
        if not reply_id:
            return current_display_msg

        code, resp = await self.adapter.call_napcat_action("get_msg", {"message_id": int(reply_id)}, timeout_seconds=6.0)
        if code != 0 or not isinstance(resp, dict):
            return re.sub(r"\[CQ:reply,[^\]]+\]", "", current_display_msg).strip()

        data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
        raw_quoted = str(data.get("raw_message") or "").strip()
        seg_quoted = self._extract_text_from_segments(data.get("message") if isinstance(data.get("message"), list) else [])

        forward_text = ""
        msg_segments = data.get("message") if isinstance(data.get("message"), list) else []
        for seg in msg_segments:
            if not isinstance(seg, dict):
                continue
            if str(seg.get("type") or "").strip().lower() == "forward":
                sdata = seg.get("data") if isinstance(seg.get("data"), dict) else {}
                forward_id = str(sdata.get("id") or sdata.get("resid") or "").strip()
                if forward_id:
                    forward_text = await self._extract_forward_text(forward_id)
                    if forward_text:
                        break

        quoted_text = seg_quoted or raw_quoted or ""
        quoted_text = re.sub(r"\[CQ:[^\]]+\]", "", quoted_text).strip()
        if forward_text:
            quoted_text = (quoted_text + " " + forward_text).strip()
        if quoted_text:
            quoted_text = quoted_text[:240]

        clean_text = re.sub(r"\[CQ:reply,[^\]]+\]", "", current_display_msg).strip()
        if not quoted_text:
            return clean_text
        if clean_text:
            return f"【引用消息：{quoted_text}】\n{clean_text}"
        return f"【引用消息：{quoted_text}】"

    async def process_images_in_message(self, raw_message: str, current_display_msg: str) -> str:
        """识别 CQ 码中的图片并调用视觉模型描述

        设计说明(QQ bot 路径 A 的视觉路由策略):
        - QQ bot 因消息管线限制,只能向后端传纯文本(不支持 OpenAI 多模态 content list),
          所以 QQ 端固定走"两阶段中转":本方法先调 VL 模型描述图片,再把文字描述发给后端主模型。
        - 后端 OpenAIClient 基类已实现"多模态主模型一阶段直通"的视觉路由
          (见 core/llm/openai_compat/client.py::_route_vision_if_needed),
          但那只对 WebSocket 直连多模态 content 的场景生效。
        - 若主对话模型是多模态,QQ 端的两阶段描述虽然多一步,但不会出错,且 VL 描述质量通常足够;
          若未来要让 QQ bot 也支持一阶段直通,需改造 send_text 支持多模态 content,改动面较大,暂不实施。
        """
        # 匹配 CQ 码中的 url 字段
        image_urls = re.findall(r'\[CQ:image,[^\]]*url=([^,\]\s]+)[^\]]*\]', raw_message)
        # 匹配 CQ 码中的 base64 字段
        base64_images = re.findall(r'\[CQ:image,[^\]]*file=base64://([^,\]\s]+)[^\]]*\]', raw_message)
        
        if not image_urls and not base64_images:
            return current_display_msg
            
        logger.info(f"Detected {len(image_urls)} URLs and {len(base64_images)} Base64 images in QQ message, processing with vision model...")
        
        descriptions = []
        http_session = await self.adapter._get_http_session()
        
        # 处理基于 URL 的图片
        for i, url in enumerate(image_urls):
            try:
                # 某些时候 URL 可能会被转义，简单处理一下
                url = url.replace("&amp;", "&")
                
                async with http_session.get(url, timeout=15) as resp:
                    if resp.status == 200:
                        img_data = await resp.read()
                        img_b64 = base64.b64encode(img_data).decode('utf-8')
                        mime = str(resp.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
                        if not mime.startswith("image/"):
                            mime = "image/png"

                        # 调用核心视觉接口
                        t0 = time.time()
                        status, data = await self.adapter._api_request(
                            "POST", 
                            "/api/v1/vision/describe", 
                            json_body={
                                "image_base64": f"data:{mime};base64,{img_b64}",
                                "prompt": "请详细描述这张图片的内容，包括场景、人物、动作、文字、色彩氛围等。描述要自然，像你在亲眼看到这张图一样。"
                            },
                            timeout_seconds=VISION_TIMEOUT_SECONDS,
                        )
                        cost_ms = int((time.time() - t0) * 1000)

                        if status == 200 and data.get("status") == "success":
                            desc = data.get("description", "")
                            logger.info(f"Vision describe result (img {i+1}/{len(image_urls)}): desc_len={len(desc)}, desc_preview={desc[:100] if desc else 'EMPTY'}")
                            if desc and not desc.startswith("[DEBUG_ERROR]"):
                                descriptions.append(f"【你看到了一张图片：{desc}】")
                                logger.info(f"Vision describe ok (img {i+1}/{len(image_urls)}), cost={cost_ms}ms")
                            else:
                                logger.warning(f"视觉识别返回错误信息或无内容 (img {i+1}/{len(image_urls)}): {desc}")
                        else:
                            logger.warning(f"视觉识别接口调用失败 (img {i+1}/{len(image_urls)}), status={status}, cost={cost_ms}ms: {data}")
                    else:
                        logger.warning(f"下载图片失败: {url}, status: {resp.status}")
            except Exception as e:
                logger.error(f"处理图片 {i+1} 时出错: {e}")

        # 处理基于 Base64 的图片
        for i, img_b64 in enumerate(base64_images):
            try:
                # 调用核心视觉接口
                t0 = time.time()
                status, data = await self.adapter._api_request(
                    "POST", 
                    "/api/v1/vision/describe", 
                    json_body={
                        "image_base64": f"data:image/png;base64,{img_b64}",
                        "prompt": "请详细描述这张图片的内容，包括场景、人物、动作、文字、色彩氛围等。描述要自然，像你在亲眼看到这张图一样。"
                    },
                    timeout_seconds=VISION_TIMEOUT_SECONDS,
                )
                cost_ms = int((time.time() - t0) * 1000)

                if status == 200 and data.get("status") == "success":
                    desc = data.get("description", "")
                    if desc and not desc.startswith("[DEBUG_ERROR]"):
                        descriptions.append(f"【你看到了一张图片：{desc}】")
                        logger.info(f"Vision describe base64 ok (img {i+1}/{len(base64_images)}), cost={cost_ms}ms")
                    else:
                        logger.warning(f"视觉识别返回错误信息或无内容 (base64 img {i+1}/{len(base64_images)}): {desc}")
                else:
                    logger.warning(f"视觉识别接口调用失败 (base64 img {i+1}/{len(base64_images)}), status={status}, cost={cost_ms}ms: {data}")
            except Exception as e:
                logger.error(f"处理 base64 图片 {i+1} 时出错: {e}")

        if not descriptions:
            # 清理掉 base64 文本防止撑爆 token，即便是没有识别出来
            clean_text = re.sub(r'\[CQ:image,[^\]]+\]', '', current_display_msg).strip()
            return clean_text if clean_text else current_display_msg
            
        # 将视觉描述插入到消息开头，以便 AI 理解上下文
        visual_context = "\n".join(descriptions)
        
        # 清理文本中的图片 CQ 码，避免干扰
        clean_text = re.sub(r'\[CQ:image,[^\]]+\]', '', current_display_msg).strip()
        
        if clean_text:
            return f"{visual_context}\n\n{clean_text}"
        else:
            return visual_context

    async def process_audio_in_message(self, raw_message: str, current_display_msg: str) -> Tuple[str, bool]:
        """识别 CQ 码中的语音并调用 STT 接口转录文本
        
        Returns:
            (transcribed_text, is_voice)
        """
        # 匹配 [CQ:record,file=...,url=...,path=...]
        # 优先从 url 字段提取下载地址；如果是本地路径或无 url，则使用 path
        audio_urls = re.findall(r'\[CQ:record,[^\]]*url=([^,\]\s]+)[^\]]*\]', raw_message)
        audio_paths = re.findall(r'\[CQ:record,[^\]]*path=([^,\]\s]+)[^\]]*\]', raw_message)

        audio_refs = []
        for item in audio_urls + audio_paths:
            if item and item not in audio_refs:
                audio_refs.append(item)

        if not audio_refs:
            return current_display_msg, False
            
        logger.info("Detected voice message in QQ, processing with STT...")
        
        transcriptions = []
        http_session = await self.adapter._get_http_session()
        
        def _normalize_local_path(p: str) -> str:
            p = urllib.parse.unquote(p or "")
            if p.lower().startswith("file://"):
                p = p[7:]
            if re.match(r"^[a-zA-Z]:/", p):
                p = p.replace("/", os.sep)
            return p

        def _is_local_path(p: str) -> bool:
            if not p:
                return False
            p = p.strip()
            if p.lower().startswith("file://"):
                return True
            if re.match(r"^[a-zA-Z]:[\\/]", p):
                return True
            if re.match(r"^[a-zA-Z]:%5c", p.lower()):
                return True
            if p.startswith("\\\\"):
                return True
            return False

        for i, ref in enumerate(audio_refs):
            try:
                # 某些时候 URL 可能会被转义，简单处理一下
                ref = ref.replace("&amp;", "&")

                audio_data = b""
                filename = ""
                content_type = ""

                if _is_local_path(ref):
                    local_path = _normalize_local_path(ref)
                    if os.path.exists(local_path):
                        with open(local_path, "rb") as f:
                            audio_data = f.read()
                        filename = os.path.basename(local_path) or f"voice_{int(time.time())}.amr"
                        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
                    else:
                        logger.warning(f"本地语音文件不存在: {local_path}")
                        continue
                else:
                    async with http_session.get(ref, timeout=20) as resp:
                        if resp.status == 200:
                            audio_data = await resp.read()
                            filename = ref.split("/")[-1].split("?")[0] or f"voice_{int(time.time())}.amr"
                            content_type = str(resp.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
                        else:
                            logger.warning(f"下载语音失败: {ref}, status: {resp.status}")
                            continue

                if not audio_data:
                    continue

                # 调用核心 STT 接口
                # 使用 aiohttp.FormData 上传文件
                form_data = aiohttp.FormData()
                form_data.add_field('file', audio_data, filename=filename, content_type=content_type)
                
                t0 = time.time()
                session = await self.adapter._get_http_session()
                headers = {}
                if XIAOYOU_ACCESS_TOKEN:
                    headers["Authorization"] = f"Bearer {XIAOYOU_ACCESS_TOKEN}"

                url_full = XIAOYOU_HTTP_BASE_URL.rstrip("/") + "/api/v1/stt?model_size=base"
                req_timeout = aiohttp.ClientTimeout(total=max(1.0, float(STT_TIMEOUT_SECONDS)))
                async with session.post(url_full, data=form_data, headers=headers, timeout=req_timeout) as stt_resp:
                    status = stt_resp.status
                    content_type_resp = str(stt_resp.headers.get("Content-Type") or "").lower()
                    if "application/json" in content_type_resp:
                        data = await stt_resp.json(content_type=None)
                    else:
                        data = {"text": await stt_resp.text()}

                cost_ms = int((time.time() - t0) * 1000)

                if status == 200 and data.get("status") == "success":
                    text = data.get("text", "").strip()
                    if text:
                        transcriptions.append(text)
                    logger.info(f"STT transcribe ok, cost={cost_ms}ms, text={text}")
                else:
                    logger.warning(f"语音识别接口调用失败, status={status}, cost={cost_ms}ms: {data}")
            except Exception as e:
                logger.error(f"处理语音时出错: {e}")

        if not transcriptions:
            return current_display_msg, False
            
        # 将转录出的文字替换掉 CQ 码
        combined_text = " ".join(transcriptions)
        
        # 清理文本中的语音 CQ 码
        clean_text = re.sub(r'\[CQ:record,[^\]]+\]', '', current_display_msg).strip()
        
        if clean_text:
            return f"{clean_text} (语音转文字: {combined_text})", True
        else:
            return combined_text, True
