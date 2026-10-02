"""ChatHistoryStore 批量写入（append_events）与逐条 append_event 的等价性回归。

背景：`scripts/import/import_dated_chat_transcript.py` 导入历史记录时逐条调用
`append_event`，而每条消息都要「打开一次 JSONL + 整份重写当天 index.json +
派生索引单独提交一次事务」，四万余条要跑几十分钟。为此给 store 增加了
`append_events` 批量接口，把上述操作按 (会话, 天, 分线) 归组后合并。

批量路径必须是**纯性能优化**，落盘结果不能有任何语义差异，所以这里逐项对齐：
JSONL 内容（除 uuid 的 event_id 外逐字相同）、当天 index.json、派生索引事件数、
以及回读顺序。另覆盖 debug/error 过滤与跨天跨会话的分组。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.services.chat_history_index import (
    get_history_index,
    reset_history_index_registry,
)
from core.services.chat_history_store import ChatHistoryStore

_DAY1 = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)
_DAY2 = _DAY1 + timedelta(days=1)

_CONV_A = "shared__persona__core_aveline"
_CONV_B = "shared__persona__core_lin"


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


def _event(
    index: int,
    *,
    conversation_id: str = _CONV_A,
    now_dt: datetime = _DAY1,
    content: str | None = None,
    role: str = "user",
) -> dict:
    """构造与 import_dated_chat_transcript 传给 append_events 的同形状事件。"""
    return {
        "conversation_id": conversation_id,
        "role": role,
        "content": content if content is not None else f"消息 {index}",
        "message_id": f"import_msg_{index:04d}",
        "event_type": "chat_message" if role == "user" else "chat_reply",
        "metadata": {
            "source": "dated_chat_transcript_import",
            "source_kind": "user_supplied",
            "imported": True,
            "source_index": index,
            "platform": "qq",
        },
        "now_dt": now_dt,
    }


def _jsonl_payloads(root: Path) -> dict[str, list[dict]]:
    """读取 root 下所有 JSONL，返回 {相对路径: [payload, ...]}（已剔除 uuid event_id）。"""
    result: dict[str, list[dict]] = {}
    for path in sorted(root.rglob("*.jsonl")):
        payloads = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            payload.pop("event_id", None)
            payloads.append(payload)
        result[path.relative_to(root).as_posix()] = payloads
    return result


def _day_indexes(root: Path) -> dict[str, dict]:
    return {
        path.relative_to(root).as_posix(): json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(root.rglob("index.json"))
    }


def test_batch_append_matches_per_event_append(tmp_path):
    """同一批事件，批量路径与逐条路径产出逐字相同的 JSONL 与索引。"""
    events = [
        _event(1, role="user", content="在吗"),
        _event(2, role="assistant", content="在。"),
        _event(3, role="user", content="今天有点累"),
        _event(4, conversation_id=_CONV_B, role="user", content="另一个人设的消息"),
        _event(5, role="assistant", content="那就早点休息。"),
        _event(6, role="user", now_dt=_DAY2, content="第二天的消息"),
    ]

    per_event_root = tmp_path / "per_event"
    batch_root = tmp_path / "batch"

    per_event_store = ChatHistoryStore(per_event_root)
    per_event_refs = [
        per_event_store.append_event(**{k: v for k, v in event.items()})
        for event in events
    ]

    batch_store = ChatHistoryStore(batch_root)
    batch_refs = batch_store.append_events(events)

    # 1) 返回值：形状、顺序、relative_path 与逐条一致（event_id 是 uuid，只比非空）
    assert len(batch_refs) == len(per_event_refs) == len(events)
    for batch_ref, per_event_ref in zip(batch_refs, per_event_refs):
        assert batch_ref["relative_path"] == per_event_ref["relative_path"]
        assert batch_ref["mirror_relative_path"] == per_event_ref["mirror_relative_path"]
        assert batch_ref["role"] == per_event_ref["role"]
        assert batch_ref["conversation_id"] == per_event_ref["conversation_id"]
        assert batch_ref["storage_scope"] == per_event_ref["storage_scope"]
        assert batch_ref["timestamp"] == per_event_ref["timestamp"]
        assert batch_ref["event_id"] not in ("", "filtered")

    # 2) 落盘：文件集合、每个文件的行数与逐行内容完全一致
    assert _jsonl_payloads(batch_root) == _jsonl_payloads(per_event_root)

    # 3) 当天 index.json 完全一致
    assert _day_indexes(batch_root) == _day_indexes(per_event_root)

    # 4) 派生索引事件数一致，且与总行数相等
    assert get_history_index(batch_root).health()["events"] == len(events)
    assert (
        get_history_index(batch_root).health()["events"]
        == get_history_index(per_event_root).health()["events"]
    )


def test_batch_append_splits_by_day_and_conversation(tmp_path):
    """跨天跨会话的一批事件，按 (会话, 天) 落到各自的文件，且行数正确。"""
    events = [
        _event(1, conversation_id=_CONV_A, now_dt=_DAY1),
        _event(2, conversation_id=_CONV_A, now_dt=_DAY1),
        _event(3, conversation_id=_CONV_A, now_dt=_DAY1),
        _event(4, conversation_id=_CONV_B, now_dt=_DAY1),
        _event(5, conversation_id=_CONV_B, now_dt=_DAY1),
        _event(6, conversation_id=_CONV_A, now_dt=_DAY2),
    ]

    store = ChatHistoryStore(tmp_path)
    store.append_events(events)

    payloads = _jsonl_payloads(tmp_path)
    assert set(payloads) == {
        f"2026/09/17/主线对话/{_CONV_A}.jsonl",
        f"2026/09/17/主线对话/{_CONV_B}.jsonl",
        f"2026/09/18/主线对话/{_CONV_A}.jsonl",
    }
    counts = {path: len(items) for path, items in payloads.items()}
    assert counts[f"2026/09/17/主线对话/{_CONV_A}.jsonl"] == 3
    assert counts[f"2026/09/17/主线对话/{_CONV_B}.jsonl"] == 2
    assert counts[f"2026/09/18/主线对话/{_CONV_A}.jsonl"] == 1

    # 同一天两个会话时，index.json 必须同时列出两个文件
    day_index = json.loads(
        (tmp_path / "2026" / "09" / "17" / "index.json").read_text(encoding="utf-8")
    )
    assert [item["relative_path"] for item in day_index["files"]] == [
        f"2026/09/17/主线对话/{_CONV_A}.jsonl",
        f"2026/09/17/主线对话/{_CONV_B}.jsonl",
    ]


def test_batch_append_filters_debug_messages_like_per_event(tmp_path):
    """被过滤的 debug/error 文本：返回 filtered 结构、不落盘、不影响同批其余事件。"""
    events = [
        _event(1, content="正常消息"),
        _event(2, content="[DEBUG_ERROR] Error: HTTP 400: {\"code\":20012}"),
        _event(3, content="另一条正常消息"),
    ]

    store = ChatHistoryStore(tmp_path)
    refs = store.append_events(events)

    assert len(refs) == 3
    assert refs[1]["event_id"] == "filtered"
    assert refs[1]["relative_path"] == ""
    assert refs[1]["storage_scope"] == "filtered"
    assert refs[0]["event_id"] not in ("", "filtered")
    assert refs[2]["event_id"] not in ("", "filtered")

    payloads = _jsonl_payloads(tmp_path)
    written = [item["content"] for items in payloads.values() for item in items]
    assert written == ["正常消息", "另一条正常消息"]


def test_batch_append_is_readable_through_the_store(tmp_path):
    """批量写入后回读顺序与入参一致，且索引路径可用（不依赖文件扫描兜底）。"""
    events = [
        _event(index, role="user" if index % 2 else "assistant", content=f"第 {index} 条")
        for index in range(1, 21)
    ]

    store = ChatHistoryStore(tmp_path)
    store.append_events(events)

    read_back = store.list_conversation_events(_CONV_A, limit=50)
    assert [item["content"] for item in read_back] == [
        f"第 {index} 条" for index in range(1, 21)
    ]


def test_batch_append_empty_input_is_noop(tmp_path):
    store = ChatHistoryStore(tmp_path)
    assert store.append_events([]) == []
    assert list(tmp_path.rglob("*.jsonl")) == []
