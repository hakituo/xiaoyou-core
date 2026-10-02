"""
短期记忆持久化测试

原实现直接写项目 history 目录（污染真实用户数据），
并依赖 time.sleep(3) 等待异步保存线程。现在改为：
- 目录重定向到 tmp_path
- 等后台加载完成后再写入，避免被延迟加载线程清空
- 用 sync_save_memory 同步落盘，去掉 sleep
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import memory.weighted_memory_manager as wmm

TEST_USER_ID = "test_user_persistence"


@pytest.fixture
def manager(tmp_path, monkeypatch):
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
        user_id=TEST_USER_ID,
        max_short_term=2,  # 很小的窗口，用于触发修剪
        auto_save_interval=0,
        skip_auto_reclassify=True,
    )
    # 后台延迟加载会用磁盘数据覆盖内存，必须等它结束后再写入测试数据
    assert mgr.ensure_data_loaded(timeout=30.0), "后台数据加载应在超时前完成"
    return mgr


def _find_in_weighted_files(weighted_dir, content):
    for file_path in weighted_dir.rglob(f"{TEST_USER_ID}_weighted.json"):
        if content in file_path.read_text(encoding="utf-8"):
            return file_path
    return None


def test_trivial_memory_is_persisted_as_short_term(manager):
    """琐碎记忆先进短期记忆，并随同步保存落到 short_term 文件"""
    content = "trivial_persistence_marker"
    manager.add_memory(content, role="user")

    assert any(
        mem.get("content") == content for mem in manager.short_term_memory
    ), "琐碎记忆应进入短期记忆"

    manager.sync_save_memory()

    short_file = manager.short_term_dir / f"{TEST_USER_ID}_short.json"
    assert short_file.exists(), f"短期记忆文件应存在: {short_file}"
    assert content in short_file.read_text(encoding="utf-8"), "琐碎记忆应落到短期记忆文件"


def test_trimming_safety(manager):
    """短期记忆被修剪后，内容仍保留在权重记忆中"""
    for text in ("msg1", "msg2", "msg3"):
        manager.add_memory(text, role="user")

    manager._trim_short_term_memory()

    assert len(manager.short_term_memory) <= 2
    assert any(
        mem.get("content") == "msg1" for mem in manager.weighted_memories.values()
    ), "被修剪的记忆必须仍存在于 weighted_memories"
