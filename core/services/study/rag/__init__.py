"""RAG：可插拔的可靠资料检索。

职责边界（避免和 ResourceRegistry / StudyLibrary 长重）：

    ResourceRegistry  只回答「这是哪份资料」——科目、可信度、路径、是否启用。
                      它不是 Retriever。
    StudyRetriever    只回答「该参考哪些片段」——切分、索引、检索、出处。
    StudyLibrary      门面：把上面两者组合起来，对外只暴露
                      search() / add_resource() / remove_resource()。

外面（TeachingOrchestrator）不需要知道底下是 BM25、Chroma 还是 Qdrant。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from core.utils.logger import get_logger

from .models import Chunk, RetrievalQuery, RetrievedChunk
from .retriever import StudyRetriever, VectorBackend

logger = get_logger("StudyLibraryRAG")

__all__ = [
    "Chunk",
    "RetrievalQuery",
    "RetrievedChunk",
    "StudyLibrary",
    "StudyRetriever",
    "VectorBackend",
]


class StudyLibrary:
    """学习资料库门面：ResourceRegistry（资料是谁） + StudyRetriever（内容在哪）。"""

    def __init__(
        self,
        *,
        retriever: Optional[StudyRetriever] = None,
        resources: Optional[Any] = None,
    ) -> None:
        self._retriever = retriever or StudyRetriever()
        self._resources = resources

    @property
    def retriever(self) -> StudyRetriever:
        return self._retriever

    # ------------------------------------------------------------------
    # 资料登记 + 入库
    # ------------------------------------------------------------------
    def add_resource(
        self,
        *,
        resource_id: str,
        path: Optional[Path] = None,
        text: str = "",
        subject: str = "",
        trust_level: str = "note",
        concept_ids: Optional[Sequence[str]] = None,
        page: Optional[int] = None,
    ) -> List[Chunk]:
        """登记并切分入库一份本地资料。

        第一版只支持 Markdown / TXT 这类纯文本。PDF 需要先解析成文本，
        等真的有教材 PDF 再加解析依赖，不提前膨胀。
        """
        if self._resources is not None and hasattr(self._resources, "get"):
            existing = self._resources.get(resource_id)
            if existing is not None:
                subject = subject or getattr(existing, "subject", "") or ""
                trust_level = trust_level or getattr(existing, "trust_level", "") or trust_level

        return self._retriever.ingest_document(
            resource_id=resource_id,
            text=text,
            path=path,
            subject=subject,
            trust_level=trust_level,
            concept_ids=concept_ids,
            page=page,
        )

    def remove_resource(self, resource_id: str) -> int:
        return self._retriever.remove_document(resource_id)

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    def search(
        self,
        query: RetrievalQuery | str,
        top_k: int = 5,
    ) -> List[RetrievedChunk]:
        return self._retriever.search(query, top_k=top_k)

    def as_context_items(self, query: RetrievalQuery | str, top_k: int = 3) -> List[Dict[str, Any]]:
        """转成可直接注入 prompt 的结构。

        带上 citation，让模型能说出「第二章 简谐运动 P37」这种可定位出处，
        而不是一堆匿名文本。
        """
        items: List[Dict[str, Any]] = []
        for hit in self.search(query, top_k=top_k):
            items.append(
                {
                    "title": hit.citation(),
                    "location": hit.source_path,
                    "excerpt": _shorten(hit.text, 160),
                    "subject": hit.subject,
                    "trust_level": hit.trust_level,
                    "score": hit.score,
                    "source": "rag",
                }
            )
        return items

    def stats(self) -> Dict[str, Any]:
        return self._retriever.stats()


def _shorten(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"
