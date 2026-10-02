"""对比「纯 BM25」与「BM25 + 向量融合」在真实笔记上的召回。

只用于人工评估，不进 CI（要加载 50s 的本地 embedding 模型）。

用法：
    venv_core\\Scripts\\python.exe tests/scripts/study/compare_rag_recall.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

NOTES = [
    "Physics/02_一轮复习/02_牛顿运动定律.md",
    "Physics/02_一轮复习/04_功和能.md",
    "Physics/02_一轮复习/05_动量.md",
    "Physics/02_一轮复习/06_静电场.md",
]

# 每个问题标注「应该命中哪个文件」，用于算 recall@3
CASES = [
    ("动能定理的内容是什么", "04_功和能", ["动能定理", "合外力做功"]),
    ("动量守恒需要的条件", "05_动量", ["动量守恒", "系统", "合外力"]),
    ("牛顿第二定律的表达式", "02_牛顿运动定律", ["牛顿第二定律", "加速度"]),
    ("电场强度怎么定义", "06_静电场", ["电场强度", "试探电荷"]),
    # 语义型：字面上和原文差别大，考验向量
    ("推箱子推不动的时候摩擦力怎么算", "02_牛顿运动定律", ["摩擦力", "静摩擦", "牛顿"]),
    ("撞完之后两个物体粘在一起属于什么碰撞", "05_动量", ["碰撞", "动量", "完全非弹性"]),
]


def main() -> int:
    from core.services.study.rag import RetrievalQuery, StudyLibrary

    root = Path("D:/AI/Study")
    library = StudyLibrary()

    ingested = 0
    for rel in NOTES:
        path = root / rel
        if not path.exists():
            print(f"跳过（不存在）: {rel}")
            continue
        chunks = library.add_resource(
            resource_id=Path(rel).stem, path=path, subject="physics", trust_level="note"
        )
        ingested += len(chunks)
    print(f"入库 {ingested} 个片段\n")
    if not ingested:
        return 1

    print(f"{'问题':<28} {'期望命中':<18} {'BM25':<8} {'融合':<8}")
    print("-" * 64)

    bm25_hits = 0
    hybrid_hits = 0
    for question, expected, keywords in CASES:
        query = RetrievalQuery(text=question, subject="physics", keywords=keywords)

        # 纯词法：临时关掉向量
        library._retriever._vector = None
        lexical = library.search(query, top_k=3)
        # 融合：恢复向量
        from core.services.study.rag.embeddings import BgeOnnxBackend

        library._retriever._vector = BgeOnnxBackend()
        library._retriever._reindex_vectors()
        hybrid = library.search(query, top_k=3)

        lex_ok = any(expected in h.source_path for h in lexical)
        hyb_ok = any(expected in h.source_path for h in hybrid)
        bm25_hits += lex_ok
        hybrid_hits += hyb_ok

        print(
            f"{question[:26]:<28} {expected:<18} "
            f"{'命中' if lex_ok else '未中':<8} {'命中' if hyb_ok else '未中':<8}"
        )

    total = len(CASES)
    print("-" * 64)
    print(f"recall@3   纯BM25: {bm25_hits}/{total}   融合: {hybrid_hits}/{total}")
    return 0


if __name__ == "__main__":
    start = time.time()
    code = main()
    print(f"\n耗时 {time.time() - start:.1f}s")
    raise SystemExit(code)
