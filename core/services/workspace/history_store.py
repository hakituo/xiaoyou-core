import asyncio
import json
import shutil
import time
from datetime import datetime, timedelta
from core.utils.time_utils import get_current_time, now_str
from pathlib import Path
from typing import Any, Dict, Optional

import aiofiles

from config.integrated_config import get_settings


class WorkspaceHistoryStore:
    def __init__(self, history_root: Path):
        self._history_root = Path(history_root).resolve()
        self._history_root.mkdir(parents=True, exist_ok=True)
        self._archive_root = self._history_root / "archive"
        self._archive_root.mkdir(parents=True, exist_ok=True)
        memory_settings = get_settings().memory
        self._last_cleanup_ts = 0.0
        self._last_archive_ts = 0.0
        self._cleanup_interval_seconds = float(
            getattr(memory_settings, "history_cleanup_interval_seconds", 300.0) or 300.0
        )
        self._archive_interval_seconds = float(
            getattr(memory_settings, "history_archive_interval_seconds", 1800.0) or 1800.0
        )
        self._archive_retention_days = int(
            getattr(memory_settings, "history_retention_days", 30) or 30
        )
        self._archive_enabled = bool(
            getattr(memory_settings, "history_auto_archive_enabled", True)
        )
        self._max_event_file_bytes = int(
            getattr(memory_settings, "history_event_file_max_bytes", 2 * 1024 * 1024)
            or (2 * 1024 * 1024)
        )
        self._max_text_chars = int(
            getattr(memory_settings, "history_event_text_max_chars", 3000) or 3000
        )
        self._max_list_items = int(
            getattr(memory_settings, "history_event_list_max_items", 64) or 64
        )
        self._max_dict_items = int(
            getattr(memory_settings, "history_event_dict_max_items", 64) or 64
        )

    def _is_sensitive_key(self, key: str) -> bool:
        lowered = str(key or "").strip().lower()
        if not lowered:
            return False
        sensitive_tokens = (
            "token",
            "secret",
            "password",
            "passwd",
            "api_key",
            "apikey",
            "authorization",
            "cookie",
            "session",
        )
        return any(token in lowered for token in sensitive_tokens)

    def _sanitize_payload(self, payload: Any, depth: int = 0) -> Any:
        if depth > 6:
            return None
        if isinstance(payload, dict):
            clean: Dict[str, Any] = {}
            for idx, (k, v) in enumerate(payload.items()):
                if idx >= self._max_dict_items:
                    break
                key = str(k)
                if self._is_sensitive_key(key):
                    clean[key] = "***"
                else:
                    clean[key] = self._sanitize_payload(v, depth + 1)
            return clean
        if isinstance(payload, list):
            items = payload[: self._max_list_items]
            return [self._sanitize_payload(v, depth + 1) for v in items]
        if isinstance(payload, tuple):
            items = list(payload[: self._max_list_items])
            return [self._sanitize_payload(v, depth + 1) for v in items]
        if isinstance(payload, str):
            text = payload.strip()
            if len(text) > self._max_text_chars:
                return text[: self._max_text_chars] + "...<truncated>"
            return text
        if isinstance(payload, (int, float, bool)) or payload is None:
            return payload
        return str(payload)

    async def _rotate_if_oversize(self, file_path: Path) -> None:
        if self._max_event_file_bytes <= 0:
            return

        def _rotate() -> None:
            if not file_path.exists():
                return
            try:
                size = file_path.stat().st_size
            except Exception:
                return
            if size < self._max_event_file_bytes:
                return
            suffix = now_str("%H%M%S")
            rotated = file_path.with_name(f"{file_path.stem}_{suffix}.jsonl")
            try:
                file_path.rename(rotated)
            except Exception:
                return

        await asyncio.to_thread(_rotate)

    def resolve_date_dir(self, date: str) -> Path:
        parsed = datetime.strptime(date, "%Y-%m-%d")
        return self._history_root / str(parsed.year) / str(parsed.month) / str(parsed.day)

    async def append_daily_task_event(
        self,
        *,
        date: str,
        category: str,
        event_type: str,
        payload: Dict[str, Any],
    ) -> None:
        date_dir = self.resolve_date_dir(date)
        date_dir.mkdir(parents=True, exist_ok=True)
        file_path = date_dir / f"{category}.jsonl"
        await self._rotate_if_oversize(file_path)
        event = {
            "ts": time.time(),
            "date": date,
            "category": category,
            "event": event_type,
            "payload": self._sanitize_payload(payload),
        }
        async with aiofiles.open(file_path, "a", encoding="utf-8") as f:
            await f.write(json.dumps(event, ensure_ascii=False) + "\n")
        await self._maintenance_if_needed()

    async def _maintenance_if_needed(self) -> None:
        await self._cleanup_if_needed()
        await self._archive_if_needed()

    async def _cleanup_if_needed(self) -> None:
        now = time.time()
        if now - self._last_cleanup_ts < self._cleanup_interval_seconds:
            return
        await self.cleanup_empty_files()
        self._last_cleanup_ts = now

    async def _archive_if_needed(self) -> None:
        if not self._archive_enabled:
            return
        now = time.time()
        if now - self._last_archive_ts < self._archive_interval_seconds:
            return
        await self.archive_old_history()
        self._last_archive_ts = now

    async def cleanup_empty_files(self) -> Dict[str, int]:
        def _cleanup() -> Dict[str, int]:
            removed_files = 0
            removed_dirs = 0
            if not self._history_root.exists():
                return {"removed_files": 0, "removed_dirs": 0}
            for path in self._history_root.rglob("*"):
                if path.is_file():
                    try:
                        if path.stat().st_size == 0:
                            path.unlink(missing_ok=True)
                            removed_files += 1
                    except Exception:
                        continue
            all_dirs = [p for p in self._history_root.rglob("*") if p.is_dir()]
            all_dirs.sort(key=lambda p: len(p.parts), reverse=True)
            for d in all_dirs:
                try:
                    next(d.iterdir())
                except StopIteration:
                    try:
                        d.rmdir()
                        removed_dirs += 1
                    except Exception:
                        pass
                except Exception:
                    continue
            return {"removed_files": removed_files, "removed_dirs": removed_dirs}

        return await asyncio.to_thread(_cleanup)

    async def archive_old_history(
        self, retention_days: Optional[int] = None
    ) -> Dict[str, int]:
        keep_days = int(retention_days or self._archive_retention_days or 30)

        def _collect_date_dirs() -> list[Path]:
            collected: list[Path] = []
            for year_or_month_dir in self._history_root.iterdir():
                if not year_or_month_dir.is_dir():
                    continue
                if year_or_month_dir.name == "archive":
                    continue
                if year_or_month_dir.name.isdigit():
                    for month_dir in year_or_month_dir.iterdir():
                        if not month_dir.is_dir():
                            continue
                        if not month_dir.name.isdigit():
                            continue
                        for day_dir in month_dir.iterdir():
                            if day_dir.is_dir() and day_dir.name.isdigit():
                                collected.append(day_dir)
                    continue
                for date_dir in year_or_month_dir.iterdir():
                    if date_dir.is_dir():
                        collected.append(date_dir)
            return collected

        def _archive() -> Dict[str, int]:
            moved_dirs = 0
            moved_files = 0
            errors = 0
            cutoff = get_current_time().date() - timedelta(days=max(1, keep_days))
            if not self._history_root.exists():
                return {"moved_dirs": 0, "moved_files": 0, "errors": 0}
            for date_dir in _collect_date_dirs():
                try:
                    parent = date_dir.parent
                    day = datetime(
                        int(parent.parent.name),
                        int(parent.name),
                        int(date_dir.name),
                    ).date()
                except Exception:
                    try:
                        day = datetime.strptime(date_dir.name, "%Y-%m-%d").date()
                    except Exception:
                        continue
                if day >= cutoff:
                    continue
                try:
                    archive_month = self._archive_root / day.strftime("%Y-%m")
                    archive_month.mkdir(parents=True, exist_ok=True)
                    target = archive_month / day.strftime("%Y-%m-%d")
                    if target.exists():
                        suffix = now_str("%H%M%S")
                        target = archive_month / f"{day.strftime('%Y-%m-%d')}_{suffix}"
                    file_count = len([p for p in date_dir.rglob("*") if p.is_file()])
                    shutil.move(str(date_dir), str(target))
                    moved_dirs += 1
                    moved_files += file_count
                except Exception:
                    errors += 1
            return {
                "moved_dirs": moved_dirs,
                "moved_files": moved_files,
                "errors": errors,
            }

        return await asyncio.to_thread(_archive)
