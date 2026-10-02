"""Curriculum -> deterministic Daily Plan candidates."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from core.services.planning import PlanCandidate
from core.services.study.concept_resolver import (
    ConceptResolver,
    CurriculumConceptIndex,
    PlannerModuleMeta,
)
from core.services.study.concept_rules import ConceptStatus
from core.services.study.concept_state import get_concept_state_manager
from core.services.study.curriculum import CurriculumProgress
from core.utils.time_utils import get_current_time


class CurriculumCandidateProvider:
    def build(
        self,
        progress: Sequence[CurriculumProgress],
        *,
        preferred_module_ids: Sequence[str] = (),
        subject_minutes: Mapping[str, int] | None = None,
        limit: int = 12,
    ) -> list[PlanCandidate]:
        pref = {str(mid): i for i, mid in enumerate(preferred_module_ids) if str(mid).strip()}
        budgets = {
            str(subject).strip().lower(): max(0, int(minutes or 0))
            for subject, minutes in (subject_minutes or {}).items()
            if str(subject).strip()
        }
        meta_map = CurriculumConceptIndex().load()
        resolver = ConceptResolver(get_concept_state_manager())
        runtime = {
            item.module.id: self._resolve_state(
                item,
                meta_map.get(
                    item.module.id,
                    PlannerModuleMeta(
                        item.module.id,
                        item.module.subject_id,
                        item.module.name,
                    ),
                ),
                resolver,
            )
            for item in progress
        }
        by_id = {item.module.id: item for item in progress}
        ranked: list[tuple[float, PlanCandidate]] = []

        for item in progress:
            m = item.module
            meta = meta_map.get(m.id, PlannerModuleMeta(m.id, m.subject_id, m.name))
            rt = runtime[m.id]
            status = str(rt["status"])
            mastery = float(rt["mastery"])
            ready, missing_names = self._readiness(item, runtime, by_id)

            if not m.required or not item.is_autonomous_planning_safe:
                continue
            if meta.planner_mode == "external":
                continue
            if meta.planner_mode == "concept" and status == ConceptStatus.MASTERED.value:
                continue
            if meta.planner_mode == "practice" and not self._practice_due(rt):
                continue
            continuing = status in {ConceptStatus.LEARNING.value, ConceptStatus.WEAK.value}
            if not ready and not continuing:
                continue

            importance = float(m.importance - 3) * 2.0
            mastery_gap = max(0.0, 1.0 - mastery) * 4.0
            readiness = 7.0 if ready else -3.0
            state = self._state_factor(status)
            advice = max(1.0, 6.0 - pref[m.id] * 0.75) if m.id in pref else 0.0
            budget = min(5.0, budgets.get(m.subject_id, 0) / 30.0)
            practice = -3.0 if meta.planner_mode == "practice" and status == ConceptStatus.MASTERED.value else 0.0
            score = 6.0 + importance + mastery_gap + readiness + state + advice + budget + practice

            desc = []
            if m.learning_objectives:
                desc.append("目标：" + "；".join(m.learning_objectives[:2]))
            if missing_names:
                desc.append("前置状态待补齐：" + "、".join(missing_names))
            if m.note_paths:
                desc.append(f"资料：{m.note_paths[0]}")

            candidate = PlanCandidate(
                key=f"curriculum:{m.id}",
                title=f"{m.subject_name} · {m.name}",
                duration_minutes=m.default_duration_minutes,
                base_score=6.0,
                category="study",
                source="template",
                priority="high" if m.importance >= 5 and ready else "normal",
                repeat_key=f"curriculum:{m.id}",
                score_factors={
                    "curriculum_importance": importance,
                    "mastery_gap": mastery_gap,
                    "prerequisite_readiness": readiness,
                    "concept_state": state,
                    "llm_advice": advice,
                    "subject_budget": budget,
                    "practice_cooldown": practice,
                },
                metadata={
                    "subject": m.subject_name,
                    "subject_id": m.subject_id,
                    "curriculum_module_id": m.id,
                    "curriculum_group": m.group,
                    "curriculum_importance": m.importance,
                    "mastery": mastery,
                    "concept_status": status,
                    "missing_prerequisites": list(missing_names),
                    "learning_objectives": list(m.learning_objectives),
                    "note_paths": list(m.note_paths),
                    "planner_preferred": m.id in pref,
                    "planner_mode": meta.planner_mode,
                    "concept_evidence": list(meta.concept_evidence),
                    "matched_concepts": list(rt["matched_names"]),
                    "description": "；".join(desc),
                    "source_type": "curriculum",
                },
            )
            ranked.append((score, candidate))

        ranked.sort(key=lambda row: (-row[0], row[1].key))
        return self._balanced_take(ranked, max(0, int(limit)))

    @staticmethod
    def _resolve_state(
        item: CurriculumProgress,
        meta: PlannerModuleMeta,
        resolver: ConceptResolver,
    ) -> dict[str, Any]:
        m = item.module
        direct = resolver.resolve(m.subject_id, m.name).primary
        if direct is not None:
            return {
                "status": direct.status.value,
                "mastery": direct.mastery,
                "last_taught_at": direct.last_taught_at,
                "next_review_at": direct.next_review_at,
                "matched_names": (direct.name,),
            }

        states = []
        for name in meta.concept_evidence:
            state = resolver.resolve(m.subject_id, name).primary
            if state is not None and all(old.concept_id != state.concept_id for old in states):
                states.append(state)
        if not states:
            return {
                "status": item.status,
                "mastery": item.mastery,
                "last_taught_at": item.last_taught_at,
                "next_review_at": item.next_review_at,
                "matched_names": (),
            }

        expected = max(1, len(meta.concept_evidence))
        statuses = {state.status for state in states}
        if ConceptStatus.WEAK in statuses:
            status = ConceptStatus.WEAK.value
        elif ConceptStatus.LEARNING in statuses:
            status = ConceptStatus.LEARNING.value
        elif len(states) == expected and all(
            state.status == ConceptStatus.MASTERED for state in states
        ):
            status = ConceptStatus.MASTERED.value
        elif any(state.status != ConceptStatus.UNKNOWN for state in states):
            status = ConceptStatus.LEARNING.value
        else:
            status = ConceptStatus.UNKNOWN.value
        reviews = sorted(str(state.next_review_at) for state in states if state.next_review_at)
        return {
            "status": status,
            "mastery": sum(float(state.mastery) for state in states) / expected,
            "last_taught_at": max((str(state.last_taught_at) for state in states), default=""),
            "next_review_at": reviews[0] if reviews else "",
            "matched_names": tuple(state.name for state in states),
        }

    @staticmethod
    def _readiness(item, runtime, by_id) -> tuple[bool, tuple[str, ...]]:
        prerequisites = tuple(item.module.prerequisites)
        if not prerequisites:
            return True, ()
        if not all(prereq in runtime for prereq in prerequisites):
            return item.is_ready, tuple(item.missing_prerequisite_names)
        missing = [
            prereq
            for prereq in prerequisites
            if runtime[prereq]["status"] != ConceptStatus.MASTERED.value
        ]
        names = tuple(
            by_id[prereq].module.name if prereq in by_id else prereq
            for prereq in missing
        )
        return not missing, names

    @staticmethod
    def _practice_due(runtime: Mapping[str, Any]) -> bool:
        if runtime["status"] != ConceptStatus.MASTERED.value:
            return True
        today = get_current_time().date()
        next_review = str(runtime.get("next_review_at") or "")
        if next_review:
            try:
                return datetime.fromisoformat(next_review[:10]).date() <= today
            except ValueError:
                pass
        last_taught = str(runtime.get("last_taught_at") or "")
        if not last_taught:
            return True
        try:
            return (today - datetime.fromisoformat(last_taught).date()).days >= 7
        except ValueError:
            return True

    @staticmethod
    def _balanced_take(rows: list[tuple[float, PlanCandidate]], limit: int) -> list[PlanCandidate]:
        if limit <= 0 or not rows:
            return []
        groups: dict[str, list[tuple[float, PlanCandidate]]] = defaultdict(list)
        for row in rows:
            groups[str(row[1].metadata.get("subject_id") or "general")].append(row)
        picked: list[tuple[float, PlanCandidate]] = []
        for _, group in sorted(groups.items(), key=lambda p: (-p[1][0][0], p[0])):
            if len(picked) >= limit:
                break
            picked.append(group.pop(0))
        rest = sorted(
            (row for group in groups.values() for row in group),
            key=lambda r: (-r[0], r[1].key),
        )
        picked.extend(rest[: max(0, limit - len(picked))])
        picked.sort(key=lambda row: (-row[0], row[1].key))
        return [candidate for _, candidate in picked]

    @staticmethod
    def _state_factor(status: str) -> float:
        if status == ConceptStatus.WEAK.value:
            return 5.0
        if status == ConceptStatus.LEARNING.value:
            return 3.0
        if status == ConceptStatus.UNKNOWN.value:
            return 0.0
        return 1.0


__all__ = ["CurriculumCandidateProvider"]
