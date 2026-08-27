import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from core.services.daily.manager import get_daily_manager
from core.services.journal.service import get_journal_service
from core.utils.data_paths import get_aveline_life_dir
from core.utils.time_utils import get_current_time, get_diary_target_date_str
from core.utils.logger import get_logger

logger = get_logger("AVELINE_LIFE")


class AvelineLifeRhythmService:
    def __init__(self):
        self._base_dir = get_aveline_life_dir()
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Dict[str, Any]] = {}

    async def build_bionic_delay_profile(
        self,
        *,
        date: Optional[str] = None,
        session_id: str = "default_user",
        force_refresh: bool = False,
        cache_ttl_seconds: int = 180,
    ) -> Dict[str, Any]:
        date_key = self._normalize_date(date)
        cache_key = f"{session_id}:{date_key}"
        now = time.time()

        if not force_refresh:
            cached = self._cache.get(cache_key) or {}
            expire_ts = float(cached.get("expire_ts") or 0.0)
            profile = cached.get("profile")
            if profile and expire_ts > now:
                return profile

        daily_record = await asyncio.to_thread(get_daily_manager().get_record, date_key)
        diary_summary = await self._get_diary_summary(date_key)
        profile = self._build_profile(
            date_key=date_key,
            session_id=session_id,
            daily_record=daily_record,
            diary_summary=diary_summary,
        )
        await self._persist_profile(profile)

        ttl = max(30, int(cache_ttl_seconds or 180))
        self._cache[cache_key] = {"expire_ts": now + ttl, "profile": profile}
        return profile

    async def _get_diary_summary(self, date_key: str) -> Dict[str, Any]:
        try:
            svc = get_journal_service()
            summary_obj = await svc.get_daily_summary(date_key)
            if summary_obj is None:
                return {}
            return summary_obj.model_dump()
        except Exception as e:
            logger.debug(f"加载日记总结失败: {e}")
            return {}

    def _build_profile(
        self,
        *,
        date_key: str,
        session_id: str,
        daily_record: Dict[str, Any],
        diary_summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        now = get_current_time()
        hour = now.hour
        profile_delay = {
            "base_multiplier": 1.0,
            "surprise_probability_multiplier": 1.0,
            "surprise_min_seconds": 90.0,
            "surprise_max_seconds": 900.0,
            "recommended_comma_split_probability": 0.72,
        }

        phase = "daytime"
        if 0 <= hour < 6:
            phase = "deep_night"
            profile_delay.update(
                {
                    "base_multiplier": 1.35,
                    "surprise_probability_multiplier": 1.8,
                    "surprise_min_seconds": 180.0,
                    "surprise_max_seconds": 1200.0,
                    "recommended_comma_split_probability": 0.62,
                }
            )
        elif 6 <= hour < 9:
            phase = "morning"
            profile_delay.update(
                {
                    "base_multiplier": 0.95,
                    "surprise_probability_multiplier": 0.8,
                    "recommended_comma_split_probability": 0.78,
                }
            )
        elif 22 <= hour <= 23:
            phase = "late_evening"
            profile_delay.update(
                {
                    "base_multiplier": 1.2,
                    "surprise_probability_multiplier": 1.4,
                    "surprise_min_seconds": 150.0,
                    "surprise_max_seconds": 1000.0,
                    "recommended_comma_split_probability": 0.66,
                }
            )

        mood = self._extract_mood(daily_record, diary_summary)
        if mood in {"tired", "sad", "anxious", "down"}:
            profile_delay["base_multiplier"] *= 1.12
            profile_delay["surprise_probability_multiplier"] *= 1.2
            profile_delay["recommended_comma_split_probability"] *= 0.9

        study_count = len(
            ((daily_record or {}).get("study") or {}).get("sessions") or []
        )
        activity_count = len((daily_record or {}).get("activities") or [])
        event_load = study_count + activity_count
        if event_load >= 6:
            profile_delay["base_multiplier"] *= 1.08
            profile_delay["surprise_probability_multiplier"] *= 1.08

        profile_delay["base_multiplier"] = round(
            max(0.75, min(1.8, float(profile_delay["base_multiplier"]))), 3
        )
        profile_delay["surprise_probability_multiplier"] = round(
            max(0.5, min(2.5, float(profile_delay["surprise_probability_multiplier"]))),
            3,
        )
        profile_delay["surprise_min_seconds"] = float(
            max(30.0, min(3600.0, float(profile_delay["surprise_min_seconds"])))
        )
        profile_delay["surprise_max_seconds"] = float(
            max(
                profile_delay["surprise_min_seconds"],
                min(7200.0, float(profile_delay["surprise_max_seconds"])),
            )
        )
        profile_delay["recommended_comma_split_probability"] = round(
            max(0.35, min(0.95, float(profile_delay["recommended_comma_split_probability"]))),
            3,
        )

        return {
            "date": date_key,
            "session_id": str(session_id or "default_user"),
            "generated_at": time.time(),
            "phase": phase,
            "signals": {
                "hour": hour,
                "mood": mood,
                "study_sessions": study_count,
                "activities": activity_count,
                "summary_available": bool(diary_summary),
            },
            "delay": profile_delay,
        }

    def _extract_mood(
        self, daily_record: Dict[str, Any], diary_summary: Dict[str, Any]
    ) -> str:
        mood_obj = (daily_record or {}).get("mood")
        mood_text = ""
        if isinstance(mood_obj, dict):
            mood_text = str(mood_obj.get("mood") or "").strip().lower()
        elif mood_obj:
            mood_text = str(mood_obj).strip().lower()
        if mood_text:
            return mood_text

        summary_mood = str((diary_summary or {}).get("mood") or "").strip().lower()
        if summary_mood:
            return summary_mood

        summary_text = str((diary_summary or {}).get("summary") or "").strip().lower()
        if any(token in summary_text for token in ["累", "疲惫", "困", "焦虑"]):
            return "tired"
        if any(token in summary_text for token in ["开心", "轻松", "愉快"]):
            return "happy"
        return "neutral"

    async def _persist_profile(self, profile: Dict[str, Any]) -> None:
        path = self._profile_path(str(profile.get("date") or ""))
        payload = json.dumps(profile, ensure_ascii=False, indent=2)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, payload, "utf-8")

    def _profile_path(self, date_str: str) -> Path:
        date_key = self._normalize_date(date_str)
        dt = datetime.strptime(date_key, "%Y-%m-%d")
        return (
            self._base_dir
            / str(dt.year)
            / str(dt.month)
            / str(dt.day)
            / "bionic_delay_profile.json"
        )

    def _normalize_date(self, date_str: Optional[str]) -> str:
        raw = str(date_str or "").strip()
        if not raw:
            return get_diary_target_date_str()
        try:
            return datetime.strptime(raw, "%Y-%m-%d").strftime("%Y-%m-%d")
        except Exception:
            return get_diary_target_date_str()


_service_instance: Optional[AvelineLifeRhythmService] = None


def get_aveline_life_rhythm_service() -> AvelineLifeRhythmService:
    global _service_instance
    if _service_instance is None:
        _service_instance = AvelineLifeRhythmService()
    return _service_instance
