"""单元测试：core/utils/data/data_paths.py —— 事件拆分与错放文件归位。

覆盖：daily event 按 scope 拆分合并、role 组合迁移、错放 memory 文件
按命名模式归位（含大小比较）、旧版 Aveline_daily_data 目录搬迁。

所有 IO 落 tmp_path，绝不触碰真实 companion_data。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.utils.data import data_paths as dp


@pytest.fixture()
def debug_on(monkeypatch):
    """打开 data_paths 的 debug 日志开关，用于覆盖调试日志分支。"""
    monkeypatch.setattr(dp, "is_debug_enabled", lambda module: True)


def _base(tmp_path: Path) -> Path:
    """创建并返回隔离的 companion_data 根目录。"""
    base = tmp_path / "companion_data"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _patch_rglob_to_yield(monkeypatch, target_name: str, pattern: str, foreign: Path) -> None:
    """让指定目录名的 rglob(pattern) 返回一个「不属于该目录」的外部路径。"""
    real_rglob = Path.rglob

    def fake_rglob(self, pat, *args, **kwargs):
        if self.name == target_name and pat == pattern:
            yield foreign
            return
        yield from real_rglob(self, pat, *args, **kwargs)

    monkeypatch.setattr(Path, "rglob", fake_rglob)


# ────────────────────────── _migrate_daily_event_layout ──────────────────────────


def test_migrate_daily_event_missing_dir(tmp_path):
    """user_data/daily 不存在时直接返回。"""
    base = _base(tmp_path)
    dp._migrate_daily_event_layout(base)
    assert not (base / dp._USER_DIR / "daily").exists()


def test_migrate_daily_event_splits_and_merges(tmp_path):
    """事件按 scope 拆分；目标已存在时做去重合并，空行/非法行归默认桶。"""
    base = _base(tmp_path)
    events = base / dp._USER_DIR / "daily" / "events"
    events.mkdir(parents=True)
    a_line = json.dumps({"source": "aveline"})
    l_line = json.dumps({"source": "ling"})
    cid_line = json.dumps({"conversation_id": "core_ling"})
    (events / "e1.jsonl").write_text(
        "\n".join([l_line, a_line, "", "bad json", "{}", "[1, 2]", cid_line]), encoding="utf-8"
    )
    a_target = base / dp._AVELINE_DIR / "daily" / "events" / "e1.jsonl"
    a_target.parent.mkdir(parents=True)
    a_target.write_text(a_line + "\n", encoding="utf-8")
    dp._migrate_daily_event_layout(base)
    l_out = (base / dp._LING_DIR / "daily" / "events" / "e1.jsonl").read_text(encoding="utf-8")
    assert l_line in l_out.splitlines() and cid_line in l_out.splitlines()
    a_out = a_target.read_text(encoding="utf-8").splitlines()
    assert a_out.count(a_line) == 1
    assert {"bad json", "{}", "[1, 2]"} <= set(a_out)


def test_migrate_daily_event_single_scope_bucket(tmp_path):
    """只有一个 scope 有事件时，另一个空桶走 continue 分支。"""
    base = _base(tmp_path)
    events = base / dp._USER_DIR / "daily" / "events"
    events.mkdir(parents=True)
    (events / "e2.jsonl").write_text(json.dumps({"source": "aveline"}) + "\n", encoding="utf-8")
    dp._migrate_daily_event_layout(base)
    assert (base / dp._AVELINE_DIR / "daily" / "events" / "e2.jsonl").exists()
    assert not (base / dp._LING_DIR / "daily" / "events" / "e2.jsonl").exists()


def test_migrate_daily_event_read_failure(tmp_path, debug_on):
    """events/*.jsonl 是目录导致读取失败时走兜底分支。"""
    base = _base(tmp_path)
    (base / dp._USER_DIR / "daily" / "events" / "bad.jsonl").mkdir(parents=True)
    dp._migrate_daily_event_layout(base)
    assert (base / dp._USER_DIR / "daily" / "events" / "bad.jsonl").is_dir()


def test_migrate_daily_event_relative_to_failure(tmp_path, monkeypatch, debug_on):
    """rglob 产出无法相对化的路径时跳过（防御分支）。"""
    base = _base(tmp_path)
    (base / dp._USER_DIR / "daily").mkdir(parents=True)
    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}", encoding="utf-8")
    _patch_rglob_to_yield(monkeypatch, "daily", "events/*.jsonl", outside)
    dp._migrate_daily_event_layout(base)
    assert outside.exists()


# ────────────────────────── _migrate_role_layout ──────────────────────────


def test_migrate_role_layout_moves_background_circle(tmp_path):
    """组合迁移：把 user_data/background_circle 归到 dual_role。"""
    base = _base(tmp_path)
    legacy_bg = base / dp._USER_DIR / "background_circle"
    (legacy_bg / "b.json").parent.mkdir(parents=True)
    (legacy_bg / "b.json").write_text("{}", encoding="utf-8")
    dp._migrate_role_layout(base)
    assert (base / "dual_role" / "background_circle" / "b.json").exists()
    assert not legacy_bg.exists()


# ────────────────────────── _migrate_misplaced_memory_files ──────────────────────────


def test_migrate_misplaced_memory_missing_root(tmp_path):
    """aveline memories 不存在时直接返回。"""
    base = _base(tmp_path)
    dp._migrate_misplaced_memory_files(base)
    assert not (base / dp._AVELINE_DIR / "memories").exists()


def test_migrate_misplaced_memory_moves_by_pattern(tmp_path, debug_on):
    """peer_* 归 dual_role，persona/scope ling 与裸角色名归 ling，其余不动。"""
    base = _base(tmp_path)
    mem = base / dp._AVELINE_DIR / "memories"
    mem.mkdir(parents=True)
    for name in (
        "peer_ling_conv_weighted.json",
        "peer_aveline_conv_short.json",
        "private_1__persona__ling_love.json",
        "private_2__scope__ling.json",
        "ling_weighted.json",
        "ling_weighted.json",
        "core_ling_short.json",
        "plain_conv.json",
    ):
        (mem / name).write_text("x", encoding="utf-8")
    (mem / "dir.json").mkdir()  # 目录形式的 .json 应被 is_file 检查跳过
    dp._migrate_misplaced_memory_files(base)
    dual = base / "dual_role" / "memories"
    ling = base / dp._LING_DIR / "memories"
    assert (dual / "peer_ling_conv_weighted.json").exists()
    assert (dual / "peer_aveline_conv_short.json").exists()
    assert (ling / "private_1__persona__ling_love.json").exists()
    assert (ling / "private_2__scope__ling.json").exists()
    assert (ling / "ling_weighted.json").exists()
    assert (ling / "ling_weighted.json").exists()
    assert (ling / "core_ling_short.json").exists()
    assert (mem / "plain_conv.json").exists()
    assert (mem / "dir.json").is_dir()


def test_migrate_misplaced_memory_conflict_keeps_larger(tmp_path, debug_on):
    """目标已存在时：源更小则删源，源更大则替换目标。"""
    base = _base(tmp_path)
    mem = base / dp._AVELINE_DIR / "memories"
    dual = base / "dual_role" / "memories"
    mem.mkdir(parents=True)
    dual.mkdir(parents=True)
    (mem / "peer_ling_small.json").write_text("ab", encoding="utf-8")
    (dual / "peer_ling_small.json").write_text("0123456789", encoding="utf-8")
    (mem / "peer_ling_big.json").write_text("0123456789", encoding="utf-8")
    (dual / "peer_ling_big.json").write_text("ab", encoding="utf-8")
    dp._migrate_misplaced_memory_files(base)
    assert not (mem / "peer_ling_small.json").exists()
    assert (dual / "peer_ling_small.json").read_text(encoding="utf-8") == "0123456789"
    assert not (mem / "peer_ling_big.json").exists()
    assert (dual / "peer_ling_big.json").read_text(encoding="utf-8") == "0123456789"


def test_migrate_misplaced_memory_relative_to_failure(tmp_path, monkeypatch):
    """rglob 产出无法相对化的路径时跳过（ValueError 防御分支）。"""
    base = _base(tmp_path)
    (base / dp._AVELINE_DIR / "memories").mkdir(parents=True)
    outside = tmp_path / "peer_ling_outside.json"
    outside.write_text("x", encoding="utf-8")
    _patch_rglob_to_yield(monkeypatch, "memories", "*.json", outside)
    dp._migrate_misplaced_memory_files(base)
    assert outside.exists()


# ────────────────────────── _migrate_legacy_layout ──────────────────────────


def test_migrate_legacy_layout_missing(tmp_path):
    """旧版目录不存在时直接返回。"""
    dp._migrate_legacy_layout(tmp_path)
    assert not (tmp_path / "companion_data").exists()


def test_migrate_legacy_layout_moves_mapped_and_misc(tmp_path):
    """已映射项归位，未映射项进 legacy_misc，最后删除旧根。"""
    project_root = tmp_path
    legacy = project_root / dp._LEGACY_BASE_NAME
    (legacy / "daily").mkdir(parents=True)
    (legacy / "daily" / "d.json").write_text("d", encoding="utf-8")
    (legacy / "reminders.json").write_text("[]", encoding="utf-8")
    (legacy / "unknown.txt").write_text("u", encoding="utf-8")
    (legacy / "aveline_life").mkdir()
    (legacy / "aveline_life" / "life.json").write_text("l", encoding="utf-8")
    dp._migrate_legacy_layout(project_root)
    base = project_root / dp._BASE_NAME
    assert (base / dp._USER_DIR / "daily" / "d.json").exists()
    assert (base / dp._USER_DIR / "reminders.json").exists()
    assert (base / dp._USER_DIR / "legacy_misc" / "unknown.txt").exists()
    assert (base / dp._AVELINE_DIR / "aveline_life" / "life.json").exists()
    assert not legacy.exists()


def test_migrate_legacy_layout_rmdir_failure(tmp_path, debug_on):
    """目录→文件冲突导致旧根删不掉时走兜底分支。"""
    project_root = tmp_path
    legacy = project_root / dp._LEGACY_BASE_NAME
    (legacy / "daily").mkdir(parents=True)
    (legacy / "daily" / "d.json").write_text("d", encoding="utf-8")
    target = project_root / dp._BASE_NAME / dp._USER_DIR / "daily"
    target.parent.mkdir(parents=True)
    target.write_text("blocker", encoding="utf-8")
    dp._migrate_legacy_layout(project_root)
    assert legacy.exists()
    assert target.read_text(encoding="utf-8") == "blocker"
