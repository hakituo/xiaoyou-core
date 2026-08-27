"""把 ChromaDB 存量向量库迁移到 bge-small-zh-v1.5（512 维，CLS pooling）。

背景：2026-08 记忆系统 embedding 从 all-MiniLM-L6-v2（384 维，mean pooling）
切换到 bge-small-zh-v1.5（512 维）。ChromaDB 集合维度由首次写入的 embedding 决定，
无法原地改维，故需：读出现有文档 -> 删除集合 -> 用统一生成器重建 -> 回灌。

安全性：
- 不丢数据：先从集合读出全部 documents/ids/metadatas，再删除重建回灌。
- 幂等：重复运行等价于把集合再重建一遍，不产生脏数据。
- 无操作跟随：count==0 的集合跳过。

用法：
    python -m venv_cpu 脚本  # 或用 venv_core
    python scripts/migrate/rebuild_chromadb_embedding_512.py          # 正式迁移
    python scripts/migrate/rebuild_chromadb_embedding_512.py --dry-run # 只打印不写入

依赖：venv_cpu（已装 chromadb、numpy、onnxruntime）。
"""
from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

_CHROMA_PERSIST_DIR = os.path.join(PROJECT_ROOT, "data", "chromadb_store")
_BATCH_SIZE = 256


def _load_embedding_function():
    """复用统一生成器，保证写入与查询都走 512 维 BGE（CLS pooling）。"""
    try:
        from memory.embedding_generator import EMBEDDING_DIMENSION, embedding_generator
    except Exception as exc:  # 统一生成器不可用时直接失败，避免静默降维
        raise RuntimeError(f"无法导入统一生成器: {exc}") from exc

    def emb_fn(inputs):
        embs = embedding_generator.generate_embeddings_batch(list(inputs))
        return [list(e) for e in embs]

    emb_fn.dimension = EMBEDDING_DIMENSION  # 供调用方检查维度
    return emb_fn


def _get_all(collection):
    """分页读取集合内全部 文档/ids/metadatas（避免一次性全量占用内存）。"""
    total = int(collection.count() or 0)
    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []
    offset = 0
    while offset < total:
        chunk = collection.get(
            limit=_BATCH_SIZE,
            offset=offset,
            include=["documents", "metadatas"],
        )
        c_ids = chunk.get("ids") or []
        if not c_ids:
            break
        c_docs = chunk.get("documents") or []
        c_metas = chunk.get("metadatas") or []
        ids.extend(c_ids)
        docs.extend(c_docs if c_docs else [None] * len(c_ids))
        metas.extend(c_metas if c_metas else [None] * len(c_ids))
        offset += len(c_ids)
    return ids, docs, metas


def _rebuild(client, name: str, emb_fn) -> tuple[int, int]:
    """对单个集合做原地重建。返回 (旧条数, 新条数)。"""
    collection = client.get_collection(name)
    ids, docs, metas = _get_all(collection)
    old = len(ids)
    if old == 0:
        return 0, 0
    client.delete_collection(name)
    new_col = client.get_or_create_collection(
        name, embedding_function=emb_fn, metadata={"hnsw:space": "cosine"}
    )
    # 数据缺失的条目给空文档，避免 chroma 报错
    added = 0
    for i in range(0, len(ids), _BATCH_SIZE):
        batch_ids = ids[i:i + _BATCH_SIZE]
        batch_docs = docs[i:i + _BATCH_SIZE]
        batch_metas = metas[i:i + _BATCH_SIZE]
        new_col.add(
            ids=batch_ids,
            documents=[d if d is not None else "" for d in batch_docs],
            metadatas=[m if m is not None else {} for m in batch_metas],
        )
        added += len(batch_ids)
    return old, added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = parser.parse_args()

    if not os.path.isdir(_CHROMA_PERSIST_DIR):
        print(f"[skip] ChromaDB 存储目录不存在: {_CHROMA_PERSIST_DIR}")
        return 0

    import chromadb

    if args.dry_run:
        client = chromadb.PersistentClient(path=_CHROMA_PERSIST_DIR)
        emb_fn = _load_embedding_function()
        print(f"[dry-run] 统一生成器维度: {getattr(emb_fn, 'dimension', '?')}")
        for name in [c.name for c in client.list_collections()]:
            if client.get_collection(name).count() == 0:
                print(f"[dry-run] 集合 {name}: 0 条，跳过")
                continue
            c = client.get_collection(name, embedding_function=emb_fn)
            raw = c.get(include=["embeddings"])
            dims = {len(e) for e in (raw.get("embeddings") or [])}
            print(
                f"[dry-run] 集合 {name}: {c.count()} 条，当前维度 {sorted(dims)} "
                f"-> 将重建为 512"
            )
        return 0

    print(f"[start] 迁移 ChromaDB: {_CHROMA_PERSIST_DIR}")
    emb_fn = _load_embedding_function()
    client = chromadb.PersistentClient(path=_CHROMA_PERSIST_DIR)
    names = [c.name for c in client.list_collections()]
    names.sort(key=lambda n: (n != "default"))  # default 知识库优先迁移
    for name in names:
        old, added = _rebuild(client, name, emb_fn)
        if old == 0:
            print(f"[skip] {name}: 0 条")
        else:
            print(f"[done] {name}: {old} -> {added} 条（512 维）")
    print("[finish] 迁移完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())