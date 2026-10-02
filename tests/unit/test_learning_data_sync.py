"""学习数据跨系统同步的单元测试（清单扫描 / 三向比对 / 传输执行 / CLI）。"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sync.learning_data.items import (  # noqa: E402
    BASE_PROJECT,
    BASE_STUDY,
    BASE_USER_DATA,
    HubLayout,
    SyncItem,
    items_for,
)
from scripts.sync.learning_data.manifest import scan  # noqa: E402
from scripts.sync.learning_data.planner import (  # noqa: E402
    CONFLICT,
    DROPPED,
    PULL,
    PUSH,
    plan,
)
from scripts.sync.learning_data.transfer import apply_actions, load_state, save_state  # noqa: E402
from scripts.sync import learning_data_sync as cli  # noqa: E402

ITEMS = (
    SyncItem("vocab", BASE_PROJECT, "output/user_data/vocab_progress.json"),
    SyncItem("daily", BASE_USER_DATA, "daily", recursive=True),
    SyncItem("study_state", BASE_STUDY, ".state", recursive=True),
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def roots(tmp_path):
    """本机三个基准根 + 对端中转目录。"""
    local = {
        BASE_PROJECT: tmp_path / "local" / "project",
        BASE_USER_DATA: tmp_path / "local" / "user_data",
        BASE_STUDY: tmp_path / "local" / "study",
    }
    for path in local.values():
        path.mkdir(parents=True, exist_ok=True)
    hub = HubLayout(tmp_path / "hub")
    for base in local:
        hub.root(base).mkdir(parents=True, exist_ok=True)
    return local, hub


def test_scan_collects_files_and_skips_backups(roots):
    local, _ = roots
    _write(local[BASE_PROJECT] / "output/user_data/vocab_progress.json", "{}")
    _write(local[BASE_USER_DATA] / "daily/2026/09/28/plan.json", "{}")
    _write(local[BASE_USER_DATA] / "daily/2026/09/28/app_usage.jsonl", "x" * 10)
    _write(local[BASE_USER_DATA] / "daily/2026/09/28/plan.json.bak", "old")

    found = scan(ITEMS, local.get)
    keys = set(found)

    assert f"{BASE_PROJECT}:output/user_data/vocab_progress.json" in keys
    assert f"{BASE_USER_DATA}:daily/2026/09/28/plan.json" in keys
    assert not any("app_usage" in key for key in keys)
    assert not any(key.endswith(".bak") for key in keys)


def test_plan_pushes_local_only_file(roots):
    local, hub = roots
    _write(local[BASE_PROJECT] / "output/user_data/vocab_progress.json", "v1")

    actions = plan(scan(ITEMS, local.get), scan(ITEMS, hub.root), {})

    assert [a.kind for a in actions] == [PUSH]
    assert actions[0].direction == "本地 → 对端"


def test_plan_pulls_peer_only_file(roots):
    local, hub = roots
    _write(hub.root(BASE_USER_DATA) / "daily/2026/09/28/plan.json", "remote")

    actions = plan(scan(ITEMS, local.get), scan(ITEMS, hub.root), {})

    assert [a.kind for a in actions] == [PULL]


def test_plan_skips_when_both_sides_equal(roots):
    local, hub = roots
    _write(local[BASE_PROJECT] / "output/user_data/vocab_progress.json", "same")
    _write(hub.root(BASE_PROJECT) / "output/user_data/vocab_progress.json", "same")

    actions = plan(scan(ITEMS, local.get), scan(ITEMS, hub.root), {})

    assert all(a.kind == "skip" for a in actions)


def test_plan_conflict_takes_newer_and_backups_loser(roots):
    local, hub = roots
    local_file = _write(local[BASE_STUDY] / ".state/student_state.json", "mine")
    peer_file = _write(hub.root(BASE_STUDY) / ".state/student_state.json", "theirs")
    # 让本机更旧，冲突应由对端取胜（拉取）
    import os
    import time

    past = time.time() - 3600
    os.utime(local_file, (past, past))
    os.utime(peer_file, (time.time(), time.time()))

    state = {}
    actions = plan(scan(ITEMS, local.get), scan(ITEMS, hub.root), state)
    result = apply_actions(
        actions,
        local_of=lambda base, rel: local[base] / Path(rel),
        peer_of=lambda base, rel: hub.resolve(base, rel),
        state=state,
    )

    assert actions[0].kind == CONFLICT
    assert actions[0].winner == "peer"
    assert local_file.read_text(encoding="utf-8") == "theirs"
    assert result.conflicts == 1
    assert not result.failed


def test_delete_is_not_propagated_by_default(roots):
    local, hub = roots
    _write(local[BASE_USER_DATA] / "daily/2026/09/28/plan.json", "keep")
    state = {}
    first = plan(scan(ITEMS, local.get), scan(ITEMS, hub.root), state)
    apply_actions(
        first,
        local_of=lambda base, rel: local[base] / Path(rel),
        peer_of=lambda base, rel: hub.resolve(base, rel),
        state=state,
    )
    (hub.root(BASE_USER_DATA) / "daily/2026/09/28/plan.json").unlink()

    actions = plan(scan(ITEMS, local.get), scan(ITEMS, hub.root), state)

    assert [a.kind for a in actions] == [DROPPED]
    assert (local[BASE_USER_DATA] / "daily/2026/09/28/plan.json").exists()


def test_state_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, {"project:a": {"sha1": "x"}})

    assert load_state(path) == {"project:a": {"sha1": "x"}}
    assert load_state(tmp_path / "missing.json") == {}


def test_cli_dry_run_then_apply(roots, tmp_path, monkeypatch, capsys):
    local, hub = roots
    monkeypatch.setattr(cli, "local_roots", lambda items: local)
    monkeypatch.setattr(cli, "default_state_path", lambda: tmp_path / "state.json")
    _write(local[BASE_PROJECT] / "output/user_data/vocab_progress.json", "v1")

    preview_code = cli.main(["--hub", str(tmp_path / "hub")])
    preview = capsys.readouterr().out
    assert preview_code == 0
    assert "计划预览" in preview
    assert not (hub.root(BASE_PROJECT) / "output/user_data/vocab_progress.json").exists()

    apply_code = cli.main(["--hub", str(tmp_path / "hub"), "--apply"])
    assert apply_code == 0
    assert (hub.root(BASE_PROJECT) / "output/user_data/vocab_progress.json").exists()


def test_cli_without_peer_returns_usage_error(monkeypatch, capsys):
    monkeypatch.delenv(cli.HUB_ENV, raising=False)

    assert cli.main(["--auto"]) == 0
    assert cli.main([]) == 2
    assert "--hub" in capsys.readouterr().out


def test_items_for_filters_groups():
    assert {item.group for item in items_for(["vocab"])} == {"vocab"}
    assert len(items_for(None)) == len(items_for([]))
