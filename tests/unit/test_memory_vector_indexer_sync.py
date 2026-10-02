"""加载期「批量同步到 C++ VectorIndexer」的确定性回归（计划 §5 C1/C7）。

锁定三条契约：
1. 扩展提供 `addRecords` 时走批量接口，不再逐条 `addRecord`（避免反复取写锁 +
   反复维护倒排索引，数千条记忆时是加载路径的主要开销之一）；
2. 扩展还是旧版（没有批量接口）时回退逐条调用，行为与之前一致；
3. 被拒记录（向量为空 / 维度不一致）必须留下 warning，而不是静默产生
   "相似度恒为 0"的僵尸向量。
"""

from __future__ import annotations

import logging

from memory.core import io_ops

_LOGGER = logging.getLogger("test_vector_indexer_sync")


class _BatchIndexer:
    """新版扩展：提供 addRecords。"""

    def __init__(self, written: int | None = None) -> None:
        self.batch_calls: list[tuple] = []
        self.single_calls: list[tuple] = []
        self.written = written

    def addRecords(self, ids, embeddings, weights, timestamps, sources, topics_list):
        self.batch_calls.append(
            (list(ids), list(embeddings), list(weights), list(timestamps),
             list(sources), list(topics_list))
        )
        return len(ids) if self.written is None else self.written

    def addRecord(self, *args):
        self.single_calls.append(args)
        return True


class _LegacyIndexer:
    """旧版扩展：只有 addRecord，且返回 None（void）。"""

    def __init__(self, accepted: bool = True) -> None:
        self.single_calls: list[tuple] = []
        self.accepted = accepted

    def addRecord(self, *args):
        self.single_calls.append(args)
        return True if self.accepted else False


class _Manager:
    def __init__(self, memories: dict, indexer) -> None:
        self.weighted_memories = memories
        self._indexer = indexer

    @property
    def vector_indexer(self):
        return self._indexer


def _memory(mid: str, embedding: list[float] | None, **extra) -> dict:
    record = {
        "id": mid,
        "content": "内容",
        "weight": 1.0,
        "timestamp": 100.0,
        "source": "chat",
        "topics": ["日常"],
    }
    if embedding is not None:
        record["embedding"] = embedding
    record.update(extra)
    return record


def test_batch_interface_used_when_available():
    indexer = _BatchIndexer()
    manager = _Manager({"m1": _memory("m1", [0.1, 0.2]), "m2": _memory("m2", [0.3, 0.4])}, indexer)

    io_ops._sync_records_to_vector_indexer(manager, None, _LOGGER)

    assert len(indexer.batch_calls) == 1
    assert indexer.single_calls == []
    ids, embeddings, weights, timestamps, sources, topics_list = indexer.batch_calls[0]
    assert sorted(ids) == ["m1", "m2"]
    assert all(len(item) == 2 for item in embeddings)
    assert weights == [1.0, 1.0]
    assert timestamps == [100.0, 100.0]
    assert sources == ["chat", "chat"]
    assert topics_list == [["日常"], ["日常"]]


def test_falls_back_to_single_calls_for_legacy_extension():
    indexer = _LegacyIndexer()
    manager = _Manager({"m1": _memory("m1", [0.1, 0.2])}, indexer)

    io_ops._sync_records_to_vector_indexer(manager, None, _LOGGER)

    assert len(indexer.single_calls) == 1
    assert indexer.single_calls[0][0] == "m1"


def test_records_without_embedding_are_skipped():
    indexer = _BatchIndexer()
    manager = _Manager(
        {
            "no_emb": _memory("no_emb", None),
            "empty_emb": _memory("empty_emb", []),
            "ok": _memory("ok", [0.1, 0.2]),
        },
        indexer,
    )

    io_ops._sync_records_to_vector_indexer(manager, None, _LOGGER)

    assert indexer.batch_calls[0][0] == ["ok"]


def test_nothing_to_sync_does_not_touch_indexer():
    indexer = _BatchIndexer()
    manager = _Manager({}, indexer)

    io_ops._sync_records_to_vector_indexer(manager, None, _LOGGER)

    assert indexer.batch_calls == []
    assert indexer.single_calls == []


def test_rejected_records_are_warned(caplog):
    indexer = _BatchIndexer(written=1)
    manager = _Manager(
        {"m1": _memory("m1", [0.1, 0.2]), "m2": _memory("m2", [0.1, 0.2, 0.3])},
        indexer,
    )

    with caplog.at_level(logging.WARNING):
        io_ops._sync_records_to_vector_indexer(manager, None, _LOGGER)

    assert any("批量写入被拒" in record.message for record in caplog.records)


def test_batch_failure_falls_back_to_single_calls(caplog):
    class _BrokenBatch(_BatchIndexer):
        def addRecords(self, *args, **kwargs):
            raise RuntimeError("boom")

    indexer = _BrokenBatch()
    manager = _Manager({"m1": _memory("m1", [0.1, 0.2])}, indexer)

    with caplog.at_level(logging.WARNING):
        io_ops._sync_records_to_vector_indexer(manager, None, _LOGGER)

    assert len(indexer.single_calls) == 1
    assert any("回退逐条写入" in record.message for record in caplog.records)


def test_legacy_rejection_is_counted(caplog):
    indexer = _LegacyIndexer(accepted=False)
    manager = _Manager({"m1": _memory("m1", [0.1, 0.2])}, indexer)

    with caplog.at_level(logging.WARNING):
        io_ops._sync_records_to_vector_indexer(manager, None, _LOGGER)

    assert any("拒绝 1 条记录" in record.message for record in caplog.records)
