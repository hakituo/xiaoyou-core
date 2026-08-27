from typing import Any, Dict, List

from core.services.study.mode_detector import SUBJECT_KEYWORDS


class StudySubjectAnalyzer:
    def __init__(self):
        # 复用 mode_detector 中的统一关键词表，额外补充 general 和 summary 相关词
        self._subject_keywords: Dict[str, List[str]] = dict(SUBJECT_KEYWORDS)
        self._subject_keywords["general"] = [
            "study", "review", "summary", "复盘", "总结", "学习",
        ]

    def classify_topic(self, topic: str) -> str:
        text = str(topic or "").strip().lower()
        if not text:
            return "general"
        for subject, keywords in self._subject_keywords.items():
            if subject == "general":
                continue  # general 作为兜底
            if any(keyword in text for keyword in keywords):
                return subject
        # 兜底匹配 general
        if any(kw in text for kw in self._subject_keywords.get("general", [])):
            return "general"
        return "general"

    def build_subject_breakdown(self, sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        bucket: Dict[str, Dict[str, Any]] = {}
        for session in sessions:
            topic = str((session or {}).get("topic") or "").strip()
            subject = self.classify_topic(topic)
            if subject not in bucket:
                bucket[subject] = {
                    "subject": subject,
                    "session_count": 0,
                    "topics": [],
                }
            bucket[subject]["session_count"] += 1
            if topic and topic not in bucket[subject]["topics"]:
                bucket[subject]["topics"].append(topic)
        result = list(bucket.values())
        result.sort(key=lambda x: int(x.get("session_count", 0)), reverse=True)
        return result
