from typing import List, Dict, Any
from domain.interfaces.base_interfaces import MemoryInterface

class InMemoryMemoryRepository(MemoryInterface):
    def __init__(self):
        self.history: List[Dict[str, Any]] = []

    async def add_message(self, role: str, content: str, **kwargs):
        self.history.append({
            "role": role,
            "content": content,
            "timestamp": kwargs.get("timestamp")
        })

    async def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.history[-limit:]

    async def search(self, query: str, limit: int = 5) -> List[str]:
        # Simple keyword search for MVP
        results = []
        for msg in self.history:
            if query in msg["content"]:
                results.append(msg["content"])
        return results[:limit]
