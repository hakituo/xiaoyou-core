"""把真实学习记录转换成共享确定性计划候选。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional, Sequence

from core.services.journal.models import DailyPlan, PlanItem
from core.services.journal.plan_policy import JournalDayPolicy, JournalPlanSettings
from core.services.planning import PlanCandidate, hhmm_to_minutes
from core.utils.logger import get_logger

logger = get_logger("JournalPlanCandidateBuilder")


@dataclass(slots=True)
class JournalPlanningFacts:
    """用户计划候选使用的真实事实快照。"""

    review_overview: Mapping[str, Any] = field(default_factory=dict)
    due_weaknesses: Sequence[Any] = field(default_factory=tuple)
    yesterday_summary: Mapping[str, Any] = field(default_factory=dict)
    previous_plan: Optional[DailyPlan] = None


@dataclass(slots=True)
class JournalCandidateBundle:
    """候选、日期策略和事实诊断。"""

    candidates: list[PlanCandidate]
    policy: JournalDayPolicy
    facts: JournalPlanningFacts
    has_learning_facts: bool


class JournalPlanCandidateBuilder:
    """读取 Study/Weakness/昨日计划并构造业务候选。"""

    def __init__(self, storage: Any, settings: JournalPlanSettings):
        self.storage = storage
        self.settings = settings

    async def load_facts(self, target_date: datetime) -> JournalPlanningFacts:
        """按精确日期读取候选事实；单个来源失败时安全降级。"""
        review_overview: Mapping[str, Any] = {}
        due_weaknesses: Sequence[Any] = ()
        yesterday_summary: Mapping[str, Any] = {}
        yesterday = target_date - timedelta(days=1)
        yesterday_str = yesterday.strftime("%Y-%m-%d")
        try:
            from core.services.study.service import get_study_service

            study_service = get_study_service()
            review_overview = study_service.get_review_overview() or {}
            # 必须传精确的昨日日期，不能依赖运行时“今天”。
            yesterday_summary = (
                study_service.get_daily_study_summary_data(yesterday_str) or {}
            )
            due_weaknesses = (
                study_service.weakness_tracker.get_due_reviews(
                    target_date.strftime("%Y-%m-%d")
                )
                or ()
            )
        except Exception as exc:
            logger.warning("加载学习计划事实失败，保留其他候选来源: %s", exc)

        previous_plan: Optional[DailyPlan] = None
        try:
            previous_plan = await self.storage.get_plan(yesterday, scope="user")
        except Exception as exc:
            logger.warning("加载昨日用户计划失败: %s", exc)
        return JournalPlanningFacts(
            review_overview=review_overview,
            due_weaknesses=due_weaknesses,
            yesterday_summary=yesterday_summary,
            previous_plan=previous_plan,
        )

    def build(
        self,
        target_date: datetime,
        facts: JournalPlanningFacts,
    ) -> JournalCandidateBundle:
        """把事实转换为稳定键候选，并在空数据时只给两个保底项。"""
        policy = self.settings.policy_for(target_date.date())
        candidates: list[PlanCandidate] = []
        candidates.extend(self._build_carryover_candidates(facts.previous_plan))
        candidates.extend(self._build_review_candidates(facts.review_overview))
        candidates.extend(self._build_weakness_candidates(facts.due_weaknesses))
        summary_candidates, summary_has_facts = self._build_summary_candidates(
            facts.yesterday_summary,
            policy,
        )
        candidates.extend(summary_candidates)

        due_count = self._due_word_count(facts.review_overview)
        has_learning_facts = bool(
            due_count
            or facts.due_weaknesses
            or self._eligible_carryovers(facts.previous_plan)
            or summary_has_facts
        )
        if not has_learning_facts:
            candidates = self._build_fallback_candidates()

        deduplicated: dict[str, PlanCandidate] = {}
        for candidate in candidates:
            previous = deduplicated.get(candidate.key)
            if previous is None or candidate.base_score > previous.base_score:
                deduplicated[candidate.key] = candidate
        return JournalCandidateBundle(
            candidates=list(deduplicated.values()),
            policy=policy,
            facts=facts,
            has_learning_facts=has_learning_facts,
        )

    def _build_review_candidates(
        self,
        overview: Mapping[str, Any],
    ) -> list[PlanCandidate]:
        due_count = self._due_word_count(overview)
        if due_count <= 0:
            return []
        duration = max(25, min(60, 20 + due_count * 2))
        return [
            PlanCandidate(
                key="vocab:due_review",
                title=f"复习到期英语词汇（{due_count} 个）",
                duration_minutes=duration,
                base_score=12.0,
                category="study",
                source="due",
                priority="high",
                repeat_key="vocab:due_review",
                window_keys=("morning", "late_morning", "afternoon"),
                metadata={"subject": "英语", "source_type": "algorithm"},
            )
        ]

    def _build_weakness_candidates(
        self,
        due_weaknesses: Sequence[Any],
    ) -> list[PlanCandidate]:
        candidates: list[PlanCandidate] = []
        for index, weakness in enumerate(due_weaknesses[:4]):
            subject = str(self._value(weakness, "subject", "") or "").strip()
            topic = str(self._value(weakness, "topic", "") or "").strip()
            item_id = str(self._value(weakness, "id", "") or f"{subject}:{topic}")
            if not topic:
                continue
            confidence = float(self._value(weakness, "confidence", 3.0) or 3.0)
            candidates.append(
                PlanCandidate(
                    key=f"weakness:{item_id}",
                    title=f"复习薄弱点：{topic}",
                    duration_minutes=35,
                    base_score=10.0,
                    category="study",
                    source="weakness",
                    priority="high",
                    repeat_key=f"weakness:{item_id}",
                    score_factors={
                        "low_confidence": max(0.0, 6.0 - confidence)
                    },
                    metadata={
                        "subject": subject or None,
                        "description": "按到期薄弱点做一次针对性巩固",
                        "source_type": "algorithm",
                        "source_index": index,
                    },
                )
            )
        return candidates

    def _build_summary_candidates(
        self,
        summary: Mapping[str, Any],
        policy: JournalDayPolicy,
    ) -> tuple[list[PlanCandidate], bool]:
        vocab = summary.get("vocab") or {}
        overview = summary.get("overview") or {}
        subjects = summary.get("subjects") or []
        blueprint = summary.get("next_day_blueprint") or {}
        yesterday_vocab_due = self._safe_int(vocab.get("to_review"))
        total_sessions = int(overview.get("total_sessions") or 0)
        top_subjects = list(overview.get("top_subjects") or [])
        has_facts = bool(
            yesterday_vocab_due or total_sessions or subjects or top_subjects
        )
        candidates: list[PlanCandidate] = []

        if yesterday_vocab_due > 0:
            candidates.append(
                PlanCandidate(
                    # 与实时到期候选共用稳定键；若两者同时存在，实时
                    # get_review_overview 候选因 base_score 更高而胜出。
                    key="vocab:due_review",
                    title=f"复核昨日词汇复习线索（{yesterday_vocab_due} 个）",
                    duration_minutes=max(25, min(45, 20 + yesterday_vocab_due)),
                    base_score=3.0,
                    category="study",
                    source="template",
                    priority="normal",
                    repeat_key="vocab:due_review",
                    window_keys=("morning", "late_morning", "afternoon"),
                    metadata={"subject": "英语", "source_type": "algorithm"},
                )
            )

        subject_names: list[str] = []
        for raw in subjects:
            if isinstance(raw, Mapping):
                name = str(raw.get("subject") or "").strip()
            else:
                name = str(raw or "").strip()
            if name and name not in subject_names:
                subject_names.append(name)
        for raw in top_subjects:
            name = str(raw or "").strip()
            if name and name not in subject_names:
                subject_names.append(name)

        for index, subject in enumerate(subject_names[:2]):
            candidates.append(
                PlanCandidate(
                    key=f"yesterday_subject:{subject}",
                    title=f"巩固昨日重点：{subject}",
                    duration_minutes=60,
                    base_score=7.0 - index,
                    category="study",
                    source="template",
                    priority="normal",
                    repeat_key=f"yesterday_subject:{subject}",
                    metadata={"subject": subject, "source_type": "algorithm"},
                )
            )

        priority_subjects = [
            str(value)
            for value in (blueprint.get("priority_subjects") or [])
            if str(value).strip() and str(value).lower() != "general"
        ]
        blueprint_blocks = list(blueprint.get("timed_blocks") or []) + list(
            blueprint.get("untimed_blocks") or []
        )
        for index, raw in enumerate(blueprint_blocks[:4]):
            if not isinstance(raw, Mapping):
                continue
            name = str(raw.get("name") or "").strip()
            # 当日词汇到期事实只认 get_review_overview；昨日 blueprint 不得
            # 把已经清空的复习队列重新当作今天事实。
            if not name or "词汇" in name:
                continue
            duration = max(15, min(90, int(raw.get("duration_minutes") or 30)))
            preferred_window = self._window_for_time(
                str(raw.get("time") or ""), policy
            )
            subject = priority_subjects[0] if priority_subjects else None
            candidates.append(
                PlanCandidate(
                    key=f"blueprint:{index}:{name}",
                    title=name,
                    duration_minutes=duration,
                    base_score=5.0 if "核心" in name else 2.0,
                    category="study",
                    source="template",
                    priority="high" if "核心" in name else "normal",
                    repeat_key=f"blueprint:{index}:{name}",
                    window_keys=(preferred_window,) if preferred_window else (),
                    metadata={"subject": subject, "source_type": "algorithm"},
                )
            )
        return candidates, has_facts

    def _build_carryover_candidates(
        self,
        previous_plan: Optional[DailyPlan],
    ) -> list[PlanCandidate]:
        candidates: list[PlanCandidate] = []
        for item in self._eligible_carryovers(previous_plan)[
            : self.settings.max_carryover_items
        ]:
            stable_key = item.source_key or item.id
            candidates.append(
                PlanCandidate(
                    key=f"carryover:{stable_key}",
                    title=item.title,
                    duration_minutes=max(10, int(item.estimated_duration_minutes or 0)),
                    base_score=14.0,
                    category=item.category,
                    source="carryover",
                    priority="high" if item.status == "in_progress" else item.priority,
                    repeat_key=stable_key,
                    score_factors={
                        "manual_origin": 8.0 if item.source_type == "manual" else 0.0,
                        "sleep_settlement": 4.0
                        if item.settlement_reason == "sleep"
                        else 0.0,
                    },
                    metadata={
                        "subject": item.subject,
                        "description": item.description,
                        "source_type": "carryover",
                        "carryover_count": int(item.carryover_count or 0) + 1,
                        "deferred_from_date": item.deferred_from_date
                        or (previous_plan.date if previous_plan else None),
                        "settlement_reason": item.settlement_reason,
                    },
                )
            )
        return candidates

    def _eligible_carryovers(
        self,
        previous_plan: Optional[DailyPlan],
    ) -> list[PlanItem]:
        if previous_plan is None:
            return []
        eligible = [
            item
            for item in previous_plan.items
            if int(item.carryover_count or 0) < self.settings.max_carryover_count
            and (
                item.status in {"pending", "in_progress"}
                or (item.status == "skipped" and item.settlement_reason == "sleep")
            )
        ]
        return sorted(
            eligible,
            key=lambda item: (
                item.source_type != "manual",
                item.status != "in_progress",
                item.time or "99:99",
                item.id,
            ),
        )

    def _build_fallback_candidates(self) -> list[PlanCandidate]:
        return [
            PlanCandidate(
                key="fallback:core_study",
                title="完成一个核心学习块",
                duration_minutes=self.settings.fallback_core_minutes,
                base_score=6.0,
                category="study",
                source="template",
                priority="high",
                repeat_key="fallback:core_study",
                metadata={"source_type": "algorithm"},
            ),
            PlanCandidate(
                key="fallback:wrapup",
                title="整理今日学习收尾",
                duration_minutes=self.settings.fallback_wrapup_minutes,
                base_score=2.0,
                category="study",
                source="template",
                priority="normal",
                repeat_key="fallback:wrapup",
                window_keys=("evening",),
                metadata={"source_type": "algorithm"},
            ),
        ]

    @staticmethod
    def _due_word_count(overview: Mapping[str, Any]) -> int:
        raw_due_words = overview.get("due_words", 0)
        due_words = len(raw_due_words) if isinstance(raw_due_words, list) else raw_due_words
        try:
            return max(
                int(overview.get("due_today_count") or 0),
                int(due_words or 0),
            )
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _window_for_time(value: str, policy: JournalDayPolicy) -> str:
        try:
            minute = hhmm_to_minutes(value)
        except (TypeError, ValueError):
            return ""
        for window in policy.windows:
            if window.start_minute <= minute < window.end_minute:
                return window.key
        return ""

    @staticmethod
    def _value(value: Any, key: str, default: Any) -> Any:
        if isinstance(value, Mapping):
            return value.get(key, default)
        return getattr(value, key, default)

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0


__all__ = [
    "JournalCandidateBundle",
    "JournalPlanCandidateBuilder",
    "JournalPlanningFacts",
]
