"""``memory.core.batch_ops`` 批量操作 API 单元测试。

设计要点：
- 全部使用纯替身对象（``_FakeManager``）驱动被测函数，不加载真实记忆后端、
  不落盘、不联网，因此可稳定复跑。
- 涉及 ``rebuild_memory_indexes_locked`` 的用例默认打桩为 spy，只断言"是否被
  调用、调用几次、参数是谁"；另有一个用例让真实实现跑一遍，验证端到端接线。
- 时钟通过替换 ``batch_ops._time`` 固定，绝不断言真实流逝时间。
"""

from __future__ import annotations

import logging
import sys
import threading
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import memory.core.batch_ops as batch_ops
import memory.core.record_ops as record_ops


# ---------------------------------------------------------------------------
# 替身对象
# ---------------------------------------------------------------------------

class _FakeTopicWeightCache:
    """记录 update_topic / remove_topic 调用的主题权重缓存替身。"""

    def __init__(self):
        self.updates = []
        self.removals = []

    def update_topic(self, topic, weight_delta, timestamp):
        self.updates.append((topic, weight_delta, timestamp))

    def remove_topic(self, topic, weight_delta):
        self.removals.append((topic, weight_delta))


class _FakeVectorIndexer:
    """可注入失败的 C++ 向量索引替身。"""

    def __init__(self, fail=False):
        self.removed = []
        self._fail = fail

    def removeRecord(self, memory_id):  # noqa: N802 - 对齐真实 C++ 绑定命名
        if self._fail:
            raise RuntimeError("cpp index unavailable")
        self.removed.append(memory_id)


class _FakeRWLock:
    """记录读/写锁获取次数的读写锁替身。"""

    def __init__(self):
        self.reads = 0
        self.writes = 0

    @contextmanager
    def read_lock(self):
        self.reads += 1
        yield

    @contextmanager
    def write_lock(self):
        self.writes += 1
        yield


class _FakeManager:
    """记忆管理器替身：只暴露 batch_ops 会触碰的属性与方法。"""

    def __init__(
        self,
        weighted=None,
        *,
        use_rw_lock=False,
        enable_optimizations=True,
        with_topic_cache=False,
        with_keyword_remover=False,
        vector_indexer=None,
        search_impl=None,
    ):
        self.lock = threading.RLock()
        self._use_rw_lock = use_rw_lock
        if use_rw_lock:
            self._rw_lock = _FakeRWLock()
        self.weighted_memories = dict(weighted or {})
        self._enable_optimizations = enable_optimizations

        if with_topic_cache:
            self._topic_weight_cache = _FakeTopicWeightCache()

        self.keyword_removals = []
        if with_keyword_remover:
            # 实例属性函数：调用时不会隐式绑定 self，签名与生产代码一致。
            self._remove_memory_from_keyword_index_locked = (
                lambda memory_id, mem: self.keyword_removals.append((memory_id, mem))
            )

        self.vector_indexer = vector_indexer

        self.add_calls = []
        self.save_count = 0
        self.topic_index_updates = 0
        self.preference_index_rebuilds = 0
        self.search_calls = []
        self.search_impl = search_impl or (lambda query: [{"id": query}])

    # --- batch_add_memories 依赖 ---
    def add_memory(self, **kwargs):
        self.add_calls.append(dict(kwargs))
        if kwargs.get("_raise"):
            raise RuntimeError("add_memory 故意失败")
        if "_return" in kwargs:
            return kwargs["_return"]
        return kwargs.get("content") or f"mem-{len(self.add_calls)}"

    # --- 落盘调度 ---
    def _schedule_save(self):
        self.save_count += 1

    # --- batch_search_memories 依赖 ---
    def search_memories(self, query, limit, min_similarity, category):
        self.search_calls.append(
            {
                "query": query,
                "limit": limit,
                "min_similarity": min_similarity,
                "category": category,
            }
        )
        return self.search_impl(query)

    # --- 真实 rebuild_memory_indexes_locked 需要的钩子 ---
    def _update_topic_index(self):
        self.topic_index_updates += 1

    def _rebuild_preference_index_locked(self):
        self.preference_index_rebuilds += 1


class _FixedTime:
    """固定时钟替身，避免断言真实流逝时间。"""

    def __init__(self, value):
        self._value = value

    def time(self):
        return self._value


# ---------------------------------------------------------------------------
# batch_add_memories
# ---------------------------------------------------------------------------

def test_batch_add_empty_items_returns_empty_without_side_effects():
    """空输入直接返回空列表，不调用 add_memory、不调度落盘。"""
    manager = _FakeManager()

    assert batch_ops.batch_add_memories(manager, []) == []
    assert manager.add_calls == []
    assert manager.save_count == 0


def test_batch_add_all_success_schedules_exactly_one_save():
    """全部成功时返回各 ID，且 N 次添加只调度 1 次落盘。"""
    manager = _FakeManager()

    results = batch_ops.batch_add_memories(
        manager,
        [{"content": "a"}, {"content": "b"}, {"content": "c"}],
    )

    assert results == ["a", "b", "c"]
    assert len(manager.add_calls) == 3
    assert manager.save_count == 1


def test_batch_add_exception_appends_none_and_skips_save():
    """单条抛异常时该位置为 None，全部失败则不调度落盘。"""
    manager = _FakeManager()

    results = batch_ops.batch_add_memories(
        manager,
        [{"content": "boom", "_raise": True}],
    )

    assert results == [None]
    assert manager.save_count == 0


def test_batch_add_falsy_id_does_not_schedule_save():
    """add_memory 返回假值（空串）时不触发落盘。"""
    manager = _FakeManager()

    results = batch_ops.batch_add_memories(manager, [{"_return": ""}])

    assert results == [""]
    assert manager.save_count == 0


def test_batch_add_mixed_results_still_schedules_once():
    """成功 / 异常 / 假值混合时，只要有 1 条成功就调度 1 次落盘。"""
    manager = _FakeManager()

    results = batch_ops.batch_add_memories(
        manager,
        [
            {"content": "ok"},
            {"content": "boom", "_raise": True},
            {"_return": ""},
        ],
    )

    assert results == ["ok", None, ""]
    assert manager.save_count == 1


def test_batch_add_uses_rw_write_lock_when_enabled():
    """启用读写锁时走 _rw_lock.write_lock()，全程只取 1 次写锁。"""
    manager = _FakeManager(use_rw_lock=True)

    batch_ops.batch_add_memories(manager, [{"content": "x"}, {"content": "y"}])

    assert manager._rw_lock.writes == 1


# ---------------------------------------------------------------------------
# batch_delete_memories
# ---------------------------------------------------------------------------

@pytest.fixture
def rebuild_spy(monkeypatch):
    """把 rebuild_memory_indexes_locked 换成 spy，避免耦合重建实现细节。"""
    calls = []

    def _spy(manager):
        calls.append(manager)

    monkeypatch.setattr(record_ops, "rebuild_memory_indexes_locked", _spy)
    return calls


def test_batch_delete_empty_ids_returns_empty():
    """空输入返回空列表。"""
    manager = _FakeManager()

    assert batch_ops.batch_delete_memories(manager, []) == []
    assert manager.save_count == 0


def test_batch_delete_missing_id_returns_false_without_rebuild(rebuild_spy):
    """ID 不存在时返回 False，且不触发索引重建 / 落盘。"""
    manager = _FakeManager(weighted={})

    results = batch_ops.batch_delete_memories(manager, ["nope"])

    assert results == [False]
    assert rebuild_spy == []
    assert manager.save_count == 0


def test_batch_delete_success_removes_entry_rebuilds_and_saves(rebuild_spy):
    """成功删除：条目被移除、重建索引 1 次、调度落盘 1 次。"""
    manager = _FakeManager(weighted={"m1": {"content": "hi"}})

    results = batch_ops.batch_delete_memories(manager, ["m1"])

    assert results == [True]
    assert "m1" not in manager.weighted_memories
    assert rebuild_spy == [manager]
    assert manager.save_count == 1


def test_batch_delete_updates_topic_cache_when_enabled(rebuild_spy):
    """启用优化且存在主题缓存时，按记忆权重递减每个主题。"""
    manager = _FakeManager(
        weighted={"m1": {"topics": ["a", "b"], "weight": 0.5}},
        with_topic_cache=True,
    )

    results = batch_ops.batch_delete_memories(manager, ["m1"])

    assert results == [True]
    assert manager._topic_weight_cache.removals == [("a", 0.5), ("b", 0.5)]


def test_batch_delete_skips_topic_cache_when_optimizations_disabled(rebuild_spy):
    """关闭优化开关时，即使有主题缓存也不更新。"""
    manager = _FakeManager(
        weighted={"m1": {"topics": ["a"], "weight": 1.0}},
        with_topic_cache=True,
        enable_optimizations=False,
    )

    batch_ops.batch_delete_memories(manager, ["m1"])

    assert manager._topic_weight_cache.removals == []


def test_batch_delete_without_topic_cache_attribute_still_succeeds(rebuild_spy):
    """管理器没有主题缓存属性时正常删除，不报错。"""
    manager = _FakeManager(weighted={"m1": {"topics": ["a"]}})

    assert batch_ops.batch_delete_memories(manager, ["m1"]) == [True]
    assert not hasattr(manager, "_topic_weight_cache")


def test_batch_delete_calls_keyword_index_remover(rebuild_spy):
    """存在关键词索引移除钩子时，用 (memory_id, mem) 调用它。"""
    mem = {"content": "hi"}
    manager = _FakeManager(weighted={"m1": mem}, with_keyword_remover=True)

    batch_ops.batch_delete_memories(manager, ["m1"])

    assert manager.keyword_removals == [("m1", mem)]


def test_batch_delete_removes_from_vector_indexer(rebuild_spy):
    """存在向量索引时，以字符串 ID 调用 removeRecord。"""
    indexer = _FakeVectorIndexer()
    manager = _FakeManager(weighted={"m1": {"content": "hi"}}, vector_indexer=indexer)

    batch_ops.batch_delete_memories(manager, ["m1"])

    assert indexer.removed == ["m1"]


def test_batch_delete_vector_indexer_failure_is_logged_but_kept_true(rebuild_spy, caplog):
    """C++ 索引删除失败只记 warning，Python 侧仍算删除成功。"""
    indexer = _FakeVectorIndexer(fail=True)
    manager = _FakeManager(weighted={"m1": {"content": "hi"}}, vector_indexer=indexer)

    with caplog.at_level(logging.WARNING, logger="memory.core.batch_ops"):
        results = batch_ops.batch_delete_memories(manager, ["m1"])

    assert results == [True]
    assert any("m1" in record.getMessage() for record in caplog.records)


def test_batch_delete_exception_appends_false(rebuild_spy):
    """循环体内异常被吞掉并记为 False，且不触发重建 / 落盘。"""
    # topics 为不可迭代对象，遍历主题时抛 TypeError。
    manager = _FakeManager(
        weighted={"m1": {"topics": 5, "weight": 1.0}},
        with_topic_cache=True,
    )

    results = batch_ops.batch_delete_memories(manager, ["m1"])

    assert results == [False]
    assert "m1" in manager.weighted_memories  # 异常发生在 del 之前，条目保留
    assert rebuild_spy == []
    assert manager.save_count == 0


def test_batch_delete_partial_results_rebuild_once(rebuild_spy):
    """部分命中时逐个返回结果，只要有一条成功就重建 1 次。"""
    manager = _FakeManager(weighted={"m2": {"content": "hi"}})

    results = batch_ops.batch_delete_memories(manager, ["missing", "m2"])

    assert results == [False, True]
    assert rebuild_spy == [manager]
    assert manager.save_count == 1


def test_batch_delete_real_rebuild_populates_category_index():
    """不替换 rebuild 实现：验证与真实索引重建的端到端接线。"""
    manager = _FakeManager(
        weighted={
            "m1": {"content": "a", "category": "work", "topics": ["t1"], "weight": 0.5},
            "m2": {"content": "b", "category": "life", "topics": ["t2"], "weight": 0.2},
        }
    )

    results = batch_ops.batch_delete_memories(manager, ["m1"])

    assert results == [True]
    assert manager.category_index["work"] == []
    assert manager.category_index["life"] == ["m2"]
    assert manager.save_count == 1
    assert manager.topic_index_updates == 1
    assert manager.preference_index_rebuilds == 1


def test_batch_delete_uses_rw_write_lock_when_enabled(rebuild_spy):
    """启用读写锁时删除路径也只取 1 次写锁。"""
    manager = _FakeManager(
        weighted={"m1": {"content": "hi"}},
        use_rw_lock=True,
    )

    batch_ops.batch_delete_memories(manager, ["m1"])

    assert manager._rw_lock.writes == 1


# ---------------------------------------------------------------------------
# batch_search_memories
# ---------------------------------------------------------------------------

def test_batch_search_empty_queries_returns_empty():
    """空查询列表直接返回空列表。"""
    manager = _FakeManager()

    assert batch_ops.batch_search_memories(manager, []) == []
    assert manager.search_calls == []


def test_batch_search_forwards_parameters_and_collects_results():
    """每个查询的结果按顺序收集，参数原样透传。"""
    manager = _FakeManager(search_impl=lambda query: [{"content": query}])

    results = batch_ops.batch_search_memories(
        manager,
        ["q1", "q2"],
        limit=3,
        min_similarity=0.7,
        category="work",
    )

    assert results == [[{"content": "q1"}], [{"content": "q2"}]]
    assert manager.search_calls == [
        {"query": "q1", "limit": 3, "min_similarity": 0.7, "category": "work"},
        {"query": "q2", "limit": 3, "min_similarity": 0.7, "category": "work"},
    ]


def test_batch_search_uses_default_arguments():
    """未显式传参时使用 limit=10 / min_similarity=0.3 / category=None。"""
    manager = _FakeManager()

    batch_ops.batch_search_memories(manager, ["q"])

    assert manager.search_calls == [
        {"query": "q", "limit": 10, "min_similarity": 0.3, "category": None}
    ]


def test_batch_search_exception_yields_empty_list_for_that_query():
    """单个查询抛异常时该位置为空列表，不影响其他查询。"""

    def _impl(query):
        if query == "bad":
            raise RuntimeError("search 故意失败")
        return [{"content": query}]

    manager = _FakeManager(search_impl=_impl)

    results = batch_ops.batch_search_memories(manager, ["bad", "good"])

    assert results == [[], [{"content": "good"}]]


# ---------------------------------------------------------------------------
# batch_update_weights
# ---------------------------------------------------------------------------

def test_batch_update_empty_updates_returns_empty():
    """空更新列表返回空列表。"""
    manager = _FakeManager()

    assert batch_ops.batch_update_weights(manager, []) == []
    assert manager.save_count == 0


def test_batch_update_missing_id_returns_false_without_save():
    """ID 不存在时返回 False，不调度落盘。"""
    manager = _FakeManager(weighted={})

    results = batch_ops.batch_update_weights(manager, [("nope", 0.5)])

    assert results == [False]
    assert manager.save_count == 0


def test_batch_update_applies_delta_and_stamps_hit_time(monkeypatch):
    """权重按 delta 累加，并写入固定时钟的 last_hit_time。"""
    monkeypatch.setattr(batch_ops, "_time", _FixedTime(1234.5))
    manager = _FakeManager(weighted={"m1": {"weight": 1.0}})

    results = batch_ops.batch_update_weights(manager, [("m1", 0.5)])

    assert results == [True]
    assert manager.weighted_memories["m1"]["weight"] == 1.5
    assert manager.weighted_memories["m1"]["last_hit_time"] == 1234.5
    assert manager.save_count == 1


def test_batch_update_clamps_weight_at_zero(monkeypatch):
    """负 delta 使权重降到 0 以下时被夹到 0.0。"""
    monkeypatch.setattr(batch_ops, "_time", _FixedTime(100.0))
    manager = _FakeManager(weighted={"m1": {"weight": 0.2}})

    batch_ops.batch_update_weights(manager, [("m1", -5.0)])

    assert manager.weighted_memories["m1"]["weight"] == 0.0


def test_batch_update_missing_weight_key_defaults_to_zero(monkeypatch):
    """记忆缺少 weight 字段时按 0.0 起算。"""
    monkeypatch.setattr(batch_ops, "_time", _FixedTime(7.0))
    manager = _FakeManager(weighted={"m1": {}})

    batch_ops.batch_update_weights(manager, [("m1", 0.3)])

    assert manager.weighted_memories["m1"]["weight"] == pytest.approx(0.3)


def test_batch_update_updates_topic_cache_when_enabled(monkeypatch):
    """启用优化且有主题缓存时，按 delta 与命中时间更新每个主题。"""
    monkeypatch.setattr(batch_ops, "_time", _FixedTime(555.0))
    manager = _FakeManager(
        weighted={"m1": {"weight": 1.0, "topics": ["a", "b"]}},
        with_topic_cache=True,
    )

    batch_ops.batch_update_weights(manager, [("m1", 0.25)])

    assert manager._topic_weight_cache.updates == [
        ("a", 0.25, 555.0),
        ("b", 0.25, 555.0),
    ]


def test_batch_update_skips_topic_cache_when_disabled(monkeypatch):
    """关闭优化开关时，即使有主题缓存也不更新。"""
    monkeypatch.setattr(batch_ops, "_time", _FixedTime(1.0))
    manager = _FakeManager(
        weighted={"m1": {"weight": 1.0, "topics": ["a"]}},
        with_topic_cache=True,
        enable_optimizations=False,
    )

    batch_ops.batch_update_weights(manager, [("m1", 0.25)])

    assert manager._topic_weight_cache.updates == []


def test_batch_update_exception_appends_false(monkeypatch):
    """循环体异常被吞掉记为 False，全部失败则不落盘。"""
    monkeypatch.setattr(batch_ops, "_time", _FixedTime(1.0))
    # 值为 list，调用 .get() 抛 AttributeError。
    manager = _FakeManager(weighted={"m1": []})

    results = batch_ops.batch_update_weights(manager, [("m1", 0.5)])

    assert results == [False]
    assert manager.save_count == 0


def test_batch_update_partial_results_schedules_once(monkeypatch):
    """部分命中时逐个返回结果，只要有成功就调度 1 次落盘。"""
    monkeypatch.setattr(batch_ops, "_time", _FixedTime(2.0))
    manager = _FakeManager(weighted={"m2": {"weight": 1.0}})

    results = batch_ops.batch_update_weights(manager, [("missing", 0.1), ("m2", 0.1)])

    assert results == [False, True]
    assert manager.save_count == 1


def test_batch_update_uses_rw_write_lock_when_enabled(monkeypatch):
    """启用读写锁时更新路径只取 1 次写锁。"""
    monkeypatch.setattr(batch_ops, "_time", _FixedTime(3.0))
    manager = _FakeManager(weighted={"m1": {"weight": 1.0}}, use_rw_lock=True)

    batch_ops.batch_update_weights(manager, [("m1", 0.1), ("m1", 0.1)])

    assert manager._rw_lock.writes == 1


def test_batch_update_does_not_share_state_across_calls(monkeypatch):
    """连续调用两次互不影响：weighted_memories 由用例各自构造。"""
    monkeypatch.setattr(batch_ops, "_time", _FixedTime(4.0))
    first = _FakeManager(weighted={"m1": {"weight": 1.0}})
    second = _FakeManager(weighted={"m1": {"weight": 10.0}})

    batch_ops.batch_update_weights(first, [("m1", 1.0)])
    batch_ops.batch_update_weights(second, [("m1", 1.0)])

    assert first.weighted_memories["m1"]["weight"] == 2.0
    assert second.weighted_memories["m1"]["weight"] == 11.0


# ---------------------------------------------------------------------------
# 真实索引重建依赖的最小契约（确保替身与生产接口一致）
# ---------------------------------------------------------------------------

def test_fake_manager_index_containers_are_defaultdicts():
    """替身未预置索引容器，验证 rebuild 会自行创建 defaultdict。"""
    manager = _FakeManager(weighted={"m1": {"content": "a", "category": "c"}})

    record_ops.rebuild_memory_indexes_locked(manager)

    assert isinstance(manager.category_index, defaultdict)
    assert manager.category_index["c"] == ["m1"]
