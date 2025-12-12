from typing import List, Dict, Any, Optional
import time
import uuid
from collections import deque

class NotificationManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(NotificationManager, cls).__new__(cls)
            cls._instance.notifications = {}  # user_id -> deque of notifications
        return cls._instance

    def add_notification(self, user_id: str, type: str, title: str, content: str, payload: Dict[str, Any] = None):
        if user_id not in self.notifications:
            self.notifications[user_id] = deque(maxlen=50)
            
        notification = {
            "id": str(uuid.uuid4()),
            "type": type,  # "text", "image", "voice", "vocabulary"
            "title": title,
            "content": content,
            "payload": payload or {},
            "timestamp": time.time(),
            "read": False
        }
        self.notifications[user_id].append(notification)
        return notification

    def get_pending_notifications(self, user_id: str) -> List[Dict[str, Any]]:
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
