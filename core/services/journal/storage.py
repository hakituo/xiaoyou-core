import aiofiles
import asyncio
import hashlib
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from datetime import datetime
import json

from core.utils.data_paths import (
    get_aveline_data_dir,
    get_ling_data_dir,
    get_user_data_dir,
    resolve_data_scope_from_source,
)
from core.utils.logger import get_logger
from core.services.journal.models import (
    JournalEntry,
    DailySummary,
    MonthlySummary,
    DailyPlan,
)

logger = get_logger("JournalStorage")

_DEDUP_WINDOW_SECONDS = 600
_DEDUP_MAX_SCAN_FILES = 40


def _resolve_active_persona_scope() -> str:
    """获取当前活跃 persona 的数据 scope（aveline/ling）"""
    try:
        from core.utils.data_paths import _resolve_scope_from_active_persona
        return _resolve_scope_from_active_persona()
    except Exception:
        return "aveline"


class JournalStorage:
    def __init__(self):
        self._base_dir = get_user_data_dir()
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._summary_cache: Dict[str, Tuple[float, object]] = {}

    def _get_scope_base_dir(self, scope: str) -> Path:
        if scope == "aveline":
            return get_aveline_data_dir()
        if scope == "ling":
            return get_ling_data_dir()
        return self._base_dir

    def _resolve_entry_scope(self, entry: JournalEntry) -> str:
        return resolve_data_scope_from_source(getattr(entry, "source", None), default="user")

    def get_daily_dir(self, date: datetime, scope: str = "user") -> Path:
        base_dir = self._get_scope_base_dir(scope)
        return (
            base_dir
            / "daily"
            / date.strftime("%Y")
            / date.strftime("%m")
            / date.strftime("%d")
        )

    def _get_diary_dir(self, date: datetime, scope: str = "user") -> Path:
        return self.get_daily_dir(date, scope=scope) / "diary"

    def _get_monthly_dir(self, date: datetime, scope: str = None) -> Path:
        if scope is None:
            scope = _resolve_active_persona_scope()
        base_dir = self._get_scope_base_dir(scope)
        return base_dir / "monthly" / date.strftime("%Y") / date.strftime("%m")

    def _compute_entry_signature(self, entry: JournalEntry) -> str:
        content = " ".join(str(entry.content or "").strip().split())
        thought = " ".join(str(entry.thought or "").strip().split())
        tags = "|".join(sorted(str(tag).strip() for tag in (entry.tags or []) if str(tag).strip()))
        raw = f"{entry.type}|{entry.source}|{content}|{thought}|{tags}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    async def _find_recent_duplicate(self, entry: JournalEntry, date: datetime) -> Optional[Path]:
        entry_dir = self._get_diary_dir(date, scope=self._resolve_entry_scope(entry))
        if not entry_dir.exists():
            return None
        target_sig = self._compute_entry_signature(entry)
        target_ts = float(entry.timestamp or 0.0)

        def _scan() -> Optional[Path]:
            files = sorted(
                entry_dir.glob("*.json"),
                key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
                reverse=True,
            )
            for fpath in files[:_DEDUP_MAX_SCAN_FILES]:
                try:
                    raw = json.loads(fpath.read_text(encoding="utf-8"))
                except Exception:
                    continue
                existing_sig = self._compute_entry_signature_from_raw(raw)
                if existing_sig != target_sig:
                    continue
                existing_ts = float(raw.get("timestamp") or 0.0)
                if abs(existing_ts - target_ts) <= _DEDUP_WINDOW_SECONDS:
                    return fpath
            return None

        return await asyncio.to_thread(_scan)

    def _compute_entry_signature_from_raw(self, raw: dict) -> str:
        content = " ".join(str(raw.get("content") or "").strip().split())
        thought = " ".join(str(raw.get("thought") or "").strip().split())
        tags_raw = raw.get("tags") or []
        tags = "|".join(sorted(str(tag).strip() for tag in tags_raw if str(tag).strip()))
        raw_str = f"{raw.get('type', '')}|{raw.get('source', '')}|{content}|{thought}|{tags}"
        return hashlib.md5(raw_str.encode("utf-8")).hexdigest()

    def _invalidate_summary_cache(self, date_key: str) -> None:
        # 清除该日期的所有 scope 缓存
        keys_to_remove = [k for k in self._summary_cache if k.startswith(date_key)]
        for k in keys_to_remove:
            self._summary_cache.pop(k, None)

    async def save_entry(self, entry: JournalEntry, date: datetime) -> str:
        try:
            scope = self._resolve_entry_scope(entry)
            entry_dir = self._get_diary_dir(date, scope=scope)
            entry_dir.mkdir(parents=True, exist_ok=True)

            duplicate_path = await self._find_recent_duplicate(entry, date)
            if duplicate_path is not None:
                return str(duplicate_path)

            filename = f"entry_{date.strftime('%H%M%S')}_{entry.id}.json"
            filepath = entry_dir / filename

            async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
                await f.write(entry.model_dump_json(indent=2))

            self._invalidate_summary_cache(date.strftime("%Y-%m-%d"))
            return str(filepath)
        except Exception as e:
            logger.error(f"Failed to save journal entry: {e}")
            raise

    async def replace_entry(self, entry: JournalEntry, date: datetime) -> str:
        """按 entry.id 原位更新日记条目，找不到时回退为新增。

        主要用于强制重生日记后同步更新自动总结条目，避免摘要文件已经更新，
        但日记条目仍保留旧正文。
        """
        scope = self._resolve_entry_scope(entry)
        entry_dir = self._get_diary_dir(date, scope=scope)
        if entry_dir.exists():
            for filepath in entry_dir.glob("*.json"):
                try:
                    async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
                        raw = json.loads(await f.read())
                except Exception:
                    continue
                if str(raw.get("id") or "") != str(entry.id or ""):
                    continue
                async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
                    await f.write(entry.model_dump_json(indent=2))
                self._invalidate_summary_cache(date.strftime("%Y-%m-%d"))
                return str(filepath)
        return await self.save_entry(entry, date)

    async def get_entries(self, date: datetime) -> List[JournalEntry]:
        try:
            files: List[Path] = []
            for scope in ("user", "aveline", "ling"):
                diary_dir = self._get_diary_dir(date, scope=scope)
                if diary_dir.exists():
                    files.extend(diary_dir.glob("*.json"))
            files.sort()

            async def _read_one(fpath: Path) -> Optional[JournalEntry]:
                try:
                    async with aiofiles.open(fpath, "r", encoding="utf-8") as f:
                        content = await f.read()
                    if not content.strip():
                        return None
                    return JournalEntry.model_validate_json(content)
                except Exception as e:
                    logger.warning(f"Skipping corrupted entry {fpath}: {e}")
                    return None

            results = await asyncio.gather(*[_read_one(f) for f in files])
            entries = [r for r in results if r is not None]
            entries.sort(key=lambda x: x.timestamp)
            return entries
        except Exception as e:
            logger.error(f"Failed to load entries for {date}: {e}")
            return []

    async def save_daily_summary(self, summary: DailySummary, date: datetime, scope: str = None) -> str:
        try:
            if scope is None:
                scope = _resolve_active_persona_scope()
            daily_dir = self.get_daily_dir(date, scope=scope)
            daily_dir.mkdir(parents=True, exist_ok=True)

            filepath = daily_dir / "diary_summary.json"
            async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
                await f.write(summary.model_dump_json(indent=2))

            date_key = date.strftime("%Y-%m-%d")
            cache_key = f"{date_key}:{scope}"
            self._summary_cache[cache_key] = (summary.generated_at, summary)
            return str(filepath)
        except Exception as e:
            logger.error(f"Failed to save daily summary: {e}")
            raise

    async def get_daily_summary(self, date: datetime, scope: str = None) -> Optional[DailySummary]:
        date_key = date.strftime("%Y-%m-%d")
        cache_key = f"{date_key}:{scope or 'any'}"
        cached = self._summary_cache.get(cache_key)
        if cached is not None:
            return cached[1]
        try:
            # 指定 scope 时只查找对应目录；未指定时依次在 aveline/ling/user 查找
            scopes = [scope] if scope else ("aveline", "ling", "user")
            for s in scopes:
                filepath = self.get_daily_dir(date, scope=s) / "diary_summary.json"
                if filepath.exists():
                    async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
                        content = await f.read()
                    if not content.strip():
                        continue
                    summary = DailySummary.model_validate_json(content)
                    self._summary_cache[cache_key] = (summary.generated_at, summary)
                    return summary
        except Exception as e:
            logger.error(f"Failed to load daily summary for {date}: {e}")
            return None

    async def save_monthly_summary(
        self, summary: MonthlySummary, date: datetime
    ) -> str:
        try:
            monthly_dir = self._get_monthly_dir(date)
            monthly_dir.mkdir(parents=True, exist_ok=True)

            filepath = monthly_dir / "summary.json"
            async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
                await f.write(summary.model_dump_json(indent=2))
            return str(filepath)
        except Exception as e:
            logger.error(f"Failed to save monthly summary: {e}")
            raise

    async def get_monthly_summary(self, date: datetime) -> Optional[MonthlySummary]:
        try:
            # 依次在 aveline/ling/user 目录查找
            for scope in ("aveline", "ling", "user"):
                filepath = self._get_monthly_dir(date, scope=scope) / "summary.json"
                if filepath.exists():
                    async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
                        content = await f.read()
                    return MonthlySummary.model_validate_json(content)
        except Exception as e:
            logger.error(f"Failed to load monthly summary for {date}: {e}")
        return None

    # ── 明日计划存储 ────────────────────────────────────────────
    def _get_plan_filepath(self, date: datetime, scope: str = "user") -> Path:
        """获取某日计划文件路径：{scope}/daily/YYYY/MM/DD/plan.json"""
        return self.get_daily_dir(date, scope=scope) / "plan.json"

    async def save_plan(
        self, plan: DailyPlan, date: datetime, scope: str = "user"
    ) -> str:
        """保存某日学习生活计划"""
        try:
            daily_dir = self.get_daily_dir(date, scope=scope)
            daily_dir.mkdir(parents=True, exist_ok=True)
            filepath = daily_dir / "plan.json"
            async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
                await f.write(plan.model_dump_json(indent=2))
            return str(filepath)
        except Exception as e:
            logger.error(f"Failed to save plan for {date}: {e}")
            raise

    async def get_plan(
        self, date: datetime, scope: str = "user"
    ) -> Optional[DailyPlan]:
        """读取某日学习生活计划"""
        try:
            # 优先读指定 scope，未指定时按 user/aveline/ling 顺序查找
            scopes = [scope] if scope else ("user", "aveline", "ling")
            for s in scopes:
                filepath = self._get_plan_filepath(date, scope=s)
                if filepath.exists():
                    async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
                        content = await f.read()
                    if not content.strip():
                        continue
                    return DailyPlan.model_validate_json(content)
        except Exception as e:
            logger.error(f"Failed to load plan for {date}: {e}")
        return None
