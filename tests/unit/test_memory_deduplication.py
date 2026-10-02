"""记忆去重与长期记忆落盘契约测试

这三个用例原来是"真单测"外衣下的集成测试：直接写项目 history 目录，
会污染真实用户数据，且依赖后台线程 + BERT 重分类，单次写锁等待可达 10 秒。
现在改为：
- 通过 monkeypatch 把记忆目录重定向到 tmp_path，不再落盘到真实 history
- 落盘契约仍走真实的 WeightedMemoryManager 保存链路
- 去重与迁移契约改为直接调用 memory.core 下的纯函数，毫秒级、无后台线程
"""

import asyncio
import json
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import memory.weighted_memory_manager as wmm
from memory.core.history_ops import get_recent_history as get_recent_history_impl
from memory.core.lifecycle_ops import migrate_legacy_data

TEST_USER_ID = "test_user_dedup"


@pytest.fixture
def memory_root(tmp_path, monkeypatch):
    """把记忆管理器的目录根重定向到临时目录

    注意：只能改 HISTORY_DIR，不能同时把 DEFAULT_HISTORY_DIR 也指向临时目录。
    build_memory_layout 用"当前目录 != 默认目录"判断是否为外部指定目录，
    两者相等时会回落到 get_memories_dir_for_conversation() 的真实用户目录。
    """
    root = tmp_path / "history"
    monkeypatch.setattr(wmm, "HISTORY_DIR", root)
    monkeypatch.setattr(wmm, "LONG_TERM_DIR", root / "long_term")
    monkeypatch.setattr(wmm, "WEIGHTED_MEMORY_DIR", root / "weighted")
    monkeypatch.setattr(wmm, "SHORT_TERM_DIR", root / "short_term")
    monkeypatch.setattr(wmm, "SENSITIVE_DIR", root / "sensitive")
    monkeypatch.setattr(wmm, "READABLE_DIR", root / "readable")
    return root


def _make_manager():
    """构造一个不做后台自动保存、不触发 BERT 重分类的记忆管理器"""
    manager = wmm.WeightedMemoryManager(
        user_id=TEST_USER_ID,
        auto_save_interval=0,
        skip_auto_reclassify=True,
    )
    assert manager.ensure_data_loaded(timeout=30.0), "后台数据加载应在超时前完成"
    return manager


class _FakeManager:
    """只提供纯函数所需属性的记忆管理器替身"""

    def __init__(self, short_term=None, weighted=None):
        self.user_id = TEST_USER_ID
        self.lock = threading.RLock()
        self._use_rw_lock = False
        self.short_term_memory = short_term if short_term is not None else []
        self.weighted_memories = weighted if weighted is not None else {}


def test_no_long_term_file_creation(memory_root):
    """长期记忆只写入 weighted 分类目录，不再生成 long_term 文件"""
    manager = _make_manager()

    manager.add_memory(
        content="This is a very important memory that should be weighted.",
        role="user",
        is_important=True,
        topics=["test"],
        category="test",
    )
    # save_memory 只排程异步保存，这里用同步落盘保证断言前文件已写出
    manager.sync_save_memory()

    long_file = manager.long_term_dir / f"{manager.user_id}_long.json"
    weighted_file = manager.weighted_memory_dir / "test" / f"{manager.user_id}_weighted.json"

    assert not long_file.exists(), "不应再生成 long_term 文件"
    assert weighted_file.exists(), f"权重记忆应写入分类目录: {weighted_file}"

    data = json.loads(weighted_file.read_text(encoding="utf-8"))
    assert any(
        m.get("content") == "This is a very important memory that should be weighted."
        for m in data.get("weighted_memories", [])
    )


def test_get_recent_history_dedupes_same_memory_id():
    """同一条记忆同时存在于短期与权重记忆时，只返回一次"""
    now = time.time()
    memory = {
        "id": "dup_id_1",
        "role": "user",
        "content": "Duplication test message",
        "timestamp": now,
        "category": "chat",
    }
    manager = _FakeManager(
        short_term=[dict(memory)],
        weighted={"dup_id_1": dict(memory)},
    )

    history = asyncio.run(get_recent_history_impl(manager, limit=10))

    count = sum(1 for m in history if m["content"] == "Duplication test message")
    assert count == 1, f"同一条记忆应只出现一次，实际 {count} 次"


def test_get_recent_history_dedupes_repeated_content():
    """8 秒窗口内重复出现的相同内容只保留一条"""
    now = time.time()
    messages = [
        {
            "id": "m1",
            "role": "user",
            "content": "重复内容",
            "timestamp": now,
            "category": "chat",
        },
        {
            "id": "m2",
            "role": "user",
            "content": "重复内容",
            "timestamp": now + 3,
            "category": "chat",
        },
        {
            "id": "m3",
            "role": "user",
            "content": "重复内容",
            "timestamp": now + 60,
            "category": "chat",
        },
    ]
    manager = _FakeManager(short_term=messages)

    history = asyncio.run(get_recent_history_impl(manager, limit=10))

    assert [m["id"] for m in history] == ["m1", "m3"]


def test_migration_legacy_data(tmp_path):
    """旧 long_term 数据会被迁移进权重记忆，并把原文件重命名为 .bak"""
    long_term_dir = tmp_path / "long_term"
    long_term_dir.mkdir(parents=True)

    legacy_data = [
        {
            "id": "legacy_1",
            "content": "Legacy memory 1",
            "role": "user",
            "timestamp": time.time(),
            "topics": ["legacy"],
        }
    ]
    long_file = long_term_dir / f"{TEST_USER_ID}_long.json"
    long_file.write_text(json.dumps(legacy_data, ensure_ascii=False), encoding="utf-8")

    saved = {}

    class _MigrationManager(_FakeManager):
        def __init__(self):
            super().__init__(weighted={})
            self.long_term_dir = long_term_dir
            self.legacy_long_term_dir = long_term_dir
            self.category_index = defaultdict(list)

        def _save_weighted_data_locked(self):
            saved["called"] = True

    manager = _MigrationManager()
    migrate_legacy_data(manager, encoding="utf-8")

    assert "legacy_1" in manager.weighted_memories, "旧记忆应迁移进权重记忆"
    migrated = manager.weighted_memories["legacy_1"]
    assert migrated.get("weight") == 1.0, "缺失的权重应补默认值"
    assert migrated.get("category") == "legacy", "缺失的分类应由 topics 推导"

    backup_file = long_term_dir / f"{TEST_USER_ID}_long.json.bak"
    assert not long_file.exists(), "原 long_term 文件应被重命名"
    assert backup_file.exists(), "应保留 .bak 备份"
    assert saved.get("called") is True, "迁移后应立即落盘"


def test_migration_skips_when_no_legacy_file(tmp_path):
    """没有旧长期记忆文件时不应产生任何副作用"""
    empty_dir = tmp_path / "empty_long_term"
    empty_dir.mkdir(parents=True)

    manager = _FakeManager(weighted={})
    manager.long_term_dir = empty_dir
    manager.legacy_long_term_dir = empty_dir

    migrate_legacy_data(manager, encoding="utf-8")

    assert manager.weighted_memories == {}
