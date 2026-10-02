"""记忆跨系统同步的单元测试（三种落盘形状的并集合并 / 扫描 / 执行）。

记忆与聊天记录同源问题：两端各自累积，整文件覆盖会丢另一边的积累。
这里把「按身份取并集」「同一条目取更新的一份」「与顺序无关且幂等」钉成用例。
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sync.learning_data.items import (  # noqa: E402
    BASE_COMPANION,
    MERGE_MEMORY,
    SyncItem,
    items_for,
)
from scripts.sync.learning_data.manifest import scan  # noqa: E402
from scripts.sync.learning_data.memory_merge import union_memory_json  # noqa: E402
from scripts.sync.learning_data.planner import MERGE, SKIP, plan  # noqa: E402
from scripts.sync.learning_data.transfer import apply_actions  # noqa: E402

MEM_ITEM = SyncItem("memories", BASE_COMPANION, "*/memories/**/*.json", merge=MERGE_MEMORY)
SHORT = "ye_data/memories/short_term/shared__scope__ye_short.json"
WEIGHTED = "ye_data/memories/weighted/chat/shared__scope__ye_weighted.json"
STATES = "ye_data/memories/persistent_states_shared__scope__ye.json"


def _memory_mode_of(_key: str) -> str:
    return MERGE_MEMORY


def _dump(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode()


def _load(raw: bytes):
    return json.loads(raw.decode("utf-8"))


def _write(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def test_union_memory_merges_short_term_arrays_by_id():
    mine = _dump(
        [{"id": "a", "timestamp": 2, "content": "本地"}, {"id": "c", "timestamp": 5}]
    )
    theirs = _dump(
        [
            {"id": "b", "timestamp": 1, "content": "对端"},
            {"id": "c", "timestamp": 9, "content": "对端更新"},
        ]
    )

    merged = _load(union_memory_json(mine, theirs))

    assert [item["id"] for item in merged] == ["b", "a", "c"]
    assert next(item for item in merged if item["id"] == "c")["content"] == "对端更新"


def test_union_memory_merges_weighted_wrapper_and_takes_later_scalar():
    mine = _dump(
        {
            "weighted_memories": [{"id": "a", "timestamp": 1}],
            "category": "chat",
            "last_updated": "2026-09-29 10:00:00",
        }
    )
    theirs = _dump(
        {
            "weighted_memories": [{"id": "b", "timestamp": 2}],
            "category": "chat",
            "last_updated": "2026-09-30 20:00:00",
        }
    )

    merged = _load(union_memory_json(mine, theirs))

    assert [item["id"] for item in merged["weighted_memories"]] == ["a", "b"]
    assert merged["last_updated"] == "2026-09-30 20:00:00"
    assert merged["category"] == "chat"


def test_union_memory_merges_persistent_state_map_by_fingerprint():
    mine = _dump({"f1": {"content": "旧", "updated_at": "2026-09-29 10:00:00"}})
    theirs = _dump(
        {
            "f1": {"content": "新", "updated_at": "2026-09-30 10:00:00"},
            "f2": {"content": "对端独有", "updated_at": "2026-09-30 11:00:00"},
        }
    )

    merged = _load(union_memory_json(mine, theirs))

    assert sorted(merged) == ["f1", "f2"]
    assert merged["f1"]["content"] == "新"
    assert merged["f2"]["content"] == "对端独有"


def test_union_memory_is_order_independent_and_idempotent():
    mine = _dump([{"id": "a", "timestamp": 2, "content": "甲"}])
    theirs = _dump([{"id": "b", "timestamp": 2, "content": "乙"}])

    merged = union_memory_json(mine, theirs)

    assert merged == union_memory_json(theirs, mine)
    assert merged == union_memory_json(merged, merged)


def test_union_memory_returns_none_on_invalid_json():
    assert union_memory_json(b"{not json", _dump([])) is None
    assert union_memory_json(_dump([]), b"") == _dump([])


def test_scan_memories_glob_covers_all_shapes_and_skips_backups(tmp_path):
    root = tmp_path / "companion"
    _write(root / SHORT, [])
    _write(root / WEIGHTED, {"weighted_memories": []})
    _write(root / STATES, {})
    _write(root / "backups/20260916/memories/sessions.json", [])

    modes = {}
    found = scan((MEM_ITEM,), lambda _base: root, modes=modes)

    for rel in (SHORT, WEIGHTED, STATES):
        assert f"{BASE_COMPANION}:{rel}" in found
    assert not any("backups" in key for key in found)
    assert modes and all(mode == MERGE_MEMORY for mode in modes.values())


def test_plan_merges_memories_when_both_sides_diverged(tmp_path):
    local = tmp_path / "local"
    peer = tmp_path / "peer"
    _write(local / SHORT, [{"id": "a", "timestamp": 1, "content": "本地"}])
    _write(peer / SHORT, [{"id": "b", "timestamp": 2, "content": "对端"}])

    actions = plan(
        scan((MEM_ITEM,), lambda _base: local),
        scan((MEM_ITEM,), lambda _base: peer),
        {},
        merge_mode_of=_memory_mode_of,
    )

    assert [a.kind for a in actions] == [MERGE]
    assert actions[0].merge == MERGE_MEMORY


def test_apply_merge_memories_writes_both_sides_and_settles(tmp_path):
    local = tmp_path / "local"
    peer = tmp_path / "peer"
    local_file = _write(local / SHORT, [{"id": "a", "timestamp": 1, "content": "本地"}])
    peer_file = _write(peer / SHORT, [{"id": "b", "timestamp": 2, "content": "对端"}])
    state = {}
    actions = plan(
        scan((MEM_ITEM,), lambda _base: local),
        scan((MEM_ITEM,), lambda _base: peer),
        state,
        merge_mode_of=_memory_mode_of,
    )

    result = apply_actions(
        actions,
        local_of=lambda _base, rel: local / Path(rel),
        peer_of=lambda _base, rel: peer / Path(rel),
        state=state,
    )

    assert result.merged == 1
    assert not result.failed
    merged = json.loads(local_file.read_text(encoding="utf-8"))
    assert [item["id"] for item in merged] == ["a", "b"]
    assert local_file.read_text(encoding="utf-8") == peer_file.read_text(encoding="utf-8")
    again = plan(
        scan((MEM_ITEM,), lambda _base: local),
        scan((MEM_ITEM,), lambda _base: peer),
        state,
        merge_mode_of=_memory_mode_of,
    )
    assert [a.kind for a in again] == [SKIP]


def test_memories_group_is_synced_by_default():
    assert "memories" in {item.group for item in items_for(None)}
