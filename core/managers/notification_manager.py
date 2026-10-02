from typing import List, Dict, Any
import time
import uuid
from collections import deque


class NotificationManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(NotificationManager, cls).__new__(cls)
            cls._instance.notifications = {}  # user_id -> deque of notifications
            cls._instance.last_poll_time = {}  # user_id -> timestamp
        return cls._instance

    def has_active_connections(self, timeout: float = 60.0) -> bool:
        """检查是否有活跃的轮询连接"""
        now = time.time()
        for last_poll in self.last_poll_time.values():
            if now - last_poll < timeout:
                return True
        return False

    def add_notification(
        self,
        user_id: str,
        type: str,
        title: str,
        content: str,
        payload: Dict[str, Any] = None,
    ):
        if user_id not in self.notifications:
            self.notifications[user_id] = deque(maxlen=50)

        notification = {
            "id": str(uuid.uuid4()),
            "type": type,  # "text", "image", "voice", "vocabulary"
            "title": title,
            "content": content,
            "payload": payload or {},
            "timestamp": time.time(),
            "read": False,
        }
        self.notifications[user_id].append(notification)
        return notification

    def get_pending_notifications(self, user_id: str) -> List[Dict[str, Any]]:
        """获取并清除待处理的通知"""
        self.last_poll_time[user_id] = time.time()
        if user_id not in self.notifications:
            return []

        # Return all unread (in this simple version, we just return all and clear, or return unread)
        # For polling, usually we want to "pop" them or mark them as read.
        # Let's pop them to ensure they are only delivered once per poll cycle.

        results = []
        while self.notifications[user_id]:
            results.append(self.notifications[user_id].popleft())

        return results


def get_notification_manager():
    return NotificationManager()
