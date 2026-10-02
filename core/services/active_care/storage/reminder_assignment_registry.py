"""
跨 persona 提醒分工注册表

职责：
- 管理 companion_data/dual_role/reminder_assignment_today.json 共享文件
- 提供读写接口供 PeerChatScheduler（协商时写入）和 checker_action_flow（发送前 check）使用
- 日期变更时自动滚动（清空重写）
- asyncio.Lock 保护并发写

数据结构示例：
{
  "date": "2026-07-05",
  "negotiation_status": "completed",  # pending | completed | failed
  "negotiated_at": 1783180777,
  "assignments": [
    {
      "reminder_id": "study:review_due",
      "title": "学习复习提醒：3个知识点到期",
      "assigned_to": "aveline",
      "assigned_at": 1783180777,
      "reason": "Aveline 学科背景更适合讲学习话题"
    }
  ],
  "pending": [
    {"reminder_id": "user_health_reminder:water", "title": "喝水提醒"}
  ]
}
"""
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger
from core.utils.data_paths import get_dual_role_reminder_assignment_path
from core.utils.time_utils import get_current_time, ts_to_str
from core.utils.async_locks import LazyAsyncLock

logger = get_logger("REMINDER_REGISTRY")


class ReminderAssignmentRegistry:
    """跨 persona 提醒分工共享池读写器

    所有方法都是 async 的（文件 IO），线程安全用 asyncio.Lock 保护。
    """

    def __init__(self):
        self._lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._cache: Optional[Dict[str, Any]] = None  # 内存缓存
        self._cache_loaded_at: float = 0.0
        self._cache_ttl: float = 5.0  # 5 秒缓存，避免频繁读盘

    # ==================== 文件读写 ====================

    def _get_file_path(self) -> Path:
        """获取共享文件路径（每次调用都重新解析，保证路径迁移生效）"""
        return get_dual_role_reminder_assignment_path()

    async def _read_raw(self) -> Dict[str, Any]:
        """从磁盘读取原始数据，文件不存在或解析失败时返回空结构"""
        path = self._get_file_path()
        if not path.exists():
            return self._empty_structure()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return self._empty_structure()
            return data
        except Exception as e:
            logger.warning("ReminderAssignmentRegistry: 读取共享文件失败: %s", e)
            return self._empty_structure()

    async def _write_raw(self, data: Dict[str, Any]) -> None:
        """写入磁盘（确保目录存在）"""
        path = self._get_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_path.replace(path)  # 原子替换

    def _empty_structure(self) -> Dict[str, Any]:
        """返回空结构"""
        return {
            "date": get_current_time().strftime("%Y-%m-%d"),
            "negotiation_status": "pending",
            "negotiated_at": 0.0,
            "assignments": [],
            "pending": [],
        }

    def _is_expired(self, data: Dict[str, Any]) -> bool:
        """检查数据是否过期（日期变更）"""
        today = get_current_time().strftime("%Y-%m-%d")
        return str(data.get("date", "")) != today

    async def _load(self, force_refresh: bool = False) -> Dict[str, Any]:
        """加载数据（带缓存 + 日期滚动）"""
        now = time.time()
        if (
            not force_refresh
            and self._cache is not None
            and (now - self._cache_loaded_at) < self._cache_ttl
        ):
            return self._cache

        async with self._lock:
            data = await self._read_raw()
            if self._is_expired(data):
                logger.info(
                    "ReminderAssignmentRegistry: 日期变更，重置共享池 (旧 date=%s)",
                    data.get("date"),
                )
                data = self._empty_structure()
                await self._write_raw(data)
            self._cache = data
            self._cache_loaded_at = now
            return data

    async def _save(self, data: Dict[str, Any]) -> None:
        """保存数据（更新缓存 + 写盘）"""
        async with self._lock:
            await self._write_raw(data)
            self._cache = data
            self._cache_loaded_at = time.time()

    # ==================== 对外接口 ====================

    async def is_assigned_to_other(
        self, reminder_id: str, current_persona: str
    ) -> bool:
        """检查某条提醒是否已分配给另一角色

        Args:
            reminder_id: 提醒唯一标识（如 "study:review_due"）
            current_persona: 当前 persona 标识（"aveline" / "ling"）

        Returns:
            True 表示已分配给对方，当前 persona 应跳过
        """
        if not reminder_id:
            return False
        data = await self._load()
        for a in data.get("assignments", []):
            if (
                str(a.get("reminder_id", "")) == reminder_id
                and str(a.get("assigned_to", "")) != current_persona
            ):
                return True
        return False

    async def is_assigned_to_self(
        self, reminder_id: str, current_persona: str
    ) -> bool:
        """检查某条提醒是否已分配给当前角色"""
        if not reminder_id:
            return False
        data = await self._load()
        for a in data.get("assignments", []):
            if (
                str(a.get("reminder_id", "")) == reminder_id
                and str(a.get("assigned_to", "")) == current_persona
            ):
                return True
        return False

    async def mark_assigned(
        self,
        reminder_id: str,
        title: str,
        persona: str,
        reason: str = "",
    ) -> None:
        """标记提醒已分配给某 persona

        - 如果已存在相同 reminder_id 的分配且属于对方，则不覆盖（先到先得）
        - 如果属于自己，则更新 reason
        - 如果不存在，则新增

        用于：
        - 协商完成后批量写入（由 NegotiationParser 调用）
        - 兜底先到先得时单个写入（由 checker_action_flow 调用）
        """
        if not reminder_id:
            return
        data = await self._load(force_refresh=True)
        assignments: List[Dict[str, Any]] = data.get("assignments", [])

        # 检查是否已存在
        for a in assignments:
            if str(a.get("reminder_id", "")) == reminder_id:
                # 已分配给对方：先到先得，不覆盖
                if str(a.get("assigned_to", "")) != persona:
                    logger.info(
                        "ReminderAssignmentRegistry: 提醒 %s 已由 %s 认领，%s 跳过",
                        reminder_id, a.get("assigned_to"), persona,
                    )
                    return
                # 已分配给自己：更新 reason
                a["title"] = title
                a["reason"] = reason
                a["assigned_at"] = time.time()
                await self._save(data)
                return

        # 新增
        assignments.append({
            "reminder_id": str(reminder_id),
            "title": str(title),
            "assigned_to": str(persona),
            "assigned_at": time.time(),
            "reason": str(reason or ""),
        })
        data["assignments"] = assignments
        await self._save(data)
        logger.info(
            "ReminderAssignmentRegistry: 提醒 %s 已分配给 %s",
            reminder_id, persona,
        )

    async def get_other_persona_assigned(self, current_persona: str) -> List[Dict[str, Any]]:
        """获取对方已认领的所有提醒列表（供 prompt 注入用）"""
        data = await self._load()
        return [
            {
                "reminder_id": a.get("reminder_id", ""),
                "title": a.get("title", ""),
                "assigned_to": a.get("assigned_to", ""),
                "time_str": _format_time(float(a.get("assigned_at", 0))),
            }
            for a in data.get("assignments", [])
            if str(a.get("assigned_to", "")) != current_persona
        ]

    async def needs_negotiation(self) -> bool:
        """是否需要协商（仅 pending 状态返回 True）

        - pending: 未协商过，需要触发协商
        - completed: 协商完成，不需要
        - failed: 协商失败，走兜底（先到先得），不再协商
        """
        data = await self._load()
        status = str(data.get("negotiation_status", "pending"))
        return status == "pending"

    async def mark_negotiation_status(self, status: str, reason: str = "") -> None:
        """标记协商状态

        Args:
            status: "pending" | "completed" | "failed"
            reason: 失败原因（仅 failed 时有意义）
        """
        if status not in ("pending", "completed", "failed"):
            logger.warning("ReminderAssignmentRegistry: 非法 status=%s", status)
            return
        data = await self._load(force_refresh=True)
        data["negotiation_status"] = status
        data["negotiated_at"] = time.time()
        if status == "failed" and reason:
            data["failure_reason"] = reason
        await self._save(data)
        logger.info(
            "ReminderAssignmentRegistry: 协商状态标记为 %s%s",
            status, f" (reason={reason})" if reason else "",
        )

    async def get_pending_reminders(self) -> List[Dict[str, Any]]:
        """获取待协商的提醒列表"""
        data = await self._load()
        return list(data.get("pending", []))

    async def set_pending_reminders(self, reminders: List[Dict[str, Any]]) -> None:
        """设置待协商的提醒列表（PeerChatScheduler 触发前写入）"""
        data = await self._load(force_refresh=True)
        data["pending"] = list(reminders or [])
        await self._save(data)

    async def get_snapshot(self) -> Dict[str, Any]:
        """获取完整快照（供 API/调试用）"""
        return await self._load(force_refresh=True)


def _format_time(ts: float) -> str:
    """时间戳转 HH:MM 字符串"""
    if not ts:
        return ""
    try:
        return ts_to_str(ts, "%H:%M")
    except Exception:
        return ""


# ==================== 全局单例 ====================

_registry: Optional[ReminderAssignmentRegistry] = None


def get_reminder_assignment_registry() -> ReminderAssignmentRegistry:
    """获取 ReminderAssignmentRegistry 单例"""
    global _registry
    if _registry is None:
        _registry = ReminderAssignmentRegistry()
    return _registry
