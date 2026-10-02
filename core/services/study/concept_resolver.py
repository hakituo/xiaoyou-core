"""Curriculum Module 与 ConceptState 的只读证据解析。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

import yaml

from core.services.study import paths
from core.services.study.concept_state import ConceptState, ConceptStateManager
from core.services.study.curriculum import DEFAULT_PROFILE

PLANNER_MODES = {"concept", "practice", "external"}


@dataclass(frozen=True, slots=True)
class ConceptResolution:
    primary: Optional[ConceptState]
    evidence: tuple[ConceptState, ...]
    matched_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlannerModuleMeta:
    module_id: str
    subject_id: str
    module_name: str
    planner_mode: str = "concept"
    concept_evidence: tuple[str, ...] = ()


class ConceptResolver:
    def __init__(self, concepts: ConceptStateManager):
        self._concepts = concepts

    def resolve(
        self,
        subject: str,
        name: str,
        *,
        evidence_names: Sequence[str] = (),
    ) -> ConceptResolution:
        subject_key = ConceptState.normalize_subject(subject)
        matches: list[ConceptState] = []
        matched_names: list[str] = []
        for raw_name in (name, *evidence_names):
            candidate_name = ConceptState.normalize_name(raw_name)
            if not candidate_name:
                continue
            state = self._concepts.get_by_name(subject_key, candidate_name)
            if state is None:
                state = self._loose(subject_key, candidate_name)
            if state is None or any(old.concept_id == state.concept_id for old in matches):
                continue
            matches.append(state)
            matched_names.append(candidate_name)
        return ConceptResolution(
            primary=self._pick_primary(matches, module_name=name),
            evidence=tuple(matches),
            matched_names=tuple(matched_names),
        )

    def _loose(self, subject: str, name: str) -> Optional[ConceptState]:
        target = ConceptState.loose_name(name)
        if not target:
            return None
        exact: list[ConceptState] = []
        suffix: list[ConceptState] = []
        for state in self._concepts.list_by_subject(subject):
            existing = ConceptState.loose_name(state.name)
            if existing == target:
                exact.append(state)
                continue
            shorter, longer = sorted((existing, target), key=len)
            if len(shorter) >= 4 and longer.endswith(shorter):
                suffix.append(state)
        if exact:
            return self._pick_primary(exact, module_name=name)
        return suffix[0] if len(suffix) == 1 else None

    @staticmethod
    def _pick_primary(states: Iterable[ConceptState], *, module_name: str) -> Optional[ConceptState]:
        rows = list(states)
        if not rows:
            return None
        target = ConceptState.loose_name(module_name)
        rows.sort(
            key=lambda state: (
                ConceptState.loose_name(state.name) != target,
                -int(state.evidence_count),
                -float(state.mastery),
                state.concept_id,
            )
        )
        return rows[0]


class CurriculumConceptIndex:
    """读取 schema v1 的可选 planner metadata；缺字段时保持旧行为。"""

    def __init__(self, root: Optional[Path] = None):
        self._root = Path(root) if root else paths.get_study_root()

    def load(self, *, profile: str = DEFAULT_PROFILE) -> dict[str, PlannerModuleMeta]:
        base = self._root / "Curriculum" / str(profile or DEFAULT_PROFILE)
        result: dict[str, PlannerModuleMeta] = {}
        if not base.is_dir():
            return result
        for path in sorted(base.glob("*.yaml")):
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            if not isinstance(raw, Mapping):
                continue
            subject = raw.get("subject")
            subject_id = str(subject.get("id") or path.stem).strip().lower() if isinstance(subject, Mapping) else path.stem.lower()
            rows = raw.get("modules")
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, Mapping):
                    continue
                module_id = str(row.get("id") or "").strip()
                module_name = str(row.get("name") or "").strip()
                if not module_id or not module_name:
                    continue
                mode = str(row.get("planner_mode") or "concept").strip().lower()
                if mode not in PLANNER_MODES:
                    mode = "concept"
                evidence = row.get("concept_evidence")
                evidence_names = tuple(
                    text
                    for text in (str(v or "").strip() for v in (evidence if isinstance(evidence, list) else []))
                    if text
                )
                result[module_id] = PlannerModuleMeta(module_id, subject_id, module_name, mode, evidence_names)
        return result

    def match_modules(
        self,
        subject: str,
        concept_name: str,
        *,
        profile: str = DEFAULT_PROFILE,
    ) -> tuple[PlannerModuleMeta, ...]:
        subject_key = ConceptState.normalize_subject(subject)
        target = ConceptState.loose_name(concept_name)
        matched: list[PlannerModuleMeta] = []
        for meta in self.load(profile=profile).values():
            if meta.subject_id != subject_key:
                continue
            names = (meta.module_name, *meta.concept_evidence)
            if any(self._match(target, ConceptState.loose_name(name)) for name in names):
                matched.append(meta)
        return tuple(matched)

    @staticmethod
    def _match(left: str, right: str) -> bool:
        if not left or not right:
            return False
        if left == right:
            return True
        shorter, longer = sorted((left, right), key=len)
        return len(shorter) >= 4 and longer.endswith(shorter)


__all__ = [
    "PLANNER_MODES",
    "ConceptResolution",
    "PlannerModuleMeta",
    "ConceptResolver",
    "CurriculumConceptIndex",
]
