import numpy as np

from memory.core.retrieval_ops import (
    get_cached_memory_embedding as get_cached_memory_embedding_impl,
)
from memory.weighted_memory_manager import embedding_generator as _shared_eg


def _create_manager(tmp_path):
    import memory.weighted_memory_manager as wmm

    wmm.HISTORY_DIR = tmp_path
    wmm.LONG_TERM_DIR = tmp_path / "long_term"
    wmm.WEIGHTED_MEMORY_DIR = tmp_path / "weighted"
    wmm.SHORT_TERM_DIR = tmp_path / "short_term"
    wmm.SENSITIVE_DIR = tmp_path / "sensitive"
    for d in (
        wmm.HISTORY_DIR,
        wmm.LONG_TERM_DIR,
        wmm.WEIGHTED_MEMORY_DIR,
        wmm.SHORT_TERM_DIR,
        wmm.SENSITIVE_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)

    mgr = wmm.WeightedMemoryManager(
        user_id="test-user",
        auto_save_interval=0,
        skip_auto_reclassify=True,
    )
    with mgr.lock:
        mgr.weighted_memories = {}
    return mgr, wmm


def test_memory_embedding_cache_is_lru(monkeypatch, tmp_path):
    mgr, wmm = _create_manager(tmp_path)
    mgr._embedding_cache_max_items = 2

    import memory.embedding_generator as eg

    v = np.ones((eg.EMBEDDING_DIMENSION,), dtype=np.float32)
    b64 = wmm.embedding_generator.embedding_to_base64(v)

    m0 = {"id": "m0", "embedding": b64}
    m1 = {"id": "m1", "embedding": b64}
    m2 = {"id": "m2", "embedding": b64}

    get_cached_memory_embedding_impl(mgr, m0, _shared_eg)
    get_cached_memory_embedding_impl(mgr, m1, _shared_eg)
    assert list(mgr._embedding_cache.keys()) == ["m0", "m1"]

    get_cached_memory_embedding_impl(mgr, m0, _shared_eg)
    assert list(mgr._embedding_cache.keys()) == ["m1", "m0"]

    get_cached_memory_embedding_impl(mgr, m2, _shared_eg)
    assert list(mgr._embedding_cache.keys()) == ["m0", "m2"]


def test_query_embedding_cache_hits(monkeypatch, tmp_path):
    mgr, wmm = _create_manager(tmp_path)
    mgr._query_embedding_cache_max_items = 4

    import memory.embedding_generator as eg

    v = np.ones((eg.EMBEDDING_DIMENSION,), dtype=np.float32)
    b64 = wmm.embedding_generator.embedding_to_base64(v)

    with mgr.lock:
        mgr.weighted_memories = {
            "m0": {
                "id": "m0",
                "content": "a",
                "embedding": b64,
                "weight": 10.0,
                "timestamp": 1.0,
                "topics": [],
            }
        }

    calls = {"n": 0}

    def _fake_generate_embedding(text):
        calls["n"] += 1
        return v

    monkeypatch.setattr(
        wmm.embedding_generator,
        "generate_embedding",
        _fake_generate_embedding,
        raising=True,
    )

    r1 = mgr.search_by_similarity("q", limit=1, min_similarity=0.0)
    assert r1 and "similarity_score" in r1[0]
    assert calls["n"] == 1

    r2 = mgr.search_by_similarity("q", limit=1, min_similarity=0.0)
    assert r2 and "weighted_score" in r2[0]
    assert calls["n"] == 1


def test_hybrid_search_returns_compatible_scores(monkeypatch, tmp_path):
    mgr, wmm = _create_manager(tmp_path)
    mgr._embedding_cache_max_items = 8
    mgr._query_embedding_cache_max_items = 8

    import memory.embedding_generator as eg

    v = np.ones((eg.EMBEDDING_DIMENSION,), dtype=np.float32)
    b64 = wmm.embedding_generator.embedding_to_base64(v)

    with mgr.lock:
        mgr.weighted_memories = {
            "m0": {
                "id": "m0",
                "content": "Python 列表推导式",
                "embedding": b64,
                "weight": 10.0,
                "timestamp": 1.0,
                "topics": ["learning"],
                "category": "learning",
                "status": "active",
                "memory_type": "fact",
                "scopes": ["local"],
            }
        }
        mgr._request_keyword_index_rebuild_locked()

    monkeypatch.setattr(
        wmm.embedding_generator,
        "generate_embedding",
        lambda text: v,
        raising=True,
    )

    res = mgr.hybrid_search(
        "我上次学的列表推导式是什么",
        limit=1,
        min_similarity=0.0,
        use_probability=False,
        scope="local",
    )
    assert res
    assert "hybrid_score" in res[0]
    assert "similarity_score" in res[0]
    assert "weighted_score" in res[0]
