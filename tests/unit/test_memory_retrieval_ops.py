"""memory/core/retrieval_ops.py 单元测试

覆盖策略：
- manager 用鸭子类型替身（_FakeManager），不启动真实存储层；
- 读/写锁用 nullcontext 替身，避免真实加锁；
- 下游协作者（hybrid_search / expand_keywords 等）按需 monkeypatch；
- 时间统一注入固定值，不依赖真实当前时间。
"""

import contextlib
import threading
import time
from collections import OrderedDict

import numpy as np
import pytest

import memory.core.retrieval_ops as ro

EMB_DIM = 4


# --------------------------------------------------------------------------- #
# 替身工具
# --------------------------------------------------------------------------- #
class _FakeWeightCalculator:
    """权重计算器替身：时间衰减直接返回原权重，保证结果确定"""

    def __init__(self, config=None):
        self.config = config or {}

    def apply_time_decay(self, weight, timestamp):
        return float(weight)


class _FakeLogger:
    """记录 warning/info/error 的日志替身"""

    def __init__(self):
        self.warnings = []
        self.errors = []
        self.infos = []

    def warning(self, msg, **kwargs):
        self.warnings.append(msg)

    def error(self, msg, **kwargs):
        self.errors.append(msg)

    def info(self, msg, **kwargs):
        self.infos.append(msg)


class _FakeManager:
    """只提供 retrieval_ops 所需属性的管理器替身"""

    def __init__(self, **kwargs):
        self.weighted_memories = {}
        self.category_index = {}
        self._keyword_index = {}
        self._keyword_graph = {}
        self._query_embedding_cache = OrderedDict()
        self._query_embedding_cache_max_items = 0
        self._embedding_cache = OrderedDict()
        self._embedding_cache_max_items = 0
        self.user_id = "u1"
        self.topic_weights = {}
        self.search_cache = None
        self.lock = threading.RLock()
        self._use_rw_lock = False
        self.weight_calculator = _FakeWeightCalculator()
        self.ensure_calls = 0
        self.sim_calls = 0
        for key, value in kwargs.items():
            setattr(self, key, value)

    def _ensure_keyword_index_ready(self):
        self.ensure_calls += 1

    def _extract_keywords(self, text):
        return [t for t in str(text).lower().split() if t]

    def _expand_keywords(self, keywords, top_k=3):
        return list(keywords)

    def _detect_emotion(self, text):
        return "neutral"

    def get_weighted_memories(self, min_weight=None, limit=10, topics=None):
        return [{"id": "gm", "min_weight": min_weight, "topics": topics}]

    def get_state_context(self):
        return {"ctx": 1}

    def get_active_states(self):
        return [{"content": "active one", "status": "active", "type": "t"}]

    def search_by_similarity(self, *args, **kwargs):
        self.sim_calls += 1
        return []


class _BadMoveCache(OrderedDict):
    """move_to_end 抛异常的缓存替身，用于触发防御性 except 分支"""

    def move_to_end(self, *args, **kwargs):
        raise RuntimeError("move_to_end boom")


class _FakeEmbeddingGenerator:
    """嵌入生成器替身，行为可注入"""

    def __init__(self, vector=None, generate=None, b64_to_emb=None,
                 cosine=None, batch=None):
        self._vector = vector if vector is not None else np.ones(EMB_DIM, dtype=np.float32)
        self._generate = generate
        self._b64_to_emb = b64_to_emb
        self._cosine = cosine
        self._batch = batch
        self.generate_calls = 0

    def generate_embedding(self, text):
        self.generate_calls += 1
        if self._generate is not None:
            return self._generate(text)
        return self._vector

    def base64_to_embedding(self, b64):
        if self._b64_to_emb is not None:
            return self._b64_to_emb(b64)
        return self._vector

    def cosine_similarity(self, a, b):
        if self._cosine is not None:
            return self._cosine(a, b)
        return 0.9

    def batch_cosine_similarity(self, query, matrix):
        if self._batch is not None:
            return self._batch(query, matrix)
        return [0.9] * len(matrix)


@pytest.fixture(autouse=True)
def _no_real_locks(monkeypatch):
    """把读写锁替换为空上下文，避免真实加锁"""
    monkeypatch.setattr(ro, "get_read_lock", lambda manager: contextlib.nullcontext())
    monkeypatch.setattr(ro, "get_write_lock", lambda manager: contextlib.nullcontext())


def _memory(mid, **kwargs):
    base = {"id": mid, "content": "", "weight": 1.0, "timestamp": 0.0}
    base.update(kwargs)
    return base


# --------------------------------------------------------------------------- #
# get_category_stats
# --------------------------------------------------------------------------- #
def test_get_category_stats_counts_and_distribution():
    """正常统计：分类计数、平均权重、占比"""
    mgr = _FakeManager()
    mgr.weighted_memories = {
        "m1": _memory("m1", category="a", weight=4.0),
        "m2": _memory("m2", category="a", weight=2.0),
        "m3": _memory("m3", category="b", weight=3.0),
    }
    stats = ro.get_category_stats(mgr)
    assert stats["total_memories"] == 3
    assert stats["counts"] == {"a": 2, "b": 1}
    assert stats["avg_weight"]["a"] == 3.0
    assert stats["distribution"]["a"] == round(2 / 3 * 100, 1)
    # 返回的应是普通 dict，而非 defaultdict
    assert type(stats["counts"]) is dict


def test_get_category_stats_missing_category_falls_back_to_uncategorized():
    """缺失/空分类统一归到 uncategorized"""
    mgr = _FakeManager()
    mgr.weighted_memories = {
        "m1": {"id": "m1", "weight": 1.0},          # 无 category
        "m2": {"id": "m2", "category": "", "weight": 1.0},  # 空 category
    }
    stats = ro.get_category_stats(mgr)
    assert stats["counts"] == {"uncategorized": 2}
    assert stats["distribution"]["uncategorized"] == 100.0


def test_get_category_stats_empty_manager():
    """空管理器不抛异常且返回零值"""
    stats = ro.get_category_stats(_FakeManager())
    assert stats["total_memories"] == 0
    assert stats["counts"] == {}
    assert stats["distribution"] == {}


# --------------------------------------------------------------------------- #
# search_by_keyword
# --------------------------------------------------------------------------- #
def test_search_by_keyword_category_and_emotion_sorting():
    """分类过滤 + 关键词权重 + 情绪加权排序"""
    mgr = _FakeManager()
    mgr.weighted_memories = {
        "m1": _memory("m1", category="a", weight=5.0, emotions=["joy"], content="x"),
        "m2": _memory("m2", category="b", weight=5.0, emotions=[], content="y"),
        "m3": _memory("m3", category="a", weight=5.0, emotions=[], content="z"),
        "m4": _memory("m4", category="c", weight=1.0, content="w"),
    }
    mgr.category_index = {"a": ["m1", "m2", "m3"]}
    mgr._keyword_index = {"kw": ["m1", "m2", "m3", "m4"], "exp": ["m1"]}
    mgr._expand_keywords = lambda kws, top_k=3: ["kw", "exp"]

    res = ro.search_by_keyword(mgr, "kw", limit=10, category="a", emotion="joy")
    # m1 有 joy 加成排前；m3 无加成；m2 分类不符被跳过；m4 不在候选集被跳过
    assert [r["id"] for r in res] == ["m1", "m3"]
    assert mgr.ensure_calls == 1
    # _sort_weight 临时字段应被清理
    assert all("_sort_weight" not in r for r in res)


def test_search_by_keyword_fallback_fulltext_filters_invalid():
    """关键词无命中时回退全文搜索，并过滤 superseded / 非 active 偏好"""
    mgr = _FakeManager()
    mgr.weighted_memories = {
        "m1": _memory("m1", content="Hello World"),
        "m2": _memory("m2", content="hello", status="superseded"),
        "m3": _memory("m3", content="hello", memory_type="preference", status="archived"),
        "m4": _memory("m4", content="unrelated"),
    }
    mgr._extract_keywords = lambda t: ["hello"]
    mgr._expand_keywords = lambda kws, top_k=3: []  # 触发 elif 分支

    res = ro.search_by_keyword(mgr, "HELLO", limit=10)
    assert [r["id"] for r in res] == ["m1"]


def test_search_by_keyword_exclude_sensitive_and_missing_memory():
    """exclude_sensitive 过滤敏感分类；索引里指向已删除记忆的 id 被跳过"""
    mgr = _FakeManager()
    mgr.weighted_memories = {
        "m1": _memory("m1", category="sensitive", content="secret"),
        "m2": _memory("m2", category="normal", content="ok"),
    }
    mgr._keyword_index = {"kw": ["m1", "m2", "gone"]}
    mgr._extract_keywords = lambda t: ["kw"]

    res = ro.search_by_keyword(mgr, "kw", exclude_sensitive=True)
    assert [r["id"] for r in res] == ["m2"]


def test_search_by_keyword_category_fallback_uses_candidate_ids():
    """指定分类且关键词无命中时，回退全文搜索只遍历候选 id"""
    mgr = _FakeManager()
    mgr.weighted_memories = {
        "m1": _memory("m1", category="a", content="target text"),
        "m2": _memory("m2", category="b", content="target text"),
    }
    mgr.category_index = {"a": ["m1"]}
    mgr._keyword_index = {}
    mgr._extract_keywords = lambda t: ["nope"]

    res = ro.search_by_keyword(mgr, "target", category="a")
    assert [r["id"] for r in res] == ["m1"]


def test_search_by_keyword_empty_query_matches_all_valid():
    """空查询：关键词权重为空，回退全文时空串命中所有有效记忆"""
    mgr = _FakeManager()
    mgr.weighted_memories = {
        "m1": _memory("m1", weight=1.0, content="a"),
        "m2": _memory("m2", weight=9.0, content="b"),
        "m3": _memory("m3", content="c", status="superseded"),
    }
    mgr._extract_keywords = lambda t: []

    res = ro.search_by_keyword(mgr, "")
    # 按 weight 降序
    assert [r["id"] for r in res] == ["m2", "m1"]


# --------------------------------------------------------------------------- #
# _deterministic_hash
# --------------------------------------------------------------------------- #
def test_deterministic_hash_stable_and_truncated():
    """同一文本哈希稳定，长度固定 16"""
    h1 = ro._deterministic_hash("abc")
    h2 = ro._deterministic_hash("abc")
    assert h1 == h2 and len(h1) == 16
    assert ro._deterministic_hash("abd") != h1


# --------------------------------------------------------------------------- #
# get_cached_query_embedding
# --------------------------------------------------------------------------- #
def test_get_cached_query_embedding_empty_query():
    """空查询直接返回 None，不生成嵌入"""
    gen = _FakeEmbeddingGenerator()
    assert ro.get_cached_query_embedding(_FakeManager(), "", gen) is None
    assert gen.generate_calls == 0


def test_get_cached_query_embedding_disabled_cache():
    """缓存容量 <= 0 时每次都直接生成"""
    mgr = _FakeManager(_query_embedding_cache_max_items=0)
    gen = _FakeEmbeddingGenerator()
    ro.get_cached_query_embedding(mgr, "q", gen)
    ro.get_cached_query_embedding(mgr, "q", gen)
    assert gen.generate_calls == 2


def test_get_cached_query_embedding_unified_cache_hit_and_miss():
    """统一缓存：首次 miss 写入，二次命中"""
    class _UC:
        def __init__(self):
            self.store = {}

        def get_query_embedding(self, key):
            return self.store.get(key)

        def put_query_embedding(self, key, value):
            self.store[key] = value

    uc = _UC()
    mgr = _FakeManager(_query_embedding_cache_max_items=8, _unified_cache=uc)
    gen = _FakeEmbeddingGenerator()
    first = ro.get_cached_query_embedding(mgr, "q", gen)
    second = ro.get_cached_query_embedding(mgr, "q", gen)
    assert gen.generate_calls == 1
    assert np.array_equal(first, second)


def test_get_cached_query_embedding_local_lru_and_bad_move():
    """无统一缓存时走本地 LRU：move_to_end 异常被吞、超容淘汰最旧"""
    mgr = _FakeManager(_query_embedding_cache_max_items=2)
    mgr._query_embedding_cache = _BadMoveCache()
    gen = _FakeEmbeddingGenerator()
    for q in ("a", "b", "c"):
        assert ro.get_cached_query_embedding(mgr, q, gen) is not None
    assert len(mgr._query_embedding_cache) == 2
    # 缓存键是查询的确定性哈希，淘汰最旧的 "a"
    assert list(mgr._query_embedding_cache.keys()) == [
        ro._deterministic_hash("b"),
        ro._deterministic_hash("c"),
    ]


# --------------------------------------------------------------------------- #
# get_cached_memory_embedding
# --------------------------------------------------------------------------- #
def test_get_cached_memory_embedding_rejects_bad_input():
    """非 dict / 缺 embedding / 缺 id 一律返回 None"""
    mgr = _FakeManager()
    gen = _FakeEmbeddingGenerator()
    assert ro.get_cached_memory_embedding(mgr, "not-a-dict", gen) is None
    assert ro.get_cached_memory_embedding(mgr, {"id": "m1"}, gen) is None
    assert ro.get_cached_memory_embedding(mgr, {"embedding": "x"}, gen) is None
    assert ro.get_cached_memory_embedding(mgr, {"id": "  ", "embedding": "x"}, gen) is None


def test_get_cached_memory_embedding_unified_cache_paths():
    """统一缓存：验证命中返回缓存值，未命中则解码后写入"""
    vec = np.ones(EMB_DIM, dtype=np.float32)

    class _UC:
        def __init__(self):
            self.valid = {}

        def get_embedding_validated(self, mid, b64):
            return self.valid.get(mid)

        def put_embedding(self, mid, b64, emb):
            self.valid[mid] = emb

    uc = _UC()
    mgr = _FakeManager(_unified_cache=uc)
    gen = _FakeEmbeddingGenerator(vector=vec)
    mem = {"id": "m1", "embedding": "b64"}
    first = ro.get_cached_memory_embedding(mgr, mem, gen)
    assert np.array_equal(first, vec)
    second = ro.get_cached_memory_embedding(mgr, mem, gen)
    assert np.array_equal(second, vec)


def test_get_cached_memory_embedding_local_cache_hit_and_mismatch():
    """本地缓存：b64 一致命中；b64 变化则重新解码"""
    mgr = _FakeManager(_embedding_cache_max_items=4)
    vec = np.ones(EMB_DIM, dtype=np.float32)
    mgr._embedding_cache["m1"] = ("old-b64", vec)
    gen = _FakeEmbeddingGenerator(vector=vec)

    hit = ro.get_cached_memory_embedding(mgr, {"id": "m1", "embedding": "old-b64"}, gen)
    assert np.array_equal(hit, vec)
    assert gen.generate_calls == 0

    miss = ro.get_cached_memory_embedding(mgr, {"id": "m1", "embedding": "new-b64"}, gen)
    assert np.array_equal(miss, vec)
    assert mgr._embedding_cache["m1"][0] == "new-b64"


def test_get_cached_memory_embedding_bad_move_and_lru_eviction():
    """本地缓存写入：move_to_end 异常被吞，超容淘汰最旧"""
    mgr = _FakeManager(_embedding_cache_max_items=1)
    mgr._embedding_cache = _BadMoveCache()
    gen = _FakeEmbeddingGenerator()
    ro.get_cached_memory_embedding(mgr, {"id": "m1", "embedding": "a"}, gen)
    ro.get_cached_memory_embedding(mgr, {"id": "m2", "embedding": "b"}, gen)
    assert list(mgr._embedding_cache.keys()) == ["m2"]


def test_get_cached_memory_embedding_hit_with_bad_move():
    """缓存命中刷新 LRU 时 move_to_end 抛异常被吞，仍返回缓存值"""
    mgr = _FakeManager(_embedding_cache_max_items=4)
    vec = np.ones(EMB_DIM, dtype=np.float32)
    mgr._embedding_cache = _BadMoveCache({"m1": ("b64", vec)})
    hit = ro.get_cached_memory_embedding(
        mgr, {"id": "m1", "embedding": "b64"}, _FakeEmbeddingGenerator(vector=vec)
    )
    assert np.array_equal(hit, vec)


def test_get_cached_memory_embedding_decode_failures():
    """解码抛异常 / 返回 None / 空向量 / 无 len 对象，均返回 None"""
    mgr = _FakeManager()

    def _raise(b64):
        raise ValueError("bad base64")

    assert ro.get_cached_memory_embedding(
        mgr, {"id": "m1", "embedding": "x"}, _FakeEmbeddingGenerator(b64_to_emb=_raise)
    ) is None
    assert ro.get_cached_memory_embedding(
        mgr, {"id": "m1", "embedding": "x"}, _FakeEmbeddingGenerator(b64_to_emb=lambda b: None)
    ) is None
    assert ro.get_cached_memory_embedding(
        mgr, {"id": "m1", "embedding": "x"}, _FakeEmbeddingGenerator(b64_to_emb=lambda b: [])
    ) is None
    # 无 __len__ 的对象：len() 抛 TypeError，被 except 捕获
    assert ro.get_cached_memory_embedding(
        mgr, {"id": "m1", "embedding": "x"}, _FakeEmbeddingGenerator(b64_to_emb=lambda b: object())
    ) is None


# --------------------------------------------------------------------------- #
# search_memories
# --------------------------------------------------------------------------- #
def test_search_memories_vector_disabled_falls_back():
    """向量搜索关闭：记录 warning 并回退关键词搜索"""
    mgr = _FakeManager()
    mgr.weighted_memories = {"m1": _memory("m1", content="hello")}
    mgr._extract_keywords = lambda t: []
    logger = _FakeLogger()
    res = ro.search_memories(
        mgr, query="hello", vector_search_enabled=False,
        embedding_generator=_FakeEmbeddingGenerator(), logger=logger,
    )
    assert [r["id"] for r in res] == ["m1"]
    assert logger.warnings


def test_search_memories_empty_query_falls_back_without_warning():
    """空查询回退关键词，且不产生 warning"""
    mgr = _FakeManager()
    mgr.weighted_memories = {}
    mgr._extract_keywords = lambda t: []
    logger = _FakeLogger()
    res = ro.search_memories(
        mgr, query="", vector_search_enabled=True,
        embedding_generator=_FakeEmbeddingGenerator(), logger=logger,
    )
    assert res == []
    assert logger.warnings == []


def test_search_memories_cache_hit_short_circuits():
    """搜索缓存命中直接返回，不进入向量计算"""
    class _Cache:
        def get_sync(self, key):
            return [{"id": "cached"}]

        def set_sync(self, *a, **k):
            raise AssertionError("命中缓存不应写入")

    mgr = _FakeManager(search_cache=_Cache())
    logger = _FakeLogger()
    res = ro.search_memories(
        mgr, query="q", vector_search_enabled=True,
        embedding_generator=_FakeEmbeddingGenerator(), logger=logger,
    )
    assert res == [{"id": "cached"}]


def test_search_memories_vector_path_success_and_cache_write():
    """向量路径成功：过滤无嵌入/敏感记忆，写回搜索缓存"""
    vec = np.ones(EMB_DIM, dtype=np.float32)
    written = {}

    class _Cache:
        def get_sync(self, key):
            return None

        def set_sync(self, key, value, ttl=None):
            written["key"] = key
            written["value"] = value

    mgr = _FakeManager(search_cache=_Cache(), category_index={"a": ["m1", "gone", "m2"]})
    mgr.weighted_memories = {
        "m1": _memory("m1", category="a", embedding="b64", weight=8.0, timestamp=1.0),
        "m2": _memory("m2", category="a", embedding="bad", weight=1.0, timestamp=1.0),
    }
    logger = _FakeLogger()
    res = ro.search_memories(
        mgr, query="q", limit=5, min_similarity=0.0, category="a",
        vector_search_enabled=True,
        embedding_generator=_FakeEmbeddingGenerator(
            vector=vec, b64_to_emb=lambda b: None if b == "bad" else vec
        ),
        logger=logger,
    )
    assert len(res) == 1 and res[0]["id"] == "m1"
    assert "hybrid_score" in res[0]
    assert written["value"] == res


def test_search_memories_skips_memories_without_embedding():
    """候选记忆缺 embedding 时被跳过，最终无有效记忆回退关键词"""
    mgr = _FakeManager()
    mgr.weighted_memories = {
        "m1": _memory("m1", content="hello"),  # 无 embedding
        "m2": _memory("m2", category="sensitive", embedding="b64"),
    }
    mgr._extract_keywords = lambda t: []
    logger = _FakeLogger()
    res = ro.search_memories(
        mgr, query="hello", vector_search_enabled=True, exclude_sensitive=True,
        embedding_generator=_FakeEmbeddingGenerator(), logger=logger,
    )
    assert [r["id"] for r in res] == ["m1"]
    assert logger.infos


def test_search_memories_numpy_failure_falls_back_to_cosine():
    """批量相似度抛异常时逐条 cosine 回退；单条异常被跳过"""
    vec = np.ones(EMB_DIM, dtype=np.float32)

    def _batch(query, matrix):
        raise RuntimeError("no numpy")

    calls = {"n": 0}

    def _cosine(a, b):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first fails")
        return 0.9

    mgr = _FakeManager()
    mgr.weighted_memories = {
        "m1": _memory("m1", embedding="b1", weight=1.0),
        "m2": _memory("m2", embedding="b2", weight=1.0),
        "m3": _memory("m3", embedding="bad", weight=1.0),  # 解码失败应被跳过
    }
    logger = _FakeLogger()
    res = ro.search_memories(
        mgr, query="q", min_similarity=0.0, vector_search_enabled=True,
        embedding_generator=_FakeEmbeddingGenerator(
            vector=vec, batch=_batch, cosine=_cosine,
            b64_to_emb=lambda b: None if b == "bad" else vec,
        ),
        logger=logger,
    )
    assert [r["id"] for r in res] == ["m2"]


def test_search_memories_no_candidates_falls_back():
    """相似度均低于阈值导致无候选，回退关键词搜索"""
    vec = np.ones(EMB_DIM, dtype=np.float32)
    mgr = _FakeManager()
    mgr.weighted_memories = {
        "m1": _memory("m1", embedding="b1", content="hello"),
    }
    mgr._extract_keywords = lambda t: []
    logger = _FakeLogger()
    res = ro.search_memories(
        mgr, query="hello", min_similarity=0.99, vector_search_enabled=True,
        embedding_generator=_FakeEmbeddingGenerator(vector=vec, batch=lambda q, m: [0.1]),
        logger=logger,
    )
    assert [r["id"] for r in res] == ["m1"]
    assert logger.infos


def test_search_memories_outer_exception_logs_and_falls_back():
    """生成查询嵌入抛异常时，外层兜底回退关键词并记录 error"""
    def _boom(text):
        raise RuntimeError("embed boom")

    mgr = _FakeManager()
    mgr.weighted_memories = {"m1": _memory("m1", content="hello")}
    mgr._extract_keywords = lambda t: []
    logger = _FakeLogger()
    res = ro.search_memories(
        mgr, query="hello", vector_search_enabled=True,
        embedding_generator=_FakeEmbeddingGenerator(generate=_boom), logger=logger,
    )
    assert [r["id"] for r in res] == ["m1"]
    assert logger.errors


def test_search_memories_fallback_skips_vanished_embedding():
    """回退逐条 cosine 时，若某条嵌入在候选收集与回退两次查询之间失效则被跳过

    用有状态的解码器模拟「同一 b64 第二次解码失败」（缓存被并发淘汰 /
    解码瞬时失败），从而命中回退循环里的 None 保护分支。
    """
    vec = np.ones(EMB_DIM, dtype=np.float32)
    state = {"n": 0}

    def _b64(b64):
        state["n"] += 1
        # 前 3 次（候选收集 2 次 + 回退第 1 条）成功，第 4 次起失效
        return None if state["n"] >= 4 else vec

    def _batch(query, matrix):
        raise RuntimeError("no numpy")

    mgr = _FakeManager()
    mgr.weighted_memories = {
        "m1": _memory("m1", embedding="b1", weight=1.0),
        "m2": _memory("m2", embedding="b2", weight=1.0),
    }
    res = ro.search_memories(
        mgr, query="q", min_similarity=0.0, vector_search_enabled=True,
        embedding_generator=_FakeEmbeddingGenerator(
            vector=vec, batch=_batch, b64_to_emb=_b64, cosine=lambda a, b: 0.9
        ),
        logger=_FakeLogger(),
    )
    assert [r["id"] for r in res] == ["m1"]


# --------------------------------------------------------------------------- #
# 主题缓存工具
# --------------------------------------------------------------------------- #
def test_get_top_topics_cache_creates_when_missing():
    """manager 无缓存属性时惰性创建"""
    mgr = _FakeManager()
    cache = ro._get_top_topics_cache(mgr)
    assert cache == {}
    assert mgr._top_topics_cache is cache


def test_cleanup_top_topics_cache_small_cache_noop():
    """条目数不超上限时直接返回"""
    cache = {"a": (time.time(), [])}
    ro._cleanup_top_topics_cache(cache)
    assert list(cache.keys()) == ["a"]


def test_cleanup_top_topics_cache_removes_expired():
    """超上限时清除过期条目"""
    now = time.time()
    cache = {f"k{i}": (now, []) for i in range(70)}
    for i in range(10):
        cache[f"k{i}"] = (now - ro._TOP_TOPICS_CACHE_TTL - 1, [])
    ro._cleanup_top_topics_cache(cache)
    assert len(cache) == 60


def test_cleanup_top_topics_cache_trims_to_max_entries():
    """过期清理后仍超两倍上限，按时间戳淘汰到上限"""
    now = time.time()
    cache = {f"k{i}": (now + i, []) for i in range(200)}
    ro._cleanup_top_topics_cache(cache)
    assert len(cache) == ro._TOP_TOPICS_CACHE_MAX_ENTRIES


def test_invalidate_top_topics_cache_with_topic_weight_cache():
    """接入 TopicWeightCache 时一并失效并清除用户缓存键"""
    class _TWC:
        def __init__(self):
            self.invalidated = 0

        def invalidate(self):
            self.invalidated += 1

    twc = _TWC()
    mgr = _FakeManager(_topic_weight_cache=twc)
    mgr._top_topics_cache = {"u1": (1.0, []), "other": (1.0, [])}
    ro.invalidate_top_topics_cache(mgr)
    assert twc.invalidated == 1
    assert "u1" not in mgr._top_topics_cache
    assert "other" in mgr._top_topics_cache


def test_invalidate_top_topics_cache_without_topic_weight_cache():
    """无 TopicWeightCache 时只清除用户缓存键，不抛异常"""
    mgr = _FakeManager()
    mgr._top_topics_cache = {}
    ro.invalidate_top_topics_cache(mgr)
    assert mgr._top_topics_cache == {}


# --------------------------------------------------------------------------- #
# get_top_topics
# --------------------------------------------------------------------------- #
def test_get_top_topics_cache_hit():
    """缓存命中且长度足够时直接返回切片"""
    now = time.time()
    mgr = _FakeManager()
    mgr._top_topics_cache = {"u1": (now, [("a", 3.0), ("b", 2.0), ("c", 1.0)])}
    res = ro.get_top_topics(mgr, limit=2)
    assert res == [("a", 3.0), ("b", 2.0)]


def test_get_top_topics_cache_expired_recomputes():
    """缓存过期时重新计算并写回缓存与 topic_weights"""
    mgr = _FakeManager()
    mgr._top_topics_cache = {"u1": (time.time() - ro._TOP_TOPICS_CACHE_TTL - 1, [("old", 1.0)])}
    mgr.weighted_memories = {
        "m1": _memory("m1", weight=5.0, topics=["alpha", "  ", "beta"]),
        "m2": _memory("m2", weight=2.0, topics=["beta"]),
    }
    res = ro.get_top_topics(mgr, limit=5)
    assert res[0] == ("beta", 7.0)
    assert mgr.topic_weights["beta"] == 7.0
    assert "u1" in mgr._top_topics_cache


def test_get_top_topics_cache_short_result_recomputes():
    """缓存结果条数不足 limit 时重新计算"""
    now = time.time()
    mgr = _FakeManager()
    mgr._top_topics_cache = {"u1": (now, [("only", 1.0)])}
    mgr.weighted_memories = {
        "m1": _memory("m1", weight=1.0, topics=["x"]),
        "m2": _memory("m2", weight=1.0, topics=["y"]),
    }
    res = ro.get_top_topics(mgr, limit=2)
    assert len(res) == 2


# --------------------------------------------------------------------------- #
# search_by_similarity
# --------------------------------------------------------------------------- #
def test_search_by_similarity_disabled_uses_weighted_memories():
    """向量关闭时直接走 get_weighted_memories"""
    mgr = _FakeManager()
    logger = _FakeLogger()
    res = ro.search_by_similarity(
        mgr, query="q", vector_search_enabled=False,
        embedding_generator=_FakeEmbeddingGenerator(), logger=logger,
    )
    assert res[0]["id"] == "gm"
    assert logger.warnings


def test_search_by_similarity_empty_query_returns_empty():
    """空查询返回空列表"""
    res = ro.search_by_similarity(
        _FakeManager(), query="", vector_search_enabled=True,
        embedding_generator=_FakeEmbeddingGenerator(), logger=_FakeLogger(),
    )
    assert res == []


def test_search_by_similarity_query_embedding_error_returns_empty():
    """查询嵌入生成失败返回空列表并记录 error"""
    def _boom(text):
        raise RuntimeError("boom")

    logger = _FakeLogger()
    res = ro.search_by_similarity(
        _FakeManager(), query="q", vector_search_enabled=True,
        embedding_generator=_FakeEmbeddingGenerator(generate=_boom), logger=logger,
    )
    assert res == []
    assert logger.errors


def test_search_by_similarity_cpp_indexer_success():
    """存在 C++ 索引器时优先使用其结果"""
    class _Res:
        def __init__(self, mid):
            self.id = mid
            self.similarity = 0.8
            self.final_score = 0.7

    class _Indexer:
        def search(self, **kwargs):
            return [_Res("m1"), _Res("missing")]

    mgr = _FakeManager(vector_indexer=_Indexer())
    mgr.weighted_memories = {"m1": _memory("m1", weight=1.0)}
    res = ro.search_by_similarity(
        mgr, query="q", vector_search_enabled=True,
        embedding_generator=_FakeEmbeddingGenerator(), logger=_FakeLogger(),
    )
    assert len(res) == 1
    assert res[0]["similarity_score"] == 0.8
    assert res[0]["weighted_score"] == 0.7


def test_search_by_similarity_cpp_indexer_failure_falls_back():
    """C++ 索引器抛异常时回退 Python 原生检索"""
    class _Indexer:
        def search(self, **kwargs):
            raise RuntimeError("cpp fail")

    mgr = _FakeManager(vector_indexer=_Indexer())
    mgr.weighted_memories = {"m1": _memory("m1", embedding="b64", weight=4.0)}
    logger = _FakeLogger()
    res = ro.search_by_similarity(
        mgr, query="q", min_similarity=0.0, vector_search_enabled=True,
        embedding_generator=_FakeEmbeddingGenerator(), logger=logger,
    )
    assert [r["id"] for r in res] == ["m1"]
    assert logger.errors
    assert "weighted_score" in res[0]


def test_search_by_similarity_python_filters():
    """Python 原生检索：min_weight / source / topics / 无嵌入 过滤生效"""
    mgr = _FakeManager()
    mgr.weighted_memories = {
        "m1": _memory("m1", embedding="b1", weight=1.0, source="chat", topics=["t1"]),
        "m2": _memory("m2", embedding="b2", weight=9.0, source="chat", topics=["t1"]),
        "m3": _memory("m3", embedding="b3", weight=9.0, source="other", topics=["t1"]),
        "m4": _memory("m4", embedding="b4", weight=9.0, source="chat", topics=["zzz"]),
        "m5": _memory("m5", weight=9.0, source="chat", topics=["t1"]),  # 无 embedding
    }
    res = ro.search_by_similarity(
        mgr, query="q", min_similarity=0.0, min_weight=5.0, source="chat",
        topics=["t1"], vector_search_enabled=True,
        embedding_generator=_FakeEmbeddingGenerator(), logger=_FakeLogger(),
    )
    assert [r["id"] for r in res] == ["m2"]


def test_search_by_similarity_skips_low_similarity_and_exceptions():
    """相似度低于阈值被跳过；单条计算抛异常被吞"""
    def _cosine(a, b):
        if b is None:
            raise RuntimeError("boom")
        return 0.1

    mgr = _FakeManager()
    mgr.weighted_memories = {"m1": _memory("m1", embedding="b1", weight=1.0)}
    res = ro.search_by_similarity(
        mgr, query="q", min_similarity=0.9, vector_search_enabled=True,
        embedding_generator=_FakeEmbeddingGenerator(cosine=_cosine), logger=_FakeLogger(),
    )
    assert res == []


def test_search_by_similarity_skips_memory_with_bad_weight():
    """单条记忆权重非法（float 转换抛异常）时被吞掉，不影响整体返回"""
    mgr = _FakeManager()
    mgr.weighted_memories = {"m1": _memory("m1", embedding="b1", weight="not-a-number")}
    res = ro.search_by_similarity(
        mgr, query="q", min_similarity=0.0, min_weight=None, vector_search_enabled=True,
        embedding_generator=_FakeEmbeddingGenerator(), logger=_FakeLogger(),
    )
    assert res == []


# --------------------------------------------------------------------------- #
# hybrid_search_memories / search_semantic_memories
# --------------------------------------------------------------------------- #
def test_hybrid_search_memories_forwards_arguments(monkeypatch):
    """正确组装并转发所有参数给 hybrid_search，且相似度回调走 manager"""
    captured = {}

    def _fake_hybrid(**kwargs):
        captured.update(kwargs)
        kwargs["search_by_similarity_fn"]("q", limit=1)
        return [{"id": "r"}]

    monkeypatch.setattr(ro, "hybrid_search", _fake_hybrid)
    mgr = _FakeManager()
    res = ro.hybrid_search_memories(
        mgr, query="q", limit=3, min_similarity=0.2, min_weight=1.0,
        keyword_weight=0.4, use_probability=False, emotion="joy", scope="local",
        exclude_categories=["sensitive"], associative_top_k=2, conflict_filter=False,
    )
    assert res == [{"id": "r"}]
    assert mgr.ensure_calls == 1
    assert captured["limit"] == 3
    assert captured["exclude_categories"] == ["sensitive"]
    assert captured["search_by_similarity_fn"] is not None
    assert mgr.sim_calls == 1


def test_search_semantic_memories_filters_types_and_categories(monkeypatch):
    """语义召回过滤 preference/state/sensitive/profile 类型与分类"""
    memories = [
        _memory("ok", memory_type="dialogue", category="learning", weight=5.0, timestamp=1.0),
        _memory("p", memory_type="preference", category="x"),
        _memory("s", memory_type="state", category="x"),
        _memory("sens", memory_type="fact", category="sensitive"),
        _memory("prof", memory_type="profile", category="x"),
        _memory("cat_p", memory_type="fact", category="preference"),
        _memory("cat_s", memory_type="fact", category="state"),
    ]
    monkeypatch.setattr(ro, "hybrid_search_memories", lambda *a, **k: list(memories))
    res = ro.search_semantic_memories(_FakeManager(), query="q", limit=10)
    assert [r["id"] for r in res] == ["ok"]
    assert res[0]["source_layer"] == "semantic_memory"


# --------------------------------------------------------------------------- #
# get_preference_state_memories
# --------------------------------------------------------------------------- #
def test_get_preference_state_memories_without_query():
    """无查询：收集 active 偏好与状态，非 active 偏好被跳过"""
    mgr = _FakeManager()
    mgr.weighted_memories = {
        "p1": _memory("p1", memory_type="preference", status="active", weight=3.0),
        "p2": _memory("p2", category="preference", status="archived", weight=3.0),
        "s1": _memory("s1", memory_type="state", weight=2.0),
        "d1": _memory("d1", memory_type="dialogue", weight=1.0),
    }
    res = ro.get_preference_state_memories(mgr, query=None, limit=10)
    assert [m["id"] for m in res["preferences"]] == ["p1"]
    assert [m["id"] for m in res["state_memories"]] == ["s1"]
    assert res["state_context"] == {"ctx": 1}
    assert res["active_states"]


def test_get_preference_state_memories_with_query_filters_text():
    """有查询：按 content/title/summary/topics 文本过滤，并过滤 active_states"""
    mgr = _FakeManager()
    mgr.weighted_memories = {
        "p1": _memory("p1", memory_type="preference", status="active",
                      content="I like tea", weight=3.0),
        "p2": _memory("p2", memory_type="preference", status="active",
                      content="I like coffee", weight=3.0),
        "s1": _memory("s1", memory_type="state", readable_title="Tea time", weight=2.0),
    }
    mgr.get_active_states = lambda: [
        {"content": "tea active", "status": "active", "type": "t"},
        {"content": "other", "status": "active", "type": "t"},
    ]
    res = ro.get_preference_state_memories(mgr, query="TEA", limit=10)
    assert [m["id"] for m in res["preferences"]] == ["p1"]
    assert [m["id"] for m in res["state_memories"]] == ["s1"]
    assert [s["content"] for s in res["active_states"]] == ["tea active"]


def test_get_preference_state_memories_topics_and_state_category():
    """topics 参与文本匹配；category=state 也归入状态"""
    mgr = _FakeManager()
    mgr.weighted_memories = {
        "s1": _memory("s1", category="state", topics=["learning"], weight=1.0),
    }
    mgr.get_active_states = lambda: []
    res = ro.get_preference_state_memories(mgr, query="learning", limit=10)
    assert [m["id"] for m in res["state_memories"]] == ["s1"]
    assert res["active_states"] == []


# --------------------------------------------------------------------------- #
# build_recall_bundle
# --------------------------------------------------------------------------- #
def test_build_recall_bundle_assembles_sections(monkeypatch):
    """召回包组装：透传语义记忆、偏好状态与 history_limit"""
    monkeypatch.setattr(ro, "search_semantic_memories", lambda *a, **k: [{"id": "sem"}])
    monkeypatch.setattr(ro, "get_preference_state_memories", lambda *a, **k: {"preferences": []})
    bundle = ro.build_recall_bundle(_FakeManager(), query="q", limit=4, history_limit=12)
    assert bundle["semantic_memories"] == [{"id": "sem"}]
    assert bundle["preference_state"] == {"preferences": []}
    assert bundle["history_limit"] == 12
