"""RAG 的数据模型。

**边界：RAG 不负责记住用户学会了什么。**
那是 ConceptState / LearningEvent / WeaknessTracker 的职责，绝不能塞进向量库——
否则刚建好的结构化学习状态又会被模糊检索架空。

RAG 只回答一个问题：

    「这次教学该参考哪些可靠材料？」

因此 RetrievedChunk 必须保留可定位的出处（chapter / section / page / source_path），
让系统能说出「高中物理选修3-4 第二章 简谐运动 P37」，
而不是只剩一坨 embedding 找出来的匿名文本。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Chunk:
    """入库前的一个片段。"""

    chunk_id: str
    resource_id: str

    text: str

    subject: str = ""
    chapter: str = ""  # 章（H1）
    section: str = ""  # 小节（H2 / H3）
    order: int = 0  # 在原文里的顺序，用于取相邻片段

    page: Optional[int] = None
    source_path: str = ""

    concept_ids: List[str] = field(default_factory=list)
    trust_level: str = ""  # textbook / handout / note / ...

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "resource_id": self.resource_id,
            "text": self.text,
            "subject": self.subject,
            "chapter": self.chapter,
            "section": self.section,
            "order": self.order,
            "page": self.page,
            "source_path": self.source_path,
            "concept_ids": list(self.concept_ids),
            "trust_level": self.trust_level,
        }


@dataclass(frozen=True)
class RetrievedChunk:
    """检索结果。带 score 与命中方式，便于排查「为什么搜到这条」。"""

    chunk_id: str
    resource_id: str

    text: str

    subject: str = ""
    chapter: str = ""
    section: str = ""

    page: Optional[int] = None
    source_path: str = ""

    concept_ids: List[str] = field(default_factory=list)
    trust_level: str = ""

    score: float = 0.0
    matched_by: str = ""  # lexical / vector / hybrid

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "resource_id": self.resource_id,
            "text": self.text,
            "subject": self.subject,
            "chapter": self.chapter,
            "section": self.section,
            "page": self.page,
            "source_path": self.source_path,
            "concept_ids": list(self.concept_ids),
            "trust_level": self.trust_level,
            "score": round(self.score, 4),
            "matched_by": self.matched_by,
        }

    def citation(self) -> str:
        """人类可读的出处，例如「第二章 简谐运动 P37」。"""
        parts = [p for p in (self.chapter, self.section) if p]
        if self.page is not None:
            parts.append(f"P{self.page}")
        location = " ".join(parts)
        if self.source_path and not location:
            return self.source_path
        return f"{location}（{self.source_path}）" if location and self.source_path else (location or self.source_path)


@dataclass
class RetrievalQuery:
    """检索意图。

    **不能拿用户原话直接去检索**——「为什么那个负号在那里」embedding 出来基本搜不到东西。
    Orchestrator 已经知道 subject / concept / 前置知识，要把这些拼进 query。
    """

    text: str = ""
    subject: str = ""
    concepts: List[str] = field(default_factory=list)  # 当前知识点
    prerequisites: List[str] = field(default_factory=list)  # ZPD 给的前置知识
    keywords: List[str] = field(default_factory=list)
    teaching_goal: str = "explain"  # explain / quiz / review
    top_k: int = 5

    def expanded_text(self) -> str:
        """把结构化意图摊平成检索串，比用户原话强得多。"""
        pieces = [
            self.subject,
            *self.concepts,
            *self.prerequisites,
            *self.keywords,
            self.text,
        ]
        seen: set[str] = set()
        ordered: List[str] = []
        for piece in pieces:
            piece = str(piece or "").strip()
            if piece and piece not in seen:
                seen.add(piece)
                ordered.append(piece)
        return " ".join(ordered)
