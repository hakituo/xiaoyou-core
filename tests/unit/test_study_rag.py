"""RAG 骨架的单测。

向量后端用**假的**实现，避免单测去加载 50s 的 embedding 模型。
真实模型的效果评估走 tests/scripts/study/compare_rag_recall.py（手动跑）。
"""

from __future__ import annotations

from core.services.study.rag import RetrievalQuery, RetrievedChunk, StudyLibrary
from core.services.study.rag.chunking import chunk_document
from core.services.study.rag.lexical import BM25, tokenize
from core.services.study.rag.retriever import StudyRetriever

NOTE = """---
aliases: [胡克定律]
tags: [物理]
---

# 弹簧振子

## 胡克定律

弹簧弹力大小与形变量成正比：

$$F = -kx$$

## 负号的含义

负号表示回复力方向始终与位移方向相反，指向平衡位置。
这是简谐运动能够往复的原因。

## 易错点

1. 忘记规定正方向
2. 把 k 当成与长度无关的量
"""


class FakeVector:
    """假的向量后端：只认「位移」和「平衡位置」这两个词。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def add(self, chunk_id: str, text: str) -> None:
        self.store[chunk_id] = text

    def remove(self, chunk_id: str) -> None:
        self.store.pop(chunk_id, None)

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        hits = [
            (cid, 1.0)
            for cid, text in self.store.items()
            if "位移" in text or "平衡位置" in text
        ]
        return hits[:top_k]


class BrokenVector(FakeVector):
    """模拟向量后端炸掉：必须能安全降级，不能让检索整体失败。"""

    def add(self, chunk_id: str, text: str) -> None:
        raise RuntimeError("boom")

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        raise RuntimeError("boom")


def test_chunk_keeps_formula_with_its_explanation():
    """公式和解释它的下一段不能被机械切分劈开。"""
    chunks = chunk_document(NOTE, resource_id="r1", suffix=".md")

    formula = next(c for c in chunks if "F = -kx" in c.text)
    meaning = next(c for c in chunks if "负号表示回复力方向" in c.text)

    assert formula.section == "胡克定律"
    assert meaning.section == "负号的含义"
    # 相邻：mid 之后紧跟着解释，顺序不能被打乱
    assert meaning.order == formula.order + 1


def test_chunk_skips_frontmatter():
    chunks = chunk_document(NOTE, resource_id="r1", suffix=".md")

    assert all("aliases" not in c.text for c in chunks)
    assert all("tags: [物理]" not in c.text for c in chunks)


def test_chunk_records_structure_and_source():
    chunks = chunk_document(
        NOTE, resource_id="r1", suffix=".md", subject="physics", source_path="a/b.md"
    )

    assert chunks[0].chapter == "弹簧振子"
    assert chunks[0].subject == "physics"
    assert chunks[0].source_path == "a/b.md"


def test_chunk_ids_are_stable_and_unique():
    a = chunk_document(NOTE, resource_id="r1", suffix=".md")
    b = chunk_document(NOTE, resource_id="r1", suffix=".md")

    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert len({c.chunk_id for c in a}) == len(a)


def test_tokenize_keeps_formulas_intact():
    tokens = tokenize("弹簧弹力 F = -kx 与 NADH 有关")

    assert "f" in tokens or "f=-kx" in tokens
    assert "nadh" in tokens


def test_bm25_ranks_keyword_match_first():
    bm25 = BM25()
    bm25.add(tokenize("动量守恒的条件是系统不受外力"))
    bm25.add(tokenize("静电场强度的定义与试探电荷有关"))

    best = bm25.best(tokenize("动量守恒 条件"), top_k=2)

    assert best[0][0] == 0


def test_query_expansion_puts_concepts_before_raw_text():
    query = RetrievalQuery(
        text="为什么那个负号在那里",
        subject="physics",
        concepts=["胡克定律"],
        prerequisites=["回复力"],
        keywords=["F=-kx"],
    )

    expanded = query.expanded_text()

    assert expanded.startswith("physics 胡克定律 回复力 F=-kx")
    assert expanded.endswith("为什么那个负号在那里")


def test_query_expansion_deduplicates():
    query = RetrievalQuery(subject="physics", concepts=["动量"], keywords=["动量"])

    assert query.expanded_text().count("动量") == 1


def test_hybrid_fusion_combines_both_signals():
    """词法和向量都命中的片段，分数应高于只命中一路的。"""
    retriever = StudyRetriever(vector_backend=FakeVector())
    retriever.ingest_document(
        resource_id="r",
        text=NOTE,
        suffix=".md",
        subject="physics",
    )

    query = RetrievalQuery(
        text="简谐运动",
        subject="physics",
        concepts=["胡克定律"],
        keywords=["位移", "平衡位置"],
    )
    hits = retriever.search(query, top_k=3)

    assert hits
    top = hits[0]
    # 负号的含义那段同时含「位移」和「平衡位置」，两路都命中
    assert top.matched_by == "hybrid"
    assert "负号表示回复力方向" in top.text


def test_vector_failure_degrades_to_lexical():
    """向量后端炸了不能让检索整体失效。"""
    retriever = StudyRetriever(vector_backend=BrokenVector())
    retriever.ingest_document(resource_id="r", text=NOTE, suffix=".md")

    hits = retriever.search(RetrievalQuery(text="胡克定律", keywords=["胡克定律"]))

    assert hits
    assert all(h.matched_by == "lexical" for h in hits)


def test_remove_document_clears_everything():
    retriever = StudyRetriever(vector_backend=FakeVector())
    retriever.ingest_document(resource_id="r", text=NOTE, suffix=".md")
    assert retriever.stats()["chunks"] > 0

    removed = retriever.remove_document("r")

    assert removed > 0
    assert retriever.stats()["chunks"] == 0


def test_reingest_same_resource_replaces_old():
    retriever = StudyRetriever(vector_backend=FakeVector())
    retriever.ingest_document(resource_id="r", text="# A\n\n内容一\n")
    second = retriever.ingest_document(resource_id="r", text="# B\n\n内容二\n")

    assert retriever.stats()["chunks"] == len(second)
    assert len(second) == 1
    assert "内容二" in second[0].text


def test_citation_is_human_readable():
    chunk = RetrievedChunk(
        chunk_id="c",
        resource_id="r",
        text="x",
        chapter="第二章 简谐运动",
        section="负号的含义",
        page=37,
        source_path="Physics/x.md",
    )

    assert "第二章 简谐运动" in chunk.citation()
    assert "P37" in chunk.citation()


def test_vector_backend_shares_the_warmed_up_singleton():
    """RAG 必须复用被预热的那个单例。

    ChatAgent 启动时后台预热的是 `get_embedding_generator()`。
    如果 RAG 另起一个实例，预热就白做了——首次检索仍会卡在模型加载上，
    而且这种退化不会报错，只会表现为「第一次查询莫名慢 10 秒」。
    """
    from memory.embedding_generator import get_embedding_generator

    from core.services.study.rag.embeddings import BgeOnnxBackend

    backend = BgeOnnxBackend()
    backend._ensure_generator()

    assert backend._generator is get_embedding_generator()


def test_library_context_items_carry_citation():
    library = StudyLibrary(retriever=StudyRetriever(vector_backend=FakeVector()))
    library.add_resource(resource_id="r", text=NOTE, subject="physics")

    items = library.as_context_items(RetrievalQuery(text="位移", keywords=["位移"]), top_k=1)

    assert items
    assert items[0]["source"] == "rag"
    assert items[0]["excerpt"]
    assert "负号的含义" in items[0]["title"]
