"""记忆向量缓存与检索契约测试

嵌入缓存已经从 manager._embedding_cache 迁移到统一缓存 UnifiedCacheManager，
构造后修改 _embedding_cache_max_items 不会再影响容量，因此 LRU 契约直接针对
统一缓存验证；检索类契约仍走真实的 WeightedMemoryManager，但目录重定向到
tmp_path（原实现直接给模块常量赋值，会污染同进程内的其他测试），
并等待后台加载完成后再注入记忆，避免被延迟加载线程清空。
"""

import threading
import time

import numpy as np
import pytest

import memory.embedding_generator as eg
from memory.core.retrieval_ops import (
    get_cached_memory_embedding as get_cached_memory_embedding_impl,
)
from memory.core.unified_cache_manager import UnifiedCacheManager
from memory.weighted_memory_manager import embedding_generator as _shared_eg


class _FakeCacheHost:
    """只提供统一缓存所需属性的管理器替身"""

    def __init__(self, unified_cache):
        self._unified_cache = unified_cache
        self._embedding_cache_max_items = 0
        self.lock = threading.RLock()
        self._use_rw_lock = False


def _base64_of(value):
    return _shared_eg.embedding_to_base64(value)


def test_memory_embedding_cache_is_lru():
    """统一缓存按 LRU 淘汰记忆嵌入"""
    uc = UnifiedCacheManager(embedding_cache_size=2, query_cache_size=1)
    host = _FakeCacheHost(uc)

    v = np.ones((eg.EMBEDDING_DIMENSION,), dtype=np.float32)
    b64 = _base64_of(v)

    m0 = {"id": "m0", "embedding": b64}
    m1 = {"id": "m1", "embedding": b64}
    m2 = {"id": "m2", "embedding": b64}

    get_cached_memory_embedding_impl(host, m0, _shared_eg)
    get_cached_memory_embedding_impl(host, m1, _shared_eg)
    assert list(uc._embedding_cache.keys()) == ["m0", "m1"]

    # 命中后刷新到队尾
    get_cached_memory_embedding_impl(host, m0, _shared_eg)
    assert list(uc._embedding_cache.keys()) == ["m1", "m0"]

    # 超出容量时淘汰最久未使用的 m1
    get_cached_memory_embedding_impl(host, m2, _shared_eg)
    assert list(uc._embedding_cache.keys()) == ["m0", "m2"]


def test_memory_embedding_cache_invalidated_when_embedding_changes():
    """记忆更新后嵌入变了，缓存不能继续返回旧向量"""
    uc = UnifiedCacheManager(embedding_cache_size=4, query_cache_size=1)
    host = _FakeCacheHost(uc)

    old_vec = np.ones((eg.EMBEDDING_DIMENSION,), dtype=np.float32)
    new_vec = np.zeros((eg.EMBEDDING_DIMENSION,), dtype=np.float32)

    memory = {"id": "m0", "embedding": _base64_of(old_vec)}
    cached = get_cached_memory_embedding_impl(host, memory, _shared_eg)
    assert np.allclose(cached, old_vec)

    memory["embedding"] = _base64_of(new_vec)
    refreshed = get_cached_memory_embedding_impl(host, memory, _shared_eg)
    assert np.allclose(refreshed, new_vec)


def _register_in_vector_index(mgr, memory):
    """把记忆同步到 C++ VectorIndexer

    检索优先走 C++ 索引器，直接改 weighted_memories 不会进入索引，
    因此测试注入数据后需要显式登记。
    """
    mgr.vector_indexer.addRecord(
        str(memory["id"]),
        [float(x) for x in np.ones((eg.EMBEDDING_DIMENSION,), dtype=np.float32)],
        float(memory.get("weight") or 0.0),
        float(memory.get("timestamp") or 0.0),
        str(memory.get("source") or ""),
        [str(t) for t in (memory.get("topics") or [])],
    )


@pytest.fixture
def manager(tmp_path, monkeypatch):
    import memory.weighted_memory_manager as wmm

    root = tmp_path / "history"
    # 只改 HISTORY_DIR：DEFAULT_HISTORY_DIR 若被一起改，
    # build_memory_layout 会认为没有外部指定目录，回落到真实用户目录
    monkeypatch.setattr(wmm, "HISTORY_DIR", root)
    monkeypatch.setattr(wmm, "LONG_TERM_DIR", root / "long_term")
    monkeypatch.setattr(wmm, "WEIGHTED_MEMORY_DIR", root / "weighted")
    monkeypatch.setattr(wmm, "SHORT_TERM_DIR", root / "short_term")
    monkeypatch.setattr(wmm, "SENSITIVE_DIR", root / "sensitive")
    monkeypatch.setattr(wmm, "READABLE_DIR", root / "readable")

    mgr = wmm.WeightedMemoryManager(
        user_id="test-user",
        auto_save_interval=0,
        skip_auto_reclassify=True,
    )
    # 后台延迟加载会从磁盘覆盖 weighted_memories，必须等它结束后再注入测试数据
    assert mgr.ensure_data_loaded(timeout=30.0), "后台数据加载应在超时前完成"
    return mgr, wmm


def test_query_embedding_cache_hits(manager, monkeypatch):
    """相同查询只生成一次嵌入，第二次命中查询缓存"""
    mgr, wmm = manager

    v = np.ones((eg.EMBEDDING_DIMENSION,), dtype=np.float32)
    b64 = _base64_of(v)

    memory = {
        "id": "m0",
        "content": "a",
        "embedding": b64,
        "weight": 10.0,
        "timestamp": time.time(),
        "topics": [],
    }
    with mgr.lock:
        mgr.weighted_memories = {"m0": memory}
    _register_in_vector_index(mgr, memory)

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
    assert calls["n"] == 1, "第二次相同查询应命中查询嵌入缓存"


def test_hybrid_search_returns_compatible_scores(manager, monkeypatch):
    """混合搜索结果同时给出 hybrid / similarity / weighted 三种分数"""
    mgr, wmm = manager

    v = np.ones((eg.EMBEDDING_DIMENSION,), dtype=np.float32)
    b64 = _base64_of(v)

    memory = {
        "id": "m0",
        "content": "Python 列表推导式",
        "embedding": b64,
        "weight": 10.0,
        "timestamp": time.time(),
        "topics": ["learning"],
        "category": "learning",
        "status": "active",
        "memory_type": "fact",
        "scopes": ["local"],
    }
    with mgr.lock:
        mgr.weighted_memories = {"m0": memory}
        mgr._request_keyword_index_rebuild_locked()
    _register_in_vector_index(mgr, memory)

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
