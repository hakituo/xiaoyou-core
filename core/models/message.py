from enum import Enum
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
import time
import uuid

class MessageType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VOICE = "voice"
    SYSTEM = "system"
    REACTION = "reaction"
    RETRACTION = "retraction"
    ERROR = "error"

@dataclass
class MessageResource:
    """资源数据（图片/音频）"""
    type: str  # image, audio
    url: Optional[str] = None
    base64: Optional[str] = None
    path: Optional[str] = None  # 本地路径
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class UnifiedMessage:
    """统一消息模型"""
    content: str
    message_type: MessageType = MessageType.TEXT
    
    # 基础元数据
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    conversation_id: str = "default"
    sender_id: str = "system"  # user, assistant, system
    
    # 扩展属性
    emotion: Optional[str] = None
    emotion_internal: Optional[Dict[str, Any]] = None
    
    # 关联资源 (图片/语音)
    resources: List[MessageResource] = field(default_factory=list)
    
    # 原始请求ID (用于链路追踪)
    request_id: Optional[str] = None
    
    # 状态
    status: str = "created"  # created, sending, sent, failed
    
    def add_image(self, url: str = None, base64_data: str = None, path: str = None):
        self.resources.append(MessageResource(
            type="image",
            url=url,
            base64=base64_data,
            path=path
        ))
        # 兼容旧字段逻辑：如果是第一张图，某些系统可能直接读 image_url
        
    def add_audio(self, url: str = None, base64_data: str = None, path: str = None, duration: float = None):
        meta = {}
        if duration:
            meta["duration"] = duration
        self.resources.append(MessageResource(
            type="audio",
            url=url,
            base64=base64_data,
            path=path,
            metadata=meta
        ))

    def to_frontend_dict(self) -> Dict[str, Any]:
        """转换为前端 (WebSocket) 兼容的字典格式"""
        data = {
            "type": "message",  # WebSocket 顶层 type
            "subtype": "response", # 默认
            "message_id": self.id,
            "timestamp": self.timestamp,
            "conversation_id": self.conversation_id,
            "content": self.content,
            "messageType": self.message_type.value, # 前端组件使用的类型
        }
        
        if self.request_id:
            data["request_id"] = self.request_id
            
        if self.emotion:
            data["emotion"] = self.emotion
        if self.emotion_internal:
            data["emotion_internal"] = self.emotion_internal
            
        # 资源平铺 (兼容前端 MessageBubble)
        for res in self.resources:
            if res.type == "image":
                if res.url:
                    data["imageUrl"] = res.url
                if res.base64:
                    data["imageBase64"] = res.base64
                if res.path:
                    data["imagePath"] = res.path
            elif res.type == "audio":
                if res.url:
                    data["audioUrl"] = res.url
                if res.base64:
                    data["audioBase64"] = res.base64
                if res.path:
                    data["audioPath"] = res.path
                # Voice ID usually comes with audio generation metadata
                if res.metadata.get("voice_id"):
                    data["voiceId"] = res.metadata["voice_id"]

        # 特殊处理
        if self.message_type == MessageType.VOICE:
            # 确保前端识别为语音消息
            pass
            
        return data
