# QQ NapCat Adapter Package
# 向后兼容 re-export：外部可通过 clients.bots.qq 直接访问核心符号

from clients.bots.qq.settings import logger, MASTER_QQ_ID, PROJECT_ROOT, CONFIG_FILE
from clients.bots.qq.config import QQAdapterConfig
from clients.bots.qq.intent import SemanticIntentRecognizer
from clients.bots.qq.face import QQFaceInjector
from clients.bots.qq.emotion import EmotionManager
from clients.bots.qq.aggregator import MessageAggregator
from clients.bots.qq.transport import NapcatTransport
from clients.bots.qq.utils import build_persona_conversation_id

# main 和 peer_chat 因互相有延迟引用，放最后导入
from clients.bots.qq.main import QQAdapter
from clients.bots.qq.peer_chat import PeerChatManager

__all__ = [
    "QQAdapter",
    "QQAdapterConfig",
    "PeerChatManager",
    "SemanticIntentRecognizer",
    "QQFaceInjector",
    "EmotionManager",
    "MessageAggregator",
    "NapcatTransport",
    "build_persona_conversation_id",
    "MASTER_QQ_ID",
    "PROJECT_ROOT",
    "CONFIG_FILE",
    "logger",
]
