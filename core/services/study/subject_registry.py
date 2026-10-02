"""Study Subject Registry 读取与高精度 canonicalization。

Registry 只描述已知学习领域，不是白名单。运行时识别不到的领域仍允许被上层
作为 exploratory/general 学习记录保存；本模块绝不把未知领域映射到高考 Curriculum。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

from core.services.study import paths
from core.utils.logger import get_logger

logger = get_logger("StudySubjectRegistry")


@dataclass(frozen=True, slots=True)
class SubjectDefinition:
    id: str
    name: str
    aliases: tuple[str, ...] = ()
    directories: tuple[str, ...] = ()
    category: str = ""
    parent: str = ""
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SubjectMatch:
    subject_id: str
    alias: str
    confidence: float


class SubjectRegistry:
    """从 ``Study/Subjects/registry.yaml`` 读取 canonical subjects。"""

    def __init__(self, root: Optional[Path] = None):
        self._root = Path(root) if root else paths.get_study_root()
        self._loaded_mtime_ns: Optional[int] = None
        self._subjects: dict[str, SubjectDefinition] = {}

    @property
    def registry_path(self) -> Path:
        return self._root / "Subjects" / "registry.yaml"

    def all(self) -> tuple[SubjectDefinition, ...]:
        self._ensure_loaded()
        return tuple(self._subjects.values())

    def get(self, subject_id: str) -> Optional[SubjectDefinition]:
        self._ensure_loaded()
        return self._subjects.get(str(subject_id or "").strip().lower())

    def canonicalize(self, value: str) -> Optional[str]:
        """把 subject id / 显示名 / 完整 alias 归一化为 canonical id。"""
        text = self._normalize(value)
        if not text:
            return None
        self._ensure_loaded()
        if text in self._subjects:
            return text
        for subject in self._subjects.values():
            if self._normalize(subject.name) == text:
                return subject.id
            if any(self._normalize(alias) == text for alias in subject.aliases):
                return subject.id
        return None

    def match_text(self, text: str) -> Optional[SubjectMatch]:
        """在自然语言中找最可靠的领域 alias。

        规则：最长 alias 优先；英文/缩写必须满足 token boundary，避免 ``AI`` 命中
        ``said``、``agent`` 命中更长标识符。中文 alias 允许子串匹配，但两个字的
        alias 会降低置信度，交给上层结合学习意图决定是否采纳。
        """
        raw = unicodedata.normalize("NFKC", str(text or ""))
        if not raw.strip():
            return None
        folded = raw.casefold()
        self._ensure_loaded()

        candidates: list[tuple[int, float, str, str]] = []
        for subject in self._subjects.values():
            for alias in (subject.name, *subject.aliases):
                normalized = unicodedata.normalize("NFKC", alias).strip()
                if not normalized:
                    continue
                alias_folded = normalized.casefold()
                if self._is_ascii_word(alias_folded):
                    pattern = rf"(?<![a-z0-9_]){re.escape(alias_folded)}(?![a-z0-9_])"
                    matched = re.search(pattern, folded) is not None
                    confidence = 0.96 if len(alias_folded) >= 3 else 0.9
                else:
                    matched = alias_folded in folded
                    confidence = 0.94 if len(alias_folded) >= 3 else 0.78
                if matched:
                    candidates.append((len(alias_folded), confidence, subject.id, normalized))

        if not candidates:
            return None
        candidates.sort(key=lambda row: (-row[0], -row[1], row[2], row[3].casefold()))
        _, confidence, subject_id, alias = candidates[0]
        return SubjectMatch(subject_id=subject_id, alias=alias, confidence=confidence)

    def _ensure_loaded(self) -> None:
        path = self.registry_path
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            if self._loaded_mtime_ns is None:
                self._subjects = {}
                self._loaded_mtime_ns = -1
            return
        if self._loaded_mtime_ns == mtime_ns:
            return

        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            rows = raw.get("subjects", []) if isinstance(raw, Mapping) else []
            loaded: dict[str, SubjectDefinition] = {}
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, Mapping):
                    continue
                subject_id = str(row.get("id") or "").strip().lower()
                name = str(row.get("name") or "").strip()
                if not subject_id or not name:
                    continue
                loaded[subject_id] = SubjectDefinition(
                    id=subject_id,
                    name=name,
                    aliases=self._str_tuple(row.get("aliases")),
                    directories=self._str_tuple(row.get("directories")),
                    category=str(row.get("category") or "").strip(),
                    parent=str(row.get("parent") or "").strip().lower(),
                    tags=self._str_tuple(row.get("tags")),
                )
            self._subjects = loaded
            self._loaded_mtime_ns = mtime_ns
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取 Subject Registry 失败，保留空/旧缓存: %s", exc)
            if self._loaded_mtime_ns is None:
                self._subjects = {}
                self._loaded_mtime_ns = mtime_ns

    @staticmethod
    def _normalize(value: str) -> str:
        return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()

    @staticmethod
    def _is_ascii_word(value: str) -> bool:
        return bool(value) and all(ord(char) < 128 for char in value) and any(
            char.isalnum() for char in value
        )

    @staticmethod
    def _str_tuple(value: Any) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(text for text in (str(item or "").strip() for item in value) if text)


_registry: Optional[SubjectRegistry] = None


def get_subject_registry() -> SubjectRegistry:
    global _registry
    if _registry is None:
        _registry = SubjectRegistry()
    return _registry


__all__ = [
    "SubjectDefinition",
    "SubjectMatch",
    "SubjectRegistry",
    "get_subject_registry",
]
