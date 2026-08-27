"""Workspace 每日任务快照。

自动生成真源是 ``journal/plan.json``；本服务只镜像主计划供 Workspace/MDP
读取。用户在 Workspace 手动维护的任务仍保留原有提醒行为。
"""

import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import aiofiles

from core.services.workspace.models import DailyTask
from core.services.workspace.history_store import WorkspaceHistoryStore
from core.utils.async_locks import LazyAsyncLock


class WorkspaceDailyTaskService:
    def __init__(
        self,
        *,
        base_dir: Path,
        get_study_overview: Callable[[], Awaitable[Dict[str, Any]]],
        write_study_text: Callable[[str, str, bool], Awaitable[Dict[str, Any]]],
        schedule_message: Callable[..., Awaitable[str]],
        delete_message: Callable[[str], Awaitable[bool]],
        append_workspace_memory: Callable[
            [str, str, List[str], Optional[Dict[str, Any]]], Awaitable[None]
        ],
    ):
        self._base_dir = Path(base_dir).resolve()
        self._lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._get_study_overview = get_study_overview
        self._write_study_text = write_study_text
        self._schedule_message = schedule_message
        self._delete_message = delete_message
        self._append_workspace_memory = append_workspace_memory
        self._history_root = self._base_dir / "history" / "daily_tasks"
        self._history_root.mkdir(parents=True, exist_ok=True)
        self._history_store = WorkspaceHistoryStore(self._history_root)

    async def get_daily_task_panel(
        self,
        *,
        date: Optional[str] = None,
    ) -> Dict[str, Any]:
        from core.services.daily.manager import get_daily_manager

        target_date = self._normalize_date(date)
        record = await asyncio.to_thread(get_daily_manager().get_record, target_date)
        task_data = self._ensure_daily_tasks_shape(record)
        if not task_data.get("timed") and not task_data.get("untimed"):
            await self.generate_daily_tasks_from_progress(date=target_date, force=False)
            record = await asyncio.to_thread(get_daily_manager().get_record, target_date)
            task_data = self._ensure_daily_tasks_shape(record)
        timed_tasks = [
            self._enrich_task_runtime(item, category="timed")
            for item in task_data.get("timed", [])
        ]
        untimed_tasks = [
            self._enrich_task_runtime(item, category="untimed")
            for item in task_data.get("untimed", [])
        ]
        focus = self._build_task_focus(
            now_ts=time.time(), timed_tasks=timed_tasks, untimed_tasks=untimed_tasks
        )
        study_overview = await self._get_study_overview()
        return {
            "date": target_date,
            "focus": focus,
            "timed_tasks": timed_tasks,
            "untimed_tasks": untimed_tasks,
            "history": {
                "root": str(self._history_root),
                "date_dir": str(self._history_store.resolve_date_dir(target_date)),
            },
            "study_overview": {
                "session_stats": study_overview.get("session_stats"),
                "study_streak_days": study_overview.get("study_streak_days"),
                "recent_files": study_overview.get("recent_files", [])[:5],
            },
        }

    async def generate_daily_tasks_from_progress(
        self, *, date: Optional[str] = None, force: bool = False
    ) -> Dict[str, Any]:
        """从 Journal 主计划刷新 Workspace 快照，不再独立生成计划。"""
        from core.services.daily.manager import get_daily_manager
        from core.services.journal import get_journal_service

        target_date = self._normalize_date(date)
        async with self._lock:
            record = await asyncio.to_thread(get_daily_manager().get_record, target_date)
            data = self._ensure_daily_tasks_shape(record)
            if not force and (data.get("timed") or data.get("untimed")):
                return {
                    "date": target_date,
                    "generated": False,
                    "reason": "tasks_exists",
                    "timed_count": len(data.get("timed", [])),
                    "untimed_count": len(data.get("untimed", [])),
                }
            journal_service = get_journal_service()
            main_plan = await journal_service.get_plan(target_date)
            if main_plan is None:
                main_plan = await journal_service.generate_plan_for_date(
                    target_date,
                    force=False,
                )

            timed_tasks: list[dict[str, Any]] = []
            untimed_tasks: list[dict[str, Any]] = []
            for item in main_plan.items:
                duration_val = max(10, int(item.estimated_duration_minutes or 0))
                status = (
                    "completed"
                    if item.status == "completed"
                    else "cancelled"
                    if item.status == "skipped"
                    else "pending"
                )
                task = DailyTask(
                    id=item.id,
                    title=item.title,
                    category="timed" if item.time else "untimed",
                    source="journal_plan_snapshot",
                    execution_time=item.time,
                    window_start=item.time,
                    window_end=(
                        self._add_minutes_to_hhmm(item.time, duration_val)
                        if item.time
                        else None
                    ),
                    duration_minutes=duration_val,
                    linked_study_topic=item.subject,
                    linked_study_path=(
                        "daily/summary.md" if "总结" in item.title else None
                    ),
                    notes=(
                        f"Journal 主计划镜像 source_type={item.source_type} "
                        f"source_key={item.source_key}"
                    ),
                    status=status,
                ).model_dump()
                if item.time:
                    timed_tasks.append(task)
                else:
                    untimed_tasks.append(task)
            data["timed"] = timed_tasks
            data["untimed"] = untimed_tasks
            record["daily_tasks"] = data
            await self._save_daily_record(target_date, record)
            await self._append_history_event(
                date=target_date,
                category="timed",
                event_type="auto_generate",
                payload={"tasks": timed_tasks, "source": "journal_plan_snapshot"},
            )
            await self._append_history_event(
                date=target_date,
                category="untimed",
                event_type="auto_generate",
                payload={"tasks": untimed_tasks, "source": "journal_plan_snapshot"},
            )
        await self._append_workspace_memory(
            f"自动生成每日任务: {target_date}",
            "workspace_daily_task",
            ["workspace", "daily_task", "auto_generate"],
            {"date": target_date, "timed_count": len(timed_tasks), "untimed_count": len(untimed_tasks)},
        )
        return {
            "date": target_date,
            "generated": True,
            "timed_count": len(timed_tasks),
            "untimed_count": len(untimed_tasks),
            "source": "journal_plan_snapshot",
            "source_plan_date": main_plan.date,
            "hard_reminders_created": 0,
        }

    async def upsert_daily_task(
        self,
        *,
        title: str,
        category: str = "untimed",
        execution_time: Optional[str] = None,
        window_start: Optional[str] = None,
        window_end: Optional[str] = None,
        duration_minutes: int = 30,
        linked_study_topic: Optional[str] = None,
        linked_study_path: Optional[str] = None,
        notes: str = "",
        task_id: Optional[str] = None,
        date: Optional[str] = None,
    ) -> Dict[str, Any]:
        from core.services.daily.manager import get_daily_manager

        normalized_category = (
            "timed" if str(category).strip().lower() == "timed" else "untimed"
        )
        target_date = self._normalize_date(date)
        duration = max(5, int(duration_minutes or 30))
        task = DailyTask(
            id=task_id or DailyTask(title=title).id,
            title=str(title).strip(),
            category=normalized_category,
            source="manual",
            execution_time=str(execution_time).strip() if execution_time else None,
            window_start=str(window_start).strip() if window_start else None,
            window_end=str(window_end).strip() if window_end else None,
            duration_minutes=duration,
            linked_study_topic=str(linked_study_topic).strip()
            if linked_study_topic
            else None,
            linked_study_path=str(linked_study_path).strip()
            if linked_study_path
            else None,
            notes=str(notes or "").strip(),
        )
        self._validate_daily_task(task)
        action = "create"
        async with self._lock:
            record = await asyncio.to_thread(get_daily_manager().get_record, target_date)
            data = self._ensure_daily_tasks_shape(record)
            bucket = data.get(normalized_category, [])
            replaced = False
            for idx, item in enumerate(bucket):
                if str(item.get("id")) == task.id:
                    existing = dict(item)
                    payload = task.model_dump()
                    payload["status"] = existing.get("status", "pending")
                    payload["created_at"] = (
                        existing.get("created_at") or payload["created_at"]
                    )
                    payload["completed_at"] = existing.get("completed_at")
                    payload["reminder_id"] = existing.get("reminder_id")
                    payload["source"] = existing.get("source") or payload.get(
                        "source", "manual"
                    )
                    if normalized_category == "timed":
                        payload["reminder_id"] = await self._refresh_task_reminder(
                            task=payload,
                            date=target_date,
                            old_reminder_id=existing.get("reminder_id"),
                        )
                    bucket[idx] = payload
                    replaced = True
                    action = "update"
                    break
            if not replaced:
                payload = task.model_dump()
                if normalized_category == "timed":
                    payload["reminder_id"] = await self._schedule_task_reminder(payload, target_date)
                bucket.append(payload)
            data[normalized_category] = bucket
            record["daily_tasks"] = data
            await self._save_daily_record(target_date, record)
            await self._append_history_event(
                date=target_date,
                category=normalized_category,
                event_type=action,
                payload=task.model_dump(),
            )

        await self._append_workspace_memory(
            f"每日任务更新: {task.title}",
            "workspace_daily_task",
            ["workspace", "daily_task", normalized_category],
            {
                "task_id": task.id,
                "date": target_date,
                "category": normalized_category,
                "linked_study_topic": task.linked_study_topic,
            },
        )
        return {"task": task.model_dump(), "date": target_date, "updated": True}

    async def replace_daily_plan(
        self,
        *,
        tasks: List[Dict[str, Any]],
        date: Optional[str] = None,
        source: str = "planner_ai",
        origin: str = "",
    ) -> Dict[str, Any]:
        from core.services.daily.manager import get_daily_manager

        target_date = self._normalize_date(date)
        created_timed: List[Dict[str, Any]] = []
        created_untimed: List[Dict[str, Any]] = []
        removed_pending = 0
        first_trigger_ts: Optional[float] = None

        async with self._lock:
            record = await asyncio.to_thread(get_daily_manager().get_record, target_date)
            data = self._ensure_daily_tasks_shape(record)

            for category in ["timed", "untimed"]:
                preserved_bucket = []
                for item in data.get(category, []):
                    item_status = str(item.get("status", "pending")).strip().lower()
                    item_source = str(item.get("source") or "").strip().lower()
                    should_replace = item_status == "pending" and item_source in {
                        "planner_ai",
                        "study_progress",
                    }
                    if should_replace:
                        removed_pending += 1
                        await self._cancel_task_reminder(item.get("reminder_id"))
                        continue
                    preserved_bucket.append(item)
                data[category] = preserved_bucket

            for raw_task in tasks:
                title = str(raw_task.get("title") or "").strip()
                if not title:
                    continue
                category = str(raw_task.get("category") or "").strip().lower()
                normalized_category = "timed" if category == "timed" else "untimed"
                execution_time = str(raw_task.get("execution_time") or "").strip() or None
                window_start = str(raw_task.get("window_start") or "").strip() or None
                window_end = str(raw_task.get("window_end") or "").strip() or None
                duration = max(5, int(raw_task.get("duration_minutes") or 30))
                linked_study_topic = (
                    str(raw_task.get("linked_study_topic") or "").strip() or None
                )
                linked_study_path = (
                    str(raw_task.get("linked_study_path") or "").strip() or None
                )
                notes = str(raw_task.get("notes") or "").strip()

                task = DailyTask(
                    title=title,
                    category=normalized_category,
                    source=source,
                    execution_time=execution_time,
                    window_start=window_start,
                    window_end=window_end,
                    duration_minutes=duration,
                    linked_study_topic=linked_study_topic,
                    linked_study_path=linked_study_path,
                    notes=notes,
                )
                self._validate_daily_task(task)
                payload = task.model_dump()

                if normalized_category == "timed":
                    payload["reminder_id"] = await self._schedule_task_reminder(
                        payload, target_date
                    )
                    trigger_ts = self._build_task_trigger_ts(
                        target_date, payload.get("execution_time")
                    )
                    if trigger_ts is not None and trigger_ts > time.time():
                        if first_trigger_ts is None or trigger_ts < first_trigger_ts:
                            first_trigger_ts = trigger_ts
                    created_timed.append(payload)
                else:
                    created_untimed.append(payload)

                data[normalized_category].append(payload)

            record["daily_tasks"] = data
            await self._save_daily_record(target_date, record)
            await self._append_history_event(
                date=target_date,
                category="plan",
                event_type="replace_plan",
                payload={
                    "source": source,
                    "origin": origin,
                    "removed_pending": removed_pending,
                    "timed": created_timed,
                    "untimed": created_untimed,
                },
            )

        await self._append_workspace_memory(
            f"写入今日计划: {target_date}",
            "workspace_daily_task",
            ["workspace", "daily_task", "plan_replace"],
            {
                "date": target_date,
                "source": source,
                "origin": origin,
                "removed_pending": removed_pending,
                "timed_count": len(created_timed),
                "untimed_count": len(created_untimed),
                "first_trigger_ts": first_trigger_ts,
            },
        )
        return {
            "date": target_date,
            "source": source,
            "origin": origin,
            "removed_pending": removed_pending,
            "timed_count": len(created_timed),
            "untimed_count": len(created_untimed),
            "first_trigger_ts": first_trigger_ts,
            "tasks": {
                "timed": created_timed,
                "untimed": created_untimed,
            },
            "updated": True,
        }

    async def update_daily_task_status(
        self, *, task_id: str, status: str, date: Optional[str] = None
    ) -> Dict[str, Any]:
        from core.services.daily.manager import get_daily_manager

        target_date = self._normalize_date(date)
        normalized_status = str(status).strip().lower()
        if normalized_status not in {"pending", "completed", "cancelled"}:
            raise ValueError("status 仅支持 pending/completed/cancelled")
        updated_task = None
        task_category = "untimed"
        async with self._lock:
            record = await asyncio.to_thread(get_daily_manager().get_record, target_date)
            data = self._ensure_daily_tasks_shape(record)
            for category in ["timed", "untimed"]:
                for item in data.get(category, []):
                    if str(item.get("id")) != str(task_id):
                        continue
                    item["status"] = normalized_status
                    item["completed_at"] = (
                        time.time() if normalized_status == "completed" else None
                    )
                    if normalized_status == "completed":
                        await self._cancel_task_reminder(item.get("reminder_id"))
                        item["reminder_id"] = None
                    updated_task = item
                    task_category = category
                    break
                if updated_task:
                    break
            if not updated_task:
                raise ValueError(f"未找到任务: {task_id}")
            record["daily_tasks"] = data
            await self._save_daily_record(target_date, record)
            await self._append_history_event(
                date=target_date,
                category=task_category,
                event_type="status",
                payload={
                    "task_id": task_id,
                    "status": normalized_status,
                    "task": updated_task,
                },
            )

        if normalized_status == "completed":
            await self._record_daily_task_completion_to_study(updated_task)

        await self._append_workspace_memory(
            f"每日任务状态更新: {updated_task.get('title')} -> {normalized_status}",
            "workspace_daily_task",
            ["workspace", "daily_task", "status"],
            {"task_id": task_id, "status": normalized_status, "date": target_date},
        )
        return {"task": updated_task, "date": target_date, "updated": True}

    async def delete_daily_task(self, *, task_id: str, date: Optional[str] = None) -> Dict[str, Any]:
        from core.services.daily.manager import get_daily_manager

        target_date = self._normalize_date(date)
        deleted = None
        deleted_category = "untimed"
        async with self._lock:
            record = await asyncio.to_thread(get_daily_manager().get_record, target_date)
            data = self._ensure_daily_tasks_shape(record)
            for category in ["timed", "untimed"]:
                bucket = data.get(category, [])
                for idx, item in enumerate(bucket):
                    if str(item.get("id")) == str(task_id):
                        deleted = bucket.pop(idx)
                        await self._cancel_task_reminder(deleted.get("reminder_id"))
                        deleted_category = category
                        break
                if deleted:
                    data[category] = bucket
                    break
            if not deleted:
                raise ValueError(f"未找到任务: {task_id}")
            record["daily_tasks"] = data
            await self._save_daily_record(target_date, record)
            await self._append_history_event(
                date=target_date,
                category=deleted_category,
                event_type="delete",
                payload=deleted,
            )
        await self._append_workspace_memory(
            f"删除每日任务: {deleted.get('title')}",
            "workspace_daily_task",
            ["workspace", "daily_task", "delete"],
            {"task_id": task_id, "date": target_date},
        )
        return {"task": deleted, "date": target_date, "deleted": True}

    async def _record_daily_task_completion_to_study(self, task: Dict[str, Any]) -> None:
        from core.services.daily.manager import get_daily_manager

        topic = str(task.get("linked_study_topic") or "").strip()
        if not topic:
            return
        title = str(task.get("title") or "任务").strip()
        await asyncio.to_thread(
            get_daily_manager().record_study,
            topic,
            f"完成每日任务: {title}",
        )
        relative_path = str(task.get("linked_study_path") or "").strip()
        if relative_path:
            line = f"[{time.strftime('%H:%M:%S')}] 完成任务: {title}\n"
            try:
                await self._write_study_text(relative_path, line, True)
            except Exception:
                return

    async def _append_history_event(
        self,
        *,
        date: str,
        category: str,
        event_type: str,
        payload: Dict[str, Any],
    ) -> None:
        await self._history_store.append_daily_task_event(
            date=date,
            category=category,
            event_type=event_type,
            payload=payload,
        )

    async def _save_daily_record(self, date: str, data: Dict[str, Any]) -> None:
        from core.services.daily.manager import get_daily_manager

        manager = get_daily_manager()
        file_path = Path(manager._get_file_path(date))
        file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = file_path.parent / f"{date}.json.tmp"
        text = json.dumps(data, ensure_ascii=False, indent=2)
        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
            await f.write(text)
        os.replace(tmp_path, file_path)

    def _normalize_date(self, date: Optional[str]) -> str:
        raw = str(date or "").strip()
        if raw:
            return raw.split(" ")[0]
        return time.strftime("%Y-%m-%d")

    def _ensure_daily_tasks_shape(self, record: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(record, dict):
            record = {}
        payload = record.get("daily_tasks")
        if not isinstance(payload, dict):
            payload = {}
        timed = payload.get("timed")
        untimed = payload.get("untimed")
        if not isinstance(timed, list):
            timed = []
        if not isinstance(untimed, list):
            untimed = []
        payload["timed"] = timed
        payload["untimed"] = untimed
        record["daily_tasks"] = payload
        return payload

    def _parse_hhmm_minutes(self, value: Optional[str]) -> Optional[int]:
        from core.utils.time_utils import parse_hhmm
        return parse_hhmm(value)

    def _add_minutes_to_hhmm(self, value: str, minutes: int) -> str:
        parsed = self._parse_hhmm_minutes(value)
        if parsed is None:
            return value
        shifted = (parsed + max(0, int(minutes))) % (24 * 60)
        return f"{shifted // 60:02d}:{shifted % 60:02d}"

    def _build_task_trigger_ts(self, date: str, hhmm: Optional[str]) -> Optional[float]:
        minute = self._parse_hhmm_minutes(hhmm)
        if minute is None:
            return None
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return None
        trigger_dt = dt.replace(hour=minute // 60, minute=minute % 60, second=0, microsecond=0)
        return trigger_dt.timestamp()

    async def _cancel_task_reminder(self, reminder_id: Any) -> None:
        rid = str(reminder_id or "").strip()
        if not rid:
            return
        try:
            await self._delete_message(rid)
        except Exception:
            return

    async def _schedule_task_reminder(self, task: Dict[str, Any], date: str) -> Optional[str]:
        trigger_ts = self._build_task_trigger_ts(date, task.get("execution_time"))
        if trigger_ts is None:
            return None
        if trigger_ts <= time.time():
            return None
        title = str(task.get("title") or "每日任务").strip()
        message = f"我来盯你一下，该开始「{title}」了。"
        try:
            return await self._schedule_message(
                message,
                trigger_ts,
                metadata={
                    "source": "daily_task",
                    "task_id": str(task.get("id") or "").strip(),
                    "task_title": title,
                    "task_category": str(task.get("category") or "").strip(),
                    "task_date": str(date or "").strip(),
                },
            )
        except Exception:
            return None

    async def _refresh_task_reminder(
        self, *, task: Dict[str, Any], date: str, old_reminder_id: Any
    ) -> Optional[str]:
        await self._cancel_task_reminder(old_reminder_id)
        return await self._schedule_task_reminder(task, date)

    def _validate_daily_task(self, task: DailyTask) -> None:
        if not task.title.strip():
            raise ValueError("任务标题不能为空")
        if task.category not in {"timed", "untimed"}:
            raise ValueError("category 仅支持 timed/untimed")
        if task.category == "timed":
            exec_min = self._parse_hhmm_minutes(task.execution_time)
            if exec_min is None:
                raise ValueError("timed 任务必须提供 execution_time(HH:MM)")
            start_min = self._parse_hhmm_minutes(task.window_start)
            end_min = self._parse_hhmm_minutes(task.window_end)
            if start_min is not None and end_min is not None:
                if start_min <= end_min:
                    in_window = start_min <= exec_min <= end_min
                else:
                    in_window = exec_min >= start_min or exec_min <= end_min
                if not in_window:
                    raise ValueError("execution_time 必须位于 window_start/window_end 区间内")

    def _enrich_task_runtime(self, task: Dict[str, Any], category: str) -> Dict[str, Any]:
        now_dt = time.localtime()
        now_minutes = now_dt.tm_hour * 60 + now_dt.tm_min
        item = dict(task)
        item["category"] = category
        item["is_completed"] = str(item.get("status")) == "completed"
        item["is_overdue"] = False
        item["minutes_to_execution"] = None
        exec_min = self._parse_hhmm_minutes(item.get("execution_time"))
        if category == "timed" and exec_min is not None:
            delta = exec_min - now_minutes
            item["minutes_to_execution"] = delta
            if (
                delta < -max(5, int(item.get("duration_minutes", 30) or 30))
                and not item["is_completed"]
            ):
                item["is_overdue"] = True
        return item

    def _build_task_focus(
        self,
        *,
        now_ts: float,
        timed_tasks: List[Dict[str, Any]],
        untimed_tasks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        pending_timed = [t for t in timed_tasks if str(t.get("status")) == "pending"]
        pending_untimed = [
            t for t in untimed_tasks if str(t.get("status")) == "pending"
        ]
        due_soon = sorted(
            [
                t
                for t in pending_timed
                if t.get("minutes_to_execution") is not None
                and t.get("minutes_to_execution") <= 30
            ],
            key=lambda x: x.get("minutes_to_execution", 99999),
        )
        overdue = [t for t in pending_timed if t.get("is_overdue")]
        return {
            "generated_at": now_ts,
            "pending_total": len(pending_timed) + len(pending_untimed),
            "timed_pending": len(pending_timed),
            "untimed_pending": len(pending_untimed),
            "timed_due_soon": due_soon[:3],
            "timed_overdue": overdue[:3],
        }


def build_daily_task_snapshot(record: Dict[str, Any]) -> Dict[str, Any]:
    data = record if isinstance(record, dict) else {}
    raw = data.get("daily_tasks")
    if not isinstance(raw, dict):
        raw = {}
    timed = raw.get("timed") if isinstance(raw.get("timed"), list) else []
    untimed = raw.get("untimed") if isinstance(raw.get("untimed"), list) else []
    timed_pending = [
        item for item in timed if str(item.get("status", "pending")) == "pending"
    ]
    untimed_pending = [
        item for item in untimed if str(item.get("status", "pending")) == "pending"
    ]
    now_dt = time.localtime()
    now_min = now_dt.tm_hour * 60 + now_dt.tm_min
    due_soon = []
    for item in timed_pending:
        text = str(item.get("execution_time") or "").strip()
        if ":" not in text:
            continue
        try:
            hour_str, minute_str = text.split(":", 1)
            t_min = int(hour_str) * 60 + int(minute_str)
        except ValueError:
            continue
        delta = t_min - now_min
        if 0 <= delta <= 30:
            due_soon.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "minutes_to_execution": delta,
                }
            )
    due_soon.sort(key=lambda x: x.get("minutes_to_execution", 99999))
    return {
        "generated_at": time.time(),
        "timed_total": len(timed),
        "untimed_total": len(untimed),
        "timed_pending": len(timed_pending),
        "untimed_pending": len(untimed_pending),
        "timed_due_soon": due_soon[:3],
        "timed": timed,
        "untimed": untimed,
    }
