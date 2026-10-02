"""考试课程地图（Curriculum / Exam Blueprint）读取与学习进度投影。

Study 仓库负责维护“考试应该学什么”的静态真源：
``{study_root}/Curriculum/<profile>/<subject>.yaml``。

本模块只读取静态课程地图，并把它与 :mod:`concept_state` 的动态掌握状态做
**只读投影**。它不会因为蓝图里出现某个知识点就创建/修改 ConceptState，避免
“读一份课程表”本身改变用户学习状态。

数据边界：
- Curriculum：考试范围、重要度、前置关系、对应 Study 笔记。
- ConceptState：用户当前掌握状态唯一权威源。
- StudyLibrary：按已知知识点寻找讲解材料。
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from core.services.study import paths
from core.services.study.concept_rules import ConceptStatus
from core.services.study.concept_state import ConceptStateManager, get_concept_state_manager
from core.utils.logger import get_logger

logger = get_logger("StudyCurriculum")

SCHEMA_VERSION = 1
DEFAULT_PROFILE = "gaokao"


class CurriculumError(ValueError):
    """课程蓝图格式错误。"""


@dataclass(frozen=True, slots=True)
class CurriculumModule:
    """一个稳定的考试知识节点。"""

    id: str
    name: str
    subject_id: str
    subject_name: str
    group: str = ""
    required: bool = True
    importance: int = 3
    default_duration_minutes: int = 60
    prerequisites: tuple[str, ...] = ()
    learning_objectives: tuple[str, ...] = ()
    note_paths: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CurriculumBlueprint:
    """单科目课程蓝图。"""

    schema_version: int
    profile_id: str
    profile_name: str
    subject_id: str
    subject_name: str
    coverage_status: str
    coverage_note: str
    source_notes: tuple[str, ...]
    modules: tuple[CurriculumModule, ...]
    source_path: str

    @property
    def is_complete(self) -> bool:
        return self.coverage_status == "complete"


@dataclass(frozen=True, slots=True)
class CurriculumProgress:
    """课程节点 + 当前 ConceptState 的只读规划快照。"""

    module: CurriculumModule
    coverage_status: str
    status: str
    mastery: float
    evidence_count: int
    last_taught_at: str
    next_review_at: str
    missing_prerequisite_ids: tuple[str, ...]
    missing_prerequisite_names: tuple[str, ...]

    @property
    def is_mastered(self) -> bool:
        return self.status == ConceptStatus.MASTERED.value

    @property
    def is_ready(self) -> bool:
        return not self.missing_prerequisite_ids

    @property
    def is_autonomous_planning_safe(self) -> bool:
        """只有完整蓝图才能被确定性计划器当作完整新课来源。"""
        return self.coverage_status == "complete"


class CurriculumService:
    """从 Study 根目录读取机器可读课程地图。"""

    def __init__(self, root: Optional[Path] = None):
        self._root = Path(root) if root else paths.get_study_root()

    @property
    def root(self) -> Path:
        return self._root

    def profile_dir(self, profile: str = DEFAULT_PROFILE) -> Path:
        safe_profile = str(profile or DEFAULT_PROFILE).strip() or DEFAULT_PROFILE
        return self._root / "Curriculum" / safe_profile

    def load_subject(
        self,
        subject: str,
        *,
        profile: str = DEFAULT_PROFILE,
    ) -> Optional[CurriculumBlueprint]:
        """读取一个科目的 YAML；不存在时返回 ``None``。

        文件名只是定位提示，真正的科目 ID 仍以 YAML 内 ``subject.id`` 为准。
        """
        subject_key = str(subject or "").strip().lower()
        if not subject_key:
            return None
        path = self.profile_dir(profile) / f"{subject_key}.yaml"
        if not path.is_file():
            return None
        return self._load_file(path)

    def load_all(
        self,
        *,
        profile: str = DEFAULT_PROFILE,
    ) -> tuple[CurriculumBlueprint, ...]:
        """读取一个 profile 下所有合法蓝图；单个坏文件不会拖垮整个计划器。"""
        base = self.profile_dir(profile)
        if not base.is_dir():
            return ()
        loaded: list[CurriculumBlueprint] = []
        for path in sorted(base.glob("*.yaml")):
            try:
                loaded.append(self._load_file(path))
            except CurriculumError as exc:
                logger.warning("跳过无效课程蓝图 %s: %s", path, exc)
            except OSError as exc:
                logger.warning("读取课程蓝图失败 %s: %s", path, exc)
        return tuple(loaded)

    def planning_snapshot(
        self,
        *,
        profile: str = DEFAULT_PROFILE,
        concept_manager: Optional[ConceptStateManager] = None,
    ) -> tuple[CurriculumProgress, ...]:
        """返回所有课程节点与当前掌握状态的只读快照。

        前置关系在 YAML 中使用稳定 module ID；ConceptState 仍按“科目 + 名称”
        维护自己的历史 ID。这里负责桥接二者，但绝不写回 ConceptState。
        """
        blueprints = self.load_all(profile=profile)
        if not blueprints:
            return ()
        blueprint_by_module_id = {
            module.id: blueprint
            for blueprint in blueprints
            for module in blueprint.modules
        }
        modules = [module for blueprint in blueprints for module in blueprint.modules]
        by_id = {module.id: module for module in modules}
        concepts = concept_manager or get_concept_state_manager()

        state_by_module: dict[str, Any] = {}
        for module in modules:
            state_by_module[module.id] = concepts.get_by_name(
                module.subject_id,
                module.name,
            )

        progress: list[CurriculumProgress] = []
        for module in modules:
            state = state_by_module.get(module.id)
            missing_ids: list[str] = []
            missing_names: list[str] = []
            for prereq_id in module.prerequisites:
                prereq_module = by_id.get(prereq_id)
                prereq_state = state_by_module.get(prereq_id)
                if (
                    prereq_module is not None
                    and prereq_state is not None
                    and prereq_state.status == ConceptStatus.MASTERED
                ):
                    continue
                missing_ids.append(prereq_id)
                missing_names.append(
                    prereq_module.name if prereq_module is not None else prereq_id
                )

            blueprint = blueprint_by_module_id[module.id]
            progress.append(
                CurriculumProgress(
                    module=module,
                    coverage_status=blueprint.coverage_status,
                    status=(
                        state.status.value
                        if state is not None
                        else ConceptStatus.UNKNOWN.value
                    ),
                    mastery=float(state.mastery) if state is not None else 0.0,
                    evidence_count=int(state.evidence_count) if state is not None else 0,
                    last_taught_at=str(state.last_taught_at) if state is not None else "",
                    next_review_at=str(state.next_review_at) if state is not None else "",
                    missing_prerequisite_ids=tuple(missing_ids),
                    missing_prerequisite_names=tuple(missing_names),
                )
            )
        return tuple(progress)

    def diagnostics(
        self,
        *,
        profile: str = DEFAULT_PROFILE,
    ) -> dict[str, Any]:
        """返回蓝图结构诊断，供测试/调试页使用。"""
        blueprints = self.load_all(profile=profile)
        modules = [module for blueprint in blueprints for module in blueprint.modules]
        known_ids = {module.id for module in modules}
        duplicate_ids: list[str] = []
        seen: set[str] = set()
        dangling: list[dict[str, str]] = []
        missing_notes: list[dict[str, str]] = []

        for module in modules:
            if module.id in seen and module.id not in duplicate_ids:
                duplicate_ids.append(module.id)
            seen.add(module.id)
            for prereq in module.prerequisites:
                if prereq not in known_ids:
                    dangling.append({"module_id": module.id, "prerequisite": prereq})
            for note_path in module.note_paths:
                if not (self._root / note_path).is_file():
                    missing_notes.append({"module_id": module.id, "path": note_path})

        return {
            "profile": profile,
            "blueprint_count": len(blueprints),
            "module_count": len(modules),
            "partial_subjects": [
                blueprint.subject_id
                for blueprint in blueprints
                if not blueprint.is_complete
            ],
            "duplicate_ids": duplicate_ids,
            "dangling_prerequisites": dangling,
            "missing_note_paths": missing_notes,
        }

    def _load_file(self, path: Path) -> CurriculumBlueprint:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise CurriculumError(f"YAML 解析失败: {exc}") from exc
        if not isinstance(raw, Mapping):
            raise CurriculumError("顶层必须是 mapping")

        version = self._int(raw.get("schema_version"), default=0)
        if version != SCHEMA_VERSION:
            raise CurriculumError(
                f"不支持 schema_version={version}，当前仅支持 {SCHEMA_VERSION}"
            )

        profile = self._mapping(raw.get("profile"))
        subject = self._mapping(raw.get("subject"))
        coverage = self._mapping(raw.get("coverage"))
        profile_id = self._required_text(profile.get("id"), "profile.id")
        profile_name = self._required_text(profile.get("name"), "profile.name")
        subject_id = self._required_text(subject.get("id"), "subject.id").lower()
        subject_name = self._required_text(subject.get("name"), "subject.name")
        coverage_status = str(coverage.get("status") or "partial").strip().lower()
        if coverage_status not in {"partial", "complete"}:
            raise CurriculumError("coverage.status 只能是 partial/complete")

        raw_modules = raw.get("modules")
        if not isinstance(raw_modules, list):
            raise CurriculumError("modules 必须是数组")

        modules: list[CurriculumModule] = []
        module_ids: set[str] = set()
        for index, value in enumerate(raw_modules):
            if not isinstance(value, Mapping):
                raise CurriculumError(f"modules[{index}] 必须是 mapping")
            module_id = self._required_text(value.get("id"), f"modules[{index}].id")
            if module_id in module_ids:
                raise CurriculumError(f"重复 module id: {module_id}")
            module_ids.add(module_id)
            module_name = self._required_text(
                value.get("name"), f"modules[{index}].name"
            )
            modules.append(
                CurriculumModule(
                    id=module_id,
                    name=module_name,
                    subject_id=subject_id,
                    subject_name=subject_name,
                    group=str(value.get("group") or "").strip(),
                    required=bool(value.get("required", True)),
                    importance=max(1, min(5, self._int(value.get("importance"), 3))),
                    default_duration_minutes=max(
                        15,
                        min(
                            180,
                            self._int(value.get("default_duration_minutes"), 60),
                        ),
                    ),
                    prerequisites=self._str_tuple(value.get("prerequisites")),
                    learning_objectives=self._str_tuple(
                        value.get("learning_objectives")
                    ),
                    note_paths=self._str_tuple(value.get("note_paths")),
                    tags=self._str_tuple(value.get("tags")),
                )
            )

        return CurriculumBlueprint(
            schema_version=version,
            profile_id=profile_id,
            profile_name=profile_name,
            subject_id=subject_id,
            subject_name=subject_name,
            coverage_status=coverage_status,
            coverage_note=str(coverage.get("note") or "").strip(),
            source_notes=self._str_tuple(raw.get("source_notes")),
            modules=tuple(modules),
            source_path=self._relative(path),
        )

    @staticmethod
    def _mapping(value: Any) -> Mapping[str, Any]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _required_text(value: Any, field_name: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise CurriculumError(f"缺少必填字段 {field_name}")
        return text

    @staticmethod
    def _str_tuple(value: Any) -> tuple[str, ...]:
        if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
            return ()
        return tuple(
            text
            for text in (str(item or "").strip() for item in value)
            if text
        )

    @staticmethod
    def _int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self._root).as_posix()
        except ValueError:
            return path.as_posix()


_curriculum_service: Optional[CurriculumService] = None


def get_curriculum_service() -> CurriculumService:
    """获取默认 Study 根目录对应的课程地图服务。"""
    global _curriculum_service
    if _curriculum_service is None:
        _curriculum_service = CurriculumService()
    return _curriculum_service


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_PROFILE",
    "CurriculumError",
    "CurriculumModule",
    "CurriculumBlueprint",
    "CurriculumProgress",
    "CurriculumService",
    "get_curriculum_service",
]
