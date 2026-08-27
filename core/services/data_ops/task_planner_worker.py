from typing import Any, Dict

from core.services.data_ops.summary_worker import _normalize_date, _run_async_from_sync
from core.services.study.service import get_study_service
from core.services.workspace.service import get_workspace_service


class TaskPlannerWorker:
    def plan_daily_tasks(
        self, *, date: str = "", force: bool = False
    ) -> Dict[str, Any]:
        date_key = _normalize_date(date)
        workspace = get_workspace_service()
        study_digest = get_study_service().get_study_daily_digest(date_key) or {}

        generation = _run_async_from_sync(
            workspace.generate_daily_tasks_from_progress(date=date_key, force=force)
        )
        panel = _run_async_from_sync(
            workspace.get_daily_task_panel(date=date_key)
        )

        return {
            "date": date_key,
            "generation": generation,
            "panel": panel,
            "study_blueprint": (study_digest or {}).get("next_day_blueprint") or {},
        }
