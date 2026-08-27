import asyncio
import os
import time
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.services.workspace.models import ScheduledMessage
from core.services.workspace.reminder_store import WorkspaceReminderStore


def _compute_next_trigger_ts(
    recurrence: str,
    base_ts: float,
    time_of_day: str = "",
    weekdays: Optional[List[int]] = None,
) -> Optional[float]:
    """根据 recurrence 类型计算下次触发时间戳。

    - daily:  基础时间 + 1 天的同一时刻
    - weekly: 下一个匹配 weekdays 的周X的 time_of_day
    - monthly: 下一个月的同一日同一时刻

    base_ts: 当前触发完成的时间戳
    返回 None 表示无法计算或 recurrence=none
    """
    if recurrence == "none":
        return None

    base_dt = datetime.fromtimestamp(base_ts)

    if recurrence == "daily":
        next_dt = base_dt + timedelta(days=1)
        # 如果指定了 time_of_day，对齐到那个时间
        if time_of_day:
            hh, mm = _parse_hhmm(time_of_day)
            if hh is not None:
                next_dt = next_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return next_dt.timestamp()

    if recurrence == "weekly":
        # weekdays: [1..7] (1=周一, 7=周日)
        valid_days = sorted({d for d in (weekdays or []) if 1 <= d <= 7})
        if not valid_days:
            # 没有指定 weekdays，退化为 daily
            return _compute_next_trigger_ts("daily", base_ts, time_of_day)
        # Python isoweekday(): 1=周一 ... 7=周日
        current_day = base_dt.isoweekday()
        for offset in range(1, 8):
            candidate_day = ((current_day - 1 + offset) % 7) + 1
            if candidate_day in valid_days:
                next_dt = base_dt + timedelta(days=offset)
                if time_of_day:
                    hh, mm = _parse_hhmm(time_of_day)
                    if hh is not None:
                        next_dt = next_dt.replace(
                            hour=hh, minute=mm, second=0, microsecond=0
                        )
                return next_dt.timestamp()
        return None

    if recurrence == "monthly":
        # 下一个月的同一日同一时刻
        year = base_dt.year
        month = base_dt.month
        day = base_dt.day
        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1
        # 处理月底越界（如 1月31日 -> 2月没有31日）
        import calendar

        last_day = calendar.monthrange(next_year, next_month)[1]
        next_day = min(day, last_day)
        next_dt = base_dt.replace(
            year=next_year, month=next_month, day=next_day
        )
        return next_dt.timestamp()

    return None


def _parse_hhmm(time_str: str) -> tuple:
    """解析 HH:MM 格式时间，失败返回 (None, None)。"""
    if not time_str:
        return None, None
    try:
        parts = str(time_str).strip().split(":")
        if len(parts) != 2:
            return None, None
        hh = int(parts[0])
        mm = int(parts[1])
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
    except (ValueError, IndexError):
        pass
    return None, None


class WorkspaceReminderService:
    def __init__(
        self,
        *,
        store: WorkspaceReminderStore,
        lock: asyncio.Lock,
        append_workspace_memory: Callable[
            [str, str, List[str], Dict[str, Any]], Awaitable[None]
        ],
    ):
        self._store = store
        self._lock = lock
        self._append_workspace_memory = append_workspace_memory

    async def schedule_message(
        self,
        message: str,
        trigger_ts: float,
        message_type: str = "text",
        metadata: Dict[str, Any] | None = None,
    ) -> str:
        msg_id = f"msg_{int(time.time())}_{os.urandom(4).hex()}"
        new_msg = ScheduledMessage(
            id=msg_id,
            trigger_ts=trigger_ts,
            message=message,
            message_type=message_type,
            status="pending",
            metadata=metadata or {},
        )

        # 临界区只做读-改-写，不调用任何外部回调，避免自死锁
        async with self._lock:
            reminders = await self._store.read()
            reminders.append(new_msg.model_dump())
            await self._store.write(reminders)

        # 回调与通知在锁外执行，避免回调链尝试重新获取同一把锁造成死锁
        try:
            await self._append_workspace_memory(
                f"新增提醒: {message}",
                "workspace_reminder",
                ["workspace", "reminder", "create"],
                {"id": msg_id, "trigger_ts": trigger_ts, "type": message_type},
            )
        except Exception:
            # 回调失败不影响业务数据一致性
            pass

        try:
            from core.services.active_care.core.service import (
                get_active_care_service,
            )

            active_care = get_active_care_service()
            if active_care is not None:
                await active_care.notify_workspace_reminder_updated(
                    trigger_ts=trigger_ts
                )
        except Exception:
            pass

        return msg_id

    async def schedule_recurring_message(
        self,
        message: str,
        first_trigger_ts: float,
        recurrence: str = "none",
        time_of_day: str = "",
        weekdays: Optional[List[int]] = None,
        message_type: str = "text",
        metadata: Dict[str, Any] | None = None,
    ) -> str:
        """P1-5: 调度周期性提醒。

        - recurrence: none/daily/weekly/monthly
        - first_trigger_ts: 首次触发时间戳
        - time_of_day: 每日触发时间（HH:MM），用于 daily/weekly/monthly
        - weekdays: [1..7]，仅 weekly 生效
        """
        if recurrence not in ("none", "daily", "weekly", "monthly"):
            recurrence = "none"
        if recurrence == "none":
            # 退化为单次提醒
            return await self.schedule_message(
                message=message,
                trigger_ts=first_trigger_ts,
                message_type=message_type,
                metadata=metadata,
            )

        msg_id = f"rcr_{int(time.time())}_{os.urandom(4).hex()}"
        next_ts = _compute_next_trigger_ts(
            recurrence=recurrence,
            base_ts=first_trigger_ts,
            time_of_day=time_of_day,
            weekdays=weekdays,
        )
        new_msg = ScheduledMessage(
            id=msg_id,
            trigger_ts=first_trigger_ts,
            message=message,
            message_type=message_type,
            status="pending",
            metadata=metadata or {},
            recurrence=recurrence,
            time_of_day=time_of_day,
            weekdays=weekdays or [],
            next_trigger_ts=next_ts,
        )

        async with self._lock:
            reminders = await self._store.read()
            reminders.append(new_msg.model_dump())
            await self._store.write(reminders)

        # 锁外回调
        try:
            await self._append_workspace_memory(
                f"新增周期提醒: {message}（{recurrence}）",
                "workspace_reminder",
                ["workspace", "reminder", "create", recurrence],
                {
                    "id": msg_id,
                    "trigger_ts": first_trigger_ts,
                    "type": message_type,
                    "recurrence": recurrence,
                    "time_of_day": time_of_day,
                    "weekdays": weekdays or [],
                },
            )
        except Exception:
            pass

        return msg_id

    async def get_pending_messages(self) -> List[ScheduledMessage]:
        async with self._lock:
            raw_list = await self._store.read()
            pending = []
            for item in raw_list:
                if item.get("status") == "pending":
                    pending.append(ScheduledMessage(**item))
            return pending

    async def check_due_messages(self, *, mark_completed: bool = True) -> List[ScheduledMessage]:
        async with self._lock:
            raw_list = await self._store.read()
            now = time.time()
            due_list = []
            updated = False
            for item in raw_list:
                if item.get("status") != "pending":
                    continue
                if item.get("trigger_ts", 0) > now:
                    continue

                msg = ScheduledMessage(**item)
                due_list.append(msg)

                if not mark_completed:
                    continue

                # 周期性提醒：滚动到下一次触发，保持 pending 状态
                recurrence = item.get("recurrence", "none")
                next_ts = item.get("next_trigger_ts")
                # 如果 next_trigger_ts 已过期，重新计算
                if recurrence and recurrence != "none" and not next_ts:
                    next_ts = _compute_next_trigger_ts(
                        recurrence=recurrence,
                        base_ts=now,
                        time_of_day=item.get("time_of_day", ""),
                        weekdays=item.get("weekdays") or [],
                    )
                # 如果 next_ts 也已过期（比如服务长时间停机），再次滚动
                if next_ts and next_ts <= now:
                    next_ts = _compute_next_trigger_ts(
                        recurrence=recurrence,
                        base_ts=next_ts,
                        time_of_day=item.get("time_of_day", ""),
                        weekdays=item.get("weekdays") or [],
                    )
                # 最多滚动 365 次，避免死循环
                guard = 0
                while next_ts and next_ts <= now and guard < 365:
                    next_ts = _compute_next_trigger_ts(
                        recurrence=recurrence,
                        base_ts=next_ts,
                        time_of_day=item.get("time_of_day", ""),
                        weekdays=item.get("weekdays") or [],
                    )
                    guard += 1

                if recurrence and recurrence != "none" and next_ts:
                    # 滚动到下次，保持 pending
                    item["trigger_ts"] = next_ts
                    item["next_trigger_ts"] = _compute_next_trigger_ts(
                        recurrence=recurrence,
                        base_ts=next_ts,
                        time_of_day=item.get("time_of_day", ""),
                        weekdays=item.get("weekdays") or [],
                    )
                    item["last_triggered_at"] = now
                    updated = True
                else:
                    # 单次提醒：标记为 completed
                    item["status"] = "completed"
                    item["triggered_at"] = now
                    updated = True

            if updated:
                await self._store.write(raw_list)
            return due_list

    async def complete_message(self, msg_id: str, *, triggered_at: float | None = None) -> bool:
        async with self._lock:
            raw_list = await self._store.read()
            changed = False
            now = float(triggered_at or time.time())
            for item in raw_list:
                if item.get("id") != msg_id:
                    continue
                if item.get("status") == "completed":
                    return True
                item["status"] = "completed"
                item["triggered_at"] = now
                changed = True
                break
            if changed:
                await self._store.write(raw_list)
            return changed

    async def delete_message(self, msg_id: str) -> bool:
        # 临界区只做读-改-写
        async with self._lock:
            raw_list = await self._store.read()
            new_list = [item for item in raw_list if item.get("id") != msg_id]
            deleted = len(new_list) != len(raw_list)
            if deleted:
                await self._store.write(new_list)

        if not deleted:
            return False

        # 回调在锁外执行，避免自死锁
        try:
            await self._append_workspace_memory(
                f"删除提醒: {msg_id}",
                "workspace_reminder",
                ["workspace", "reminder", "delete"],
                {"id": msg_id},
            )
        except Exception:
            pass
        return True
