"""StudyRetriever：本地可信资料的检索入口。

设计要点：
- **词法优先**：BM25 先跑，公式/缩写这类内容靠它；
- **向量可插拔**：`vector_backend` 留空槽，接入 embedding 后自动参与融合，
  接口不变，Orchestrator 不需要知道底下是 BM25 还是向量库；
- **不存学习状态**：这里只有「材料」，用户的掌握情况在 ConceptState，
  绝不把 mastery / LearningEvent 混进来。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence

from core.utils.logger import get_logger

from .chunking import chunk_document
from .lexical import BM25, tokenize
from .models import Chunk, RetrievalQuery, RetrievedChunk

logger = get_logger("StudyRetriever")

#: 词法与向量分数的融合权重（先只跑词法，向量接入后按此权重混合）
LEXICAL_WEIGHT = 0.6
VECTOR_WEIGHT = 0.4


class VectorBackend(Protocol):
    """向量后端接口。先留空，接入时实现这三个方法即可。"""

    def add(self, chunk_id: str, text: str) -> None: ...

    def search(self, query: str, top_k: int) -> List[tuple[str, float]]: ...

    def remove(self, chunk_id: str) -> None: ...


class StudyRetriever:
    """本地资料的片段级检索。"""

    def __init__(
        self,
        index_path: Optional[Path] = None,
        *,
        vector_backend: Optional[VectorBackend] = None,
        enable_vector: bool = True,
    ) -> None:
        self._index_path = index_path
        self._vector = vector_backend
        self._enable_vector = enable_vector
        self._lock = threading.RLock()

        if enable_vector and vector_backend is None:
            # 惰性：拿不到就纯词法，绝不因为向量不可用而让检索整体失效
            try:
                from .embeddings import BgeOnnxBackend

                self._vector = BgeOnnxBackend()
            except Exception as e:  # noqa: BLE001
                logger.debug("向量后端不可用，使用纯词法检索: %s", e)
                self._vector = None

        self._chunks: Dict[str, Chunk] = {}
        self._doc_tokens: Dict[str, List[str]] = {}
        self._bm25 = BM25()
        self._bm25_positions: List[str] = []  # BM25 内部序号 -> chunk_id
        self._by_resource: Dict[str, List[str]] = {}

        if index_path is not None:
            self._load()

    # ------------------------------------------------------------------
    # 入库
    # ------------------------------------------------------------------
    def ingest_document(
        self,
        *,
        resource_id: str,
        text: str = "",
        path: Optional[Path] = None,
        suffix: str = ".md",
        subject: str = "",
        trust_level: str = "",
        concept_ids: Optional[Sequence[str]] = None,
        page: Optional[int] = None,
    ) -> List[Chunk]:
        """把一份资料切分并入库；重复入库同一 resource_id 会先清掉旧的。"""
        if path is not None and not text:
            text = self._read(path)
            suffix = path.suffix or suffix

        if not text.strip():
            return []

        self.remove_document(resource_id)

        chunks = chunk_document(
            text,
            resource_id=resource_id,
            suffix=suffix,
            subject=subject,
            source_path=str(path or ""),
            trust_level=trust_level,
            page=page,
        )
        if concept_ids:
            from .chunking import with_concepts

            chunks = [with_concepts(c, list(concept_ids)) for c in chunks]

        with self._lock:
            for chunk in chunks:
                self._chunks[chunk.chunk_id] = chunk
                tokens = tokenize(chunk.text)
                self._doc_tokens[chunk.chunk_id] = tokens
                self._bm25.add(tokens)
                self._bm25_positions.append(chunk.chunk_id)
                if self._vector is not None:
                    try:
                        self._vector.add(chunk.chunk_id, chunk.text)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("向量入库失败，降级为纯词法: %s", e)
                        self._vector = None
            self._by_resource[resource_id] = [c.chunk_id for c in chunks]

        self._save()
        return chunks

    def remove_document(self, resource_id: str) -> int:
        """移除某份资料的全部片段，返回移除数量。"""
        with self._lock:
            ids = self._by_resource.pop(resource_id, [])
            for chunk_id in ids:
                self._chunks.pop(chunk_id, None)
                self._doc_tokens.pop(chunk_id, None)
                if self._vector is not None:
                    try:
                        self._vector.remove(chunk_id)
                    except Exception:  # noqa: BLE001
                        pass
            if not ids:
                return 0
            # BM25 不支持删除，整体重建更省心
            self._rebuild_bm25()
            self._save()
            return len(ids)

    def _rebuild_bm25(self) -> None:
        self._bm25 = BM25()
        self._bm25_positions = []
        for chunk_id in self._chunks:
            tokens = self._doc_tokens.get(chunk_id) or tokenize(self._chunks[chunk_id].text)
            self._bm25.add(tokens)
            self._bm25_positions.append(chunk_id)

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    def search(self, query: RetrievalQuery | str, top_k: int = 5) -> List[RetrievedChunk]:
        if isinstance(query, str):
            query = RetrievalQuery(text=query)
        top_k = query.top_k or top_k

        query_text = query.expanded_text()
        query_tokens = tokenize(query_text)

        with self._lock:
            scores: Dict[str, float] = {}
            matched: Dict[str, str] = {}

            lexical = self._bm25.best(query_tokens, top_k=max(top_k * 4, 20))
            max_lexical = max((s for _, s in lexical), default=0.0) or 1.0
            for position, score in lexical:
                if position >= len(self._bm25_positions):
                    continue
                chunk_id = self._bm25_positions[position]
                scores[chunk_id] = LEXICAL_WEIGHT * (score / max_lexical)
                matched[chunk_id] = "lexical"

            vector_hits = self._vector_search(query_text, top_k)
            if vector_hits:
                max_vec = max((s for _, s in vector_hits), default=0.0) or 1.0
                for chunk_id, score in vector_hits:
                    if chunk_id not in self._chunks:
                        continue
                    scores[chunk_id] = scores.get(chunk_id, 0.0) + VECTOR_WEIGHT * (
                        score / max_vec
                    )
                    matched[chunk_id] = "hybrid" if chunk_id in matched else "vector"

            ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:top_k]
            results: List[RetrievedChunk] = []
            for chunk_id, score in ranked:
                chunk = self._chunks.get(chunk_id)
                if chunk is None:
                    continue
                results.append(self._to_retrieved(chunk, score, matched.get(chunk_id, "lexical")))
            return results

    def _vector_search(self, query_text: str, top_k: int) -> List[tuple[str, float]]:
        if self._vector is None:
            return []
        try:
            return self._vector.search(query_text, max(top_k * 4, 20))
        except Exception as e:  # noqa: BLE001
            logger.warning("向量检索失败，降级为纯词法: %s", e)
            self._vector = None
            return []

    @staticmethod
    def _to_retrieved(chunk: Chunk, score: float, matched_by: str) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=chunk.chunk_id,
            resource_id=chunk.resource_id,
            text=chunk.text,
            subject=chunk.subject,
            chapter=chunk.chapter,
            section=chunk.section,
            page=chunk.page,
            source_path=chunk.source_path,
            concept_ids=list(chunk.concept_ids),
            trust_level=chunk.trust_level,
            score=score,
            matched_by=matched_by,
        )

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            logger.warning("读取资料失败 %s: %s", path, e)
            return ""

    def _save(self) -> None:
        if self._index_path is None:
            return
        try:
            self._index_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "chunks": [c.to_dict() for c in self._chunks.values()],
            }
            self._index_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as e:
            logger.warning("保存检索索引失败: %s", e)

    def _load(self) -> None:
        if self._index_path is None or not self._index_path.exists():
            return
        try:
            payload = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.warning("检索索引损坏，按空索引启动: %s", e)
            return
        for item in payload.get("chunks") or []:
            try:
                chunk = Chunk(
                    chunk_id=item["chunk_id"],
                    resource_id=item["resource_id"],
                    text=item["text"],
                    subject=item.get("subject", ""),
                    chapter=item.get("chapter", ""),
                    section=item.get("section", ""),
                    order=item.get("order", 0),
                    page=item.get("page"),
                    source_path=item.get("source_path", ""),
                    concept_ids=list(item.get("concept_ids") or []),
                    trust_level=item.get("trust_level", ""),
                )
            except KeyError:
                continue
            with self._lock:
                self._chunks[chunk.chunk_id] = chunk
                self._doc_tokens[chunk.chunk_id] = tokenize(chunk.text)
                self._by_resource.setdefault(chunk.resource_id, []).append(chunk.chunk_id)
        self._rebuild_bm25()
        # 索引是持久化的，但向量只在内存里——加载后必须补算，
        # 否则重启后向量检索会静默失效（只剩词法，且没人会发现）。
        self._reindex_vectors()

    def _reindex_vectors(self) -> None:
        if self._vector is None:
            return
        try:
            self._vector.reindex({cid: c.text for cid, c in self._chunks.items()})
        except Exception as e:  # noqa: BLE001
            logger.warning("向量索引重建失败，降级为纯词法: %s", e)
            self._vector = None

    # ------------------------------------------------------------------
    def stats(self) -> Dict[str, Any]:
        return {
            "chunks": len(self._chunks),
            "resources": len(self._by_resource),
            "vector_enabled": self._vector is not None,
        }
