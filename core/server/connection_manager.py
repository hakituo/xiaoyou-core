import time
import logging
import asyncio
from typing import Set, Dict, Any

logger = logging.getLogger(__name__)

class ConnectionManager:
    """
    Manages WebSocket connections and heartbeats.
    """
    def __init__(self, max_connections: int = 10, heartbeat_timeout: int = 60):
        self.active_connections: Set[Any] = set()
        self.heartbeats: Dict[Any, float] = {}
        self.max_connections = max_connections
        self.heartbeat_timeout = heartbeat_timeout

    async def connect(self, websocket: Any) -> bool:
        """Register a new connection. Returns False if max connections reached."""
        if len(self.active_connections) >= self.max_connections:
            return False
        self.active_connections.add(websocket)
        self.heartbeats[websocket] = time.time()
        return True

    def disconnect(self, websocket: Any):
        """Unregister a connection."""
        self.active_connections.discard(websocket)
        if websocket in self.heartbeats:
            del self.heartbeats[websocket]

    def update_heartbeat(self, websocket: Any):
        """Update the last heartbeat time for a connection."""
        self.heartbeats[websocket] = time.time()

    async def check_heartbeats(self):
        """Check for timed out connections and close them."""
        now = time.time()
        to_close = []
        for ws, last_ping in self.heartbeats.items():
            if now - last_ping > self.heartbeat_timeout:
                to_close.append(ws)
        
        for ws in to_close:
            remote_addr = getattr(ws, 'remote_address', 'unknown')
            logger.warning(f"Client {remote_addr} heartbeat timeout. Closing connection.")
            try:
                await ws.close(code=1008, reason="Heartbeat timeout")
            except Exception:
                pass
            finally:
                self.disconnect(ws)

    def get_active_count(self) -> int:
        return len(self.active_connections)

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast a message to all active connections."""
        import json
        try:
            msg_str = json.dumps(message)
        except Exception as e:
            logger.error(f"Failed to serialize broadcast message: {e}")
            return

        to_remove = []
        for ws in self.active_connections:
            try:
                await ws.send(msg_str)
            except Exception:
                to_remove.append(ws)
        
        for ws in to_remove:
            self.disconnect(ws)

# Global Instance
_connection_manager_instance = None

def get_connection_manager() -> ConnectionManager:
    global _connection_manager_instance
    if _connection_manager_instance is None:
        _connection_manager_instance = ConnectionManager()
    return _connection_manager_instance
