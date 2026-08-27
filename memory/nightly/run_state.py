"""nightly 按目标日期持久化的运行状态。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, Optional

from core.utils.atomic_io import safe_json_dump, safe_json_load
from core.utils.data_paths import get_user_data_dir
from core.utils.time_utils import now_iso


class NightlyRunStateStore:
    """记录每个目标日期的 scope/global 完成进度，支持重启后续跑。"""

    def __init__(self, state_path: Optional[Path] = None) -> None:
        self.state_path = state_path or (
            get_user_data_dir() / "nightly" / "run_state.json"
        )
        self._lock = threading.RLock()
        # 仅用于阻止同一进程内并发执行；磁盘上的 running 状态允许新进程续跑。
        self._active_targets: set[str] = set()

    def begin(self, target_date: str, trigger_reason: str) -> str:
        """尝试开始目标日期任务，返回 run/completed/active。"""
        with self._lock:
            data = self._load()
            run = self._get_run(data, target_date)
            if run.get("status") == "completed":
                return "completed"
            if target_date in self._active_targets:
                return "active"

            self._active_targets.add(target_date)
            timestamp = now_iso()
            run.setdefault("started_at", timestamp)
            run.setdefault("completed_scopes", [])
            run.setdefault("scope_errors", {})
            run.setdefault("global_completed", False)
            run["status"] = "running"
            run["trigger_reason"] = trigger_reason
            run["updated_at"] = timestamp
            self._save(data)
            return "run"

    def get_completed_scopes(self, target_date: str) -> set[str]:
        with self._lock:
            run = self._get_run(self._load(), target_date)
            return {
                str(scope)
                for scope in run.get("completed_scopes", [])
                if str(scope).strip()
            }

    def is_global_completed(self, target_date: str) -> bool:
        with self._lock:
            run = self._get_run(self._load(), target_date)
            return bool(run.get("global_completed"))

    def mark_scope_completed(self, target_date: str, scope: str) -> None:
        with self._lock:
            data = self._load()
            run = self._get_run(data, target_date)
            completed = {
                str(item)
                for item in run.get("completed_scopes", [])
                if str(item).strip()
            }
            completed.add(scope)
            run["completed_scopes"] = sorted(completed)
            errors = dict(run.get("scope_errors") or {})
            errors.pop(scope, None)
            run["scope_errors"] = errors
            run["updated_at"] = now_iso()
            self._save(data)

    def mark_scope_failed(self, target_date: str, scope: str, error: str) -> None:
        with self._lock:
            data = self._load()
            run = self._get_run(data, target_date)
            errors = dict(run.get("scope_errors") or {})
            errors[scope] = str(error)[:500]
            run["scope_errors"] = errors
            run["updated_at"] = now_iso()
            self._save(data)

    def mark_global_completed(self, target_date: str) -> None:
        with self._lock:
            data = self._load()
            run = self._get_run(data, target_date)
            run["global_completed"] = True
            run.pop("global_error", None)
            run["updated_at"] = now_iso()
            self._save(data)

    def mark_global_failed(self, target_date: str, error: str) -> None:
        with self._lock:
            data = self._load()
            run = self._get_run(data, target_date)
            run["global_error"] = str(error)[:500]
            run["updated_at"] = now_iso()
            self._save(data)

    def finish(self, target_date: str, *, completed: bool) -> None:
        with self._lock:
            data = self._load()
            run = self._get_run(data, target_date)
            timestamp = now_iso()
            run["status"] = "completed" if completed else "partial"
            run["updated_at"] = timestamp
            if completed:
                run["completed_at"] = timestamp
            self._active_targets.discard(target_date)
            self._save(data)

    def release(self, target_date: str) -> None:
        """异常退出时释放进程内占用，磁盘状态保留为 partial。"""
        with self._lock:
            self._active_targets.discard(target_date)

    def _load(self) -> Dict[str, Any]:
        raw = safe_json_load(self.state_path, default={})
        if not isinstance(raw, dict):
            raw = {}
        runs = raw.get("runs")
        if not isinstance(runs, dict):
            raw["runs"] = {}
        return raw

    @staticmethod
    def _get_run(data: Dict[str, Any], target_date: str) -> Dict[str, Any]:
        runs = data.setdefault("runs", {})
        run = runs.get(target_date)
        if not isinstance(run, dict):
            run = {}
            runs[target_date] = run
        return run

    def _save(self, data: Dict[str, Any]) -> None:
        runs = data.get("runs") or {}
        if isinstance(runs, dict) and len(runs) > 14:
            keep = set(sorted(runs)[-14:])
            data["runs"] = {key: value for key, value in runs.items() if key in keep}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        safe_json_dump(data, self.state_path)
