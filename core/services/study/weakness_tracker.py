"""薄弱点追踪与间隔复习调度器

追踪用户在各科目中遇到的困难知识点，并通过间隔复习算法调度复习提醒。

持久化路径：{study_root}/.state/weaknesses.json
间隔复习调度：默认 [1, 3, 7, 14] 天
  - quality >= 4：正常推进到下一级
  - quality == 3：维持当前级
  - quality <  3：回退一级（重新巩固）
"""
import hashlib
import json
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time, now_str

logger = get_logger("WeaknessTracker")


# ------------------------------------------------------------------
# 数据模型
# ------------------------------------------------------------------

class WeaknessItem(BaseModel):
    """单个薄弱知识点"""
    id: str
    subject: str
    topic: str
    first_reported: str
    last_reviewed: str = ""
    review_count: int = 0
    next_review_date: str = ""
    confidence: float = Field(default=3.0, ge=0.0, le=10.0)
    review_level: int = 0          # 当前在间隔序列中的位置（0=首次，未复习）
    source: str = "chat_detected"  # self_reported / chat_detected / test_error
    is_mastered: bool = False

    @staticmethod
    def make_id(subject: str, topic: str) -> str:
        """根据科目+知识点生成稳定 ID"""
        raw = f"{subject.lower().strip()}::{topic.strip()}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]


# ------------------------------------------------------------------
# 路径辅助
# ------------------------------------------------------------------

def _get_state_dir() -> Path:
    try:
        from config.integrated_config import get_settings
        from core.utils.common import get_project_root
        settings = get_settings()
        study_root = str(getattr(settings, "study", None).study_root or "").strip()
        if study_root:
            p = Path(study_root).expanduser()
            if not p.is_absolute():
                p = get_project_root() / p
            return (p / ".state").resolve()
    except Exception:
        pass
    return Path("data/study/.state").resolve()


def _get_weakness_file() -> Path:
    return _get_state_dir() / "weaknesses.json"


def _get_review_intervals() -> List[int]:
    """从配置读取间隔复习天数"""
    try:
        from config.integrated_config import get_settings
        settings = get_settings()
        return settings.study.get_review_intervals()
    except Exception:
        return [1, 3, 7, 14]


# ------------------------------------------------------------------
# 管理器
# ------------------------------------------------------------------

class WeaknessTracker:
    """薄弱点追踪与间隔复习调度"""

    _instance: Optional["WeaknessTracker"] = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._lock = threading.Lock()
        self._items: Optional[List[WeaknessItem]] = None
        self._file = _get_weakness_file()

    @classmethod
    def get_instance(cls) -> "WeaknessTracker":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ---- 加载 / 保存 ----

    def _load(self) -> List[WeaknessItem]:
        with self._lock:
            if self._items is not None:
                return self._items
            try:
                if self._file.exists():
                    data = json.loads(self._file.read_text(encoding="utf-8"))
                    self._items = [WeaknessItem(**item) for item in data.get("items", [])]
                else:
                    self._items = []
            except Exception as e:
                logger.warning(f"加载薄弱点数据失败: {e}")
                self._items = []
            return self._items

    def _save(self) -> None:
        with self._lock:
            if self._items is None:
                return
            try:
                self._file.parent.mkdir(parents=True, exist_ok=True)
                payload = {"items": [item.model_dump() for item in self._items]}
                self._file.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                logger.error(f"保存薄弱点数据失败: {e}")

    def _get_items(self) -> List[WeaknessItem]:
        if self._items is None:
            self._load()
        return self._items  # type: ignore

    # ---- 公共 API ----

    def record_weakness(
        self,
        subject: str,
        topic: str,
        source: str = "chat_detected",
    ) -> WeaknessItem:
        """记录一个薄弱知识点（已存在则更新来源）"""
        items = self._get_items()
        item_id = WeaknessItem.make_id(subject, topic)

        # 查找已有记录
        for item in items:
            if item.id == item_id and not item.is_mastered:
                # 已存在且未 mastered，更新来源
                item.source = source
                self._save()
                return item.model_copy()

        # 新建
        today = now_str("%Y-%m-%d")
        intervals = _get_review_intervals()
        first_interval = intervals[0] if intervals else 1
        next_review = (get_current_time() + timedelta(days=first_interval)).strftime("%Y-%m-%d")

        new_item = WeaknessItem(
            id=item_id,
            subject=subject.lower().strip(),
            topic=topic.strip(),
            first_reported=today,
            next_review_date=next_review,
            source=source,
        )
        items.append(new_item)
        self._save()
        logger.info(f"记录薄弱点: [{subject}] {topic}")
        return new_item.model_copy()

    def get_due_reviews(self, date: Optional[str] = None) -> List[WeaknessItem]:
        """获取今天（或指定日期）该复习的薄弱点"""
        target_date = date or now_str("%Y-%m-%d")
        items = self._get_items()
        due = [
            item for item in items
            if not item.is_mastered
            and item.next_review_date
            and item.next_review_date <= target_date
        ]
        # 按 confidence 升序（最不自信的优先复习）
        due.sort(key=lambda x: x.confidence)
        return due

    def mark_reviewed(self, item_id: str, quality: int) -> Optional[WeaknessItem]:
        """
        记录复习结果，更新 confidence 和下次复习日期。

        quality: 0-5
          >= 4: 正常推进到下一级
          == 3: 维持当前级
          <  3: 回退一级

        返回更新后的 WeaknessItem 副本。
        """
        items = self._get_items()
        intervals = _get_review_intervals()
        today = now_str("%Y-%m-%d")

        for item in items:
            if item.id != item_id:
                continue

            item.last_reviewed = today
            item.review_count += 1

            # 调整 confidence
            if quality >= 4:
                item.confidence = min(10.0, item.confidence + 1.5)
            elif quality == 3:
                item.confidence = min(10.0, item.confidence + 0.5)
            else:
                item.confidence = max(0.0, item.confidence - 1.0)

            # 调整 review_level
            if quality >= 4:
                item.review_level = min(item.review_level + 1, len(intervals) - 1)
            elif quality < 3:
                item.review_level = max(0, item.review_level - 1)
            # quality == 3: level 不变

            # 计算下次复习日期
            if item.confidence >= 9.0 and item.review_level >= len(intervals) - 1:
                # 已经掌握，标记为 mastered
                item.is_mastered = True
                item.next_review_date = ""
                logger.info(f"薄弱点已掌握: [{item.subject}] {item.topic}")
            else:
                level_idx = min(item.review_level, len(intervals) - 1)
                days = intervals[level_idx] if level_idx < len(intervals) else intervals[-1]
                item.next_review_date = (
                    get_current_time() + timedelta(days=days)
                ).strftime("%Y-%m-%d")

            self._save()
            # 返回副本，避免调用方持有引用被后续修改影响
            return item.model_copy()

        return None

    def promote_to_mastered(self, item_id: str) -> bool:
        """手动将薄弱点标记为已掌握"""
        items = self._get_items()
        for item in items:
            if item.id == item_id:
                item.is_mastered = True
                item.confidence = 10.0
                item.next_review_date = ""
                self._save()
                return True
        return False

    def get_weakness_report(self) -> Dict[str, Any]:
        """
        生成薄弱点报告：
        - 按科目分组
        - 每组内按紧急度排序（next_review_date 最早 + confidence 最低）
        - 区分：待复习 / 活跃 / 已掌握
        """
        items = self._get_items()
        today = now_str("%Y-%m-%d")

        active = [i for i in items if not i.is_mastered]
        mastered = [i for i in items if i.is_mastered]
        due = [i for i in active if i.next_review_date and i.next_review_date <= today]

        # 按科目分组
        by_subject: Dict[str, List[Dict]] = {}
        for item in active:
            subj = item.subject
            if subj not in by_subject:
                by_subject[subj] = []
            by_subject[subj].append(item.model_dump())

        # 每组内排序：confidence 升序
        for subj in by_subject:
            by_subject[subj].sort(key=lambda x: x["confidence"])

        return {
            "total_active": len(active),
            "total_mastered": len(mastered),
            "due_today": len(due),
            "by_subject": by_subject,
            "due_items": [i.model_dump() for i in due],
        }

    def get_active_count(self) -> int:
        """返回当前活跃（未掌握）的薄弱点数量"""
        return sum(1 for i in self._get_items() if not i.is_mastered)


def get_weakness_tracker() -> WeaknessTracker:
    """工厂函数，获取全局单例"""
    return WeaknessTracker.get_instance()
