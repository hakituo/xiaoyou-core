import time
from typing import Any, Dict, List

from core.services.study.subject_analyzer import StudySubjectAnalyzer


class StudySummaryBuilder:
    def __init__(self, analyzer: StudySubjectAnalyzer):
        self._analyzer = analyzer

    def build_daily_summary(
        self,
        *,
        date: str,
        dictionary_stats: Dict[str, Any],
        session_stats: Dict[str, Any],
        sessions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        to_review = int((dictionary_stats or {}).get("to_review") or 0)
        learned_words = int((dictionary_stats or {}).get("learned_words") or 0)
        daily_quota = 20
        new_words_quota = max(0, daily_quota - to_review)
        subject_breakdown = self._analyzer.build_subject_breakdown(sessions)
        top_subjects = [item.get("subject") for item in subject_breakdown[:2] if item.get("subject")]
        total_sessions = len(sessions)
        active = bool((session_stats or {}).get("active"))
        blueprint = self._build_next_day_blueprint(
            to_review=to_review,
            total_sessions=total_sessions,
            top_subjects=top_subjects,
        )
        parts = []
        if to_review > 0:
            parts.append(f"Review {to_review} words")
        if new_words_quota > 0:
            parts.append(f"Learn {new_words_quota} new words")
        target = " + ".join(parts) if parts else "No vocabulary tasks for today"
        suggestion = "保持当前节奏，先完成复习再推进新内容。"
        if to_review > 15:
            suggestion = "复习压力较高，建议把早间时段留给词汇巩固。"
        elif total_sessions >= 6:
            suggestion = "昨天学习密度很高，今天建议加强错题整理与总结。"
        elif total_sessions <= 1:
            core_block = next(
                (b for b in blueprint["timed_blocks"] if b["name"] == "核心学习块"),
                None,
            )
            duration = core_block["duration_minutes"] if core_block else 90
            suggestion = f"昨日学习记录较少，今天建议先完成一个{duration}分钟核心学习块。"
        return {
            "date": date or time.strftime("%Y-%m-%d"),
            "vocab": {
                "total_learned": learned_words,
                "to_review": to_review,
                "daily_quota": daily_quota,
                "target": target,
            },
            "session": {
                "active": active,
                "words_reviewed": int((session_stats or {}).get("words_reviewed") or 0),
                "accuracy": float((session_stats or {}).get("accuracy") or 0.0),
                "streak": int((session_stats or {}).get("streak") or 0),
            },
            "subjects": subject_breakdown,
            "overview": {
                "total_sessions": total_sessions,
                "top_subjects": top_subjects,
            },
            "next_day_blueprint": blueprint,
            "suggestion": suggestion,
        }

    def _build_next_day_blueprint(
        self, *, to_review: int, total_sessions: int, top_subjects: List[str]
    ) -> Dict[str, Any]:
        if total_sessions >= 8:
            intensity = "balanced"
            first_slot = "10:30"
            second_slot = "16:30"
        elif total_sessions >= 4:
            intensity = "normal"
            first_slot = "09:30"
            second_slot = "15:00"
        else:
            intensity = "boost"
            first_slot = "09:00"
            second_slot = "14:00"
        return {
            "intensity": intensity,
            "timed_blocks": [
                {"name": "词汇复习", "time": first_slot, "duration_minutes": 45},
                {"name": "核心学习块", "time": second_slot, "duration_minutes": 90},
            ],
            "untimed_blocks": [
                {"name": "整理错题本", "duration_minutes": 30},
                {"name": "记录今日学习总结", "duration_minutes": 20},
            ],
            "priority_subjects": top_subjects or ["general"],
            "review_target": to_review,
        }
