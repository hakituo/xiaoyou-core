"""可信资源层（Resource / Source）。

定位
----
教学不应只能依赖模型参数记忆。知识点或教学任务可以绑定教材、用户笔记、官方文档等
高可信参考资料；第一版只做**接口与结构**（登记、绑定 concept、按 concept/关键词
检索），不做完整 RAG——检索结果只返回资源位置与摘要，由上层决定如何取用。

持久化：``{study_root}/.state/resources.json``
"""
from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core.services.study.paths import backup_corrupt_file, get_state_file
from core.utils.atomic_io import safe_json_dump
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

logger = get_logger("StudyResources")

SCHEMA_VERSION = 1

# 资源类型
RESOURCE_KINDS = ("textbook", "user_note", "official_doc", "reference", "other")


class ResourceRef(BaseModel):
    """一条可信参考资料。"""

    resource_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str
    kind: str = "reference"
    location: str = ""            # 本地路径或 URL
    subject: str = ""
    concepts: List[str] = Field(default_factory=list)  # 绑定的 concept_id
    trusted: bool = True
    summary: str = ""
    added_at: str = ""

    def model_post_init(self, __context: Any) -> None:  # noqa: D105
        if not self.added_at:
            self.added_at = get_current_time().isoformat(timespec="seconds")
        if self.kind not in RESOURCE_KINDS:
            self.kind = "other"
        self.subject = str(self.subject or "").lower().strip()


class ResourceRegistry:
    """资源登记与检索（线程安全的 JSON 持久化单例）。"""

    _instance: Optional["ResourceRegistry"] = None
    _instance_lock = threading.Lock()

    def __init__(self, state_file: Optional[Path] = None):
        self._lock = threading.RLock()
        self._items: Optional[Dict[str, ResourceRef]] = None
        self._file = Path(state_file) if state_file else get_state_file("resources.json")

    @classmethod
    def get_instance(cls) -> "ResourceRegistry":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ---- 加载 / 保存 ----

    def _load(self) -> Dict[str, ResourceRef]:
        with self._lock:
            if self._items is not None:
                return self._items
            if not self._file.exists():
                self._items = {}
                return self._items
            try:
                import json

                raw = json.loads(self._file.read_text(encoding="utf-8"))
                items = raw.get("resources", []) if isinstance(raw, dict) else []
                self._items = {
                    r.resource_id: r
                    for r in (ResourceRef(**item) for item in items)
                }
            except Exception as e:  # noqa: BLE001
                backup = backup_corrupt_file(self._file)
                logger.error("加载资源登记失败，已备份到 %s：%s", backup, e)
                self._items = {}
            return self._items

    def _save(self) -> None:
        with self._lock:
            if self._items is None:
                return
            try:
                payload = {
                    "version": SCHEMA_VERSION,
                    "resources": [r.model_dump(mode="json") for r in self._items.values()],
                }
                safe_json_dump(payload, self._file, encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                logger.error("保存资源登记失败：%s", e)

    # ---- 公共 API ----

    def add(
        self,
        title: str,
        *,
        kind: str = "reference",
        location: str = "",
        subject: str = "",
        summary: str = "",
        concept_ids: Optional[List[str]] = None,
    ) -> ResourceRef:
        """登记一条资源。"""
        with self._lock:
            items = self._load()
            ref = ResourceRef(
                title=str(title).strip(),
                kind=kind,
                location=str(location).strip(),
                subject=subject,
                summary=str(summary).strip(),
                concepts=list(dict.fromkeys(concept_ids or [])),
            )
            items[ref.resource_id] = ref
            self._save()
            return ref

    def link_concept(self, resource_id: str, concept_id: str) -> bool:
        """把资源绑定到某个知识点。"""
        with self._lock:
            ref = self._load().get(str(resource_id))
            if ref is None:
                return False
            if concept_id and concept_id not in ref.concepts:
                ref.concepts.append(concept_id)
                self._save()
            return True

    def list_for_concept(self, concept_id: str) -> List[ResourceRef]:
        """返回绑定到指定知识点的资源。"""
        return [r for r in self._load().values() if concept_id in r.concepts]

    def list_for_subject(self, subject: str) -> List[ResourceRef]:
        key = str(subject or "").lower().strip()
        return [r for r in self._load().values() if r.subject == key]

    def search(self, query: str, *, limit: int = 5) -> List[ResourceRef]:
        """按标题/摘要/位置做轻量关键词检索（第一版不接向量库）。"""
        q = str(query or "").strip().lower()
        if not q:
            return []
        hits: List[ResourceRef] = []
        for ref in self._load().values():
            haystack = f"{ref.title} {ref.summary} {ref.location}".lower()
            if q in haystack:
                hits.append(ref)
            if len(hits) >= limit:
                break
        return hits

    def to_dict(self) -> Dict[str, Any]:
        items = list(self._load().values())
        return {"total": len(items), "items": [r.model_dump(mode="json") for r in items]}

    def reset_cache(self) -> None:
        with self._lock:
            self._items = None


def get_resource_registry() -> ResourceRegistry:
    return ResourceRegistry.get_instance()
