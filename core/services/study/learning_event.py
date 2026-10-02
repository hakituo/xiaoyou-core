"""学习事件（LearningEvent）——append-only 的学习证据日志。

定位
----
``ConceptState`` 是聚合后的**当前状态**，只保留最新结论；本模块保留**可追溯的
学习证据**：谁在什么时候教了什么、用户答对还是答错、有没有用提示、暴露了哪个
误区。教学策略分析、学习日志、复盘都应该读这里，而不是让 ConceptState 直接吞掉
全部历史细节。

两级权威（authority）
--------------------
同一条日志里混着两种性质完全不同的东西，必须靠 ``authority`` 分开：

- ``confirmed``：**学习事实**。由显式教学 API（``study_record_*``）写入，
  可以做后续推理，可以进 prompt，可以驱动 ConceptState / ZPD / 复习计划。
- ``observed``：**非权威遥测**。由被动正则（``observe_message``）写入，
  只用于留痕、调试、跨轮绑定；**默认不喂回 LLM**，也永远不能自己变成事实。

被动观察是「高召回 / 低精度」的：日常聊天里真正的学习语句极少，正则再准，
假阳性数量也会超过真记录。所以它以 ``observed`` 落盘，等待显式工具把它
「提升」为 ``confirmed``——提升动作必须由 LLM 工具发起，遥测自己不能完成。

注意 ``source``（chat / review / tool / api）**不是**权威判据：显式 API 写
``source="api"``，而 ``record_teaching`` 等内部默认 ``source="chat"``。

历史数据兼容：老 JSONL 没有 ``authority`` 字段，读取时通过
``effective_authority()`` 保守推断，**不重写原文件**（append-only 不可变）。

持久化：``{study_root}/.state/learning_events/YYYY-MM-DD.jsonl``（每天一个文件，
纯追加写入，不重写历史），默认保留 90 天。
"""
from __future__ import annotations

import json
import threading
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field

from core.services.study.paths import get_event_dir
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time, now_str

logger = get_logger("LearningEvent")

# 事件文件保留天数
DEFAULT_KEEP_DAYS = 90

# 权威等级
AUTHORITY_CONFIRMED = "confirmed"   # 学习事实（显式教学 API 写入）
AUTHORITY_OBSERVED = "observed"     # 非权威遥测（被动正则写入）
AUTHORITY_LEGACY = "legacy"         # 老数据：字段缺失，按类型保守推断得到
AUTHORITIES = frozenset({AUTHORITY_CONFIRMED, AUTHORITY_OBSERVED})

# 读取时的 authority 筛选语义
AUTHORITY_ALL = "all"               # 不筛选（调试 / 遥测回放专用）


class LearningEventType(str, Enum):
    """学习事件类型。"""

    TAUGHT = "taught"                              # 讲解了一个知识点
    EXPLAINED = "explained"                        # 换角度解释 / 举例
    QUESTION_ASKED = "question_asked"              # 向用户提问（发起检索练习）
    ANSWER_CORRECT = "answer_correct"              # 用户答对
    ANSWER_INCORRECT = "answer_incorrect"          # 用户答错
    ANSWER_PARTIAL = "answer_partial"              # 用户部分答对
    ANSWER_PENDING_EVALUATION = "answer_pending_evaluation"  # 疑似作答但尚未评价
    HINT_GIVEN = "hint_given"                      # 给出提示
    SELF_REPORTED_CONFUSION = "self_reported_confusion"  # 用户自述没听懂
    REVIEW_SUCCESS = "review_success"              # 间隔复习答对
    REVIEW_FAILURE = "review_failure"              # 间隔复习答错
    MASTERY_CLAIM = "mastery_claim"                # 用户自称已掌握（不作为掌握证据）
    PREREQUISITE_GAP = "prerequisite_gap"          # 前置知识缺口


# 事件类型 → 推断权威等级（仅用于老数据兜底，见 effective_authority）
# 「教了什么 / 答得怎么样」这类是学习事实；「问了一句 / 自称掌握」只是痕迹。
_CONFIRMED_EVENT_TYPES = frozenset(
    {
        LearningEventType.TAUGHT,
        LearningEventType.EXPLAINED,
        LearningEventType.HINT_GIVEN,
        LearningEventType.ANSWER_CORRECT,
        LearningEventType.ANSWER_INCORRECT,
        LearningEventType.ANSWER_PARTIAL,
        LearningEventType.REVIEW_SUCCESS,
        LearningEventType.REVIEW_FAILURE,
    }
)
_OBSERVED_EVENT_TYPES = frozenset(
    {
        LearningEventType.QUESTION_ASKED,
        LearningEventType.ANSWER_PENDING_EVALUATION,
        LearningEventType.MASTERY_CLAIM,
    }
)
# 自述没听懂：可能是用户当面对 AI 说的（api / tool / review），
# 也可能只是正则从聊天记录里捞出来的。前者可信，后者不可信。
_CONFUSION_CONFIRMED_SOURCES = frozenset({"tool", "api", "review", "self_reported"})


class LearningEvent(BaseModel):
    """单条学习事件（不可变证据）。"""

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    event_type: LearningEventType
    subject: str = "general"
    concept_id: str = ""
    concept_name: str = ""
    timestamp: str = ""
    # 本次表现质量 0-1（答题类事件才有）
    quality: Optional[float] = None
    used_hint: bool = False
    user_answer_summary: str = ""
    misconception: Optional[str] = None
    source: str = "chat"          # chat / review / tool / api
    intent: str = ""              # 触发本次事件的教学意图
    session_id: str = ""
    # 权威等级：confirmed（学习事实）/ observed（非权威遥测）/ ""（老数据缺失）。
    # 新写入**必须**显式给出，由 LearningEventStore.record() 强制；
    # 这里留空是为了让没有该字段的老 JSONL 仍能反序列化。
    authority: str = ""

    def model_post_init(self, __context: Any) -> None:  # noqa: D105
        if not self.timestamp:
            self.timestamp = get_current_time().isoformat(timespec="seconds")
        self.subject = str(self.subject or "general").lower().strip() or "general"
        if self.quality is not None:
            self.quality = max(0.0, min(1.0, float(self.quality)))


def effective_authority(event: LearningEvent) -> str:
    """取事件的有效权威等级，兼容没有 ``authority`` 字段的老数据。

    新数据一律用自身字段（写入时已强制明确）。老数据按**事件类型优先**推断，
    ``source`` 只在类型有歧义时参与——因为 ``source`` 本身不是权威判据
    （显式 API 写 ``source="api"``，而内部教学写入默认 ``source="chat"``）。

    ``SELF_REPORTED_CONFUSION`` 是最需要小心的一类：用户当面对 AI 说的
    「我没听懂」是真的，正则从聊天流里捞出来的不是。老数据只能靠 source 区分，
    判不准时**失败关闭**（降级为 observed），宁可少认一条事实，不可多认一条。
    """
    raw = str(getattr(event, "authority", "") or "").strip().lower()
    if raw in AUTHORITIES:
        return raw

    etype = event.event_type
    if etype in _CONFIRMED_EVENT_TYPES:
        return AUTHORITY_CONFIRMED
    if etype in _OBSERVED_EVENT_TYPES:
        return AUTHORITY_OBSERVED
    if etype == LearningEventType.SELF_REPORTED_CONFUSION:
        src = str(getattr(event, "source", "") or "").strip().lower()
        return (
            AUTHORITY_CONFIRMED
            if src in _CONFUSION_CONFIRMED_SOURCES
            else AUTHORITY_OBSERVED
        )
    if etype == LearningEventType.PREREQUISITE_GAP:
        return AUTHORITY_CONFIRMED
    # 未知类型：失败关闭
    return AUTHORITY_OBSERVED


class LearningEventStore:
    """学习事件存储（JSONL 追加写入 + 按天分文件）。"""

    _instance: Optional["LearningEventStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self, event_dir: Optional[Path] = None, keep_days: int = DEFAULT_KEEP_DAYS):
        self._lock = threading.Lock()
        self._dir = Path(event_dir) if event_dir else get_event_dir()
        self._keep_days = max(1, int(keep_days))
        self._pruned = False

    @classmethod
    def get_instance(cls) -> "LearningEventStore":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def append(self, event: LearningEvent) -> LearningEvent:
        """追加一条事件。写入失败只记录日志，不打断教学主流程。

        新事件**必须**带明确的 authority。缺失就拒绝写入并报错——静默兜底成
        ``confirmed`` 会让遥测伪装成事实，这正是本模块要防的事。
        """
        authority = str(getattr(event, "authority", "") or "").strip().lower()
        if authority not in AUTHORITIES:
            raise ValueError(
                f"学习事件缺少明确的 authority（应为 observed / confirmed）："
                f"event_type={event.event_type.value}, source={event.source}"
            )
        with self._lock:
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
                path = self._file_for(event.timestamp)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n")
            except Exception as e:  # noqa: BLE001
                logger.error("写入学习事件失败：%s", e)
            if not self._pruned:
                self._pruned = True
                self.prune()
        return event

    def record(self, *, authority: str, **kwargs: Any) -> LearningEvent:
        """构造并追加一条事件。

        Args:
            authority: **必填**。``confirmed`` 表示学习事实（显式教学 API），
                ``observed`` 表示非权威遥测（被动正则）。故意不设默认值：
                默认值会让调用方在不作判断的情况下把遥测写成事实。
        """
        return self.append(LearningEvent(authority=authority, **kwargs))

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    def read(
        self,
        *,
        concept_id: Optional[str] = None,
        subject: Optional[str] = None,
        event_types: Optional[Iterable[LearningEventType]] = None,
        days: int = 7,
        limit: int = 100,
        authority: Optional[str] = AUTHORITY_CONFIRMED,
    ) -> List[LearningEvent]:
        """按条件读取最近的事件（按时间正序返回）。

        Args:
            authority: 权威筛选，默认 ``confirmed``——即常规读取**默认只看学习
                事实**，遥测不会顺手漏进 prompt / ZPD / 日记。要看全量必须显式
                传 ``AUTHORITY_ALL`` 或 ``None``（调试、遥测回放场景）。
        """
        wanted_auth = _normalize_authority_filter(authority)
        wanted = {str(t) for t in event_types} if event_types else None
        events: List[LearningEvent] = []
        for path in self._recent_files(days):
            for event in self._read_file(path):
                if concept_id and event.concept_id != concept_id:
                    continue
                if subject and event.subject != str(subject).lower().strip():
                    continue
                if wanted and event.event_type.value not in wanted:
                    continue
                if wanted_auth is not None and effective_authority(event) != wanted_auth:
                    continue
                events.append(event)
        events.sort(key=lambda e: e.timestamp)
        return events[-limit:] if limit and limit > 0 else events

    def count(
        self,
        *,
        concept_id: str,
        event_type: LearningEventType,
        days: int = 90,
        authority: Optional[str] = AUTHORITY_CONFIRMED,
    ) -> int:
        return len(
            self.read(
                concept_id=concept_id,
                event_types=[event_type],
                days=days,
                limit=0,
                authority=authority,
            )
        )

    def read_date(
        self, date: str, *, limit: int = 200, authority: Optional[str] = AUTHORITY_CONFIRMED
    ) -> List[LearningEvent]:
        """读取**指定日期**的事件（按时间正序）。

        与 ``read(days=N)`` 的区别：后者取「最近 N 个存在的文件」，当天没有事件时
        会退到更早的日期；日记/日报要按目标日期回溯历史，必须精确到天。

        ``authority`` 默认 ``confirmed``：学习日记只记学习事实，不记遥测。
        """
        day = str(date or "").strip()
        if not day:
            return []
        path = self._dir / f"{day}.jsonl"
        if not path.exists():
            return []
        events = [
            e
            for e in self._read_file(path)
            if wanted_authority_ok(e, authority)
        ]
        events.sort(key=lambda e: e.timestamp)
        return events[-limit:] if limit and limit > 0 else events

    def latest_for_concept(
        self, concept_id: str, days: int = 30, authority: Optional[str] = AUTHORITY_CONFIRMED
    ) -> Optional[LearningEvent]:
        events = self.read(
            concept_id=concept_id, days=days, limit=1, authority=authority
        )
        return events[-1] if events else None

    def to_dict(
        self,
        *,
        concept_id: Optional[str] = None,
        days: int = 7,
        limit: int = 30,
        authority: Optional[str] = AUTHORITY_CONFIRMED,
    ) -> Dict[str, Any]:
        events = self.read(
            concept_id=concept_id, days=days, limit=limit, authority=authority
        )
        return {
            "count": len(events),
            "items": [e.model_dump(mode="json") for e in events],
        }

    # ------------------------------------------------------------------
    # 维护
    # ------------------------------------------------------------------

    def prune(self, keep_days: Optional[int] = None) -> int:
        """删除超过保留期的历史事件文件，返回删除数量。"""
        keep = max(1, int(keep_days if keep_days is not None else self._keep_days))
        try:
            if not self._dir.exists():
                return 0
            files = sorted(self._dir.glob("*.jsonl"))
            removed = 0
            for path in files[:-keep]:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    continue
            return removed
        except Exception as e:  # noqa: BLE001
            logger.warning("清理历史学习事件失败：%s", e)
            return 0

    def reset_cache(self) -> None:
        """重置内部状态（测试用）。"""
        with self._lock:
            self._pruned = False

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _file_for(self, timestamp: str) -> Path:
        day = str(timestamp or "")[:10] or now_str("%Y-%m-%d")
        return self._dir / f"{day}.jsonl"

    def _recent_files(self, days: int) -> List[Path]:
        if not self._dir.exists():
            return []
        count = max(1, int(days))
        return sorted(self._dir.glob("*.jsonl"))[-count:]

    @staticmethod
    def _read_file(path: Path) -> List[LearningEvent]:
        out: List[LearningEvent] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(LearningEvent(**json.loads(line)))
                    except Exception:  # noqa: BLE001
                        # 单行损坏不影响其余事件
                        continue
        except OSError as e:
            logger.debug("读取学习事件文件失败 %s：%s", path, e)
            return []
        return out


def _normalize_authority_filter(authority: Optional[str]) -> Optional[str]:
    """把 authority 筛选参数归一化成「要匹配的等级」或 None（=不筛选）。

    - ``None`` / ``"all"`` → None：全量读取（调试、遥测回放）
    - ``"confirmed"`` / ``"observed"`` → 对应等级
    - 其他值 → 抛错。写错筛选条件比不筛选更危险，宁可让它炸出来。
    """
    if authority is None:
        return None
    value = str(authority).strip().lower()
    if value in ("", AUTHORITY_ALL):
        return None
    if value in AUTHORITIES:
        return value
    raise ValueError(f"非法的 authority 筛选值：{authority!r}（应为 confirmed / observed / all）")


def wanted_authority_ok(event: LearningEvent, authority: Optional[str]) -> bool:
    """单条事件是否通过 authority 筛选（供 read_date 等精确读取复用）。"""
    wanted = _normalize_authority_filter(authority)
    return wanted is None or effective_authority(event) == wanted


def get_learning_event_store() -> LearningEventStore:
    """工厂函数，获取全局单例。"""
    return LearningEventStore.get_instance()
