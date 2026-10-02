"""WebSocket 广播协调器。

封装 WebSocketManager 的状态广播逻辑，提供类型化的广播方法。
"""

import uuid
from typing import Any, Dict

from core.interfaces.websocket.websocket_manager import get_websocket_manager
from core.utils.logger import get_logger
from core.utils.time_utils import now_iso

logger = get_logger("LIFE_SIMULATION")


class WebSocketCoordinator:
    """WebSocket 广播协调器，负责状态/仪式/反应消息的广播。"""

    def __init__(self, ws_manager=None):
        self._ws_manager = ws_manager

    @property
    def ws_manager(self):
        if self._ws_manager is None:
            self._ws_manager = get_websocket_manager()
        return self._ws_manager

    @staticmethod
    def current_persona_meta() -> tuple[str, str]:
        """当前活跃角色的 (persona_filename, 角色显示名)。

        仪式/自发反应是"角色当下的行为"，广播时把归属角色带上，客户端才能：
        - 用角色名做通知标题（否则一律显示默认的 Aveline）；
        - 点击通知直达该角色的会话（否则只能落到聊天主页）。
        拿不到角色时返回空串，客户端按默认值兜底。
        """
        try:
            from core.character.managers.persona_manager import get_persona_manager

            persona_manager = get_persona_manager()
            filename = str(persona_manager.get_current_filename() or "").strip()
            identity = (persona_manager.get_current_persona() or {}).get("identity") or {}
            name = str(identity.get("name") or "").strip()
            return filename, name
        except Exception as exc:  # 广播不能因为查角色失败而中断
            logger.debug(f"读取当前角色失败，广播不带角色信息: {exc}")
            return "", ""

    async def broadcast_state(self, state: Dict[str, Any]):
        """广播生命状态更新。

        timestamp 直接取 state["timestamp"]，与原 service.py 行为一致。
        """
        await self.ws_manager.broadcast(
            {
                "type": "life_status",
                "data": state,
                "timestamp": state["timestamp"],
            }
        )

    async def broadcast_ritual(self, ritual: str):
        """广播仪式事件。"""
        persona_filename, role_name = self.current_persona_meta()
        await self.ws_manager.broadcast(
            {
                "type": "ritual_event",
                "id": str(uuid.uuid4()),
                "content": ritual,
                # 归属角色：客户端据此显示角色名并直达该角色会话
                "persona_filename": persona_filename,
                "role_name": role_name,
                "timestamp": now_iso(),
            }
        )

    async def broadcast_reaction(self, reaction: str):
        """广播自发反应事件。"""
        persona_filename, role_name = self.current_persona_meta()
        await self.ws_manager.broadcast(
            {
                "type": "spontaneous_reaction",
                "id": str(uuid.uuid4()),
                "content": reaction,
                "persona_filename": persona_filename,
                "role_name": role_name,
                "timestamp": now_iso(),
            }
        )
