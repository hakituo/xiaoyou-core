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
        await self.ws_manager.broadcast(
            {
                "type": "ritual_event",
                "id": str(uuid.uuid4()),
                "content": ritual,
                "timestamp": now_iso(),
            }
        )

    async def broadcast_reaction(self, reaction: str):
        """广播自发反应事件。"""
        await self.ws_manager.broadcast(
            {
                "type": "spontaneous_reaction",
                "id": str(uuid.uuid4()),
                "content": reaction,
                "timestamp": now_iso(),
            }
        )
