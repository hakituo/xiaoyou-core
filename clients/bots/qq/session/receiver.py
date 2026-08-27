"""QQ 适配器会话接收处理模块。

负责从 Xiaoyou Core 接收 WebSocket 消息并按类型分发处理。
从 qq_adapter_session.py 拆分而来，采用 session 实例注入策略。
"""
import json
import os
import time

from clients.bots.qq.settings import logger
from clients.bots.qq.utils import (
    _build_cq_image,
    build_persona_conversation_id,
)


class SessionReceiver:
    """会话接收处理器，负责解析并分发服务端消息。"""

    def __init__(self, session):
        # 持有外层 XiaoyouSession 实例
        self.session = session

    async def receive_from_xiaoyou(self):
        """从 WS 接收消息并按类型（chunk/finish/message/proactive 等）分发。"""
        session = self.session
        full_response = ""
        full_response_is_proactive = False
        try:
            async for message in session.ws:
                session.last_activity = time.time()
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    subtype = data.get("subtype")
                    if await session._handle_server_heartbeat(data):
                        continue
                    if msg_type == "pong":
                        continue

                    if msg_type == "chunk":
                        content = str(data.get("content", "") or "")
                        full_response += content
                        full_response_is_proactive = False
                        continue

                    if msg_type == "finish":
                        if full_response:
                            logger.info(f"[{session.session_id}] LLM原始回复 [{msg_type}] ({len(full_response)}字): {full_response}")
                            if full_response:
                                await session._send_full_response_with_split(
                                    full_response,
                                    enable_surprise_delay=full_response_is_proactive,
                                )
                            full_response = ""
                            full_response_is_proactive = False
                        session._force_full_response = False
                        continue

                    if msg_type == "error":
                        err_msg = (
                            str(data.get("message") or "").strip()
                            or str(data.get("error") or "").strip()
                            or "生成回复时发生错误"
                        )
                        await session.adapter.send_to_napcat(session.session_id, err_msg)
                        full_response = ""
                        full_response_is_proactive = False
                        session._force_full_response = False
                        continue

                    if msg_type == "message":
                        if data.get("is_proactive"):
                            target_id = str(data.get("conversation_id") or "")

                            is_target_match = (target_id == session.session_id)
                            if not is_target_match and "__persona__" in target_id:
                                base_cid = target_id.split("__persona__", 1)[0]
                                is_target_match = (base_cid == session.session_id)
                            if session.session_id == "default_user" and target_id == "default_user":
                                is_target_match = True

                            if not is_target_match:
                                logger.debug(f"[{session.session_id}] Ignoring proactive message for {target_id}")
                                continue

                            logger.info(f"[{session.session_id}] 接收并处理主动关怀消息")

                        if subtype == "response_chunk":
                            content = str(data.get("content") or "")
                            if content:
                                full_response += content
                                full_response_is_proactive = bool(data.get("is_proactive"))
                            continue

                        if subtype == "proactive_notification":
                            content = data.get("content")
                            if content:
                                if await session._is_duplicate_proactive_global(str(content)):
                                    continue
                                message_type = str(data.get("message_type") or "").strip().lower()
                                if message_type == "voice":
                                    prefs = session.adapter._session_prefs.get(session.session_id) if isinstance(session.adapter._session_prefs, dict) else {}
                                    ref = prefs.get("reference_audio") if isinstance(prefs, dict) else None
                                    sent_voice = await session.adapter._send_voice_response(session.session_id, str(content), ref)
                                    if sent_voice:
                                        continue
                                await session._send_full_response_with_split(
                                    str(content),
                                    enable_surprise_delay=True,
                                )
                            continue

                        if subtype == "response_done":
                            if full_response:
                                logger.info(f"[{session.session_id}] LLM原始回复 ({len(full_response)}字): {full_response}")
                                if (
                                    full_response_is_proactive
                                    and await session._is_duplicate_proactive_global(full_response)
                                ):
                                    full_response = ""
                                    full_response_is_proactive = False
                                    session._force_full_response = False
                                    continue
                                await session._send_full_response_with_split(
                                    full_response,
                                    enable_surprise_delay=full_response_is_proactive,
                                )
                                full_response = ""
                                full_response_is_proactive = False
                            else:
                                logger.warning(f"[{session.session_id}] response_done 到达但 full_response 为空，用户可能未收到回复")
                            session._force_full_response = False
                            continue

                        if subtype == "response":
                            content = data.get("content")
                            if content:
                                content_text = str(content)
                                logger.info(f"[{session.session_id}] LLM原始回复 [response] ({len(content_text)}字): {content_text}")
                                if bool(data.get("is_proactive")) and await session._is_duplicate_proactive_global(content_text):
                                    full_response = ""
                                    full_response_is_proactive = False
                                    session._force_full_response = False
                                    continue
                                await session._send_full_response_with_split(
                                    content_text,
                                    enable_surprise_delay=bool(data.get("is_proactive")),
                                )
                                full_response = ""
                                full_response_is_proactive = False
                            session._force_full_response = False
                            continue

                        if subtype == "acknowledged":
                            continue

                        if not subtype:
                            content = data.get("content")
                            if content:
                                await session._send_full_response_with_split(
                                    str(content),
                                    enable_surprise_delay=bool(data.get("is_proactive")),
                                )
                                full_response = ""
                                full_response_is_proactive = False
                            continue

                    if msg_type == "proactive_message":
                        target_id = str(data.get("conversation_id") or "")
                        is_target_match = (target_id == session.session_id)
                        if session.session_id == "default_user" and target_id == "default_user":
                            is_target_match = True
                        if not is_target_match and "__persona__" in target_id:
                            base_cid = target_id.split("__persona__", 1)[0]
                            # 放宽匹配：build_persona_conversation_id 现统一用 "shared" 作 base
                            # 以实现跨平台记忆互通，因此 shared base 也应进入 persona 校验
                            if base_cid == session.session_id or base_cid == "shared":
                                # multi QQ 模式：检查 persona 是否匹配当前 adapter
                                adapter_persona = str(getattr(session._cfg, 'persona_filename', '') or '').strip()
                                if adapter_persona:
                                    expected_cid = build_persona_conversation_id(session.session_id, adapter_persona)
                                    is_target_match = (target_id == expected_cid)
                                    if not is_target_match:
                                        logger.debug(
                                            f"[{session.session_id}] Ignoring proactive_message: "
                                            f"persona mismatch (target={target_id}, expected={expected_cid})"
                                        )
                                else:
                                    is_target_match = True
                        if not is_target_match:
                            logger.debug(f"[{session.session_id}] Ignoring proactive_message for {target_id}")
                            continue

                        logger.info(f"[{session.session_id}] 接收并处理主动关怀消息 (proactive_message), target={target_id}")

                        content = data.get("content")
                        if not content:
                            continue

                        if await session._is_duplicate_proactive_global(str(content)):
                            continue

                        # 支持 peer_chat 指定目标QQ号（发送到对方的QQ号）
                        target_qq_id = str(data.get("target_qq_id") or "").strip()
                        is_peer_script = bool(data.get("is_peer_script", False))
                        msg_sub_type = str(data.get("message_type") or "").strip().lower()
                        # 检测是否为 peer script 消息（兼容两种标记方式）
                        if target_qq_id and (is_peer_script or msg_sub_type == "peer_script"):
                            # 剧本消息：直接通过 adapter 发送到对方QQ，不创建temp session
                            logger.info(f"[{session.session_id}] peer_chat剧本消息，发送到对方QQ: {target_qq_id}")
                            await session.adapter.send_to_napcat(f"peer_{target_qq_id}", str(content))
                            continue
                        elif target_qq_id:
                            # 非剧本消息（如提及用户）：发送到对方QQ，继续处理
                            logger.info(f"[{session.session_id}] peer_chat消息，发送到对方QQ: {target_qq_id}")
                            await session.adapter.send_to_napcat(f"peer_{target_qq_id}", str(content))

                        message_type = str(data.get("message_type") or "text").strip().lower()
                        if message_type == "voice":
                            prefs = session.adapter._session_prefs.get(session.session_id) if isinstance(session.adapter._session_prefs, dict) else {}
                            ref = prefs.get("reference_audio") if isinstance(prefs, dict) else None
                            sent_voice = await session.adapter._send_voice_response(session.session_id, str(content), ref)
                            if sent_voice:
                                continue

                        await session._send_full_response_with_split(
                            str(content),
                            enable_surprise_delay=True,
                        )
                        continue

                    if msg_type == "image_status":
                        data_content = data.get("data")
                        if data_content and data_content.get("status") == "started":
                            prompt = data_content.get("prompt", "")
                            await session.adapter.send_to_napcat(session.session_id, f"🎨 正在为您生成图片: {prompt}")
                        continue

                    if msg_type == "image_result":
                        data_content = data.get("data")
                        if data_content and data_content.get("success"):
                            image_path = data_content.get("image_path")
                            if image_path and os.path.exists(image_path):
                                await session.adapter.send_to_napcat(session.session_id, _build_cq_image(image_path))
                        continue

                    if msg_type == "emotion_update":
                        try:
                            data_content = data.get("data")
                            if data_content:
                                if "visual_emotion_weights" in data_content:
                                    session.adapter.update_emotion(session.session_id, data_content["visual_emotion_weights"])
                                elif "primary_emotion" in data_content:
                                    session.adapter.update_emotion(
                                        session.session_id, {str(data_content["primary_emotion"]): 1.0}
                                    )
                        except Exception:
                            pass
                        continue

                except json.JSONDecodeError:
                    pass
        except Exception as e:
            logger.error(f"[{session.session_id}] Receive error: {e}")
            if full_response:
                try:
                    await session._send_full_response_with_split(
                        full_response,
                        enable_surprise_delay=full_response_is_proactive,
                    )
                except Exception:
                    pass
            raise
