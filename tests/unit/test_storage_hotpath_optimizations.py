"""P0-P2 存储/检索热路径优化的确定性回归。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from core.agents.chat_agent_components.persona_system.prompt import context_engine
from core.character.people import conversation_source
from core.services.chat_history_store import ChatHistoryStore
from core.services.workspace import history_store as workspace_history_store
from core.tools import search_chat_history_tool
from core.tools.search_chat_history_tool import SearchChatHistoryTool
from core.utils.data import scope_registry


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in events),
        encoding="utf-8",
    )


def _event(eid: str, ts: float, content: str = "消息") -> dict:
    return {
        "event_id": eid,
        "conversation_id": "shared__persona__core_aveline",
        "message_id": eid,
        "event_type": "message",
        "role": "user",
        "content": content,
        "timestamp": ts,
        "metadata": {},
    }


def test_chat_history_append_incrementally_updates_existing_day_index(
    tmp_path, monkeypatch
):
    store = ChatHistoryStore(tmp_path)
    now = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)
    store.append_event(
        conversation_id="shared__persona__core_aveline",
        role="user",
        content="第一条",
        message_id="m1",
        now_dt=now,
    )

    day_dir = tmp_path / "2026" / "09" / "17"
    index_path = day_dir / "index.json"
    first = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(first["files"]) == 1

    def fail_full_rebuild(*_args, **_kwargs):
        raise AssertionError("已有有效 index 时不应再次全量 rglob 重建")

    monkeypatch.setattr(store, "_write_day_index", fail_full_rebuild)
    store.append_event(
        conversation_id="shared__persona__core_ling",
        role="assistant",
        content="第二条",
        message_id="m2",
        now_dt=now,
    )

    second = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(second["files"]) == 2
    assert {item["conversation_id"] for item in second["files"]} == {
        "shared__persona__core_aveline",
        "shared__persona__core_ling",
    }


def test_recent_events_stops_before_older_day_once_limit_is_satisfied(
    tmp_path, monkeypatch
):
    """锁定文件扫描 fallback 路径的日期早停语义。

    2026-09-17 起 `list_recent_events` 默认走 SQLite 派生索引（一次 SQL 即可），
    按日期倒序的文件扫描退化为索引不可用时的兜底实现。本用例显式关闭索引，
    继续验证兜底路径「够 limit 就不再向旧日期扫描」的行为不回退。
    """
    import core.services.chat_history_index as chat_history_index

    def _boom(*_args, **_kwargs):
        raise RuntimeError("index disabled for baseline")

    monkeypatch.setattr(chat_history_index, "get_history_index", _boom)
    newest = tmp_path / "2026" / "09" / "17"
    older = tmp_path / "2026" / "09" / "16"
    _write_jsonl(
        newest / "lane" / "new.jsonl",
        [_event("n1", 30), _event("n2", 31), _event("n3", 32)],
    )
    _write_jsonl(older / "lane" / "old.jsonl", [_event("o1", 1)])

    visited: list[Path] = []
    original_rglob = Path.rglob

    def tracked_rglob(path: Path, pattern: str):
        visited.append(path)
        return original_rglob(path, pattern)

    monkeypatch.setattr(Path, "rglob", tracked_rglob)
    result = ChatHistoryStore(tmp_path).list_recent_events(limit=2, roles=["user"])

    assert [item["event_id"] for item in result] == ["n2", "n3"]
    assert newest in visited
    assert older not in visited


def test_search_history_scope_scan_uses_shared_tokenizer(tmp_path, monkeypatch):
    history = tmp_path / "2026" / "09" / "17" / "lane" / "history.jsonl"
    _write_jsonl(history, [_event("hit", 1, content="这里包含统一分词命中")])

    calls: list[str] = []

    def fake_tokenizer(query: str) -> list[str]:
        calls.append(query)
        return ["统一分词"]

    monkeypatch.setattr(search_chat_history_tool, "_tokenize_query", fake_tokenizer)
    result = SearchChatHistoryTool()._scan_events(
        search_roots=[tmp_path],
        query="任意中文查询",
        limit=20,
        roles=None,
        before_ts=None,
        after_ts=None,
        scope="",
    )

    assert calls == ["任意中文查询"]
    assert [item["event_id"] for item in result] == ["hit"]


def test_scope_history_scan_excludes_current_conversation_file(tmp_path, monkeypatch):
    tool = SearchChatHistoryTool()
    captured = {}

    # 注意：core.utils 把 core.utils.data_paths 重绑到 sys.modules 后并没有在
    # core.utils 上留下同名属性，所以 monkeypatch 的字符串形式（依赖 getattr）
    # 会 AttributeError。这里直接对真实模块对象打补丁。
    from core.utils.data import data_paths as data_paths_module

    monkeypatch.setattr(
        data_paths_module,
        "get_chat_history_dir_for_conversation",
        lambda _cid: tmp_path,
    )

    def fake_scan_events(**kwargs):
        captured["filter"] = kwargs["file_filter"]
        return []

    monkeypatch.setattr(tool, "_scan_events", fake_scan_events)
    cid = "shared__persona__core_aveline"
    tool._search_in_scope_dir(
        conversation_id=cid,
        query="x",
        limit=20,
        roles=None,
        before_ts=None,
        after_ts=None,
    )

    current = tmp_path / "2026" / "09" / "17" / f"{cid}.jsonl"
    other = tmp_path / "2026" / "09" / "17" / "legacy.jsonl"
    assert captured["filter"](current) is False
    assert captured["filter"](other) is True


def test_people_source_only_visits_dates_overlapping_recent_window(
    tmp_path, monkeypatch
):
    fixed_now = datetime(2026, 9, 17, 6, tzinfo=timezone.utc)
    monkeypatch.setattr(conversation_source, "get_current_time", lambda: fixed_now)
    monkeypatch.setattr("core.utils.common.get_project_root", lambda: tmp_path)

    chat_root = tmp_path / "companion_data" / "aveline_data" / "chat_history"
    recent_ts = (fixed_now - timedelta(hours=1)).timestamp()
    old_ts = (fixed_now - timedelta(days=3)).timestamp()
    _write_jsonl(
        chat_root / "2026" / "09" / "17" / "lane" / "recent.jsonl",
        [_event("recent", recent_ts)],
    )
    _write_jsonl(
        chat_root / "2026" / "09" / "14" / "lane" / "old.jsonl",
        [_event("old", old_ts)],
    )

    result = conversation_source.PeopleConversationSource.load_new_messages(0.0)
    assert [item["event_id"] for item in result] == ["recent"]


def test_knowledge_catalog_cache_reuses_scan_until_explicit_clear(
    tmp_path, monkeypatch
):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "a.json").write_text(
        json.dumps(
            {
                "id": "fixture.a",
                "topic": "测试",
                "facts": {"value": "A"},
                "retrieval": {"keywords": ["测试"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    context_engine.clear_knowledge_cache()
    original = context_engine.load_chunks
    calls = 0

    def tracked_load(directory: Path):
        nonlocal calls
        calls += 1
        return original(directory)

    monkeypatch.setattr(context_engine, "load_chunks", tracked_load)
    first = context_engine.load_chunks_cached(knowledge)
    second = context_engine.load_chunks_cached(knowledge)
    assert first == second
    assert calls == 1

    context_engine.clear_knowledge_cache(knowledge)
    context_engine.load_chunks_cached(knowledge)
    assert calls == 2
    context_engine.clear_knowledge_cache()


def test_scope_registry_change_probe_is_throttled(monkeypatch, tmp_path):
    calls: list[Path] = []
    ticks = iter([100.0, 101.0])

    monkeypatch.setattr(scope_registry, "_REGISTRY_INITIALIZED", True)
    monkeypatch.setattr(scope_registry, "_ACTIVE_CONFIGS_DIR", tmp_path)
    monkeypatch.setattr(scope_registry, "_CONFIG_SNAPSHOT", (0, 0))
    monkeypatch.setattr(scope_registry, "_CONFIG_CHECK_INTERVAL_SECONDS", 60.0)
    monkeypatch.setattr(scope_registry, "_LAST_CONFIG_CHECK_MONOTONIC", 0.0)
    monkeypatch.setattr(scope_registry.time, "monotonic", lambda: next(ticks))

    def fake_snapshot(path: Path):
        calls.append(path)
        return (0, 0)

    monkeypatch.setattr(scope_registry, "_config_snapshot", fake_snapshot)
    scope_registry._refresh_if_configs_changed()
    scope_registry._refresh_if_configs_changed()
    assert calls == [tmp_path]


def test_workspace_history_store_defers_first_maintenance_and_scans_once(
    tmp_path, monkeypatch
):
    settings = SimpleNamespace(memory=SimpleNamespace())
    monkeypatch.setattr(workspace_history_store, "get_settings", lambda: settings)
    monkeypatch.setattr(workspace_history_store.time, "time", lambda: 100.0)
    store = workspace_history_store.WorkspaceHistoryStore(tmp_path)

    assert store._last_cleanup_ts == 100.0
    assert store._last_archive_ts == 100.0

    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "empty.jsonl").touch()
    calls = 0
    original_rglob = Path.rglob

    def tracked_rglob(path: Path, pattern: str):
        nonlocal calls
        if path == tmp_path:
            calls += 1
        return original_rglob(path, pattern)

    monkeypatch.setattr(Path, "rglob", tracked_rglob)
    result = asyncio.run(store.cleanup_empty_files())
    assert result["removed_files"] == 1
    assert calls == 1
