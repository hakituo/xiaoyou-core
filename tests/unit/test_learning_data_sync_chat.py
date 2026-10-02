"""聊天历史跨系统同步的单元测试（并集合并 / 通配符扫描 / CLI）。

聊天记录与学习数据最大的不同：同一个会话文件两边都可能追加，整文件覆盖会丢消息。
这里把「不丢消息」「结果与先后顺序无关」「幂等」三件事钉成用例。
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sync import learning_data_sync as cli  # noqa: E402
from scripts.sync.learning_data.chat_merge import (  # noqa: E402
    union_bytes,
    union_day_index,
    union_jsonl,
)
from scripts.sync.learning_data.items import (  # noqa: E402
    BASE_COMPANION,
    MERGE_INDEX,
    MERGE_JSONL,
    HubLayout,
    SyncItem,
    items_for,
)
from scripts.sync.learning_data.manifest import scan  # noqa: E402
from scripts.sync.learning_data.planner import MERGE, PULL, SKIP, plan  # noqa: E402
from scripts.sync.learning_data.transfer import apply_actions  # noqa: E402

CHAT_ITEMS = (
    SyncItem("chat", BASE_COMPANION, "*/chat_history/**/*.jsonl", merge=MERGE_JSONL),
    SyncItem("chat", BASE_COMPANION, "*/chat_history/**/index.json", merge=MERGE_INDEX),
)

CONV = "ye_data/chat_history/2026/09/30/主线对话/shared__persona__ye.jsonl"
INDEX = "ye_data/chat_history/2026/09/30/index.json"


def _mode_of(key: str) -> str:
    return MERGE_JSONL if key.endswith(".jsonl") else MERGE_INDEX


def _event(event_id: str, ts: float, content: str) -> str:
    return json.dumps(
        {"event_id": event_id, "timestamp": ts, "content": content}, ensure_ascii=False
    )


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def roots(tmp_path):
    """本机 companion_data 根 + 对端中转目录。"""
    local = tmp_path / "companion"
    local.mkdir(parents=True, exist_ok=True)
    hub = HubLayout(tmp_path / "hub")
    hub.root(BASE_COMPANION).mkdir(parents=True, exist_ok=True)
    return local, hub


def test_union_jsonl_keeps_both_sides_and_ignores_argument_order():
    left = (_event("a", 3, "本地") + "\n").encode()
    right = (_event("b", 1, "对端") + "\n").encode()

    merged = union_jsonl(left, right)

    assert merged == union_jsonl(right, left)
    assert merged == union_jsonl(merged, merged)
    ids = [json.loads(line)["event_id"] for line in merged.decode("utf-8").splitlines()]
    assert ids == ["b", "a"]


def test_union_jsonl_dedupes_same_event_id():
    line = _event("dup", 5, "同一条")

    merged = union_jsonl((line + "\n").encode(), (line + "\n").encode())

    assert merged.decode("utf-8").splitlines() == [line]


def test_union_jsonl_keeps_lines_without_event_id():
    older = json.dumps({"timestamp": 1, "content": "无 id 一"}, ensure_ascii=False)
    newer = json.dumps({"timestamp": 2, "content": "无 id 二"}, ensure_ascii=False)

    merged = union_jsonl((newer + "\n").encode(), (older + "\n").encode())

    assert merged.decode("utf-8").splitlines() == [older, newer]


def test_union_day_index_merges_entries_and_prefers_titled():
    left = json.dumps({"files": [{"relative_path": "b.jsonl", "readable_title": ""}]}).encode()
    right = json.dumps(
        {
            "files": [
                {"relative_path": "b.jsonl", "readable_title": "Ye"},
                {"relative_path": "a.jsonl", "readable_title": "Aveline"},
            ]
        }
    ).encode()

    merged = json.loads(union_day_index(left, right).decode("utf-8"))

    assert [item["relative_path"] for item in merged["files"]] == ["a.jsonl", "b.jsonl"]
    assert merged["files"][1]["readable_title"] == "Ye"
    assert union_bytes(MERGE_INDEX, left, right) is not None


def test_scan_chat_glob_keeps_jsonl_and_index_but_not_sqlite(roots):
    local, _ = roots
    _write(local / CONV, _event("a", 1, "hi") + "\n")
    _write(local / INDEX, json.dumps({"files": []}))
    _write(local / "ye_data/indexes/chat_history.db", "db")
    _write(local / "ye_data/indexes/chat_history.db-wal", "wal")

    modes = {}
    found = scan(CHAT_ITEMS, lambda _base: local, modes=modes)

    assert f"{BASE_COMPANION}:{CONV}" in found
    assert f"{BASE_COMPANION}:{INDEX}" in found
    assert not any(key.endswith((".db", ".db-wal")) for key in found)
    assert modes[f"{BASE_COMPANION}:{CONV}"] == MERGE_JSONL
    assert modes[f"{BASE_COMPANION}:{INDEX}"] == MERGE_INDEX


def test_plan_merges_when_both_sides_diverged(roots):
    local, hub = roots
    _write(local / CONV, _event("a", 1, "本地") + "\n")
    _write(hub.root(BASE_COMPANION) / CONV, _event("b", 2, "对端") + "\n")

    actions = plan(
        scan(CHAT_ITEMS, lambda _base: local),
        scan(CHAT_ITEMS, hub.root),
        {},
        merge_mode_of=_mode_of,
    )

    assert [a.kind for a in actions] == [MERGE]
    assert actions[0].merge == MERGE_JSONL
    assert actions[0].direction == "双向并集"


def test_plan_copies_when_only_peer_changed(roots):
    local, hub = roots
    _write(local / CONV, _event("a", 1, "旧") + "\n")
    local_scan = scan(CHAT_ITEMS, lambda _base: local)
    _write(
        hub.root(BASE_COMPANION) / CONV,
        _event("a", 1, "旧") + "\n" + _event("b", 2, "新") + "\n",
    )
    state = {key: stat.as_state() for key, stat in local_scan.items()}

    actions = plan(local_scan, scan(CHAT_ITEMS, hub.root), state, merge_mode_of=_mode_of)

    assert [a.kind for a in actions] == [PULL]


def test_apply_merge_writes_both_sides_and_settles(roots):
    local, hub = roots
    local_file = _write(local / CONV, _event("a", 1, "本地") + "\n")
    peer_file = _write(hub.root(BASE_COMPANION) / CONV, _event("b", 2, "对端") + "\n")
    state = {}
    actions = plan(
        scan(CHAT_ITEMS, lambda _base: local),
        scan(CHAT_ITEMS, hub.root),
        state,
        merge_mode_of=_mode_of,
    )

    result = apply_actions(
        actions,
        local_of=lambda _base, rel: local / Path(rel),
        peer_of=hub.resolve,
        state=state,
    )

    assert result.merged == 1
    assert not result.failed
    local_text = local_file.read_text(encoding="utf-8")
    assert local_text == peer_file.read_text(encoding="utf-8")
    assert len(local_text.splitlines()) == 2
    again = plan(
        scan(CHAT_ITEMS, lambda _base: local),
        scan(CHAT_ITEMS, hub.root),
        state,
        merge_mode_of=_mode_of,
    )
    assert [a.kind for a in again] == [SKIP]


def test_chat_group_is_synced_by_default():
    assert "chat" in {item.group for item in items_for(None)}


def test_cli_chat_group_dry_run_then_apply(roots, tmp_path, monkeypatch, capsys):
    local, hub = roots
    _write(local / CONV, _event("a", 1, "hi") + "\n")
    monkeypatch.setattr(cli, "local_roots", lambda _items: {BASE_COMPANION: local})
    monkeypatch.setattr(cli, "default_state_path", lambda: tmp_path / "state.json")
    hub_path = tmp_path / "hub"

    preview = cli.main(["--hub", str(hub_path), "--groups", "chat"])
    assert preview == 0
    assert "合并 0" in capsys.readouterr().out
    assert not (hub.root(BASE_COMPANION) / CONV).exists()

    applied = cli.main(["--hub", str(hub_path), "--groups", "chat", "--apply"])
    assert applied == 0
    assert (hub.root(BASE_COMPANION) / CONV).exists()
