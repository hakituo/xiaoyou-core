import json
from pathlib import Path

import pytest

from core.services.workspace.daily_task_service import WorkspaceDailyTaskService


class _FakeDailyManager:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, date: str) -> str:
        return str(self.root / f"{date}.json")

    def get_record(self, date: str):
        file_path = Path(self._get_file_path(date))
        if not file_path.exists():
            return {}
        return json.loads(file_path.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_replace_daily_plan_replaces_generated_pending_tasks_only(monkeypatch, tmp_path):
    manager = _FakeDailyManager(tmp_path / "daily")

    date = "2099-12-31"
    seed_path = Path(manager._get_file_path(date))
    seed_path.write_text(
        json.dumps(
            {
                "daily_tasks": {
                    "timed": [
                        {
                            "id": "planner-old",
                            "title": "旧计划任务",
                            "category": "timed",
                            "source": "planner_ai",
                            "execution_time": "08:00",
                            "window_start": "08:00",
                            "window_end": "09:00",
                            "duration_minutes": 60,
                            "status": "pending",
                            "reminder_id": "reminder-old-1",
                        },
                        {
                            "id": "completed-old",
                            "title": "已完成计划任务",
                            "category": "timed",
                            "source": "planner_ai",
                            "execution_time": "07:00",
                            "window_start": "07:00",
                            "window_end": "07:30",
                            "duration_minutes": 30,
                            "status": "completed",
                            "reminder_id": None,
                        },
                        {
                            "id": "study-old",
                            "title": "自动学习任务",
                            "category": "timed",
                            "source": "study_progress",
                            "execution_time": "10:00",
                            "window_start": "10:00",
                            "window_end": "11:00",
                            "duration_minutes": 60,
                            "status": "pending",
                            "reminder_id": "reminder-old-2",
                        },
                    ],
                    "untimed": [
                        {
                            "id": "manual-keep",
                            "title": "手动保留任务",
                            "category": "untimed",
                            "source": "manual",
                            "duration_minutes": 20,
                            "status": "pending",
                        }
                    ],
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("core.services.daily.manager.get_daily_manager", lambda: manager)

    scheduled = []
    deleted = []
    memories = []

    async def _get_study_overview():
        return {}

    async def _write_study_text(path: str, content: str, append: bool):
        return {"path": path, "content": content, "append": append}

    async def _schedule_message(message: str, trigger_ts: float, metadata=None, type="text"):
        scheduled.append({"message": message, "trigger_ts": trigger_ts, "metadata": metadata, "type": type})
        return f"msg-{len(scheduled)}"

    async def _delete_message(msg_id: str):
        deleted.append(msg_id)
        return True

    async def _append_workspace_memory(content, category, topics, metadata=None):
        memories.append(
            {
                "content": content,
                "category": category,
                "topics": topics,
                "metadata": metadata or {},
            }
        )

    service = WorkspaceDailyTaskService(
        base_dir=tmp_path / "workspace",
        get_study_overview=_get_study_overview,
        write_study_text=_write_study_text,
        schedule_message=_schedule_message,
        delete_message=_delete_message,
        append_workspace_memory=_append_workspace_memory,
    )

    result = await service.replace_daily_plan(
        date=date,
        tasks=[
            {
                "title": "新的深度学习块",
                "category": "timed",
                "execution_time": "21:00",
                "window_start": "21:00",
                "window_end": "22:00",
                "duration_minutes": 60,
            }
        ],
        source="planner_ai",
        origin="帮我重新安排今天",
    )

    saved_record = manager.get_record(date)
    timed_titles = [item["title"] for item in saved_record["daily_tasks"]["timed"]]
    untimed_titles = [item["title"] for item in saved_record["daily_tasks"]["untimed"]]

    assert "旧计划任务" not in timed_titles
    assert "自动学习任务" not in timed_titles
    assert "已完成计划任务" in timed_titles
    assert "新的深度学习块" in timed_titles
    assert "手动保留任务" in untimed_titles
    assert deleted == ["reminder-old-1", "reminder-old-2"]
    assert scheduled and scheduled[0]["metadata"]["source"] == "daily_task"
    assert result["timed_count"] == 1
    assert result["removed_pending"] == 2
    assert memories and memories[-1]["category"] == "workspace_daily_task"
