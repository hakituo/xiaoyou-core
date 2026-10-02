# Bots package — 公共 API re-export（向后兼容）
# 外部代码可直接 from clients.bots import QQAdapter / PeerChatManager 等

from clients.bots.qq.main import QQAdapter
from clients.bots.qq.peer_chat import PeerChatManager
from clients.bots.qq.settings import MASTER_QQ_ID
from clients.bots.qq.utils import build_persona_conversation_id

__all__ = [
    "QQAdapter",
    "PeerChatManager",
    "MASTER_QQ_ID",
    "build_persona_conversation_id",
    "QQOfficialAdapter",
]

# QQOfficialAdapter 依赖 botpy（可选），使用延迟导入
def __getattr__(name):
    if name == "QQOfficialAdapter":
        from clients.bots.qq_official.adapter import QQOfficialAdapter
        return QQOfficialAdapter
    raise AttributeError(f"module 'clients.bots' has no attribute {name!r}")
