"""结构化学生状态管理器

与 Markdown 档案（Math Monitor / 观察日志）互补的 JSON 级画像数据。
Markdown 给 AI 读，JSON 给系统查询、分析、决策用。

持久化路径：{study_root}/.state/student_state.json
"""
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core.utils.atomic_io import safe_json_dump
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time, now_str

logger = get_logger("StudentState")

# 最近学习知识点保留上限
_MAX_RECENT_TOPICS = 20
# 困难知识点保留上限
_MAX_STRUGGLING_TOPICS = 30


# ------------------------------------------------------------------
# 数据模型
# ------------------------------------------------------------------

class SubjectState(BaseModel):
    """单个科目的结构化进度状态"""
    subject: str
    total_sessions: int = 0
    total_minutes: int = 0
    confidence: float = Field(default=5.0, ge=0.0, le=10.0, description="掌握度 0-10")
    last_studied: str = ""
    recent_topics: List[str] = Field(default_factory=list)
    struggling_topics: List[str] = Field(default_factory=list)

    def add_topic(self, topic: str) -> None:
        """记录一个学习过的知识点（去重，保留最近 N 个）"""
        if not topic:
            return
        # 去重：如果已在列表中，先移除再追加到末尾
        self.recent_topics = [t for t in self.recent_topics if t != topic]
        self.recent_topics.append(topic)
        if len(self.recent_topics) > _MAX_RECENT_TOPICS:
            self.recent_topics = self.recent_topics[-_MAX_RECENT_TOPICS:]

    def add_struggling_topic(self, topic: str) -> None:
        """记录一个困难知识点"""
        if not topic:
            return
        if topic not in self.struggling_topics:
            self.struggling_topics.append(topic)
        if len(self.struggling_topics) > _MAX_STRUGGLING_TOPICS:
            self.struggling_topics = self.struggling_topics[-_MAX_STRUGGLING_TOPICS:]

    def remove_struggling_topic(self, topic: str) -> None:
        """将困难知识点标记为已克服"""
        self.struggling_topics = [t for t in self.struggling_topics if t != topic]


class StudentState(BaseModel):
    """完整的学生结构化状态"""
    subjects: Dict[str, SubjectState] = Field(default_factory=dict)
    learning_style: str = "unknown"
    daily_goal_minutes: int = 120
    streak_days: int = 0
    longest_streak_days: int = 0
    total_sessions: int = 0
    last_active_date: str = ""
    created_at: str = ""
    updated_at: str = ""


# ------------------------------------------------------------------
# 管理器
# ------------------------------------------------------------------

def _get_study_root() -> Path:
    """从配置读取 study 根路径"""
    try:
        from config.integrated_config import get_settings
        from core.utils.common import get_project_root
        settings = get_settings()
        study_root = str(getattr(settings, "study", None).study_root or "").strip()
        if study_root:
            p = Path(study_root).expanduser()
            if not p.is_absolute():
                p = get_project_root() / p
            return p.resolve()
    except Exception:
        pass
    return Path("data/study").resolve()


def _get_state_dir() -> Path:
    return _get_study_root() / ".state"


def _get_state_file() -> Path:
    return _get_state_dir() / "student_state.json"


class StudentStateManager:
    """学生状态管理器，线程安全的 JSON 持久化单例"""

    _instance: Optional["StudentStateManager"] = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._lock = threading.Lock()
        self._state: Optional[StudentState] = None
        self._state_file = _get_state_file()

    @classmethod
    def get_instance(cls) -> "StudentStateManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ---- 加载 / 保存 ----

    def load(self) -> StudentState:
        """从 JSON 文件加载状态，不存在则返回空状态"""
        with self._lock:
            if self._state is not None:
                return self._state
            try:
                if self._state_file.exists():
                    data = json.loads(self._state_file.read_text(encoding="utf-8"))
                    self._state = StudentState(**data)
                    logger.info(f"已加载学生状态: {self._state.total_sessions} 个会话")
                else:
                    self._state = StudentState(
                        created_at=get_current_time().isoformat(timespec="seconds")
                    )
            except Exception as e:
                logger.warning(f"加载学生状态失败，使用空状态: {e}")
                self._state = StudentState(
                    created_at=get_current_time().isoformat(timespec="seconds")
                )
            return self._state

    def save(self) -> None:
        """将当前状态持久化到 JSON"""
        with self._lock:
            if self._state is None:
                return
            try:
                self._state.updated_at = get_current_time().isoformat(timespec="seconds")
                self._state_file.parent.mkdir(parents=True, exist_ok=True)
                data = self._state.model_dump()
                # P0-17: 用原子写入保存学生状态，避免进程崩溃导致学习进度丢失
                safe_json_dump(data, self._state_file, encoding="utf-8")
            except Exception as e:
                logger.error(f"保存学生状态失败: {e}")

    def get_state(self) -> StudentState:
        """获取当前状态（懒加载）"""
        if self._state is None:
            self.load()
        return self._state  # type: ignore

    # ---- 会话更新 ----

    def update_from_session(
        self,
        subject: str,
        topics: List[str],
        duration_min: int,
        struggles: Optional[List[str]] = None,
    ) -> StudentState:
        """会话结束后更新学生状态"""
        state = self.get_state()
        today = now_str("%Y-%m-%d")

        # 获取或创建科目状态
        key = subject.lower().strip() or "general"
        if key not in state.subjects:
            state.subjects[key] = SubjectState(subject=key)

        subj = state.subjects[key]
        subj.total_sessions += 1
        subj.total_minutes += max(0, duration_min)
        subj.last_studied = today
        for topic in (topics or []):
            subj.add_topic(topic)
        for struggle in (struggles or []):
            subj.add_struggling_topic(struggle)

        # 更新全局统计
        state.total_sessions += 1
        state.last_active_date = today

        # 更新 streak
        self._update_streak(state, today)

        self.save()
        return state

    def update_confidence(self, subject: str, delta: float) -> None:
        """调整科目掌握度（+/- delta）"""
        state = self.get_state()
        key = subject.lower().strip()
        if key in state.subjects:
            subj = state.subjects[key]
            subj.confidence = max(0.0, min(10.0, subj.confidence + delta))
            self.save()

    def get_priority_subjects(self) -> List[Dict[str, Any]]:
        """按 confidence 升序返回科目列表（薄弱优先）"""
        state = self.get_state()
        items = [
            {"subject": s.subject, "confidence": s.confidence, "last_studied": s.last_studied}
            for s in state.subjects.values()
        ]
        items.sort(key=lambda x: x["confidence"])
        return items

    def get_subject_status(self, subject: str) -> Optional[Dict[str, Any]]:
        """返回指定科目的当前状态"""
        state = self.get_state()
        key = subject.lower().strip()
        subj = state.subjects.get(key)
        if subj is None:
            return None
        return subj.model_dump()

    def mark_topic_mastered(self, subject: str, topic: str) -> None:
        """标记知识点已掌握：从 struggling 移除，confidence 小幅提升"""
        state = self.get_state()
        key = subject.lower().strip()
        if key in state.subjects:
            state.subjects[key].remove_struggling_topic(topic)
            state.subjects[key].confidence = min(
                10.0, state.subjects[key].confidence + 0.3
            )
            self.save()

    def get_streak_info(self) -> Dict[str, int]:
        """返回 streak 信息"""
        state = self.get_state()
        return {
            "current_streak": state.streak_days,
            "longest_streak": state.longest_streak_days,
            "last_active_date": state.last_active_date,
        }

    def to_dict(self) -> Dict[str, Any]:
        """返回完整状态的字典形式"""
        return self.get_state().model_dump()

    # ---- 内部方法 ----

    @staticmethod
    def _update_streak(state: StudentState, today: str) -> None:
        """更新连续学习天数"""
        if not state.last_active_date or state.last_active_date == today:
            # 同一天多次学习，streak 不变
            if not state.last_active_date:
                state.streak_days = 1
            return
        try:
            last_date = datetime.strptime(state.last_active_date, "%Y-%m-%d").date()
            today_date = datetime.strptime(today, "%Y-%m-%d").date()
            diff = (today_date - last_date).days
            if diff == 1:
                # 连续第二天学习
                state.streak_days += 1
            elif diff > 1:
                # 断掉了
                state.streak_days = 1
            # diff <= 0 不处理（同一天已在上面处理）
        except ValueError:
            state.streak_days = 1
        # 更新历史最长 streak
        if state.streak_days > state.longest_streak_days:
            state.longest_streak_days = state.streak_days


def get_student_state_manager() -> StudentStateManager:
    """工厂函数，获取全局单例"""
    return StudentStateManager.get_instance()
