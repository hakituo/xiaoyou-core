import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from core.services.workspace.daily_task_service import build_daily_task_snapshot
from core.utils.time_utils import get_current_time, get_diary_target_date_str, ts_to_str


class WorkspaceSnapshotBuilder:
    async def build(
        self,
        date: Optional[str],
        diary_limit: int,
        reminders: List[Dict[str, Any]],
        status_storage_path: str,
    ) -> Dict[str, Any]:
        from core.services.workspace.status_manager import get_user_status_manager
        from core.services.journal.service import get_journal_service
        from core.services.daily.manager import get_daily_manager

        target_date = self._normalize_date(date)

        status_manager = get_user_status_manager()
        statuses = await asyncio.to_thread(status_manager.get_active_statuses)
        status_summary = await asyncio.to_thread(status_manager.get_status_summary)

        journal_service = get_journal_service()
        diary_entries = await journal_service.get_entries(target_date)
        if diary_limit > 0:
            diary_entries = diary_entries[-diary_limit:]

        daily_manager = get_daily_manager()
        daily_record = await asyncio.to_thread(daily_manager.get_record, target_date)
        fallback_sleep = ""
        if target_date == self._normalize_date(None):
            prev_date = self._get_previous_date(target_date)
            prev_record = await asyncio.to_thread(daily_manager.get_record, prev_date)
            # 兼容新旧格式
            prev_sc = (prev_record.get("sleep_cycle") or prev_record.get("schedule") if isinstance(prev_record, dict) else {}) or {}
            fallback_sleep = str(
                prev_sc.get("sleep")
                or ""
            ).strip()
        daily_summary = self._render_daily_summary(
            daily_record, fallback_sleep=fallback_sleep
        )
        portrait_completeness = self._evaluate_daily_record_quality(
            daily_record, fallback_sleep=fallback_sleep
        )
        daily_tasks = build_daily_task_snapshot(daily_record)

        diary_summary_obj = await journal_service.get_daily_summary(target_date)
        diary_summary = diary_summary_obj.model_dump() if diary_summary_obj else None

        pending_for_day: List[Dict[str, Any]] = []
        completed_for_day: List[Dict[str, Any]] = []
        for item in reminders:
            trigger_ts = item.get("trigger_ts")
            trigger_date = self._date_from_timestamp(trigger_ts)
            if trigger_date != target_date:
                continue
            if item.get("status") == "pending":
                pending_for_day.append(item)
            elif item.get("status") == "completed":
                completed_for_day.append(item)

        recent_diary = [
            {
                "id": entry.id,
                "time": entry.time_str,
                "type": entry.type,
                "content": entry.content,
                "mood": entry.mood,
                "thought": entry.thought,
                "tags": entry.tags,
            }
            for entry in diary_entries
        ]

        return {
            "date": target_date,
            "status": {
                "count": len(statuses),
                "items": statuses,
                "summary": status_summary,
                "storage_path": status_storage_path,
            },
            "daily_record": daily_record,
            "daily_summary_text": daily_summary,
            "portrait_completeness": portrait_completeness,
            "daily_tasks": daily_tasks,
            "diary": {
                "count": len(diary_entries),
                "recent_entries": recent_diary,
                "summary": diary_summary,
            },
            "reminders": {
                "pending_count": len(pending_for_day),
                "completed_count": len(completed_for_day),
                "pending": pending_for_day,
                "completed": completed_for_day,
            },
        }

    def _normalize_date(self, date: Optional[str]) -> str:
        if date:
            raw = str(date).strip()
            if raw:
                return raw.split(" ")[0]
        return get_diary_target_date_str()

    def _get_previous_date(self, date: str) -> str:
        try:
            base = datetime.strptime(str(date), "%Y-%m-%d")
        except Exception:
            base = get_current_time()
        return (base - timedelta(days=1)).strftime("%Y-%m-%d")

    def _date_from_timestamp(self, ts: Any) -> Optional[str]:
        try:
            return ts_to_str(float(ts), "%Y-%m-%d")
        except Exception:
            return None

    def _render_daily_summary(
        self, record: Dict[str, Any], fallback_sleep: str = ""
    ) -> str:
        data = record if isinstance(record, dict) else {}
        lines = ["【Today's Portrait】"]

        # 兼容新旧格式
        sc = data.get("sleep_cycle") or data.get("schedule") or {}
        wakeup = sc.get("wakeup")
        sleep = sc.get("sleep")
        duration = sc.get("duration")
        
        if sleep and wakeup:
            duration_str = f" ({duration})" if duration else ""
            lines.append(f"- Sleep: {sleep} → {wakeup}{duration_str}")
        elif wakeup:
            lines.append(f"- Wakeup: {wakeup}")
        elif sleep:
            lines.append(f"- Sleep: {sleep}")
        elif fallback_sleep:
            lines.append(f"- Last night sleep: {fallback_sleep}")

        meals = data.get("meals", [])
        if meals:
            import re
            
            food_items = []
            drink_total = 0
            for m in meals:
                m_type = str(m.get("type", "meal")).lower()
                m_content = str(m.get("content", ""))
                
                if m_type == "drink":
                    # Try extract amount
                    match = re.search(r"(\d+)", m_content)
                    if match:
                        drink_total += int(match.group(1))
                else:
                    food_items.append(f"{m_type}({m_content})")
            
            meal_text = ", ".join(food_items) if food_items else "No meals"
            if drink_total > 0:
                meal_text += f"; Water: {drink_total}ml"
            
            lines.append(f"- Meals: {meal_text}")
        else:
            lines.append("- Meals: No records")

        study_sessions = data.get("study", {}).get("sessions", [])
        if study_sessions:
            topics = list(
                {
                    str(session.get("topic", "")).strip()
                    for session in study_sessions
                    if str(session.get("topic", "")).strip()
                }
            )
            if topics:
                lines.append(f"- Study: {', '.join(topics)} ({len(study_sessions)} sessions)")

        activities = data.get("activities", [])
        if activities:
            activity_text = ", ".join(
                [str(item.get("content", "")).strip() for item in activities if item]
            )
            if activity_text:
                lines.append(f"- Activities: {activity_text}")

        health = data.get("health", [])
        if health:
            health_text = ", ".join(
                [str(item.get("symptom", "")).strip() for item in health if item]
            )
            if health_text:
                lines.append(f"- Health: {health_text}")

        mood = data.get("mood")
        if mood:
            if isinstance(mood, dict):
                mood_name = mood.get("mood")
                mood_detail = mood.get("detail", "")
                lines.append(f"- Mood: {mood_name} ({mood_detail})")
            else:
                lines.append(f"- Mood: {mood}")

        return "\n".join(lines)

    def _evaluate_daily_record_quality(
        self, record: Dict[str, Any], fallback_sleep: str = ""
    ) -> Dict[str, Any]:
        data = record if isinstance(record, dict) else {}
        # 兼容新旧格式
        sc = data.get("sleep_cycle") or data.get("schedule") or {}
        meals = data.get("meals", [])
        study_sessions = data.get("study", {}).get("sessions", [])
        activities = data.get("activities", [])
        health = data.get("health", [])
        mood = data.get("mood")

        checks = {
            "wakeup": bool(sc.get("wakeup")),
            "sleep": bool(sc.get("sleep")) or bool(str(fallback_sleep).strip()),
            "meal": bool(meals),
            "activity": bool(activities),
            "mood": bool(mood),
            "study": bool(study_sessions),
            "health": bool(health),
        }
        total = len(checks)
        passed = len([ok for ok in checks.values() if ok])
        score = int((passed / total) * 100) if total > 0 else 0
        missing_items = [name for name, ok in checks.items() if not ok]

        return {
            "score": score,
            "missing_items": missing_items,
            "signals": checks,
        }
