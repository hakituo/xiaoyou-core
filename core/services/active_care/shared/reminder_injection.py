"""
计划提醒注入共享状态管理器

当用户正在聊天时，Active Care 将提醒内容写入此存储，
主程序在下次 LLM 调用时读取并注入到上下文中。
"""
import time
from typing import Any, Dict, Optional

from core.utils.logger import get_module_logger
from core.utils.async_locks import LazyAsyncLock

logger = get_module_logger("REMINDER_INJECTION", "active_care_schedule.log")


class ReminderInjectionStore:
    """计划提醒注入存储

    当用户正在聊天时，Active Care 将提醒内容写入此存储，
    主程序在下次 LLM 调用时读取并注入到上下文中。

    特性：
    - 线程安全（asyncio.Lock）
    - 自动过期机制（TTL）
    - 单例模式（全局唯一实例）
    """

    def __init__(self):
        self._lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._pending_reminders: list[Dict[str, Any]] = []
        # 用户最后交互时间戳（由 stream_orchestrator 更新）
        self._user_last_interaction_ts: float = 0.0

    def _cleanup_expired_locked(self) -> None:
        """清理已过期提醒。调用方需已持有 _lock。"""
        now = time.time()
        active_items = [
            item
            for item in self._pending_reminders
            if float(item.get("expires_at") or 0.0) > now
        ]
        if len(active_items) != len(self._pending_reminders):
            expired_count = len(self._pending_reminders) - len(active_items)
            logger.info("ReminderInjection: 自动清理 %d 条过期提醒", expired_count)
        self._pending_reminders = active_items

    @staticmethod
    def _normalize_item(item: Dict[str, Any]) -> Dict[str, Any]:
        """移除内部字段，返回可注入主对话的提醒项。"""
        return {
            "reminder_text": str(item.get("reminder_text") or "").strip(),
            "task_title": str(item.get("task_title") or "").strip(),
            "recent_chat_summary": str(item.get("recent_chat_summary") or "").strip(),
            "created_ts": float(item.get("created_ts") or 0.0),
        }

    def _build_result_locked(self) -> Optional[Dict[str, Any]]:
        """将队列中的提醒合并为单个注入结果。调用方需已持有 _lock。"""
        if not self._pending_reminders:
            return None

        items = [
            self._normalize_item(item)
            for item in sorted(
                self._pending_reminders,
                key=lambda item: float(item.get("created_ts") or 0.0),
            )
        ]
        if len(items) == 1:
            result = dict(items[0])
            result["reminder_items"] = items
            result["merged_count"] = 1
            return result

        unique_titles: list[str] = []
        for item in items:
            title = item["task_title"]
            if title and title not in unique_titles:
                unique_titles.append(title)

        combined_lines = []
        for item in items:
            title = item["task_title"]
            text = item["reminder_text"]
            if title and title not in text:
                combined_lines.append(f"- {title}：{text}")
            else:
                combined_lines.append(f"- {text}")

        recent_chat_summary = ""
        for item in reversed(items):
            recent_chat_summary = item["recent_chat_summary"]
            if recent_chat_summary:
                break

        return {
            "task_title": "、".join(unique_titles),
            "reminder_text": "你有多条计划提醒需要自然带入对话：\n" + "\n".join(combined_lines),
            "recent_chat_summary": recent_chat_summary,
            "reminder_items": items,
            "merged_count": len(items),
        }

    async def set_pending_reminder(
        self,
        reminder_text: str,
        task_title: str = "",
        recent_chat_summary: str = "",
        ttl_seconds: int = 300,
    ) -> None:
        """设置待注入的提醒内容

        Args:
            reminder_text: 提醒文本内容
            task_title: 任务标题
            recent_chat_summary: 最近聊天记录摘要
            ttl_seconds: 过期时间（秒），默认5分钟
        """
        async with self._lock:
            self._cleanup_expired_locked()
            normalized_text = str(reminder_text or "").strip()
            normalized_title = str(task_title or "").strip()
            normalized_summary = str(recent_chat_summary or "").strip()
            expires_at = time.time() + ttl_seconds

            # 相同任务标题+提醒内容只保留一份，避免连续重复覆盖/堆积
            for item in self._pending_reminders:
                if (
                    str(item.get("reminder_text") or "").strip() == normalized_text
                    and str(item.get("task_title") or "").strip() == normalized_title
                ):
                    item["recent_chat_summary"] = normalized_summary
                    item["created_ts"] = time.time()
                    item["expires_at"] = expires_at
                    logger.info(
                        "ReminderInjection: 刷新待注入提醒 task=%s ttl=%ds queue=%d",
                        normalized_title[:30] if normalized_title else "(无标题)",
                        ttl_seconds,
                        len(self._pending_reminders),
                    )
                    return

            self._pending_reminders.append(
                {
                    "reminder_text": normalized_text,
                    "task_title": normalized_title,
                    "recent_chat_summary": normalized_summary,
                    "created_ts": time.time(),
                    "expires_at": expires_at,
                }
            )
            logger.info(
                "ReminderInjection: 设置待注入提醒 task=%s ttl=%ds queue=%d",
                normalized_title[:30] if normalized_title else "(无标题)",
                ttl_seconds,
                len(self._pending_reminders),
            )

    async def get_and_clear(self) -> Optional[Dict[str, Any]]:
        """获取并清除待注入的提醒

        Returns:
            提醒内容字典，如果无待注入提醒或已过期则返回 None
        """
        async with self._lock:
            self._cleanup_expired_locked()
            if not self._pending_reminders:
                return None

            reminder = self._build_result_locked()
            self._pending_reminders = []
            logger.info(
                "ReminderInjection: 获取待注入提醒 count=%d task=%s",
                int(reminder.get("merged_count") or 0),
                str(reminder.get("task_title", ""))[:30],
            )
            return reminder

    async def has_pending(self) -> bool:
        """检查是否有待注入的提醒"""
        async with self._lock:
            self._cleanup_expired_locked()
            return bool(self._pending_reminders)

    async def clear(self) -> None:
        """清除待注入的提醒"""
        async with self._lock:
            self._pending_reminders = []

    def update_user_interaction(self, timestamp: Optional[float] = None) -> None:
        """更新用户最后交互时间戳

        由 stream_orchestrator 在用户发消息时调用。

        Args:
            timestamp: 时间戳，默认为当前时间
        """
        self._user_last_interaction_ts = timestamp or time.time()

    def is_user_recently_active(self, threshold_seconds: int = 600) -> bool:
        """检查用户是否最近活跃（正在聊天或刚聊完不久）

        Args:
            threshold_seconds: 时间窗口（秒），默认10分钟

        Returns:
            如果用户在时间窗口内有交互则返回 True
        """
        if self._user_last_interaction_ts <= 0:
            return False
        elapsed = time.time() - self._user_last_interaction_ts
        return elapsed < threshold_seconds

    def get_user_last_interaction_ts(self) -> float:
        """获取用户最后交互时间戳"""
        return self._user_last_interaction_ts

    def get_recent_chat_context(self) -> str:
        """获取最近聊天上下文摘要

        从 Active Care context 中获取最近的用户消息，用于注入提醒时提供对话背景。

        Returns:
            最近聊天记录的文本摘要，如果没有则返回空字符串
        """
        try:
            from core.services.active_care.core.service import get_active_care_service
            active_care = get_active_care_service()
            if hasattr(active_care, 'context') and hasattr(active_care.context, 'recent_user_messages'):
                recent_msgs = active_care.context.recent_user_messages
                if recent_msgs:
                    # 取最近3条消息作为上下文
                    recent = recent_msgs[-3:] if len(recent_msgs) > 3 else recent_msgs
                    return " | ".join([str(msg.get('content', ''))[:50] for msg in recent])
        except Exception as e:
            logger.debug(f"获取最近聊天上下文失败: {e}")
        return ""


# ==================== 全局单例 ====================

_store_instance: Optional[ReminderInjectionStore] = None


def get_reminder_injection_store() -> ReminderInjectionStore:
    """获取全局提醒注入存储单例"""
    global _store_instance
    if _store_instance is None:
        _store_instance = ReminderInjectionStore()
    return _store_instance
