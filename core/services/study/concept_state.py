"""通用知识点级学习状态（ConceptState）。

定位
----
``StudentState`` 只有科目级 confidence 和 recent/struggling topics，颗粒度太粗，
撑不起「AI 家教」需要的知识点级判断。本模块新增知识点级状态，回答四个问题：

1. 用户会什么（``status == mastered``）
2. 用户不会什么（``status == weak``）
3. 用户刚学过什么（``last_taught_at`` / ``status == learning``）
4. 哪些只是听过但没经过检索验证（``successful_retrievals == 0``）

同时区分「独立答对」与「靠提示答对」：``hint_assisted_successes`` 单独计数，
提示成功不计入 ``independent_success_streak``，因此不会被误判为掌握。

状态机与阈值、掌握度增量、复习排期等**纯规则**在 ``concept_rules.py``，
本文件只负责数据模型与持久化。

数据所有权
----------
ConceptState 是**知识点掌握状态的唯一权威源**。WeaknessTracker 只作为它的
复习调度投影；LLM 不能直接改这里的数据，所有写入必须走
``apply_evaluation`` / ``mark_taught`` / ``mark_confused``。

持久化：``{study_root}/.state/concepts.json``
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core.services.study.concept_rules import (
    MASTERED_MASTERY_THRESHOLD,
    MASTERED_STREAK_THRESHOLD,
    ConceptStatus,
    clamp,
    clamp01,
    compute_mastery_delta,
    compute_next_review,
    max_review_level,
    recompute_status,
)
from core.services.study.paths import backup_corrupt_file, get_state_file
from core.utils.atomic_io import safe_json_dump
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time, now_str

logger = get_logger("ConceptState")

# 状态文件结构版本，便于后续迁移
SCHEMA_VERSION = 1

__all__ = [
    "ConceptStatus",
    "ConceptState",
    "ConceptStateManager",
    "get_concept_state_manager",
    "MASTERED_MASTERY_THRESHOLD",
    "MASTERED_STREAK_THRESHOLD",
]


class ConceptState(BaseModel):
    """单个知识点的聚合状态（不是历史明细，明细见 LearningEvent）。"""

    concept_id: str
    subject: str
    name: str

    status: ConceptStatus = ConceptStatus.UNKNOWN
    mastery: float = Field(default=0.0, ge=0.0, le=1.0, description="掌握度 0-1")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="自信度 0-1")
    evidence_count: int = 0

    # 检索表现：只有独立答对才推动「掌握」判定
    successful_retrievals: int = 0
    failed_retrievals: int = 0
    hint_assisted_successes: int = 0
    independent_success_streak: int = 0
    independent_failure_streak: int = 0

    # 教学接触
    taught_count: int = 0
    first_seen_at: str = ""
    last_taught_at: str = ""
    last_tested_at: str = ""
    last_success_at: str = ""

    prerequisites: List[str] = Field(default_factory=list)

    # 间隔复习（日期字符串 YYYY-MM-DD，便于与 WeaknessTracker 对齐）
    next_review_at: str = ""
    review_level: int = 0

    last_updated_at: str = ""

    # ---- 便捷判断 ----

    @property
    def is_mastered(self) -> bool:
        return self.status == ConceptStatus.MASTERED

    @property
    def is_weak(self) -> bool:
        return self.status == ConceptStatus.WEAK

    @property
    def verified_by_retrieval(self) -> bool:
        """是否通过过独立检索验证（区分「听过」与「能答出来」）。"""
        return self.independent_success_streak > 0 or self.successful_retrievals > 0

    @property
    def is_confirmed_state(self) -> bool:
        """是否**被显式学习动作确认过**的状态（而非空壳占位）。

        用途：``latest_concept()`` 这类「承接上一轮」的回落入口只认它，
        免得把从没被学过的占位概念当成「最近讨论过的知识点」。

        **`first_seen_at` 不参与判定**——它在 ``get_or_create()`` 创建任何状态时
        就立刻写入，而新建状态按设计就是 ``UNKNOWN / evidence_count=0``。
        它表示「什么时候第一次进入状态存储」，不是「什么时候被确认学过」，
        赋予它 authority 语义会让所有空壳自动通过。

        判定条件看起来冗余，是**故意给历史数据容错**的。正常路径下
        ``mark_taught`` / ``apply_evaluation`` / ``mark_confused`` 都会留下证据，
        ``evidence_count > 0`` 几乎就够了；但有两个明确例外必须覆盖：

        - ``mark_mastered()`` 是人工纠正入口，可以把全新知识点直接设为 MASTERED，
          这种状态没有常规教学证据，却显然是显式权威状态，不能被过滤掉；
        - 历史数据里可能存在 evidence_count 没同步好、但明显已教学 / 已测试的记录。

        等 reconcile 做完、状态一致性有保证后，本 helper 可以收缩成::

            return state.evidence_count > 0 or state.status != ConceptStatus.UNKNOWN
        """
        return bool(
            self.evidence_count > 0
            or self.status != ConceptStatus.UNKNOWN
            or self.taught_count > 0
            or str(self.last_taught_at or "").strip()
            or str(self.last_tested_at or "").strip()
            or self.successful_retrievals > 0
            or self.failed_retrievals > 0
        )

    @staticmethod
    def make_id(subject: str, name: str) -> str:
        """根据科目+知识点名生成稳定 ID。

        哈希规则与 ``WeaknessItem.make_id`` **完全一致**，这样 ConceptState
        与薄弱视图指向同一条知识点，跨模块按 id 互查不会错位。
        """
        raw = f"{str(subject).lower().strip()}::{str(name).strip()}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def normalize_subject(subject: str) -> str:
        return str(subject or "").lower().strip() or "general"

    @staticmethod
    def normalize_name(name: str) -> str:
        return " ".join(str(name or "").split())

    @staticmethod
    def loose_name(name: str) -> str:
        """宽松归一化，用于识别同一个知识点的不同写法。

        LLM 在不同轮次可能把同一个知识点写成「F = -kx」和「F = -kx（回复力方向）」，
        严格 ID 会把它们当成两个知识点，导致学习证据被劈开。
        此处去掉括号内容与空白后比较，只用于**匹配**，不改动展示名。
        """
        import re

        text = str(name or "")
        text = re.sub(r"[（(][^（()）]*[)）]", "", text)
        text = re.sub(r"\s+", "", text)
        return text.strip().lower()


class ConceptStateManager:
    """知识点状态管理器（线程安全的 JSON 持久化单例）。"""

    _instance: Optional["ConceptStateManager"] = None
    _instance_lock = threading.Lock()

    def __init__(self, state_file: Optional[Path] = None):
        self._lock = threading.RLock()
        self._concepts: Optional[Dict[str, ConceptState]] = None
        self._state_file = Path(state_file) if state_file else get_state_file("concepts.json")

    @classmethod
    def get_instance(cls) -> "ConceptStateManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # 加载 / 保存
    # ------------------------------------------------------------------

    def load(self) -> Dict[str, ConceptState]:
        """加载全部知识点状态；文件损坏时备份并安全重建。"""
        with self._lock:
            if self._concepts is not None:
                return self._concepts

            if not self._state_file.exists():
                self._concepts = {}
                return self._concepts

            try:
                import json

                raw = json.loads(self._state_file.read_text(encoding="utf-8"))
                items = raw.get("concepts", {}) if isinstance(raw, dict) else {}
                concepts: Dict[str, ConceptState] = {}
                for key, value in items.items():
                    try:
                        state = ConceptState(**value)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("跳过损坏的知识点记录 %s: %s", key, exc)
                        continue
                    concepts[state.concept_id or key] = state
                self._concepts = concepts
                logger.info("已加载知识点状态：%d 个 concept", len(concepts))
            except Exception as e:  # noqa: BLE001
                backup = backup_corrupt_file(self._state_file)
                logger.error("加载知识点状态失败，已备份损坏文件到 %s：%s", backup, e)
                self._concepts = {}
            return self._concepts

    def save(self) -> None:
        """原子写盘。"""
        with self._lock:
            if self._concepts is None:
                return
            try:
                payload = {
                    "version": SCHEMA_VERSION,
                    "updated_at": get_current_time().isoformat(timespec="seconds"),
                    "concepts": {
                        cid: state.model_dump(mode="json")
                        for cid, state in self._concepts.items()
                    },
                }
                safe_json_dump(payload, self._state_file, encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                logger.error("保存知识点状态失败：%s", e)

    def _all(self) -> Dict[str, ConceptState]:
        if self._concepts is None:
            self.load()
        return self._concepts  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get(self, concept_id: str) -> Optional[ConceptState]:
        return self._all().get(str(concept_id))

    def get_by_name(self, subject: str, name: str) -> Optional[ConceptState]:
        return self._all().get(ConceptState.make_id(subject, name))

    def all_concepts(self) -> List[ConceptState]:
        """返回全部知识点状态的列表快照。"""
        return list(self._all().values())

    def list_by_subject(
        self, subject: str, *, status: Optional[ConceptStatus] = None
    ) -> List[ConceptState]:
        key = ConceptState.normalize_subject(subject)
        items = [c for c in self._all().values() if c.subject == key]
        if status is not None:
            items = [c for c in items if c.status == status]
        return items

    def list_due(self, date: Optional[str] = None) -> List[ConceptState]:
        """返回到期该复习的知识点（不含 unknown）。"""
        target = date or now_str("%Y-%m-%d")
        items = [
            c
            for c in self._all().values()
            if c.status != ConceptStatus.UNKNOWN
            and c.next_review_at
            and c.next_review_at <= target
        ]
        items.sort(key=lambda c: (c.next_review_at, c.mastery))
        return items

    def list_weak(self, limit: Optional[int] = None) -> List[ConceptState]:
        items = [c for c in self._all().values() if c.status == ConceptStatus.WEAK]
        items.sort(key=lambda c: (c.mastery, c.next_review_at or "9999-12-31"))
        return items[:limit] if limit else items

    def get_mastered_names(self, subject: Optional[str] = None) -> List[str]:
        """返回已掌握知识点名称，供 ZPD 前置判定使用。"""
        key = ConceptState.normalize_subject(subject) if subject else None
        return [
            c.name
            for c in self._all().values()
            if c.status == ConceptStatus.MASTERED and (key is None or c.subject == key)
        ]

    def to_dict(self, *, subject: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """返回序列化快照（供 API / prompt 使用）。"""
        items = list(self._all().values())
        if subject:
            key = ConceptState.normalize_subject(subject)
            items = [c for c in items if c.subject == key]
        items.sort(key=lambda c: (c.mastery, c.last_updated_at), reverse=True)
        return {
            "total": len(items),
            "items": [c.model_dump(mode="json") for c in items[:limit]],
        }

    # ------------------------------------------------------------------
    # 写入（唯一权威入口）
    # ------------------------------------------------------------------

    def get_or_create(
        self,
        subject: str,
        name: str,
        *,
        prerequisites: Optional[List[str]] = None,
    ) -> ConceptState:
        """获取或创建知识点状态。"""
        with self._lock:
            key = ConceptState.normalize_subject(subject)
            display = ConceptState.normalize_name(name)
            cid = ConceptState.make_id(key, display)
            concepts = self._all()
            state = concepts.get(cid)
            if state is None:
                # 名称漂移兜底：先按宽松名找已有知识点，避免同一概念被拆成多条
                state = self._find_by_loose_name(key, display)
            if state is None:
                now = get_current_time().isoformat(timespec="seconds")
                state = ConceptState(
                    concept_id=cid,
                    subject=key,
                    name=display,
                    first_seen_at=now,
                    last_updated_at=now,
                    prerequisites=list(prerequisites or []),
                )
                concepts[cid] = state
                self.save()
            elif prerequisites:
                # 补齐前置知识，不覆盖已有内容
                merged = list(dict.fromkeys([*state.prerequisites, *prerequisites]))
                if merged != state.prerequisites:
                    state.prerequisites = merged
                    self.save()
            return state

    # 允许「限定词后缀/前缀」合并的最短长度，避免把短知识点误并
    # （如「动量」不能被「动量守恒」吞掉，故阈值设为 4）
    MIN_SUFFIX_MERGE_LEN = 4

    def _find_by_loose_name(self, subject: str, name: str) -> Optional[ConceptState]:
        """在指定科目内按宽松名查找已存在的知识点。

        两级匹配：
        1. 宽松名完全相等（去括号、去空白、忽略大小写）；
        2. 一方是另一方的**后缀**且较短者至少 4 个字符——处理模型加上限定词的写法，
           如「胡克定律 F=-kx」与「F = -kx」。
           长度下限用于避免「动量」被「动量守恒」这类不同知识点误并。
        """
        target = ConceptState.loose_name(name)
        if not target:
            return None
        for state in self._all().values():
            if state.subject != subject:
                continue
            existing = ConceptState.loose_name(state.name)
            if existing == target:
                return state
            shorter, longer = sorted((existing, target), key=len)
            if len(shorter) >= self.MIN_SUFFIX_MERGE_LEN and longer.endswith(shorter):
                return state
        return None

    def mark_taught(
        self,
        subject: str,
        name: str,
        *,
        action: str = "taught",
        prerequisites: Optional[List[str]] = None,
    ) -> ConceptState:
        """记录一次教学接触（讲解/举例/给提示等）。

        注意：教学接触只把 unknown 推进到 learning，**绝不会**直接变成 mastered。
        """
        with self._lock:
            state = self.get_or_create(subject, name, prerequisites=prerequisites)
            now = get_current_time().isoformat(timespec="seconds")
            state.taught_count += 1
            state.evidence_count += 1
            state.last_taught_at = now
            state.last_updated_at = now
            if state.status == ConceptStatus.UNKNOWN:
                state.status = ConceptStatus.LEARNING
            self.save()
            return state

    def apply_evaluation(
        self,
        subject: str,
        name: str,
        *,
        correctness: float,
        independent: bool = True,
        used_hint: bool = False,
        confidence_delta: float = 0.0,
        prerequisites: Optional[List[str]] = None,
    ) -> ConceptState:
        """应用一次答题评价，更新掌握度与状态。

        掌握度增量由后端规则计算，**不采用** LLM 返回的 mastery_delta，
        避免模型直接操纵用户的学习状态。

        Args:
            correctness: 0-1，答对程度
            independent: 是否独立作答（未看答案/未要提示）
            used_hint: 是否使用了提示
            confidence_delta: LLM 给出的自信度增量（会被裁剪）
        """
        with self._lock:
            state = self.get_or_create(subject, name, prerequisites=prerequisites)
            now = get_current_time().isoformat(timespec="seconds")
            today = now_str("%Y-%m-%d")

            correctness = clamp01(correctness)
            # 用了提示就不算独立作答，避免「提示成功」被记成独立掌握
            effective_independent = bool(independent) and not bool(used_hint)

            state.mastery = clamp01(
                state.mastery
                + compute_mastery_delta(
                    correctness=correctness,
                    independent=effective_independent,
                    used_hint=bool(used_hint),
                )
            )
            state.confidence = clamp01(
                state.confidence + clamp(confidence_delta, -0.3, 0.3)
            )
            state.evidence_count += 1
            state.last_tested_at = now
            state.last_updated_at = now

            if correctness >= MASTERED_MASTERY_THRESHOLD:
                state.successful_retrievals += 1
                state.last_success_at = now
                if effective_independent:
                    state.independent_success_streak += 1
                    state.independent_failure_streak = 0
                    state.review_level = min(state.review_level + 1, max_review_level())
                else:
                    # 提示成功不推动 streak，也不推进复习等级
                    state.hint_assisted_successes += 1
            elif correctness < 0.5:
                state.failed_retrievals += 1
                state.independent_success_streak = 0
                state.independent_failure_streak += 1
                state.review_level = max(0, state.review_level - 1)
            else:
                # 部分正确：不奖励 streak，也不惩罚到 failure
                state.independent_success_streak = 0

            recompute_status(state)
            state.next_review_at = compute_next_review(state, today)
            self.save()
            logger.info(
                "知识点状态更新：[%s] %s -> %s (mastery=%.2f)",
                state.subject,
                state.name,
                state.status.value,
                state.mastery,
            )
            return state

    def mark_confused(self, subject: str, name: str, *, mastery_penalty: float = 0.05) -> ConceptState:
        """记录「用户自述没听懂」。

        自述没听懂不足以判定为答错，因此只做轻微下调掌握度 + 清零成功连击，
        但会立刻把状态推到 weak，让它进入薄弱视图与复习调度。
        """
        with self._lock:
            state = self.get_or_create(subject, name)
            today = now_str("%Y-%m-%d")
            state.evidence_count += 1
            state.independent_success_streak = 0
            state.independent_failure_streak = max(1, state.independent_failure_streak)
            state.mastery = clamp01(state.mastery - max(0.0, float(mastery_penalty)))
            state.last_updated_at = get_current_time().isoformat(timespec="seconds")
            recompute_status(state)
            state.next_review_at = compute_next_review(state, today)
            self.save()
            return state

    def mark_mastered(self, subject: str, name: str) -> ConceptState:
        """手动标记为已掌握（人工纠正用）。

        正常教学流程**不应**走这里——掌握必须由多次独立检索证据驱动；
        本方法只服务于用户/管理端显式纠正（如历史数据迁移或误判修复）。
        """
        with self._lock:
            state = self.get_or_create(subject, name)
            today = now_str("%Y-%m-%d")
            state.mastery = max(state.mastery, MASTERED_MASTERY_THRESHOLD + 0.1)
            state.independent_success_streak = max(
                state.independent_success_streak, MASTERED_STREAK_THRESHOLD
            )
            state.independent_failure_streak = 0
            state.evidence_count += 1
            state.last_updated_at = get_current_time().isoformat(timespec="seconds")
            recompute_status(state)
            state.next_review_at = compute_next_review(state, today)
            self.save()
            return state

    def set_prerequisites(self, subject: str, name: str, prerequisites: List[str]) -> ConceptState:
        """显式设置前置知识。"""
        with self._lock:
            state = self.get_or_create(subject, name)
            state.prerequisites = list(dict.fromkeys(prerequisites or []))
            state.last_updated_at = get_current_time().isoformat(timespec="seconds")
            self.save()
            return state

    def reset_cache(self) -> None:
        """清空内存缓存（测试用，避免跨用例共享全局状态）。"""
        with self._lock:
            self._concepts = None


def get_concept_state_manager() -> ConceptStateManager:
    """工厂函数，获取全局单例。"""
    return ConceptStateManager.get_instance()
