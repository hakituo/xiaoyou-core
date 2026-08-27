from typing import Any, Dict
from core.models.message import MessageType, UnifiedMessage
import time


class MessageComposer:
    """消息组装器"""

    @staticmethod
    def create_text(content: str, **kwargs) -> UnifiedMessage:
        return UnifiedMessage(content=content, message_type=MessageType.TEXT, **kwargs)

    @staticmethod
    def create_image(
        prompt: str,
        image_url: str = None,
        base64: str = None,
        path: str = None,
        **kwargs,
    ) -> UnifiedMessage:
        msg = UnifiedMessage(
            content=prompt,  # 图片通常伴随提示词或空文本
            message_type=MessageType.IMAGE,
            **kwargs,
        )
        msg.add_image(url=image_url, base64_data=base64, path=path)
        return msg

    @staticmethod
    def create_voice(
        content: str,
        audio_url: str = None,
        base64: str = None,
        path: str = None,
        voice_id: str = None,
        **kwargs,
    ) -> UnifiedMessage:
        msg = UnifiedMessage(content=content, message_type=MessageType.VOICE, **kwargs)
        # Voice ID passed in metadata of resource
        msg.add_audio(url=audio_url, base64_data=base64, path=path)
        if voice_id and msg.resources:
            msg.resources[0].metadata["voice_id"] = voice_id
        return msg

    @staticmethod
    def create_chunk(
        content: str, message_id: str, conversation_id: str, request_id: str = None
    ) -> Dict[str, Any]:
        """创建流式响应块 (保持原有轻量级字典格式，不使用完整对象)"""
        return {
            "type": "message",
            "subtype": "response_chunk",
            "content": content,
            "timestamp": time.time(),
            "message_id": message_id,
            "conversation_id": conversation_id,
            "request_id": request_id or message_id,
        }

    @staticmethod
    def format_for_websocket(msg: UnifiedMessage) -> Dict[str, Any]:
        """将统一消息对象格式化为 WebSocket 负载"""
        return msg.to_frontend_dict()
