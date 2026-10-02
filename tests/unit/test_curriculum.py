from __future__ import annotations

from pathlib import Path

import pytest

from core.services.study.concept_rules import ConceptStatus
from core.services.study.concept_state import ConceptStateManager
from core.services.study.curriculum import CurriculumError, CurriculumService


_SAMPLE = """\
schema_version: 1
profile:
  id: gaokao
  name: 高考
subject:
  id: physics
  name: 物理
coverage:
  status: partial
  note: 测试样例
source_notes:
  - Physics/00_物理MOC.md
modules:
  - id: physics.mechanics.kinematics
    name: 质点运动学
    group: 力学主线
    required: true
    importance: 4
    default_duration_minutes: 60
    prerequisites: []
    learning_objectives:
      - 掌握速度与加速度
    note_paths:
      - Physics/02_一轮复习/01_质点运动学.md
    tags: [一轮, 力学]
  - id: physics.mechanics.newton
    name: 牛顿运动定律
    group: 力学主线
    required: true
    importance: 5
    default_duration_minutes: 75
    prerequisites:
      - physics.mechanics.kinematics
    learning_objectives:
      - 熟练进行受力分析
    note_paths:
      - Physics/02_一轮复习/02_牛顿运动定律.md
    tags: [一轮, 力学]
"""


def _write_blueprint(root: Path, text: str = _SAMPLE) -> Path:
    target = root / "Curriculum" / "gaokao" / "physics.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def test_load_partial_curriculum_and_preserve_stable_fields(tmp_path: Path) -> None:
    _write_blueprint(tmp_path)
    service = CurriculumService(root=tmp_path)

    blueprint = service.load_subject("physics")

    assert blueprint is not None
    assert blueprint.profile_id == "gaokao"
    assert blueprint.subject_id == "physics"
    assert blueprint.coverage_status == "partial"
    assert blueprint.is_complete is False
    assert [item.id for item in blueprint.modules] == [
        "physics.mechanics.kinematics",
        "physics.mechanics.newton",
    ]
    assert blueprint.modules[1].prerequisites == (
        "physics.mechanics.kinematics",
    )
    assert blueprint.modules[1].importance == 5


def test_planning_snapshot_is_read_only_and_reports_missing_prerequisite(
    tmp_path: Path,
) -> None:
    _write_blueprint(tmp_path)
    concepts = ConceptStateManager(state_file=tmp_path / ".state" / "concepts.json")
    service = CurriculumService(root=tmp_path)

    assert concepts.all_concepts() == []
    snapshot = service.planning_snapshot(concept_manager=concepts)

    assert concepts.all_concepts() == []
    assert snapshot[0].status == ConceptStatus.UNKNOWN.value
    assert snapshot[0].is_ready is True
    assert snapshot[1].missing_prerequisite_ids == (
        "physics.mechanics.kinematics",
    )
    assert snapshot[1].missing_prerequisite_names == ("质点运动学",)


def test_mastered_prerequisite_unlocks_next_module(tmp_path: Path) -> None:
    _write_blueprint(tmp_path)
    concepts = ConceptStateManager(state_file=tmp_path / ".state" / "concepts.json")
    prerequisite = concepts.get_or_create("physics", "质点运动学")
    prerequisite.status = ConceptStatus.MASTERED
    prerequisite.mastery = 0.9
    concepts.save()

    snapshot = CurriculumService(root=tmp_path).planning_snapshot(
        concept_manager=concepts
    )

    by_id = {item.module.id: item for item in snapshot}
    assert by_id["physics.mechanics.newton"].is_ready is True
    assert by_id["physics.mechanics.newton"].missing_prerequisite_ids == ()


def test_unknown_schema_version_is_rejected(tmp_path: Path) -> None:
    path = _write_blueprint(tmp_path, _SAMPLE.replace("schema_version: 1", "schema_version: 99"))
    service = CurriculumService(root=tmp_path)

    with pytest.raises(CurriculumError, match="schema_version"):
        service._load_file(path)


def test_diagnostics_report_missing_notes_and_dangling_prerequisites(
    tmp_path: Path,
) -> None:
    _write_blueprint(
        tmp_path,
        _SAMPLE.replace(
            "physics.mechanics.kinematics\n    learning_objectives",
            "physics.mechanics.missing\n    learning_objectives",
        ),
    )
    service = CurriculumService(root=tmp_path)

    diagnostics = service.diagnostics()

    assert diagnostics["blueprint_count"] == 1
    assert diagnostics["module_count"] == 2
    assert diagnostics["partial_subjects"] == ["physics"]
    assert diagnostics["dangling_prerequisites"] == [
        {
            "module_id": "physics.mechanics.newton",
            "prerequisite": "physics.mechanics.missing",
        }
    ]
    assert len(diagnostics["missing_note_paths"]) == 2
