import asyncio
import concurrent.futures
from datetime import datetime, timedelta
from typing import Any, Dict, List

from core.services.daily.manager import get_daily_manager
from core.services.journal.service import get_journal_service
from core.services.study.service import get_study_service
from core.services.workspace.service import get_workspace_service
from core.utils.time_utils import get_diary_target_date_str


def _normalize_date(date: str) -> str:
    """解析日期字符串；未提供时走统一凌晨归属逻辑"""
    raw = str(date or "").strip()
    if not raw:
        return get_diary_target_date_str()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").strftime("%Y-%m-%d")
    except Exception:
        return get_diary_target_date_str()


def _run_async_from_sync(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=60)
    return asyncio.run(coro)


class DataSummaryWorker:
    def build_daily_digest(
        self, *, date: str = "", include_diary_summary: bool = True
    ) -> Dict[str, Any]:
        date_key = _normalize_date(date)
        daily_record = get_daily_manager().get_record(date_key) or {}
        study_digest = get_study_service().get_study_daily_digest(date_key) or {}
        workspace = get_workspace_service()

        task_panel = _run_async_from_sync(
            workspace.get_daily_task_panel(date=date_key)
        )

        diary_summary = None
        if include_diary_summary:
            summary_obj = _run_async_from_sync(
                get_journal_service().generate_daily_summary(date_key, force=False)
            )
            diary_summary = summary_obj.model_dump() if summary_obj else None

        timed_tasks = list(task_panel.get("timed_tasks") or [])
        untimed_tasks = list(task_panel.get("untimed_tasks") or [])
        tasks_all = timed_tasks + untimed_tasks
        completed = [t for t in tasks_all if str(t.get("status")) == "completed"]
        return {
            "date": date_key,
            "study_digest": study_digest,
            "diary_summary": diary_summary,
            "task_focus": task_panel.get("focus") or {},
            "task_stats": {
                "timed_total": len(timed_tasks),
                "untimed_total": len(untimed_tasks),
                "completed_total": len(completed),
            },
            "daily_record": daily_record,
        }

    def build_weekly_report(self, *, anchor_date: str = "") -> Dict[str, Any]:
        end_date = datetime.strptime(
            _normalize_date(anchor_date), "%Y-%m-%d"
        ).date()
        dates: List[str] = []
        records: List[Dict[str, Any]] = []
        for i in range(6, -1, -1):
            d = end_date - timedelta(days=i)
            key = d.strftime("%Y-%m-%d")
            dates.append(key)
            records.append(get_daily_manager().get_record(key) or {})
        total_sessions = 0
        total_meals = 0
        completed_tasks = 0
        pending_tasks = 0
        top_subjects: Dict[str, int] = {}
        for rec in records:
            study_sessions = ((rec.get("study") or {}).get("sessions") or [])
            total_sessions += len(study_sessions)
            for session in study_sessions:
                topic = str(session.get("topic") or "").strip().lower()
                if topic:
                    top_subjects[topic] = int(top_subjects.get(topic) or 0) + 1
            total_meals += len(rec.get("meals") or [])
            daily_tasks = rec.get("daily_tasks") or {}
            task_items = list(daily_tasks.get("timed") or []) + list(
                daily_tasks.get("untimed") or []
            )
            for task in task_items:
                if str(task.get("status") or "") == "completed":
                    completed_tasks += 1
                else:
                    pending_tasks += 1
        sorted_subjects = sorted(
            top_subjects.items(), key=lambda x: x[1], reverse=True
        )[:5]
        return {
            "range": {"start": dates[0], "end": dates[-1], "days": len(dates)},
            "metrics": {
                "study_sessions": total_sessions,
                "meals_recorded": total_meals,
                "tasks_completed": completed_tasks,
                "tasks_pending": pending_tasks,
            },
            "top_subjects": [
                {"subject": subject, "count": count}
                for subject, count in sorted_subjects
            ],
            "dates": dates,
        }
