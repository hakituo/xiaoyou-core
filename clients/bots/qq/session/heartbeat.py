"""QQ 适配器会话心跳处理模块。

负责处理服务端心跳 ping/pong 协议，保持 WebSocket 连接活跃。
从 qq_adapter_session.py 拆分而来，采用 session 实例注入策略。
"""
import json
import time

from clients.bots.qq.settings import logger


class SessionHeartbeatHandler:
    """会话心跳处理器，处理服务端 ping 并回复 pong。"""

    def __init__(self, session):
        # 持有外层 XiaoyouSession 实例，用于访问 ws/session_id 等属性
        self.session = session

    async def handle_server_heartbeat(self, data: dict) -> bool:
        """处理服务端心跳消息，如果是 ping 则回复 pong。

        Args:
            data: 服务端发来的消息字典

        Returns:
            bool: True 表示已处理（是心跳消息），False 表示非心跳消息需继续处理
        """
        msg_type = str((data or {}).get("type") or "").strip().lower()
        if msg_type != "ping":
            return False
        if not self.session.ws:
            return True
        payload = {
            "type": "pong",
            "text": "__heartbeat__",
            "timestamp": data.get("timestamp", time.time()),
            "client_id": self.session._client_id,
            "user_id": self.session.session_id,
            "platform": "qq",
        }
        try:
            await self.session.ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            logger.debug(f"[{self.session.session_id}] heartbeat reply failed: {e}")
        return True
