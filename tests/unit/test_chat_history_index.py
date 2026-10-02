"""ChatHistory SQLite 派生索引（B1-B2）的确定性回归。

覆盖 PLAN_history_sqlite_memory_perf.md §十 的用例：
JSONL 写入成功而 DB 失败不影响消息可见性、DB 被删后自动重建、rebuild 幂等、
recent-N 尾部语义、各维度过滤与文件扫描实现结果一致、旧数据兼容、
损坏行/半行容错、并发读写、delete_conversation 同步清索引。

时间相关断言一律使用固定 `now_dt`；并发用例只断言最终一致性与无异常。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.services.chat_history_index import (
    SCHEMA_VERSION,
    ChatHistoryIndex,
    get_history_index,
    reset_history_index_registry,
)
from core.services.chat_history_store import ChatHistoryStore

_FIXED_NOW = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolate_index_registry(monkeypatch):
    """隔离模块级索引注册表与"其它 scope root"，避免用例互相污染或扫到真机数据。"""
    reset_history_index_registry()
    monkeypatch.setattr(
        "core.services.chat_history_store.get_all_chat_history_dirs",
        lambda: [],
    )
    yield
    reset_history_index_registry()


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def _jsonl_line(event: dict) -> str:
    return json.dumps(event, ensure_ascii=False)


def _event(
    event_id: str,
    timestamp: float,
    *,
    content: str = "消息",
    role: str = "user",
    conversation_id: str = "shared__persona__core_aveline",
    event_type: str = "message",
    metadata: dict | None = None,
) -> dict:
    return {
        "event_id": event_id,
        "conversation_id": conversation_id,
        "message_id": event_id,
        "event_type": event_type,
        "role": role,
        "content": content,
        "timestamp": timestamp,
        "created_at": "2026-09-17 12:00:00",
        "metadata": metadata if metadata is not None else {},
        "readable_title": "Aveline / 主线对话",
        "storage_scope": "aveline",
    }


def _disable_index(monkeypatch) -> None:
    """关闭索引，强制走文件扫描实现（作为语义基线）。

    直接让索引工厂抛异常，而不是替换 ``ChatHistoryStore._synced_index``——
    后者是 staticmethod，用 getattr/setattr 打补丁会在撤销时退化成普通函数。
    """
    import core.services.chat_history_index as chat_history_index

    def _boom(*_args, **_kwargs):
        raise RuntimeError("index disabled for baseline")

    monkeypatch.setattr(chat_history_index, "get_history_index", _boom)
    reset_history_index_registry()


def _store(tmp_path: Path) -> ChatHistoryStore:
    return ChatHistoryStore(tmp_path)


# ----------------------------------------------------------------------
# 同步与容错
# ----------------------------------------------------------------------
def test_append_event_keeps_jsonl_visible_when_index_write_fails(tmp_path, monkeypatch):
    """JSONL 写入成功而 DB 写失败时：消息不丢、append 返回值不变、索引自愈。"""
    state = {"fail": True}
    original = ChatHistoryIndex.append_events

    def maybe_fail(self, *args, **kwargs):
        if state["fail"]:
            raise RuntimeError("disk I/O error")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ChatHistoryIndex, "append_events", maybe_fail)
    store = _store(tmp_path)
    result = store.append_event(
        conversation_id="shared__persona__core_aveline",
        role="user",
        content="索引写失败也要留下",
        message_id="m1",
        now_dt=_FIXED_NOW,
    )

    assert result["event_id"] not in ("", "filtered")
    assert result["relative_path"].endswith(".jsonl")
    assert result["conversation_id"] == "shared__persona__core_aveline"
    files = list(tmp_path.rglob("*.jsonl"))
    assert len(files) == 1
    assert "索引写失败也要留下" in files[0].read_text(encoding="utf-8")
    # 索引里确实没写进去（append 失败），但 files 表也没被错误地标记为已同步
    assert get_history_index(tmp_path).health()["events"] == 0

    # 下次查询 ensure_sync 补齐（mark_stale 已让 TTL 失效）
    state["fail"] = False
    events = store.list_conversation_events("shared__persona__core_aveline", limit=10)
    assert [item["content"] for item in events] == ["索引写失败也要留下"]


def test_index_rebuilds_after_db_file_removed(tmp_path):
    store = _store(tmp_path)
    for index in range(3):
        store.append_event(
            conversation_id="shared__persona__core_aveline",
            role="user",
            content=f"第{index}条",
            message_id=f"m{index}",
            now_dt=_FIXED_NOW,
        )
    assert len(store.list_conversation_events("shared__persona__core_aveline")) == 3

    index = get_history_index(tmp_path)
    db_path = index.db_path
    # Windows 下必须先关闭连接才能删除正在使用的 db 文件
    reset_history_index_registry()
    for suffix in ("", "-wal", "-shm"):
        target = Path(str(db_path) + suffix)
        if target.exists():
            target.unlink()
    assert not db_path.exists()

    events = store.list_conversation_events("shared__persona__core_aveline")
    assert len(events) == 3
    assert get_history_index(tmp_path).health()["ok"] is True


def test_rebuild_is_idempotent_and_event_ids_are_unique(tmp_path):
    day = tmp_path / "2026" / "09" / "17" / "lane"
    _write_jsonl(
        day / "shared__persona__core_aveline.jsonl",
        [
            _jsonl_line(_event("e1", 1.0)),
            _jsonl_line(_event("e2", 2.0)),
            _jsonl_line(_event("e1", 1.0)),  # 重复 event_id
        ],
    )
    index = get_history_index(tmp_path)
    first = index.rebuild()
    second = index.rebuild()
    assert first["events"] == 2
    assert second["events"] == 2
    assert index.health()["events"] == 2
    assert index.health()["schema_version"] == SCHEMA_VERSION


def test_corrupt_and_partial_lines_do_not_break_rebuild(tmp_path):
    day = tmp_path / "2026" / "09" / "17" / "lane"
    target = day / "shared__persona__core_aveline.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        b""
        + _jsonl_line(_event("e1", 1.0)).encode("utf-8")
        + b"\n"
        + b"{not json at all}\n"
        + b"\n"
        + b'{"event_id": "e2", "timestamp": 2.0, "content": "\xe6\x9c\xaa\xe5\xae\x8c\xe6\x88\x90'
    )
    index = get_history_index(tmp_path)
    result = index.rebuild()
    assert result["events"] == 1
    events = index.query(limit=0)
    assert [item["event_id"] for item in events] == ["e1"]


def test_legacy_rows_without_event_id_or_metadata_are_indexed_and_deduped(tmp_path):
    day = tmp_path / "2026" / "09" / "17" / "lane"
    legacy = {
        "conversation_id": "shared__persona__core_aveline",
        "role": "user",
        "content": "没有 event_id 的老记录",
        "timestamp": 1.0,
    }
    _write_jsonl(
        day / "shared__persona__core_aveline.jsonl",
        [_jsonl_line(legacy), _jsonl_line(legacy)],
    )
    index = get_history_index(tmp_path)
    index.rebuild()
    events = index.query(limit=0)
    assert len(events) == 1
    assert events[0]["event_id"].startswith("legacy:")
    assert events[0]["metadata"] == {}
    assert events[0]["content"] == "没有 event_id 的老记录"


def test_append_events_does_not_claim_untracked_file_is_fully_synced(tmp_path):
    """文件已有历史行但索引没见过时，append 不得把偏移推到文件末尾。"""
    store = _store(tmp_path)
    store.append_event(
        conversation_id="shared__persona__core_aveline",
        role="user",
        content="索引认识的第一条",
        message_id="m1",
        now_dt=_FIXED_NOW,
    )
    target = next(tmp_path.rglob("*.jsonl"))

    # 直接往真源补历史行，并删掉索引库，模拟"索引从没见过这个文件"
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(_jsonl_line(_event("old1", 1.0, content="更早的一条")) + "\n")
        handle.write(_jsonl_line(_event("old2", 2.0, content="更早的另一条")) + "\n")
    db_path = get_history_index(tmp_path).db_path
    reset_history_index_registry()
    for suffix in ("", "-wal", "-shm"):
        leftover = Path(str(db_path) + suffix)
        if leftover.exists():
            leftover.unlink()

    size_before = target.stat().st_size
    assert size_before > 0
    store.append_event(
        conversation_id="shared__persona__core_aveline",
        role="user",
        content="新写入的一条",
        message_id="m3",
        now_dt=_FIXED_NOW,
    )

    index = get_history_index(tmp_path)
    index.ensure_sync(force=True)
    contents = {item["content"] for item in index.query(limit=0)}
    assert contents == {"索引认识的第一条", "更早的一条", "更早的另一条", "新写入的一条"}
    assert index.health()["files"] == 1


# ----------------------------------------------------------------------
# 查询语义
# ----------------------------------------------------------------------
def test_recent_events_returns_tail_in_ascending_order(tmp_path):
    day = tmp_path / "2026" / "09" / "17" / "lane"
    _write_jsonl(
        day / "shared__persona__core_aveline.jsonl",
        [_jsonl_line(_event(f"e{i}", float(i))) for i in range(1, 8)],
    )
    result = _store(tmp_path).list_recent_events(limit=3, roles=["user"])
    assert [item["event_id"] for item in result] == ["e5", "e6", "e7"]


def test_recent_events_index_and_file_scan_agree(tmp_path, monkeypatch):
    day = tmp_path / "2026" / "09" / "17" / "lane"
    lines = [
        _jsonl_line(_event("a1", 1.0, role="user")),
        _jsonl_line(_event("a2", 2.0, role="assistant")),
        _jsonl_line(_event("a3", 3.0, role="system")),
        _jsonl_line(_event("a4", 4.0, role="user", event_type="chat_thought")),
        _jsonl_line(_event("a5", 5.0, role="user")),
    ]
    _write_jsonl(day / "shared__persona__core_aveline.jsonl", lines)

    store = _store(tmp_path)
    indexed = store.list_recent_events(limit=3, roles=["user", "assistant"])

    reset_history_index_registry()
    _disable_index(monkeypatch)
    scanned = _store(tmp_path).list_recent_events(limit=3, roles=["user", "assistant"])

    assert [item["event_id"] for item in indexed] == [
        item["event_id"] for item in scanned
    ]
    assert [item["event_id"] for item in indexed] == ["a2", "a4", "a5"]


def test_recent_events_applies_predicate_like_file_scan(tmp_path, monkeypatch):
    day = tmp_path / "2026" / "09" / "17" / "lane"
    lines = [
        _jsonl_line(_event("p1", 1.0, content="")),
        _jsonl_line(_event("p2", 2.0, content="有内容")),
        _jsonl_line(
            _event("p3", 3.0, content="有内容", metadata={"hidden": True}),
        ),
        _jsonl_line(_event("p4", 4.0, content="有内容")),
    ]
    _write_jsonl(day / "shared__persona__core_aveline.jsonl", lines)

    def predicate(payload: dict) -> bool:
        return bool(str(payload.get("content") or "").strip()) and not (
            isinstance(payload.get("metadata"), dict)
            and payload["metadata"].get("hidden")
        )

    indexed = _store(tmp_path).list_recent_events(limit=5, predicate=predicate)
    reset_history_index_registry()
    _disable_index(monkeypatch)
    scanned = _store(tmp_path).list_recent_events(limit=5, predicate=predicate)

    assert [item["event_id"] for item in indexed] == ["p2", "p4"]
    assert [item["event_id"] for item in indexed] == [
        item["event_id"] for item in scanned
    ]


def test_conversation_query_filters_match_file_scan(tmp_path, monkeypatch):
    day = tmp_path / "2026" / "09" / "17" / "lane"
    cid = "shared__persona__core_aveline"
    _write_jsonl(
        day / f"{cid}.jsonl",
        [
            _jsonl_line(_event("q1", 1.0, content="初中女生的话题")),
            _jsonl_line(_event("q2", 2.0, content="初二女生的话题", role="assistant")),
            _jsonl_line(_event("q3", 3.0, content="今天天气不错")),
            _jsonl_line(_event("q4", 4.0, content="QQ 上的记录", metadata={"platform": "qq"})),
            _jsonl_line(_event("q5", 5.0, content="obsidian 的记录", metadata={"platform": "obsidian"})),
            _jsonl_line(_event("q6", 6.0, content="内心独白", event_type="chat_thought")),
        ],
    )

    cases = [
        {"query": "初中女生"},
        {"query": "初二"},
        {"query": "不存在的词"},
        {"roles": ["assistant"]},
        {"before": 4.0},
        {"limit": 2},
        {"query": "女生", "roles": ["user"], "limit": 1},
    ]
    store = _store(tmp_path)
    for kwargs in cases:
        reset_history_index_registry()
        indexed = store.list_conversation_events(cid, **kwargs)
        reset_history_index_registry()
        _disable_index(monkeypatch)
        scanned = _store(tmp_path).list_conversation_events(cid, **kwargs)
        assert [item["event_id"] for item in indexed] == [
            item["event_id"] for item in scanned
        ], kwargs


def test_platform_qq_filter_includes_rows_without_platform(tmp_path):
    day = tmp_path / "2026" / "09" / "17" / "lane"
    cid = "shared__persona__core_aveline"
    _write_jsonl(
        day / f"{cid}.jsonl",
        [
            _jsonl_line(_event("s1", 1.0, content="无 platform")),
            _jsonl_line(_event("s2", 2.0, content="qq", metadata={"platform": "qq"})),
            _jsonl_line(_event("s3", 3.0, content="obsidian", metadata={"platform": "obsidian"})),
        ],
    )
    index = get_history_index(tmp_path)
    index.ensure_sync()
    qq_ids = [item["event_id"] for item in index.query(platform="qq", limit=0)]
    obsidian_ids = [item["event_id"] for item in index.query(platform="obsidian", limit=0)]
    assert qq_ids == ["s1", "s2"]
    assert obsidian_ids == ["s3"]


def test_query_supports_scope_role_type_and_time_range(tmp_path):
    day = tmp_path / "2026" / "09" / "17" / "lane"
    cid = "shared__persona__core_aveline"
    _write_jsonl(
        day / f"{cid}.jsonl",
        [
            _jsonl_line(_event("t1", 1.0, role="user")),
            _jsonl_line(_event("t2", 2.0, role="assistant", event_type="chat_thought")),
            _jsonl_line(_event("t3", 3.0, role="system")),
        ],
    )
    index = get_history_index(tmp_path)
    index.ensure_sync()
    assert [item["event_id"] for item in index.query(storage_scope="aveline", limit=0)] == [
        "t1",
        "t2",
        "t3",
    ]
    assert [item["event_id"] for item in index.query(roles=["user"], limit=0)] == ["t1"]
    assert [
        item["event_id"]
        for item in index.query(exclude_event_types=["chat_thought"], limit=0)
    ] == ["t1", "t3"]
    assert [
        item["event_id"] for item in index.query(event_types=["chat_thought"], limit=0)
    ] == ["t2"]
    assert [item["event_id"] for item in index.query(after=2.0, limit=0)] == ["t2", "t3"]
    assert [item["event_id"] for item in index.query(before=2.0, limit=0)] == ["t1"]
    assert [item["event_id"] for item in index.query(conversation_ids=[], limit=0)] == []


def test_query_tail_semantics_with_offset(tmp_path):
    day = tmp_path / "2026" / "09" / "17" / "lane"
    cid = "shared__persona__core_aveline"
    _write_jsonl(
        day / f"{cid}.jsonl",
        [_jsonl_line(_event(f"o{i}", float(i))) for i in range(1, 7)],
    )
    index = get_history_index(tmp_path)
    index.ensure_sync()
    assert [item["event_id"] for item in index.query(limit=2)] == ["o5", "o6"]
    assert [item["event_id"] for item in index.query(limit=2, offset=2)] == ["o3", "o4"]


def test_get_event_content_uses_index_then_falls_back(tmp_path, monkeypatch):
    day = tmp_path / "2026" / "09" / "17" / "lane"
    cid = "shared__persona__core_aveline"
    target = day / f"{cid}.jsonl"
    _write_jsonl(target, [_jsonl_line(_event("c1", 1.0, content="点查正文"))])

    store = _store(tmp_path)
    ref = {
        "event_id": "c1",
        "relative_path": target.relative_to(tmp_path).as_posix(),
        "storage_scope": "aveline",
    }
    assert store.get_event_content(ref) == "点查正文"

    reset_history_index_registry()
    _disable_index(monkeypatch)
    assert _store(tmp_path).get_event_content(ref) == "点查正文"
    assert (
        _store(tmp_path).get_event_content(
            {**ref, "event_id": "missing"}
        )
        is None
    )


def test_delete_conversation_clears_index_and_files(tmp_path):
    store = _store(tmp_path)
    for index in range(2):
        store.append_event(
            conversation_id="shared__persona__core_aveline",
            role="user",
            content=f"待删{index}",
            message_id=f"d{index}",
            now_dt=_FIXED_NOW,
        )
    index = get_history_index(tmp_path)
    assert index.health()["events"] == 2

    result = store.delete_conversation("shared__persona__core_aveline")
    assert result["removed_files"] == 1
    assert index.health()["events"] == 0
    assert index.health()["files"] == 0
    assert not list(tmp_path.rglob("*.jsonl"))


def test_concurrent_queries_and_appends_stay_consistent(tmp_path):
    day = tmp_path / "2026" / "09" / "17" / "lane"
    cid = "shared__persona__core_aveline"
    _write_jsonl(
        day / f"{cid}.jsonl",
        [_jsonl_line(_event(f"base{i}", float(i))) for i in range(1, 21)],
    )
    store = _store(tmp_path)
    index = get_history_index(tmp_path)
    index.ensure_sync()

    errors: list[BaseException] = []
    barrier = threading.Barrier(3)

    def reader() -> None:
        try:
            barrier.wait()
            for _ in range(20):
                rows = index.query(roles=["user"], limit=5)
                assert len(rows) <= 5
                assert store.list_recent_events(limit=5, roles=["user"])
        except BaseException as exc:  # pragma: no cover - 失败时用于定位
            errors.append(exc)

    def writer() -> None:
        try:
            barrier.wait()
            for i in range(20):
                store.append_event(
                    conversation_id=cid,
                    role="user",
                    content=f"并发{i}",
                    message_id=f"w{i}",
                    now_dt=_FIXED_NOW,
                )
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=reader), threading.Thread(target=reader), threading.Thread(target=writer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    index.ensure_sync(force=True)
    rows = index.query(file_stems=[cid], limit=0)
    assert len(rows) == 40
    assert len({item["event_id"] for item in rows}) == 40
