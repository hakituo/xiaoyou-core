import os
import json
import time
import asyncio
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from typing import List, Dict, Optional, Any

from core.utils.common import get_project_root
from core.utils.data_paths import get_user_data_dir, get_user_reminders_file
from config.integrated_config import get_settings

from core.utils.logger import get_logger
from core.services.workspace.models import DiaryEntry, ScheduledMessage
from core.services.workspace.daily_task_service import WorkspaceDailyTaskService
from core.services.workspace.reminder_store import WorkspaceReminderStore
from core.services.workspace.reminder_service import WorkspaceReminderService
from core.services.workspace.study_bridge import collect_study_overview
from core.utils.async_locks import LazyAsyncLock
from core.utils.time_utils import get_current_time

logger = get_logger("WorkspaceService")
ALLOWED_STUDY_ACTIONS = {
    "list",
    "read_text",
    "write_text",
    "append_text",
    "read_json",
    "write_json",
    "mkdir",
    "exists",
    "highlight",
}
STUDY_ACTIONS_REQUIRE_PATH = {
    "read_text",
    "write_text",
    "append_text",
    "read_json",
    "write_json",
    "mkdir",
    "exists",
    "highlight",
}
STUDY_ACTIONS_REQUIRE_CONTENT = {"write_text", "append_text"}


class WorkspaceService:
    """
    个人工作区服务
    管理 Aveline 的日记、待办事项、定时消息等“可操控”文件
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(WorkspaceService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._project_root = get_project_root()
        self._base_dir = get_user_data_dir()
        self._reminders_file = get_user_reminders_file()
        self._reminders_lock = LazyAsyncLock()  # P2-8: 改用 LazyAsyncLock 避免在 __init__ 中创建 asyncio.Lock（无事件循环时会出错）
        self._reminder_store = WorkspaceReminderStore(self._reminders_file)
        self._reminder_service = WorkspaceReminderService(
            store=self._reminder_store,
            lock=self._reminders_lock,
            append_workspace_memory=self._append_workspace_memory,
        )
        self._study_root = self._resolve_study_root()
        self._study_lock = LazyAsyncLock()

        # 确保基础目录存在
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._daily_task_service = WorkspaceDailyTaskService(
            base_dir=self._base_dir,
            get_study_overview=self.get_study_linked_overview,
            write_study_text=self.write_study_text,
            schedule_message=self.schedule_message,
            delete_message=self.delete_message,
            append_workspace_memory=self._append_workspace_memory,
        )

        self._initialized = True

    # --- Status Management (Integrated) ---

    async def add_user_status(
        self, name: str, description: str, duration_days: Optional[int] = None
    ) -> str:
        """添加用户持续性状态"""
        from core.services.workspace.status_manager import get_user_status_manager

        manager = get_user_status_manager()
        result = await asyncio.to_thread(
            manager.add_status, name, description, duration_days
        )
        await self._append_workspace_memory(
            content=f"新增状态: {name} - {description}",
            category="workspace_status",
            topics=["workspace", "status"],
            metadata={"name": name, "duration_days": duration_days},
        )
        return result

    async def remove_user_status(self, name: str) -> str:
        """移除用户持续性状态"""
        from core.services.workspace.status_manager import get_user_status_manager

        manager = get_user_status_manager()
        result = await asyncio.to_thread(manager.remove_status, name)
        await self._append_workspace_memory(
            content=f"移除状态: {name}",
            category="workspace_status",
            topics=["workspace", "status"],
            metadata={"name": name},
        )
        return result

    async def get_user_status_summary(self) -> str:
        """获取用户状态摘要"""
        from core.services.workspace.status_manager import get_user_status_manager

        manager = get_user_status_manager()
        return await asyncio.to_thread(manager.get_status_summary)

    async def get_user_status_storage_path(self) -> str:
        from core.services.workspace.status_manager import get_user_status_manager

        manager = get_user_status_manager()
        return await asyncio.to_thread(manager.get_storage_path)

    # --- Diary Management (Delegated to JournalService) ---

    async def write_diary(
        self,
        content: str,
        mood: str = "neutral",
        thought: str = None,
        type: str = "daily",
    ) -> str:
        """写入日记 (Delegate to JournalService)"""
        from core.services.journal.service import get_journal_service

        return await get_journal_service().write_entry(
            content, mood, thought, type
        )

    async def get_todays_diary(self) -> List[DiaryEntry]:
        """获取今天的日记列表"""
        return await self.get_diary(date=None)

    async def get_diary(
        self, date: Optional[str] = None, limit: Optional[int] = None
    ) -> List[DiaryEntry]:
        from core.services.journal.service import get_journal_service

        entries = await get_journal_service().get_entries(date)

        # Convert JournalEntry to DiaryEntry for backward compatibility
        result = []
        for e in entries:
            # 透传 source 字段，前端按作者(user/aveline/ling)分组显示
            result.append(
                DiaryEntry(
                    id=e.id,
                    timestamp=e.timestamp,
                    time_str=e.time_str,
                    type=e.type,
                    content=e.content,
                    thought=e.thought,
                    mood=e.mood,
                    tags=e.tags,
                    source=e.source,
                )
            )

        if limit and limit > 0:
            return result[-limit:]
        return result

    async def get_diary_summary(
        self, date: Optional[str] = None, persona: str = "aveline"
    ) -> Optional[Dict[str, Any]]:
        from core.services.journal.service import get_journal_service

        summary = await get_journal_service().get_daily_summary(date, persona=persona)
        return summary.model_dump() if summary else None

    async def generate_diary_summary(
        self, date: Optional[str] = None, force: bool = False
    ) -> Dict[str, Any]:
        from core.services.journal.service import get_journal_service

        summary = await get_journal_service().generate_daily_summary(date, force)
        return summary.model_dump()

    async def get_daily_workspace_snapshot(
        self, date: Optional[str] = None, diary_limit: int = 20
    ) -> Dict[str, Any]:
        from core.services.workspace.snapshot import WorkspaceSnapshotBuilder

        reminders = await self._read_reminders()
        status_storage_path = await self.get_user_status_storage_path()
        builder = WorkspaceSnapshotBuilder()
        return await builder.build(
            date=date,
            diary_limit=diary_limit,
            reminders=reminders,
            status_storage_path=status_storage_path,
        )

    async def _get_recent_conversation_history(
        self, conversation_id: str, history_limit: int = 20
    ) -> List[Dict[str, Any]]:
        try:
            from core.agents.chat_agent import get_default_chat_agent

            cid = str(conversation_id or "").strip() or "default_user"
            limit = max(1, min(int(history_limit or 20), 200))
            agent = get_default_chat_agent()
            mm = agent._get_memory_manager(cid)
            history: List[Dict[str, Any]] = []
            fetch_limit = limit + 1
            if hasattr(mm, "get_recent_history"):
                try:
                    history = await mm.get_recent_history(cid, fetch_limit)
                except TypeError:
                    history = await mm.get_recent_history(cid, fetch_limit)
            elif hasattr(mm, "get_history"):
                raw = await asyncio.to_thread(mm.get_history, limit=fetch_limit)
                if isinstance(raw, list):
                    history = raw
            if len(history) > limit:
                history = history[-limit:]
            result = []
            for item in history:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "").strip().lower()
                if role not in {"user", "assistant"}:
                    continue
                result.append(
                    {
                        "role": role,
                        "content": str(item.get("content") or "").strip(),
                        "timestamp": float(item.get("timestamp") or 0.0),
                    }
                )
            return result
        except Exception:
            return []

    async def get_learning_panel_bundle(
        self,
        *,
        conversation_id: str = "default_user",
        date: Optional[str] = None,
        history_limit: int = 20,
    ) -> Dict[str, Any]:
        from core.character.managers.dependency_manager import get_dependency_manager
        from core.emotion.manager import get_emotion_manager
        from core.services.life_simulation.service import get_life_simulation_service
        from core.services.study.service import get_study_service

        snapshot = await self.get_daily_workspace_snapshot(
            date=date, diary_limit=max(10, min(int(history_limit or 20), 200))
        )
        study_overview = await self.get_study_linked_overview()
        recent_chat = await self._get_recent_conversation_history(
            conversation_id=conversation_id, history_limit=history_limit
        )
        diary_summary = await self.get_diary_summary(date=date)
        status_summary = await self.get_user_status_summary()

        dep_manager = get_dependency_manager()
        intimacy = float(dep_manager.get_intimacy_level() or 0.0)
        emo_state = get_emotion_manager().get_current_state("user")
        life_state = get_life_simulation_service().get_state()
        study_stats = get_study_service().get_dictionary_stats()

        primary_emotion = "neutral"
        if emo_state and getattr(emo_state, "primary_emotion", None):
            primary_emotion = str(emo_state.primary_emotion.value)

        return {
            "conversation_id": str(conversation_id or "").strip() or "default_user",
            "date": str((snapshot or {}).get("date") or ""),
            "study_panel": study_overview,
            "user_panel": {
                "display_name": str(get_settings().user.display_name or "").strip() or "用户",
                "intimacy": intimacy,
                "status_summary": status_summary,
                "life_state": life_state,
                "study_stats": study_stats,
            },
            "aveline_panel": {
                "emotion": primary_emotion,
                "energy": float((life_state or {}).get("energy", 100)),
                "mood": (life_state or {}).get("mood", 100),
            },
            "workspace_snapshot": snapshot,
            "recent_chat_history": recent_chat,
            "diary_summary": diary_summary,
            "journal_context": {
                "portrait": ((snapshot or {}).get("status") or {}).get("summary", ""),
                "recent_diary": (snapshot or {}).get("recent_diary") or [],
                "recent_chat": recent_chat,
                "study_sessions": (((snapshot or {}).get("portrait") or {}).get("study") or {}).get("sessions") or [],
            },
        }

    async def get_study_root_path(self) -> str:
        tool = self._build_study_data_tool()
        return str(tool._base_dir)

    async def list_study_items(
        self, relative_path: str = ".", recursive: bool = False, limit: int = 200
    ) -> Dict[str, Any]:
        if recursive:
            return await self._list_study_items_recursive(relative_path, limit)
        result = await self._run_study_data_tool("list", path=relative_path)
        if isinstance(result, str):
            raise ValueError(result)
        root = await self.get_study_root_path()
        raw_items = result.get("items", []) if isinstance(result, dict) else []
        items: List[Dict[str, Any]] = []
        for item in raw_items:
            name = str(item.get("name", ""))
            rel = (
                name
                if relative_path in [".", "", "/"]
                else f"{str(relative_path).strip('/').strip()}".rstrip("/") + "/" + name
            )
            items.append(
                {
                    "name": name,
                    "path": rel.replace("\\", "/"),
                    "is_dir": str(item.get("type")) == "dir",
                    "size": int(item.get("size", 0) or 0),
                    "modified_at": float(item.get("mtime", 0) or 0),
                }
            )
        return {
            "root": root,
            "current": str(relative_path or "."),
            "items": items,
        }

    async def read_study_text(self, relative_path: str, max_chars: int = 200000) -> Dict[str, Any]:
        result = await self._run_study_data_tool("read_text", path=relative_path)
        if isinstance(result, str) and result.startswith("Error:"):
            if "不存在" in result:
                raise FileNotFoundError(result)
            raise ValueError(result)
        content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        if max_chars > 0:
            content = content[:max_chars]
        return {
            "path": str(relative_path).replace("\\", "/"),
            "content": content,
        }

    async def write_study_text(
        self, relative_path: str, content: str, append: bool = False
    ) -> Dict[str, Any]:
        action = "append_text" if append else "write_text"
        async with self._study_lock:
            result = await self._run_study_data_tool(
                action, path=relative_path, content=content
            )
        if isinstance(result, str) and result.startswith("Error:"):
            raise ValueError(result)
        return {
            "path": str(relative_path).replace("\\", "/"),
            "written": True,
            "appended": append,
        }

    async def get_study_linked_overview(self) -> Dict[str, Any]:
        return await collect_study_overview(self)

    async def run_study_data_action(
        self,
        action: str,
        path: Optional[str] = None,
        content: Optional[str] = None,
        json_content: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._validate_study_action_inputs(action, path, content, json_content)
        result = await self._run_study_data_tool(
            action, path=path, content=content, json_content=json_content
        )
        if isinstance(result, str) and result.startswith("Error:"):
            raise ValueError(result)
        auto_record = None
        if action in {"write_text", "append_text"} and path and content:
            auto_record = await self._auto_record_study_file_write(path, content)
            preview = " ".join(str(content).strip().split())[:160]
            await self._append_workspace_memory(
                content=f"Study 文件{action}: {path} | {preview}",
                category="workspace_study",
                topics=["workspace", "study", action],
                metadata={"path": path, "action": action},
            )
        elif action == "write_json" and path:
            await self._append_workspace_memory(
                content=f"Study 文件write_json: {path}",
                category="workspace_study",
                topics=["workspace", "study", "write_json"],
                metadata={"path": path, "action": action},
            )
        return {
            "action": action,
            "path": path,
            "result": result,
            "auto_record": auto_record,
        }

    async def record_study_progress(
        self,
        topic: str,
        content: str,
        relative_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        from core.services.daily.manager import get_daily_manager

        daily_result = await asyncio.to_thread(
            get_daily_manager().record_study, topic, content
        )
        file_result = None
        if relative_path:
            ts = time.strftime("%H:%M:%S")
            line = f"[{ts}] {topic}: {content}\n"
            file_result = await self.write_study_text(relative_path, line, append=True)
        return {"daily_record": daily_result, "file_record": file_result}

    async def get_daily_task_panel(self, date: Optional[str] = None) -> Dict[str, Any]:
        return await self._daily_task_service.get_daily_task_panel(date=date)

    async def generate_daily_tasks_from_progress(
        self, date: Optional[str] = None, force: bool = False
    ) -> Dict[str, Any]:
        return await self._daily_task_service.generate_daily_tasks_from_progress(
            date=date, force=force
        )

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
        return await self._daily_task_service.upsert_daily_task(
            title=title,
            category=category,
            execution_time=execution_time,
            window_start=window_start,
            window_end=window_end,
            duration_minutes=duration_minutes,
            linked_study_topic=linked_study_topic,
            linked_study_path=linked_study_path,
            notes=notes,
            task_id=task_id,
            date=date,
        )

    async def update_daily_task_status(
        self,
        task_id: str,
        status: str,
        date: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self._daily_task_service.update_daily_task_status(
            task_id=task_id,
            status=status,
            date=date,
        )

    async def delete_daily_task(self, task_id: str, date: Optional[str] = None) -> Dict[str, Any]:
        return await self._daily_task_service.delete_daily_task(
            task_id=task_id,
            date=date,
        )

    async def replace_daily_plan(
        self,
        *,
        tasks: List[Dict[str, Any]],
        date: Optional[str] = None,
        source: str = "planner_ai",
        origin: str = "",
    ) -> Dict[str, Any]:
        return await self._daily_task_service.replace_daily_plan(
            tasks=tasks,
            date=date,
            source=source,
            origin=origin,
        )

    # --- Scheduled Messages (Reminders) ---

    async def schedule_message(
        self,
        message: str,
        trigger_ts: float,
        type: str = "text",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        return await self._reminder_service.schedule_message(
            message=message,
            trigger_ts=trigger_ts,
            message_type=type,
            metadata=metadata,
        )

    async def schedule_recurring_message(
        self,
        message: str,
        first_trigger_ts: float,
        recurrence: str = "none",
        time_of_day: str = "",
        weekdays: Optional[List[int]] = None,
        type: str = "text",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """P1-5: 调度周期性提醒。"""
        return await self._reminder_service.schedule_recurring_message(
            message=message,
            first_trigger_ts=first_trigger_ts,
            recurrence=recurrence,
            time_of_day=time_of_day,
            weekdays=weekdays,
            message_type=type,
            metadata=metadata,
        )

    async def get_pending_messages(self) -> List[ScheduledMessage]:
        return await self._reminder_service.get_pending_messages()

    async def check_due_messages(
        self, *, mark_completed: bool = True
    ) -> List[ScheduledMessage]:
        return await self._reminder_service.check_due_messages(
            mark_completed=mark_completed
        )

    async def complete_message(
        self, msg_id: str, *, triggered_at: Optional[float] = None
    ) -> bool:
        return await self._reminder_service.complete_message(
            msg_id, triggered_at=triggered_at
        )

    async def delete_message(self, msg_id: str) -> bool:
        return await self._reminder_service.delete_message(msg_id)

    # --- Internal Helpers ---

    async def _read_reminders(self) -> List[Dict[str, Any]]:
        async with self._reminders_lock:
            return await self._reminder_store.read()

    def _resolve_study_root(self) -> Path:
        settings = get_settings()
        study_root = str(getattr(settings, "study", None).study_root or "").strip()
        if study_root:
            root = Path(study_root).expanduser()
            if not root.is_absolute():
                root = (self._project_root / root).resolve()
            else:
                root = root.resolve()
            return root
        return (self._project_root / "Study").resolve()

    def _resolve_study_path(self, relative_path: str) -> Path:
        rel = str(relative_path or ".").strip()
        candidate = Path(rel)
        target = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self._study_root / candidate).resolve()
        )
        base = str(self._study_root)
        target_str = str(target)
        if target_str == base:
            return target
        if not target_str.startswith(base + os.sep):
            raise ValueError(f"禁止访问 Study 目录之外的路径: {target_str}")
        return target

    def _build_study_data_tool(self):
        from core.tools.study_data_tool import StudyDataTool

        return StudyDataTool()

    async def _run_study_data_tool(
        self,
        action: str,
        path: Optional[str] = None,
        content: Optional[str] = None,
        json_content: Optional[Dict[str, Any]] = None,
    ) -> Any:
        tool = self._build_study_data_tool()
        raw = await tool._run(
            action=action, path=path, content=content, json_content=json_content
        )
        text = str(raw).strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except Exception:
                return text
        return text

    def _validate_study_action_inputs(
        self,
        action: str,
        path: Optional[str],
        content: Optional[str],
        json_content: Optional[Dict[str, Any]],
    ) -> None:
        if action not in ALLOWED_STUDY_ACTIONS:
            raise ValueError(f"不支持的 Study action: {action}")
        if action in STUDY_ACTIONS_REQUIRE_PATH and not str(path or "").strip():
            raise ValueError(f"{action} 需要 path")
        if action in STUDY_ACTIONS_REQUIRE_CONTENT and content is None:
            raise ValueError(f"{action} 需要 content")
        if action == "write_json" and json_content is None:
            raise ValueError("write_json 需要 json_content")

    async def _append_workspace_memory(
        self,
        content: str,
        category: str,
        topics: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            from memory.weighted_memory_manager import get_weighted_memory_manager

            manager = await asyncio.to_thread(get_weighted_memory_manager, "default_user")
            if not manager:
                return
            await asyncio.to_thread(
                partial(
                    manager.add_memory,
                    content=content,
                    source="workspace",
                    category=category,
                    topics=topics,
                    metadata=metadata or {},
                )
            )
        except Exception as e:
            logger.warning(f"写入 workspace 联动记忆失败: {e}")

    async def _list_study_items_recursive(
        self, relative_path: str, limit: int
    ) -> Dict[str, Any]:
        root = Path(await self.get_study_root_path())
        start = self._resolve_study_path(relative_path)
        if not root.exists() or not start.exists():
            current = "." if relative_path in {"", ".", "/"} else str(relative_path)
            return {
                "root": str(root),
                "current": current.replace("\\", "/"),
                "items": [],
            }

        def _walk() -> List[Dict[str, Any]]:
            items: List[Dict[str, Any]] = []
            for child in sorted(start.rglob("*"), key=lambda p: str(p).lower()):
                if len(items) >= max(1, limit):
                    break
                stat = child.stat()
                items.append(
                    {
                        "name": child.name,
                        "path": str(child.relative_to(root)).replace("\\", "/"),
                        "is_dir": child.is_dir(),
                        "size": stat.st_size,
                        "modified_at": stat.st_mtime,
                    }
                )
            return items

        items = await asyncio.to_thread(_walk)
        return {
            "root": str(root),
            "current": str(start.relative_to(root)).replace("\\", "/"),
            "items": items,
        }

    async def _auto_record_study_file_write(self, relative_path: str, content: str) -> Optional[Dict[str, Any]]:
        from core.services.daily.manager import get_daily_manager

        suffix = Path(relative_path).suffix.lower()
        if suffix not in {".md", ".txt"}:
            return None
        preview = " ".join(str(content).strip().split())
        if not preview:
            return None
        preview = preview[:120]
        topic = str(relative_path).replace("\\", "/").split("/")[0] or "study"
        daily_result = await asyncio.to_thread(
            get_daily_manager().record_study, topic, f"文件更新: {relative_path} | {preview}"
        )
        return {"topic": topic, "daily_record": daily_result}

    # --- 源码文件操作（供 auto_heal 使用，安全沙箱） ---

    ALLOWED_SOURCE_DIRS = {"core", "config", "routers", "memory"}
    ALLOWED_SOURCE_EXTENSIONS = {".py", ".yaml", ".yml", ".json", ".toml"}

    def _resolve_source_path(self, relative_path: str) -> Path:
        """解析源码文件路径，严格限制在项目允许的源码目录内"""
        rel = str(relative_path or "").strip().replace("\\", "/")
        if not rel:
            raise ValueError("路径不能为空")

        parts = rel.split("/")
        if not parts or parts[0] not in self.ALLOWED_SOURCE_DIRS:
            raise ValueError(f"禁止访问源码目录之外的路径: {rel}（允许: {', '.join(sorted(self.ALLOWED_SOURCE_DIRS))}）")

        if ".." in parts:
            raise ValueError(f"禁止路径穿越: {rel}")

        target = (self._project_root / rel).resolve()
        project_str = str(self._project_root.resolve())
        target_str = str(target)
        if not target_str.startswith(project_str + os.sep) and target_str != project_str:
            raise ValueError(f"禁止访问项目目录之外的路径: {target_str}")

        if target.suffix.lower() not in self.ALLOWED_SOURCE_EXTENSIONS:
            raise ValueError(f"禁止操作此类型文件: {target.suffix}（允许: {', '.join(sorted(self.ALLOWED_SOURCE_EXTENSIONS))}）")

        return target

    async def read_source_file(self, relative_path: str, max_chars: int = 200000) -> Dict[str, Any]:
        """读取项目源码文件（安全沙箱）"""
        target = self._resolve_source_path(relative_path)
        if not target.exists():
            raise FileNotFoundError(f"文件不存在: {relative_path}")
        if not target.is_file():
            raise ValueError(f"不是文件: {relative_path}")

        def _read():
            return target.read_text(encoding="utf-8")

        content = await asyncio.to_thread(_read)
        if max_chars > 0:
            content = content[:max_chars]
        return {
            "path": relative_path.replace("\\", "/"),
            "content": content,
            "size": len(content),
        }

    async def write_source_file(self, relative_path: str, content: str) -> Dict[str, Any]:
        """写入项目源码文件（安全沙箱，仅限 auto_heal 调用）"""
        target = self._resolve_source_path(relative_path)

        backup_path = str(target) + ".auto_heal_backup"
        if target.exists():
            def _backup():
                existing = target.read_text(encoding="utf-8")
                Path(backup_path).write_text(existing, encoding="utf-8")
                return existing
            original = await asyncio.to_thread(_backup)
        else:
            original = ""  # noqa: F841

        def _write():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        await asyncio.to_thread(_write)

        await self._append_workspace_memory(
            content=f"源码文件修改: {relative_path}",
            category="auto_heal",
            topics=["auto_heal", "source_edit"],
            metadata={"path": relative_path, "has_backup": True},
        )

        return {
            "path": relative_path.replace("\\", "/"),
            "written": True,
            "has_backup": True,
            "backup_path": backup_path,
        }

    async def _get_recent_study_files(self, limit: int = 10) -> List[Dict[str, Any]]:
        root = Path(await self.get_study_root_path())
        if not root.exists():
            return []

        def _collect() -> List[Dict[str, Any]]:
            files = [p for p in root.rglob("*") if p.is_file()]
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            result: List[Dict[str, Any]] = []
            for file_path in files[: max(1, limit)]:
                stat = file_path.stat()
                result.append(
                    {
                        "path": str(file_path.relative_to(root)).replace("\\", "/"),
                        "size": stat.st_size,
                        "modified_at": stat.st_mtime,
                    }
                )
            return result

        return await asyncio.to_thread(_collect)

    async def _get_study_streak_days(self) -> int:
        from core.services.daily.manager import get_daily_manager

        records_root = Path(get_daily_manager().root_dir)

        def _calc() -> int:
            date_to_study: Dict[str, bool] = {}
            for file_path in records_root.rglob("*.json"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    sessions = (data.get("study") or {}).get("sessions") or []
                    if sessions:
                        date_key = str(data.get("date") or "").strip()
                        if not date_key:
                            date_key = file_path.stem
                        try:
                            date_key = datetime.strptime(
                                date_key, "%Y-%m-%d"
                            ).strftime("%Y-%m-%d")
                        except Exception:
                            continue
                        date_to_study[date_key] = True
                except Exception:
                    continue
            if not date_to_study:
                return 0
            streak = 0

            current = get_current_time().date()
            while True:
                key = current.strftime("%Y-%m-%d")
                if key in date_to_study:
                    streak += 1
                    current = current - timedelta(days=1)
                    continue
                break
            return streak

        return await asyncio.to_thread(_calc)

def get_workspace_service() -> WorkspaceService:
    return WorkspaceService()
