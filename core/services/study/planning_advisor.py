"""受约束的 LLM 学习内容顾问；模型只能对白名单 Curriculum 做软排序。"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from core.services.scheduler.task.task_scheduler import get_global_scheduler
from core.services.study.concept_resolver import CurriculumConceptIndex
from core.services.study.curriculum import CurriculumProgress
from core.utils.json_utils import extract_json_object
from core.utils.logger import get_logger

logger = get_logger("StudyPlanningAdvisor")
MAX_ADVICE_ITEMS = 8
MAX_PROMPT_MODULES = 40


@dataclass(frozen=True, slots=True)
class StudyPlanningAdvice:
    priority_module_ids: tuple[str, ...] = ()
    subject_minutes: tuple[tuple[str, int], ...] = ()
    rationale: str = ""
    source: str = "deterministic"

    @property
    def subject_minutes_map(self) -> dict[str, int]:
        return dict(self.subject_minutes)


class StudyPlanningAdvisor:
    async def advise(
        self,
        *,
        target_date: str,
        daily_goal_minutes: int,
        curriculum_progress: Sequence[CurriculumProgress],
        review_overview: Mapping[str, Any],
        due_weaknesses: Sequence[Any],
        yesterday_summary: Mapping[str, Any],
    ) -> StudyPlanningAdvice:
        index = CurriculumConceptIndex()
        meta = index.load()
        # JournalPlanCandidateBuilder 持有的就是这个 list；在这里做 exam-scope
        # 事实清洗，Tutor/Teaching 的通用 WeaknessTracker 视图仍保留发散学习。
        if isinstance(due_weaknesses, list) and meta:
            due_weaknesses[:] = self._exam_weaknesses(due_weaknesses, index, meta)

        eligible = [
            item for item in curriculum_progress
            if item.module.required
            and not item.is_mastered
            and item.is_autonomous_planning_safe
            and getattr(meta.get(item.module.id), "planner_mode", "concept") != "external"
            and (item.is_ready or item.status in {"learning", "weak"})
        ]
        if not eligible:
            return StudyPlanningAdvice()
        prompt = self._build_prompt(
            target_date=target_date,
            daily_goal_minutes=daily_goal_minutes,
            eligible=eligible,
            review_overview=review_overview,
            due_weaknesses=due_weaknesses,
            yesterday_summary=yesterday_summary,
        )
        return self.parse(
            await self._call_llm(prompt),
            eligible=eligible,
            daily_goal_minutes=daily_goal_minutes,
        )

    @staticmethod
    def _exam_weaknesses(items, index: CurriculumConceptIndex, meta) -> list[Any]:
        kept = []
        for item in items:
            get = item.get if isinstance(item, Mapping) else lambda key, default=None: getattr(item, key, default)
            subject = str(get("subject", "") or "").strip().lower()
            topic = str(get("topic", "") or "").strip()
            if not subject or not topic:
                continue
            matches = index.match_modules(subject, topic)
            if any(getattr(meta.get(match.module_id), "planner_mode", "concept") != "external" for match in matches):
                kept.append(item)
        return kept

    @staticmethod
    def parse(
        payload: Any,
        *,
        eligible: Sequence[CurriculumProgress],
        daily_goal_minutes: int,
    ) -> StudyPlanningAdvice:
        if isinstance(payload, str):
            if not payload.strip():
                return StudyPlanningAdvice()
            try:
                data = extract_json_object(payload.strip())
            except Exception:
                return StudyPlanningAdvice()
        elif isinstance(payload, Mapping):
            data = dict(payload)
        else:
            return StudyPlanningAdvice()
        if not isinstance(data, Mapping):
            return StudyPlanningAdvice()

        eligible_ids = {item.module.id for item in eligible}
        priority: list[str] = []
        raw_ids = data.get("priority_module_ids") or []
        if isinstance(raw_ids, list):
            for value in raw_ids:
                module_id = str(value or "").strip()
                if module_id in eligible_ids and module_id not in priority:
                    priority.append(module_id)
                if len(priority) >= MAX_ADVICE_ITEMS:
                    break

        allowed_subjects = {item.module.subject_id for item in eligible}
        minutes: list[tuple[str, int]] = []
        remaining = max(0, int(daily_goal_minutes))
        raw_minutes = data.get("subject_minutes") or {}
        if isinstance(raw_minutes, Mapping):
            for subject, raw_value in raw_minutes.items():
                key = str(subject or "").strip().lower()
                if key not in allowed_subjects or remaining <= 0:
                    continue
                try:
                    value = min(max(0, int(raw_value or 0)), remaining)
                except (TypeError, ValueError):
                    continue
                if value:
                    minutes.append((key, value))
                    remaining -= value

        by_subject: dict[str, list[CurriculumProgress]] = defaultdict(list)
        for item in eligible:
            by_subject[item.module.subject_id].append(item)
        for rows in by_subject.values():
            rows.sort(key=StudyPlanningAdvisor._priority_key)
        for subject, budget in minutes:
            used = 0
            for item in by_subject.get(subject, []):
                if item.module.id not in priority:
                    priority.append(item.module.id)
                used += max(1, int(item.module.default_duration_minutes))
                if used >= budget or len(priority) >= MAX_ADVICE_ITEMS:
                    break
            if len(priority) >= MAX_ADVICE_ITEMS:
                break

        rationale = str(data.get("rationale") or "").strip()[:500]
        if not priority and not minutes:
            return StudyPlanningAdvice()
        return StudyPlanningAdvice(
            priority_module_ids=tuple(priority[:MAX_ADVICE_ITEMS]),
            subject_minutes=tuple(minutes),
            rationale=rationale,
            source="llm",
        )

    @staticmethod
    def _priority_key(item: CurriculumProgress) -> tuple[int, int, str]:
        state_rank = {"weak": 0, "learning": 1, "unknown": 2}.get(item.status, 3)
        return (state_rank, -int(item.module.importance), item.module.id)

    @staticmethod
    def _balanced_sample(
        eligible: Sequence[CurriculumProgress], limit: int = MAX_PROMPT_MODULES
    ) -> list[CurriculumProgress]:
        groups: dict[str, list[CurriculumProgress]] = defaultdict(list)
        for item in eligible:
            groups[item.module.subject_id].append(item)
        for rows in groups.values():
            rows.sort(key=StudyPlanningAdvisor._priority_key)
        output: list[CurriculumProgress] = []
        subjects = sorted(groups)
        while len(output) < limit and any(groups.values()):
            for subject in subjects:
                if groups[subject] and len(output) < limit:
                    output.append(groups[subject].pop(0))
        return output

    @staticmethod
    def _build_prompt(
        *,
        target_date: str,
        daily_goal_minutes: int,
        eligible: Sequence[CurriculumProgress],
        review_overview: Mapping[str, Any],
        due_weaknesses: Sequence[Any],
        yesterday_summary: Mapping[str, Any],
    ) -> list[dict[str, str]]:
        modules = [
            {
                "id": item.module.id,
                "subject": item.module.subject_id,
                "name": item.module.name,
                "importance": item.module.importance,
                "minutes": item.module.default_duration_minutes,
                "status": item.status,
                "mastery": round(float(item.mastery), 3),
                "ready": item.is_ready,
            }
            for item in StudyPlanningAdvisor._balanced_sample(eligible)
        ]
        weaknesses = []
        for item in due_weaknesses[:10]:
            get = item.get if isinstance(item, Mapping) else lambda k, d=None: getattr(item, k, d)
            weaknesses.append({
                "subject": get("subject", ""),
                "topic": get("topic", ""),
                "confidence": get("confidence", None),
            })
        context = {
            "date": target_date,
            "daily_goal_minutes": daily_goal_minutes,
            "eligible_curriculum_modules": modules,
            "due_vocab_count": int(review_overview.get("due_today_count") or 0),
            "due_weaknesses": weaknesses,
            "yesterday": {
                "overview": yesterday_summary.get("overview") or {},
                "subjects": yesterday_summary.get("subjects") or [],
            },
        }
        system = (
            "你是高考学习计划顾问。只能选择 user JSON 中给出的 module id；"
            "不能创造考试范围，也不能写 plan.json。输出严格 JSON："
            '{"priority_module_ids":["..."],"subject_minutes":{"physics":120},'
            '"rationale":"简短理由"}。subject_minutes 总和不得超过 daily_goal_minutes。'
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ]

    async def _call_llm(self, messages: list[dict[str, str]]) -> str:
        raw_out = ""
        try:
            async for chunk in get_global_scheduler().submit_llm_task(
                messages,
                max_tokens=500,
                temperature=0.2,
                model_hint=self._model_hint(),
            ):
                if isinstance(chunk, str):
                    raw_out += chunk
                elif isinstance(chunk, dict) and chunk.get("content"):
                    raw_out += str(chunk.get("content") or "")
        except Exception as exc:
            logger.warning("Study Planning Advisor 调用失败，回退确定性排序: %s", exc)
        return raw_out

    @staticmethod
    def _model_hint() -> str:
        try:
            from config.model_config import get_journal_model, load_model_config
            routing = load_model_config()
            study = routing.get("study_models") or {}
            if isinstance(study, Mapping) and str(study.get("planning") or "").strip():
                return str(study["planning"]).strip()
            return str(get_journal_model() or "").strip()
        except Exception:
            return ""


_advisor: Optional[StudyPlanningAdvisor] = None


def get_study_planning_advisor() -> StudyPlanningAdvisor:
    global _advisor
    if _advisor is None:
        _advisor = StudyPlanningAdvisor()
    return _advisor


__all__ = ["MAX_ADVICE_ITEMS", "StudyPlanningAdvice", "StudyPlanningAdvisor", "get_study_planning_advisor"]
