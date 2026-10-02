"""原始历史搜索应跨同角色会话召回，不能被当前提问的命中截断。"""

import json
from pathlib import Path

import pytest

from core.services import chat_history_store
from core.tools import search_chat_history_tool
from core.tools.search_chat_history_tool import SearchChatHistoryTool
from core.utils import data_paths


def write_event(root: Path, cid: str, eid: str, ts: float, **fields) -> dict:
    event = {
        "event_id": eid, "conversation_id": cid, "timestamp": ts,
        "role": "user", "event_type": "chat_message", "content": "归档线索",
        "metadata": {"platform": "qq"},
        **fields,
    }
    path = root / "2026" / "09" / "01" / f"{cid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


@pytest.fixture
def archive(tmp_path, monkeypatch):
    root = tmp_path / "current_role" / "chat_history"
    other = tmp_path / "other_role" / "chat_history"
    store = chat_history_store.ChatHistoryStore(root)
    monkeypatch.setattr(chat_history_store, "get_chat_history_store", lambda: store)
    monkeypatch.setattr(data_paths, "get_chat_history_dir_for_conversation", lambda _cid: root)
    monkeypatch.setattr(chat_history_store, "get_all_chat_history_dirs", lambda: [root, other])
    monkeypatch.setattr(search_chat_history_tool, "should_exclude_sensitive", lambda **_kw: False)
    return root, other


def search(**kwargs):
    return SearchChatHistoryTool()._search_in_store(**{
        "conversation_id": "web_role_aveline", "query": "归档线索", "limit": 20,
        "roles": None, "before_ts": None, "after_ts": None, "scope": "local",
        **kwargs,
    })


def test_current_hit_does_not_hide_legacy_conversations(archive):
    root, other = archive
    write_event(root, "web_old", "old-web", 10)
    write_event(root, "qq_old", "old-qq", 20)
    write_event(root, "web_role_aveline", "current", 30)
    write_event(root, "web_role_ling", "misplaced-other-role", 35)
    write_event(other, "qq_other", "other-role", 40)
    assert [e["event_id"] for e in search()] == ["old-web", "old-qq", "current"]


def test_filter_before_limit_and_keep_archive_dates(archive, monkeypatch):
    root, _other = archive
    write_event(root, "old", "too-old", 1)
    write_event(root, "old", "wanted", 10)
    write_event(root, "old", "future", 60)
    write_event(root, "web_role_aveline", "wrong-platform", 20, metadata={"platform": "obsidian"})
    write_event(root, "web_role_aveline", "thought", 30, event_type="chat_thought")
    write_event(root, "web_role_aveline", "wrong-role", 40, role="assistant")
    write_event(root, "web_role_aveline", "excluded", 45, metadata={"topics": ["sensitive"], "platform": "qq"})
    monkeypatch.setattr(search_chat_history_tool, "should_exclude_sensitive", lambda **_kw: True)
    events = search(limit=1, roles=["user"], after_ts=5, before_ts=50, source="qq", scope="sfw")
    assert [e["event_id"] for e in events] == ["wanted"]


def test_limit_applies_after_merging_and_deduplicating(archive):
    root, _other = archive
    write_event(root, "old", "old", 10)
    write_event(root, "web_role_aveline", "current", 20)
    assert [e["event_id"] for e in search(limit=2)] == ["old", "current"]
    assert [e["event_id"] for e in search(limit=1)] == ["current"]


def test_missing_event_id_does_not_duplicate_current_hit(archive):
    root, _other = archive
    write_event(root, "old", "", 10)
    write_event(root, "web_role_aveline", "", 20)
    assert [e["timestamp"] for e in search()] == [10, 20]


def test_empty_query_can_read_old_date_range(archive):
    root, _other = archive
    write_event(root, "old", "wanted-day", 10, content="当天普通聊天")
    write_event(root, "web_role_aveline", "current-day", 20)
    assert [e["event_id"] for e in search(query="", before_ts=15)] == ["wanted-day"]
