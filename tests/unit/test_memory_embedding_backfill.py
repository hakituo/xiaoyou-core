"""缺失 embedding 补算「不阻塞启动 + 不跨锁推理」的确定性回归。

背景：补算会触发嵌入模型加载与 ORT/CUDA 首次推理（实测 42s，稳态单条仅 7ms），
旧实现把整段包在写锁里跑在 `_deferred_load` 关键路径上，导致
`ensure_data_loaded(timeout=30)` 超时放行、首轮对话拿不到记忆。

本文件锁定两条契约：
1. 加载期只做零成本预检，真正的补算延后到数据就绪之后（`_pending_embedding_backfill`）；
2. 补算函数推理期间**不持有写锁**，因此可以安全地放到后台线程。
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from pathlib import Path

from memory.core import io_ops, vector_ops
from memory.weighted_memory_manager import WeightedMemoryManager

_LOGGER = logging.getLogger("test_embedding_backfill")


class _StubManager:
    """只提供 `_load_weighted_data_locked` / `generate_missing_embeddings` 用到的接口。"""

    def __init__(self) -> None:
        self.user_id = "stub"
        self.weighted_memories: dict = {}
        self.category_index = defaultdict(list)
        self.topic_weights = defaultdict(float)
        self.topics = defaultdict(list)
        self.emotion_memory_map = defaultdict(list)
        self.content_dedupe_index: dict = {}
        self.important_prompts: list = []
        self.legacy_weighted_dir = None
        # 普通 Lock（非 RLock）：推理期间若仍持锁，非阻塞 acquire 会失败
        self.lock = threading.Lock()
        self._use_rw_lock = False
        self.backfill_calls = 0
        self.scheduled_saves = 0

    def _hydrate_weighted_memory_record(self, memory):
        return memory

    def _normalize_memory_record(self, memory):
        return memory, False

    def _update_topic_index(self) -> None:
        return None

    def _rebuild_preference_index_locked(self) -> None:
        return None

    def _schedule_save(self) -> None:
        self.scheduled_saves += 1

    def generate_missing_embeddings(self) -> int:
        self.backfill_calls += 1
        return 0


class _FakeGenerator:
    def __init__(self, manager: _StubManager) -> None:
        self.manager = manager
        self.infer_calls = 0
        self.lock_held_during_infer = False

    def ensure_model_loaded(self) -> None:
        return None

    def generate_embedding(self, text: str):
        self.infer_calls += 1
        # 推理期间必须已经释放写锁：拿不到就说明补算还跨着锁跑
        if not self.manager.lock.acquire(blocking=False):
            self.lock_held_during_infer = True
        else:
            self.manager.lock.release()
        return [0.1, 0.2]

    def embedding_to_base64(self, embedding) -> str:
        return "encoded"


def _write_weighted_file(root: Path, user_id: str, memories: list) -> None:
    (root / f"{user_id}_weighted.json").write_text(
        json.dumps({"weighted_memories": memories}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_load_defers_missing_embedding_backfill(tmp_path):
    """加载期不得直接跑补算，只记录待补算条数。"""
    manager = _StubManager()
    _write_weighted_file(
        tmp_path, manager.user_id, [{"id": "m1", "content": "你好", "timestamp": 1.0}]
    )

    io_ops._load_weighted_data_locked(
        manager,
        weighted_memory_dir=tmp_path,
        default_encoding="utf-8",
        logger=_LOGGER,
    )

    assert manager.backfill_calls == 0, "加载期不应同步执行 embedding 补算"
    assert manager._pending_embedding_backfill == 1


def test_load_records_zero_when_everything_has_embedding(tmp_path):
    manager = _StubManager()
    _write_weighted_file(
        tmp_path,
        manager.user_id,
        [{"id": "m1", "content": "你好", "timestamp": 1.0, "embedding": "b64"}],
    )

    io_ops._load_weighted_data_locked(
        manager,
        weighted_memory_dir=tmp_path,
        default_encoding="utf-8",
        logger=_LOGGER,
    )

    assert manager.backfill_calls == 0
    assert manager._pending_embedding_backfill == 0


def test_generate_missing_embeddings_does_not_hold_write_lock_while_inferring():
    manager = _StubManager()
    manager.weighted_memories = {"m1": {"id": "m1", "content": "你好"}}
    generator = _FakeGenerator(manager)

    count = vector_ops.generate_missing_embeddings(
        manager,
        vector_search_enabled=True,
        embedding_generator=generator,
        logger=_LOGGER,
    )

    assert count == 1
    assert generator.infer_calls == 1
    assert generator.lock_held_during_infer is False
    assert manager.weighted_memories["m1"]["embedding"] == "encoded"
    assert manager.scheduled_saves == 1


def test_generate_missing_embeddings_skips_empty_content_and_existing_embeddings():
    manager = _StubManager()
    manager.weighted_memories = {
        "empty": {"id": "empty", "content": ""},
        "has": {"id": "has", "content": "已有", "embedding": "b64"},
        "need": {"id": "need", "content": "缺失"},
    }
    generator = _FakeGenerator(manager)

    count = vector_ops.generate_missing_embeddings(
        manager,
        vector_search_enabled=True,
        embedding_generator=generator,
        logger=_LOGGER,
    )

    assert count == 1
    assert generator.infer_calls == 1
    assert "embedding" not in manager.weighted_memories["empty"]


def test_generate_missing_embeddings_rechecks_before_writeback():
    """推理期间记录已被其它线程补上时，回写阶段不得覆盖。"""
    manager = _StubManager()
    manager.weighted_memories = {"m1": {"id": "m1", "content": "你好"}}
    generator = _FakeGenerator(manager)

    original = generator.generate_embedding

    def racing(text: str):
        manager.weighted_memories["m1"]["embedding"] = "其它线程写入"
        return original(text)

    generator.generate_embedding = racing

    count = vector_ops.generate_missing_embeddings(
        manager,
        vector_search_enabled=True,
        embedding_generator=generator,
        logger=_LOGGER,
    )

    assert count == 0
    assert manager.weighted_memories["m1"]["embedding"] == "其它线程写入"


def test_generate_missing_embeddings_returns_zero_without_pending():
    manager = _StubManager()
    generator = _FakeGenerator(manager)

    assert (
        vector_ops.generate_missing_embeddings(
            manager,
            vector_search_enabled=True,
            embedding_generator=generator,
            logger=_LOGGER,
        )
        == 0
    )
    assert generator.infer_calls == 0


def test_run_pending_embedding_backfill_is_idempotent():
    manager = _StubManager()

    # 没有待补算 → 不触发
    assert WeightedMemoryManager.run_pending_embedding_backfill(manager) == 0
    assert manager.backfill_calls == 0

    manager._pending_embedding_backfill = 3
    assert WeightedMemoryManager.run_pending_embedding_backfill(manager) == 0
    assert manager.backfill_calls == 1
    # 标记已清零：重复调用不再触发
    assert WeightedMemoryManager.run_pending_embedding_backfill(manager) == 0
    assert manager.backfill_calls == 1
