"""每日学习状态追踪器

追踪当天所有学习活动：会话记录、知识点掌握状态、困难点。
每天一个 JSON 文件，供 TutorEngine 和 API 查询使用。

持久化路径：{study_root}/.state/daily/{YYYY-MM-DD}.json
"""
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core.utils.logger import get_logger
from core.utils.time_utils import now_str

logger = get_logger("DailyTracker")


# ------------------------------------------------------------------
# 数据模型
# ------------------------------------------------------------------

class SessionRecord(BaseModel):
    """一次学习会话的记录"""
    subject: str
    topics: List[str] = Field(default_factory=list)
    duration_minutes: int = 0
    started_at: float = Field(default_factory=time.time)
    ended_at: float = 0.0
    notes: str = ""


class KnowledgePointRecord(BaseModel):
    """单个知识点的学习记录"""
    subject: str
    topic: str
    status: str = "new"  # new / reviewed / mastered / struggling
    recorded_at: float = Field(default_factory=time.time)


class StruggleRecord(BaseModel):
    """学习中遇到的困难"""
    subject: str
    topic: str
    description: str = ""
    recorded_at: float = Field(default_factory=time.time)


class DailyRecord(BaseModel):
    """一天的完整学习记录"""
    date: str
    sessions: List[SessionRecord] = Field(default_factory=list)
    knowledge_points: List[KnowledgePointRecord] = Field(default_factory=list)
    struggles: List[StruggleRecord] = Field(default_factory=list)
    total_study_minutes: int = 0
    subjects_studied: List[str] = Field(default_factory=list)


# ------------------------------------------------------------------
# 路径辅助
# ------------------------------------------------------------------

def _get_state_daily_dir() -> Path:
    try:
        from config.integrated_config import get_settings
        from core.utils.common import get_project_root
        settings = get_settings()
        study_root = str(getattr(settings, "study", None).study_root or "").strip()
        if study_root:
            p = Path(study_root).expanduser()
            if not p.is_absolute():
                p = get_project_root() / p
            return (p / ".state" / "daily").resolve()
    except Exception:
        pass
    return Path("data/study/.state/daily").resolve()


def _get_daily_file(date_str: str) -> Path:
    return _get_state_daily_dir() / f"{date_str}.json"


# ------------------------------------------------------------------
# 管理器
# ------------------------------------------------------------------

class DailyTracker:
    """每日学习状态追踪器"""

    _instance: Optional["DailyTracker"] = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._lock = threading.Lock()
        # 缓存已加载的日期数据：date_str -> DailyRecord
        self._cache: Dict[str, DailyRecord] = {}

    @classmethod
    def get_instance(cls) -> "DailyTracker":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ---- 加载 / 保存 ----

    def _load(self, date_str: str) -> DailyRecord:
        """加载指定日期的记录"""
        with self._lock:
            if date_str in self._cache:
                return self._cache[date_str]
            filepath = _get_daily_file(date_str)
            try:
                if filepath.exists():
                    data = json.loads(filepath.read_text(encoding="utf-8"))
                    record = DailyRecord(**data)
                else:
                    record = DailyRecord(date=date_str)
            except Exception as e:
                logger.warning(f"加载每日记录失败 [{date_str}]: {e}")
                record = DailyRecord(date=date_str)
            self._cache[date_str] = record
            return record

    def _save(self, date_str: str) -> None:
        """保存指定日期的记录"""
        with self._lock:
            record = self._cache.get(date_str)
            if record is None:
                return
            try:
                filepath = _get_daily_file(date_str)
                filepath.parent.mkdir(parents=True, exist_ok=True)
                filepath.write_text(
                    json.dumps(record.model_dump(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                logger.error(f"保存每日记录失败 [{date_str}]: {e}")

    # ---- 公共 API ----

    def get_today(self) -> DailyRecord:
        """获取今天的学习记录（懒加载）"""
        today = now_str("%Y-%m-%d")
        return self._load(today)

    def get_date(self, date_str: str) -> DailyRecord:
        """获取指定日期的学习记录"""
        return self._load(date_str)

    def record_session(
        self,
        subject: str,
        topics: List[str],
        duration_min: int,
        notes: str = "",
        date: Optional[str] = None,
    ) -> SessionRecord:
        """记录一次学习会话"""
        date_str = date or now_str("%Y-%m-%d")
        record = self._load(date_str)

        session = SessionRecord(
            subject=subject.lower().strip(),
            topics=[t.strip() for t in topics if t.strip()],
            duration_minutes=max(0, duration_min),
            notes=notes,
            ended_at=time.time(),
        )
        record.sessions.append(session)
        record.total_study_minutes += session.duration_minutes

        # 更新已学科目列表
        subj_key = session.subject or "general"
        if subj_key not in record.subjects_studied:
            record.subjects_studied.append(subj_key)

        self._save(date_str)
        logger.info(f"记录学习会话: [{subject}] {duration_min}分钟, {len(topics)}个知识点")
        return session

    def record_knowledge_point(
        self,
        subject: str,
        topic: str,
        status: str = "new",
        date: Optional[str] = None,
    ) -> KnowledgePointRecord:
        """
        记录知识点学习状态。

        status: new(新学) / reviewed(复习) / mastered(掌握) / struggling(困难)
        """
        if status not in ("new", "reviewed", "mastered", "struggling"):
            status = "new"

        date_str = date or now_str("%Y-%m-%d")
        record = self._load(date_str)

        kp = KnowledgePointRecord(
            subject=subject.lower().strip(),
            topic=topic.strip(),
            status=status,
        )
        record.knowledge_points.append(kp)
        self._save(date_str)
        return kp

    def record_struggle(
        self,
        subject: str,
        topic: str,
        description: str = "",
        date: Optional[str] = None,
    ) -> StruggleRecord:
        """记录学习中遇到的困难"""
        date_str = date or now_str("%Y-%m-%d")
        record = self._load(date_str)

        struggle = StruggleRecord(
            subject=subject.lower().strip(),
            topic=topic.strip(),
            description=description.strip(),
        )
        record.struggles.append(struggle)
        self._save(date_str)
        return struggle

    def get_subject_breakdown(self, date: Optional[str] = None) -> Dict[str, Any]:
        """
        返回各科目今天的学习分布。

        格式：{subject: {sessions: int, minutes: int, topics: [str], struggles: int}}
        """
        date_str = date or now_str("%Y-%m-%d")
        record = self._load(date_str)

        breakdown: Dict[str, Dict[str, Any]] = {}

        for session in record.sessions:
            subj = session.subject or "general"
            if subj not in breakdown:
                breakdown[subj] = {"sessions": 0, "minutes": 0, "topics": [], "struggles": 0}
            breakdown[subj]["sessions"] += 1
            breakdown[subj]["minutes"] += session.duration_minutes
            for topic in session.topics:
                if topic not in breakdown[subj]["topics"]:
                    breakdown[subj]["topics"].append(topic)

        for struggle in record.struggles:
            subj = struggle.subject or "general"
            if subj in breakdown:
                breakdown[subj]["struggles"] += 1

        return breakdown

    def get_summary_stats(self, date: Optional[str] = None) -> Dict[str, Any]:
        """返回当天的摘要统计"""
        date_str = date or now_str("%Y-%m-%d")
        record = self._load(date_str)

        kp_by_status = {"new": 0, "reviewed": 0, "mastered": 0, "struggling": 0}
        for kp in record.knowledge_points:
            if kp.status in kp_by_status:
                kp_by_status[kp.status] += 1

        return {
            "date": date_str,
            "total_study_minutes": record.total_study_minutes,
            "sessions_count": len(record.sessions),
            "subjects_studied": record.subjects_studied,
            "knowledge_points_new": kp_by_status["new"],
            "knowledge_points_reviewed": kp_by_status["reviewed"],
            "knowledge_points_mastered": kp_by_status["mastered"],
            "knowledge_points_struggling": kp_by_status["struggling"],
            "struggles_count": len(record.struggles),
        }

    def get_recent_days(self, n: int = 7) -> List[DailyRecord]:
        """获取最近 N 天有记录的 DailyRecord（用于周分析）"""
        daily_dir = _get_state_daily_dir()
        if not daily_dir.exists():
            return []

        files = sorted(daily_dir.glob("*.json"), reverse=True)[:n]
        records = []
        for f in files:
            date_str = f.stem
            records.append(self._load(date_str))
        return records


def get_daily_tracker() -> DailyTracker:
    """工厂函数，获取全局单例"""
    return DailyTracker.get_instance()
