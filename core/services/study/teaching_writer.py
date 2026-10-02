"""教学状态写入 —— 学习状态变更的唯一落库路径。

从 ``teaching_orchestrator.py`` 抽出的**写入层**。所有对 ConceptState /
LearningEvent 的修改都收敛在这里，保证：

- LLM 只提供结构化评价，掌握度增量与状态由后端规则计算；
- 教学接触只推进到 learning，掌握必须由独立检索证据驱动；
- 每次写入后单向投影到薄弱视图与科目画像，避免多源打架。

两条写入通道，权限完全不同（见 ``learning_event`` 的 authority 说明）：

==================  ==========================  ==========================
通道                典型入口                    ConceptState 写权限
==================  ==========================  ==========================
显式教学（事实）    ``record_teaching`` 等      ✅ 可建、可改
被动观察（遥测）    ``observe_message``         ❌ 一律不可，只读绑定
==================  ==========================  ==========================

编排器只负责决定「该调用哪个写入动作」，具体怎么写由本模块负责。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.services.study.concept_state import ConceptState, ConceptStateManager
from core.services.study.evaluation import EvaluationService
from core.services.study.learning_event import (
    AUTHORITY_CONFIRMED,
    AUTHORITY_OBSERVED,
    LearningEventStore,
    LearningEventType,
)
from core.services.study.signal_detector import LearningIntent, LearningSignal
from core.utils.logger import get_logger

logger = get_logger("TeachingWriter")

# 被动观察的教学意图 → 事件类型。全部落在遥测侧（见 learning_event 的类型推断）。
_OBSERVED_EVENT_FOR_INTENT = {
    LearningIntent.CONFUSION: LearningEventType.SELF_REPORTED_CONFUSION,
    LearningIntent.MASTERY_CLAIM: LearningEventType.MASTERY_CLAIM,
    LearningIntent.ANSWER_ATTEMPT: LearningEventType.ANSWER_PENDING_EVALUATION,
    LearningIntent.PURE_QUERY: LearningEventType.QUESTION_ASKED,
    LearningIntent.TEACHING_REQUEST: LearningEventType.QUESTION_ASKED,
}


class TeachingWriter:
    """学习状态的唯一写入入口。"""

    def __init__(
        self,
        concepts: ConceptStateManager,
        events: LearningEventStore,
        evaluation: Optional[EvaluationService] = None,
    ):
        self._concepts = concepts
        self._events = events
        self._evaluation = evaluation or EvaluationService()

    # ------------------------------------------------------------------
    # 依赖获取（延迟导入，避免循环依赖）
    # ------------------------------------------------------------------

    @staticmethod
    def _weakness():
        from core.services.study.weakness_tracker import get_weakness_tracker

        return get_weakness_tracker()

    @staticmethod
    def _student_state():
        from core.services.study.student_state import get_student_state_manager

        return get_student_state_manager()

    @staticmethod
    def _daily_tracker():
        from core.services.study.daily_tracker import get_daily_tracker

        return get_daily_tracker()

    # ------------------------------------------------------------------
    # 教学接触
    # ------------------------------------------------------------------

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
        """记录一次教学接触（讲解 / 举例 / 给提示）。

        教学接触只会把知识点推进到 learning，不会直接变成 mastered。
        """
        if not subject or not concept:
            return {"status": "error", "message": "缺少 subject 或 concept"}

        event_type = {
            "taught": LearningEventType.TAUGHT,
            "explained": LearningEventType.EXPLAINED,
            "hint": LearningEventType.HINT_GIVEN,
        }.get(action, LearningEventType.TAUGHT)

        state = self._concepts.mark_taught(
            subject, concept, action=action, prerequisites=prerequisites
        )
        self._events.record(
            authority=AUTHORITY_CONFIRMED,
            event_type=event_type,
            subject=state.subject,
            concept_id=state.concept_id,
            concept_name=state.name,
            source=source,
            intent=intent,
            used_hint=event_type == LearningEventType.HINT_GIVEN,
        )
        self.project(state)
        return {
            "status": "success",
            "concept_id": state.concept_id,
            "status_after": state.status.value,
            "mastery": state.mastery,
        }

    # ------------------------------------------------------------------
    # 自述没听懂
    # ------------------------------------------------------------------

    def record_confusion(
        self,
        subject: str,
        concept: str,
        *,
        description: str = "",
        source: str = "chat",
        intent: str = "confusion",
    ) -> Dict[str, Any]:
        """记录用户自述没理解：写入事件并把知识点降级到薄弱。

        这里不给掌握度加任何分，但会立刻把状态推成 weak，
        让它进入薄弱视图与复习调度——这正是「查漏补缺」的入口。
        """
        if not subject or not concept:
            return {"status": "error", "message": "缺少 subject 或 concept"}

        state = self._concepts.mark_confused(subject, concept)

        self._events.record(
            authority=AUTHORITY_CONFIRMED,
            event_type=LearningEventType.SELF_REPORTED_CONFUSION,
            subject=state.subject,
            concept_id=state.concept_id,
            concept_name=state.name,
            source=source,
            intent=intent,
            user_answer_summary=description[:200],
            misconception=description[:200] or None,
        )
        self.project(state)
        try:
            self._daily_tracker().record_struggle(state.subject, state.name, description)
        except Exception as e:  # noqa: BLE001
            logger.warning("写入每日困难记录失败：%s", e)

        return {
            "status": "success",
            "concept_id": state.concept_id,
            "status_after": state.status.value,
            "mastery": state.mastery,
            "next_review_at": state.next_review_at,
        }

    # ------------------------------------------------------------------
    # 作答评价（闭环核心）
    # ------------------------------------------------------------------

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
        """记录一次作答并评价。

        评价载荷由 LLM 提供（结构化 JSON），这里做范围校验；
        状态更新与掌握度增量全部由后端计算，LLM 无法直接改状态。

        Returns:
            ``{"status": "error"}`` 表示载荷不可信，调用方不应更新任何状态。
        """
        if not subject or not concept:
            return {"status": "error", "message": "缺少 subject 或 concept"}

        result, warnings = self._evaluation.parse(evaluation)
        if result is None:
            logger.warning("评价载荷不可信，已放弃状态更新：%s", warnings)
            return {"status": "error", "message": "评价载荷不可信", "warnings": warnings}

        state = self._concepts.apply_evaluation(
            subject,
            concept,
            correctness=result.correctness,
            independent=result.independent,
            used_hint=result.used_hint,
            confidence_delta=result.confidence_delta,
        )

        event_type = result.event_type
        if is_review:
            event_type = (
                LearningEventType.REVIEW_SUCCESS
                if result.verdict == "correct"
                else LearningEventType.REVIEW_FAILURE
            )

        self._events.record(
            authority=AUTHORITY_CONFIRMED,
            event_type=event_type,
            subject=state.subject,
            concept_id=state.concept_id,
            concept_name=state.name,
            quality=result.correctness,
            used_hint=result.used_hint,
            user_answer_summary=str(user_answer or "")[:200],
            misconception=result.misconception,
            source=source,
            intent=intent,
        )
        self.project(state)
        self._record_daily_outcome(state, result.verdict, result.misconception)

        return {
            "status": "success",
            "concept_id": state.concept_id,
            "verdict": result.verdict,
            "status_after": state.status.value,
            "mastery": state.mastery,
            "independent": result.independent,
            "used_hint": result.used_hint,
            "next_review_at": state.next_review_at,
            "recommended_action": result.recommended_action,
            "warnings": warnings,
        }

    def _record_daily_outcome(
        self, state: ConceptState, verdict: str, misconception: Optional[str]
    ) -> None:
        """把有意义的状态变化写入每日记录（避免同一知识点反复刷屏）。"""
        try:
            daily = self._daily_tracker()
            if verdict == "correct":
                daily.record_knowledge_point(
                    state.subject,
                    state.name,
                    "mastered" if state.is_mastered else "reviewed",
                )
            elif verdict == "incorrect":
                daily.record_knowledge_point(state.subject, state.name, "struggling")
                daily.record_struggle(state.subject, state.name, misconception or "")
        except Exception as e:  # noqa: BLE001
            logger.warning("写入每日学习记录失败：%s", e)

    # ------------------------------------------------------------------
    # 普通聊天自动观察
    # ------------------------------------------------------------------

    def observe_message(
        self,
        message: str,
        *,
        source: str = "chat",
        latest_concept: Optional[ConceptState] = None,
        signal: Optional[LearningSignal] = None,
    ) -> Dict[str, Any]:
        """普通聊天里的自动观察入口。

        **这是非权威遥测层。** 它只能做三件事：观察、留痕、绑定。它不能建状态、
        不能改状态、不能进正常 prompt。

        为什么要这么严：被动观察是「高召回 / 低精度」的。日常聊天里真正的学习语句
        极少，正则再准，假阳性数量也会超过真记录；而被正则捞出来的东西一旦能落进
        ``ConceptState``，就会顺着 ``get_context() → prompt → LLM 调工具`` 绕一圈
        变成正式事实。所以这里全部写 ``authority="observed"``：
        ``latest_concept()`` 不认它、复习计划不认它、prompt 默认不喂它。
        要变成事实，必须由 LLM 显式调 ``study_record_*``。

        作答的**对错判定**同样不在这里做——必须由 LLM 调
        ``study_record_answer`` 走 ``record_answer``。
        """
        if signal is None:
            from core.services.study.signal_detector import detect_learning_signal

            signal = detect_learning_signal(message)

        if not signal.is_learning:
            return {"status": "skipped", "reason": "not_learning"}

        # 抽不出知识点时，回落到最近一次讨论的知识点（已确认的那种）。
        # 作答尤其依赖这条：用户常常只说「答案是…」，不带知识点名。
        # 若连最近讨论过的知识点都没有，说明没有学习上下文，直接跳过。
        concepts = list(signal.concepts)
        subject = signal.subject
        if not concepts:
            if latest_concept is None:
                return {"status": "skipped", "reason": "no_concept"}
            concepts = [latest_concept.name]
            subject = latest_concept.subject

        if not subject:
            # 抽得出知识点却认不出科目时（「我没听懂，压缩是什么意思」），
            # 用最近讨论过的科目兜底，否则整条证据会被丢弃。
            if latest_concept is None:
                return {"status": "skipped", "reason": "no_subject"}
            subject = latest_concept.subject

        # 绑定到已有概念是为了让痕迹可追溯，**不是**为了造概念。
        # 只读不建：找不到已确认的知识点时，痕迹照样落盘，只是没有 concept_id。
        bound = self._bind_concept(subject, concepts, latest_concept=latest_concept)

        recorded: List[str] = []
        for name in concepts:
            concept_id, concept_name = bound.get(name, ("", name))
            self._record_observation(
                event_type=_OBSERVED_EVENT_FOR_INTENT.get(
                    signal.intent, LearningEventType.QUESTION_ASKED
                ),
                subject=subject,
                concept_id=concept_id,
                concept_name=concept_name,
                intent=signal.intent.value,
                message=message,
                source=source,
            )
            recorded.append(name)

        return {
            "status": "recorded",
            "authority": AUTHORITY_OBSERVED,
            "intent": signal.intent.value,
            "subject": subject,
            "concepts": recorded,
        }

    def _bind_concept(
        self,
        subject: str,
        names: List[str],
        *,
        latest_concept: Optional[ConceptState] = None,
    ) -> Dict[str, tuple]:
        """把观察到的名字绑到**已存在**的知识点上（只读不建）。

        Returns:
            ``{消息里的名字: (concept_id, 规范名)}``；绑不上的名字缺席，
            调用方用 ``("", 原名字)`` 兜底——痕迹可以没有 concept_id，
            但不能因此被丢掉，也不能因此凭空造出一个概念。
        """
        out: Dict[str, tuple] = {}
        for name in names:
            state = self._concepts.get_by_name(subject, name)
            if state is None:
                state = self._concepts._find_by_loose_name(subject, name)
            if state is not None:
                out[name] = (state.concept_id, state.name)
            elif latest_concept is not None and name == latest_concept.name:
                out[name] = (latest_concept.concept_id, latest_concept.name)
        return out

    def _record_observation(
        self,
        *,
        event_type: LearningEventType,
        subject: str,
        concept_id: str,
        concept_name: str,
        intent: str,
        message: str,
        source: str,
    ) -> None:
        """落一条 ``observed`` 遥测事件。**不触碰 ConceptState。**

        这是被动观察唯一的写出口：想加新的被动识别类型，就加到这里，
        不允许再出现第二个直写状态的入口。
        """
        self._events.record(
            authority=AUTHORITY_OBSERVED,
            event_type=event_type,
            subject=subject or "general",
            concept_id=concept_id,
            concept_name=concept_name,
            source=source,
            intent=intent,
            user_answer_summary=str(message or "")[:200],
        )

    # ------------------------------------------------------------------
    # 投影（ConceptState -> 薄弱视图 / 科目画像）
    # ------------------------------------------------------------------

    def project(self, state: ConceptState) -> None:
        """把知识点状态单向投影到薄弱视图与科目画像。"""
        try:
            self._weakness().sync_from_concept_state(state)
        except Exception as e:  # noqa: BLE001
            logger.warning("投影薄弱视图失败：%s", e)

        try:
            concepts = self._concepts.list_by_subject(state.subject)
            if concepts:
                avg = sum(c.mastery for c in concepts) / len(concepts)
                self._student_state().upsert_subject_rollup(
                    state.subject,
                    confidence=round(avg * 10.0, 2),
                    topics=[c.name for c in concepts[-10:]],
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("投影科目画像失败：%s", e)
