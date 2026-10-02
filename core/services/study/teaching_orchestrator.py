"""教学编排器（TeachingOrchestrator）—— LLM-aware 的教学协调层。

职责边界
--------
``TutorEngine`` 继续做**规则 / 统计 / 计划层**（不调 LLM、纯聚合）。
本模块是 LLM-aware 的**协调层**，只负责「决定该做什么」，具体实现都在兄弟模块：

| 模块 | 职责 |
|---|---|
| ``concept_rules.py``     | 状态机、阈值、掌握度增量、复习排期的纯规则 |
| ``concept_state.py``     | ConceptState 模型与持久化（权威状态） |
| ``learning_event.py``    | 学习证据日志（append-only） |
| ``evaluation.py``        | 评价载荷校验 |
| ``signal_detector.py``   | 学习信号识别与概念抽取 |
| ``zpd.py``               | ZPD 判定与教学动作决策 |
| ``teaching_context.py``  | 六路数据汇总与 prompt 注入文本 |
| ``teaching_writer.py``   | 学习状态写入（唯一落库路径） |

编排器对外提供稳定 API，内部只做转发与串联，避免重新膨胀成 God Class。
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from core.services.study.concept_state import (
    ConceptState,
    ConceptStateManager,
    get_concept_state_manager,
)
from core.services.study.learning_event import (
    LearningEventStore,
    get_learning_event_store,
)
from core.services.study.signal_detector import LearningIntent, detect_learning_signal
from core.services.study.teaching_context import MAX_DUE_ITEMS, TeachingContextBuilder
from core.services.study.teaching_writer import TeachingWriter
from core.services.study.zpd import decide_action, judge_zpd
from core.utils.logger import get_logger
from core.utils.time_utils import now_str

logger = get_logger("TeachingOrchestrator")

__all__ = ["TeachingOrchestrator", "get_teaching_orchestrator"]


class TeachingOrchestrator:
    """教学编排器（单例）。"""

    _instance: Optional["TeachingOrchestrator"] = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        concept_manager: Optional[ConceptStateManager] = None,
        event_store: Optional[LearningEventStore] = None,
    ):
        self._concepts = concept_manager or get_concept_state_manager()
        self._events = event_store or get_learning_event_store()
        self._context = TeachingContextBuilder(self._concepts, self._events)
        self._writer = TeachingWriter(self._concepts, self._events)

    @classmethod
    def get_instance(cls) -> "TeachingOrchestrator":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ==================================================================
    # 内部组件（供 facade 层复用同一实例）
    # ==================================================================

    @property
    def concepts(self) -> ConceptStateManager:
        return self._concepts

    @property
    def events(self) -> LearningEventStore:
        return self._events

    # ==================================================================
    # 1. 情境识别与概念解析
    # ==================================================================

    def analyze(self, message: str) -> Dict[str, Any]:
        """识别当前消息的教学情境与候选知识点。"""
        signal = detect_learning_signal(message)
        return {
            "is_learning": signal.is_learning,
            "intent": signal.intent.value,
            "subject": signal.subject,
            "concepts": signal.concepts,
            "confidence": signal.confidence,
            "evidence": signal.evidence,
        }

    def resolve_concepts(
        self, message: str, subject: Optional[str] = None
    ) -> List[ConceptState]:
        """把消息里的候选知识点解析成 ConceptState（缺失则创建）。"""
        return self._context.resolve_concepts(message, subject)

    # ==================================================================
    # 2. 决策
    # ==================================================================

    def judge_zpd(self, concept: ConceptState) -> Dict[str, Any]:
        """判断某个知识点当前的最近发展区。"""
        return judge_zpd(concept, self._concepts)

    def decide_action(
        self,
        intent: LearningIntent,
        zpd: Dict[str, Any],
        concept: Optional[ConceptState],
        *,
        due_count: int = 0,
    ) -> Dict[str, Any]:
        """按情境 + ZPD 决定下一步教学动作。"""
        return decide_action(intent, zpd, concept, due_count=due_count)

    def next_action(self, message: str) -> Dict[str, Any]:
        """对外的高层入口：给一句用户消息，返回教学动作建议。"""
        ctx = self.get_context(message)
        return {
            "intent": ctx.get("intent"),
            "subject": ctx.get("subject"),
            "target_concepts": [c["name"] for c in (ctx.get("target_concepts") or [])],
            "zpd": ctx.get("zpd"),
            "action": ctx.get("recommended_action"),
            "due_count": ctx.get("due_count", 0),
        }

    # ==================================================================
    # 3. 读取
    # ==================================================================

    def get_context(
        self, message: Optional[str] = None, subject: Optional[str] = None
    ) -> Dict[str, Any]:
        """汇总持久化学习状态，供教学前读取。"""
        return self._context.get_context(message, subject)

    def get_context_block(self, message: Optional[str] = None) -> str:
        """把学习状态压成紧凑文本，用于 prompt 注入。"""
        return self._context.get_context_block(message)

    # ==================================================================
    # 4. 写入（转发给 TeachingWriter，保持对外 API 稳定）
    # ==================================================================

    def record_teaching(
        self,
        subject: str,
        concept: str,
        *,
        action: str = "taught",
        source: str = "chat",
        prerequisites: Optional[List[str]] = None,
        intent: str = "",
    ) -> Dict[str, Any]:
        """记录一次教学接触（讲解 / 举例 / 给提示）。"""
        return self._writer.record_teaching(
            subject,
            concept,
            action=action,
            source=source,
            prerequisites=prerequisites,
            intent=intent,
        )

    def record_confusion(
        self,
        subject: str,
        concept: str,
        *,
        description: str = "",
        source: str = "chat",
        intent: str = "confusion",
    ) -> Dict[str, Any]:
        """记录用户自述没理解（进入薄弱与复习调度）。"""
        return self._writer.record_confusion(
            subject, concept, description=description, source=source, intent=intent
        )

    def record_answer(
        self,
        subject: str,
        concept: str,
        evaluation: Any,
        *,
        user_answer: str = "",
        source: str = "chat",
        intent: str = "answer_attempt",
        is_review: bool = False,
    ) -> Dict[str, Any]:
        """记录一次作答并评价 —— 教学闭环的核心。"""
        return self._writer.record_answer(
            subject,
            concept,
            evaluation,
            user_answer=user_answer,
            source=source,
            intent=intent,
            is_review=is_review,
        )

    def observe_message(self, message: str, *, source: str = "chat") -> Dict[str, Any]:
        """普通聊天里的自动观察入口（非权威遥测，只记痕迹）。

        写入侧不建状态、不改状态；``latest`` 只用来**绑定**到已有知识点，
        不参与任何准入判断。``latest_concept()`` 已排除无证据的空壳，
        所以这里的回落到不了被清理掉的历史假阳性上。
        """
        signal = detect_learning_signal(message)
        # 只要识别为学习场景就取最近讨论的知识点：它既用于「抽不出概念」时的
        # 回落，也用于「抽得出概念却认不出科目」时的科目兜底。
        latest = self._context.latest_concept(signal.subject) if signal.is_learning else None
        return self._writer.observe_message(
            message, source=source, latest_concept=latest, signal=signal
        )

    def project(self, state: ConceptState) -> None:
        """把知识点状态单向投影到薄弱视图与科目画像。"""
        self._writer.project(state)

    # ==================================================================
    # 6. 按日汇总（供角色日记 / 日报消费）
    # ==================================================================

    def get_daily_concept_summary(self, date: str = "") -> Dict[str, Any]:
        """汇总指定日期的知识点级学习情况。

        数据来源分两层，口径不同要分清：
        - **当天的教学行为**（讲了什么、答对/答错、自述没听懂、靠提示答对）
          从 ``LearningEvent`` 按日期回溯，历史准确；
        - **当前薄弱 / 未验证 / 已掌握** 是 ``ConceptState`` 的**当前快照**，
          不做历史还原——日记里只能作为「目前状态」表述，不能写成「当天」。
        """
        from core.services.study.learning_event import LearningEventType

        day = str(date or "").strip() or now_str("%Y-%m-%d")
        events = self._events.read_date(day)

        taught: List[str] = []
        correct: List[str] = []
        incorrect: List[str] = []
        confused: List[str] = []
        hint_assisted: List[str] = []

        def _add(bucket: List[str], name: str) -> None:
            if name and name not in bucket:
                bucket.append(name)

        for event in events:
            label = event.concept_name or event.subject
            if event.event_type in (LearningEventType.TAUGHT, LearningEventType.EXPLAINED):
                _add(taught, label)
            elif event.event_type in (
                LearningEventType.ANSWER_CORRECT,
                LearningEventType.REVIEW_SUCCESS,
            ):
                _add(correct, label)
                if event.used_hint:
                    _add(hint_assisted, label)
            elif event.event_type in (
                LearningEventType.ANSWER_INCORRECT,
                LearningEventType.REVIEW_FAILURE,
            ):
                _add(incorrect, label)
            elif event.event_type == LearningEventType.SELF_REPORTED_CONFUSION:
                _add(confused, label)

        concepts = self._concepts.all_concepts()
        mastered = [c.name for c in concepts if c.is_mastered]
        weak = [
            {"subject": c.subject, "name": c.name, "mastery": round(c.mastery, 2)}
            for c in self._concepts.list_weak(limit=5)
        ]
        unverified = [
            c.name for c in concepts if not c.verified_by_retrieval and not c.is_mastered
        ]

        if not events and not concepts:
            return {}

        return {
            "date": day,
            "total_concepts": len(concepts),
            "taught": taught[:5],
            "correct": correct[:5],
            "incorrect": incorrect[:5],
            "confused": confused[:5],
            "hint_assisted": hint_assisted[:5],
            "mastered_total": len(mastered),
            "mastered_names": mastered[:5],
            "weak": weak,
            "weak_count": len(weak),
            "unverified_count": len(unverified),
            "unverified_names": unverified[:5],
        }

    # ==================================================================
    # 7. 复习与计划
    # ==================================================================

    def get_review_items(self, limit: int = 10) -> Dict[str, Any]:
        """合并 ConceptState 到期项与薄弱视图，返回统一复习清单。"""
        items: List[Dict[str, Any]] = []
        seen = set()

        for c in self._concepts.list_due():
            if c.concept_id in seen:
                continue
            seen.add(c.concept_id)
            items.append(
                {
                    "concept_id": c.concept_id,
                    "subject": c.subject,
                    "name": c.name,
                    "status": c.status.value,
                    "mastery": c.mastery,
                    "next_review_at": c.next_review_at,
                    "source": "concept_state",
                }
            )

        try:
            for w in self._weakness().get_due_reviews():
                if w.id in seen:
                    continue
                seen.add(w.id)
                items.append(
                    {
                        "concept_id": w.id,
                        "subject": w.subject,
                        "name": w.topic,
                        "status": "weak",
                        "mastery": round(w.confidence / 10.0, 2),
                        "next_review_at": w.next_review_date,
                        "source": "weakness_view",
                    }
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("读取薄弱复习项失败：%s", e)

        items.sort(
            key=lambda x: (x.get("next_review_at") or "9999-12-31", x.get("mastery", 0))
        )
        return {"date": now_str("%Y-%m-%d"), "total": len(items), "items": items[:limit]}

    def get_plan(self) -> Dict[str, Any]:
        """今日学习计划 = TutorEngine 计划 + 到期知识点复习。"""
        try:
            from core.services.study.tutor_engine import get_tutor_engine

            plan = get_tutor_engine().generate_study_plan()
        except Exception as e:  # noqa: BLE001
            logger.warning("生成学习计划失败：%s", e)
            plan = {"items": [], "total_planned_minutes": 0}

        due = self.get_review_items(limit=MAX_DUE_ITEMS)
        plan["concept_reviews"] = due.get("items", [])
        plan["due_concept_count"] = due.get("total", 0)
        return plan

    # ==================================================================
    # 内部
    # ==================================================================

    @staticmethod
    def _weakness():
        from core.services.study.weakness_tracker import get_weakness_tracker

        return get_weakness_tracker()


def get_teaching_orchestrator() -> TeachingOrchestrator:
    """工厂函数，获取全局单例。"""
    return TeachingOrchestrator.get_instance()
