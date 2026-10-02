"""单元测试：core/utils/data/data_paths_migrations.py

覆盖数据目录迁移逻辑的各条分支：幂等跳过、旧目录不存在、目标冲突、
多步骤迁移顺序、异常兜底分支等。

所有文件 IO 一律落在 ``tmp_path``，绝不触碰真实的 companion_data / user_data。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.utils.data import data_paths_migrations as m


# ────────────────────────── 公共工具 ──────────────────────────


def _base(tmp_path: Path) -> Path:
    """创建并返回一个隔离的 companion_data 根目录。"""
    base = tmp_path / "companion_data"
    base.mkdir(parents=True, exist_ok=True)
    return base


@pytest.fixture()
def debug_on(monkeypatch):
    """打开 data_paths 的 debug 日志开关，用于覆盖调试日志分支。"""
    monkeypatch.setattr(m, "is_debug_enabled", lambda module: True)


def _patch_rglob_to_yield(monkeypatch, target_name: str, pattern: str, foreign: Path) -> None:
    """让指定目录名的 rglob(pattern) 返回一个「不属于该目录」的外部路径。

    用于构造 ``relative_to`` 失败这一防御分支（真实文件系统 API 不会产生这种结果）。
    """
    real_rglob = Path.rglob

    def fake_rglob(self, pat, *args, **kwargs):
        if self.name == target_name and pat == pattern:
            yield foreign
            return
        yield from real_rglob(self, pat, *args, **kwargs)

    monkeypatch.setattr(Path, "rglob", fake_rglob)


# ────────────────────────── _move_path_merge ──────────────────────────


def test_move_path_merge_src_missing_is_noop(tmp_path):
    """源不存在时直接返回，不创建目标。"""
    src = tmp_path / "no_such"
    dst = tmp_path / "dst" / "x"
    m._move_path_merge(src, dst)
    assert not dst.exists()
    assert not dst.parent.exists()


def test_move_path_merge_dst_missing_moves(tmp_path):
    """目标不存在时直接移动。"""
    src = tmp_path / "a" / "f.txt"
    src.parent.mkdir(parents=True)
    src.write_text("hello", encoding="utf-8")
    dst = tmp_path / "b" / "deep" / "f.txt"
    m._move_path_merge(src, dst)
    assert dst.read_text(encoding="utf-8") == "hello"
    assert not src.exists()


def test_move_path_merge_file_onto_file_keeps_both(tmp_path):
    """文件→文件冲突时不做任何事。"""
    src = tmp_path / "s.txt"
    src.write_text("src", encoding="utf-8")
    dst = tmp_path / "d.txt"
    dst.write_text("dst", encoding="utf-8")
    m._move_path_merge(src, dst)
    assert src.read_text(encoding="utf-8") == "src"
    assert dst.read_text(encoding="utf-8") == "dst"


def test_move_path_merge_file_onto_dir_keeps_src(tmp_path):
    """文件→目录冲突时保留源文件。"""
    src = tmp_path / "s.txt"
    src.write_text("src", encoding="utf-8")
    dst = tmp_path / "d"
    dst.mkdir()
    m._move_path_merge(src, dst)
    assert src.exists()
    assert dst.is_dir()


def test_move_path_merge_dir_onto_file_keeps_src(tmp_path):
    """目录→文件冲突时保留源目录。"""
    src = tmp_path / "s"
    src.mkdir()
    (src / "child.txt").write_text("c", encoding="utf-8")
    dst = tmp_path / "d.txt"
    dst.write_text("d", encoding="utf-8")
    m._move_path_merge(src, dst)
    assert src.is_dir()
    assert (src / "child.txt").exists()


def test_move_path_merge_dirs_merge_recursively(tmp_path):
    """目录→目录时递归合并，随后删除源目录。"""
    src = tmp_path / "s"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "a.txt").write_text("a", encoding="utf-8")
    (src / "top.txt").write_text("t", encoding="utf-8")
    dst = tmp_path / "d"
    dst.mkdir()
    m._move_path_merge(src, dst)
    assert (dst / "sub" / "a.txt").read_text(encoding="utf-8") == "a"
    assert (dst / "top.txt").read_text(encoding="utf-8") == "t"
    assert not src.exists()


def test_move_path_merge_rmdir_failure_logs(tmp_path, debug_on):
    """合并后源目录仍非空（子项冲突未移动）时，rmdir 失败走兜底分支。"""
    src = tmp_path / "s"
    src.mkdir()
    (src / "conflict.txt").write_text("src", encoding="utf-8")
    dst = tmp_path / "d"
    dst.mkdir()
    (dst / "conflict.txt").write_text("dst", encoding="utf-8")
    m._move_path_merge(src, dst)
    # 子文件冲突未被移动，源目录删除失败但不应抛异常
    assert src.exists()
    assert (src / "conflict.txt").read_text(encoding="utf-8") == "src"


# ────────────────────────── _scope_to_chat_history_root ──────────────────────────


@pytest.mark.parametrize(
    ("scope", "dir_name"),
    [
        ("user", m._USER_DIR),
        ("ling", m._LING_DIR),
        ("xiaolu", m._XIAOLU_DIR),
        ("yeye", m._YEYE_DIR),
        ("dual_role", m._AVELINE_DIR),
        ("aveline", m._AVELINE_DIR),
    ],
)
def test_scope_to_chat_history_root_builtin(tmp_path, scope, dir_name):
    """各内置 scope 映射到对应角色目录。"""
    base = tmp_path / "companion_data"
    assert m._scope_to_chat_history_root(base, scope) == (
        base / dir_name / "chat_history"
    ).resolve()


def test_scope_to_chat_history_root_invalid_falls_back(tmp_path):
    """非法 scope 归到 aveline。"""
    base = tmp_path / "companion_data"
    assert m._scope_to_chat_history_root(base, "not_a_scope") == (
        base / m._AVELINE_DIR / "chat_history"
    ).resolve()


def test_scope_to_chat_history_root_dynamic(tmp_path, monkeypatch):
    """动态 scope 使用其声明的目录名。"""
    base = tmp_path / "companion_data"
    monkeypatch.setattr(m, "_VALID_SCOPES", set(m._VALID_SCOPES) | {"custom_role"})
    monkeypatch.setattr(
        m,
        "_DYNAMIC_SCOPES",
        {**m._DYNAMIC_SCOPES, "custom_role": {"dir": "custom_role_data", "slugs": set()}},
    )
    assert m._scope_to_chat_history_root(base, "custom_role") == (
        base / "custom_role_data" / "chat_history"
    ).resolve()


# ────────────────────────── iter_existing_chat_history_roots ──────────────────────────


def test_iter_existing_chat_history_roots_only_existing(tmp_path, monkeypatch):
    """只产出实际存在的 chat_history 根目录（含动态 scope）。"""
    base = tmp_path / "companion_data"
    (base / m._USER_DIR / "chat_history").mkdir(parents=True)
    (base / m._LING_DIR / "chat_history").mkdir(parents=True)
    (base / "dyn_data" / "chat_history").mkdir(parents=True)
    monkeypatch.setattr(m, "_DYNAMIC_SCOPES", {"dyn": {"dir": "dyn_data", "slugs": set()}})
    roots = list(m.iter_existing_chat_history_roots(base))
    assert len(roots) == 3
    assert (base / m._USER_DIR / "chat_history").resolve() in roots
    assert (base / m._LING_DIR / "chat_history").resolve() in roots
    assert (base / "dyn_data" / "chat_history").resolve() in roots


def test_iter_existing_chat_history_roots_none(tmp_path, monkeypatch):
    """一个都不存在时产出空序列。"""
    base = tmp_path / "companion_data"
    base.mkdir()
    monkeypatch.setattr(m, "_DYNAMIC_SCOPES", {})
    assert list(m.iter_existing_chat_history_roots(base)) == []


# ────────────────────────── _resolve_scope_from_chat_history_path ──────────────────────────


def test_resolve_scope_from_chat_history_path_ling_by_cn_name():
    """路径含「Ling」判定为 ling。"""
    assert m._resolve_scope_from_chat_history_path(["Ling", "conv.jsonl"]) == "ling"


def test_resolve_scope_from_chat_history_path_ling_by_slug():
    """路径含 ling 判定为 ling。"""
    assert m._resolve_scope_from_chat_history_path(["LING", "conv.jsonl"]) == "ling"


def test_resolve_scope_from_chat_history_path_default_aveline():
    """其余情况归 aveline，空片段被过滤。"""
    assert m._resolve_scope_from_chat_history_path([None, "", "other"]) == "aveline"
    assert m._resolve_scope_from_chat_history_path([]) == "aveline"


# ────────────────────────── _target_chat_history_parts ──────────────────────────


def test_target_chat_history_parts_drops_middle_level():
    """层级 >= 5 时去掉第 4 段（索引 3）。"""
    assert m._target_chat_history_parts(["a", "b", "c", "d", "e"]) == ["a", "b", "c", "e"]


def test_target_chat_history_parts_short_and_filtered():
    """层级 < 5 时原样返回，并过滤空片段。"""
    assert m._target_chat_history_parts([None, "a", "b"]) == ["a", "b"]
    assert m._target_chat_history_parts(["a", "b", "c", "d"]) == ["a", "b", "c", "d"]


# ────────────────────────── _split_daily_event_scope ──────────────────────────


def test_split_daily_event_scope_invalid_json_default(debug_on):
    """非法 JSON 返回默认 scope。"""
    assert m._split_daily_event_scope("not json", default_scope="aveline") == "aveline"


def test_split_daily_event_scope_non_dict_default():
    """JSON 不是对象时返回默认 scope。"""
    assert m._split_daily_event_scope("[1, 2]", default_scope="ling") == "ling"


def test_split_daily_event_scope_by_conversation_id():
    """有 conversation_id 时按其解析 scope。"""
    line = json.dumps({"conversation_id": "core_ling"})
    assert m._split_daily_event_scope(line, default_scope="aveline") == "ling"


def test_split_daily_event_scope_by_source():
    """无 conversation_id 时按 source 解析 scope。"""
    line = json.dumps({"source": "ling"})
    assert m._split_daily_event_scope(line, default_scope="aveline") == "ling"


def test_split_daily_event_scope_empty_payload_default():
    """对象里两个字段都为空时返回默认 scope。"""
    assert m._split_daily_event_scope("{}", default_scope="aveline") == "aveline"


# ────────────────────────── _migrate_active_care_layout ──────────────────────────


def test_migrate_active_care_layout_missing_root(tmp_path):
    """旧 active_care 根不存在时直接返回。"""
    base = _base(tmp_path)
    m._migrate_active_care_layout(base)
    assert not (base / "active_care").exists()


def test_migrate_active_care_layout_moves_roles(tmp_path):
    """aveline / ling 两个子目录分别归位并删除旧根。"""
    base = _base(tmp_path)
    legacy = base / "active_care"
    (legacy / "aveline").mkdir(parents=True)
    (legacy / "aveline" / "a.json").write_text("a", encoding="utf-8")
    (legacy / "ling").mkdir(parents=True)
    (legacy / "ling" / "l.json").write_text("l", encoding="utf-8")
    m._migrate_active_care_layout(base)
    assert (base / m._AVELINE_DIR / "active_care" / "a.json").exists()
    assert (base / m._LING_DIR / "active_care" / "l.json").exists()
    assert not legacy.exists()


def test_migrate_active_care_layout_rmdir_failure(tmp_path, debug_on):
    """存在无法识别的残留子目录时，旧根删除失败走兜底分支。"""
    base = _base(tmp_path)
    legacy = base / "active_care"
    (legacy / "aveline").mkdir(parents=True)
    (legacy / "misc").mkdir(parents=True)
    m._migrate_active_care_layout(base)
    assert legacy.exists()
    assert (legacy / "misc").is_dir()


# ────────────────────────── _migrate_user_chat_history_layout ──────────────────────────


def test_migrate_user_chat_history_missing_dir(tmp_path):
    """user_data/chat_history 不存在时直接返回。"""
    base = _base(tmp_path)
    m._migrate_user_chat_history_layout(base)
    assert not (base / m._USER_DIR / "chat_history").exists()


def test_migrate_user_chat_history_buckets_and_removes_index(tmp_path):
    """按 scope 分桶移动 jsonl，并删除 index.json。"""
    base = _base(tmp_path)
    user_chat = base / m._USER_DIR / "chat_history"
    (user_chat / "Ling").mkdir(parents=True)
    (user_chat / "Ling" / "conv1.jsonl").write_text("{}", encoding="utf-8")
    (user_chat / "other").mkdir(parents=True)
    (user_chat / "other" / "conv2.jsonl").write_text("{}", encoding="utf-8")
    (user_chat / "index.json").write_text("[]", encoding="utf-8")
    m._migrate_user_chat_history_layout(base)
    assert (base / m._LING_DIR / "chat_history" / "Ling" / "conv1.jsonl").exists()
    assert (base / m._AVELINE_DIR / "chat_history" / "other" / "conv2.jsonl").exists()
    assert not (user_chat / "index.json").exists()


def test_migrate_user_chat_history_relative_to_failure(tmp_path, monkeypatch, debug_on):
    """rglob 产出无法相对化的路径时跳过而非崩溃（防御分支）。"""
    base = _base(tmp_path)
    user_chat = base / m._USER_DIR / "chat_history"
    user_chat.mkdir(parents=True)
    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}", encoding="utf-8")
    _patch_rglob_to_yield(monkeypatch, "chat_history", "*.jsonl", outside)
    m._migrate_user_chat_history_layout(base)
    assert outside.exists()


def test_migrate_user_chat_history_index_unlink_failure(tmp_path, debug_on):
    """index.json 是目录导致 unlink 失败时走兜底分支。"""
    base = _base(tmp_path)
    user_chat = base / m._USER_DIR / "chat_history"
    (user_chat / "index.json").mkdir(parents=True)
    m._migrate_user_chat_history_layout(base)
    assert (user_chat / "index.json").is_dir()


# ────────────────────────── _migrate_daily_diary_layout ──────────────────────────


def test_migrate_daily_diary_missing_dir(tmp_path):
    """user_data/daily 不存在时直接返回。"""
    base = _base(tmp_path)
    m._migrate_daily_diary_layout(base)
    assert not (base / m._USER_DIR / "daily").exists()


def test_migrate_daily_diary_buckets_by_scope(tmp_path):
    """按 source 把日记分到 aveline / ling，并跳过非角色 scope。"""
    base = _base(tmp_path)
    daily = base / m._USER_DIR / "daily"
    (daily / "diary").mkdir(parents=True)
    (daily / "diary" / "a.json").write_text(
        json.dumps({"source": "aveline"}, ensure_ascii=False), encoding="utf-8"
    )
    (daily / "diary" / "l.json").write_text(
        json.dumps({"source": "ling"}, ensure_ascii=False), encoding="utf-8"
    )
    (daily / "diary" / "u.json").write_text(
        json.dumps({"source": "unknown_user"}, ensure_ascii=False), encoding="utf-8"
    )
    m._migrate_daily_diary_layout(base)
    assert (base / m._AVELINE_DIR / "daily" / "diary" / "a.json").exists()
    assert (base / m._LING_DIR / "daily" / "diary" / "l.json").exists()
    assert (daily / "diary" / "u.json").exists()


def test_migrate_daily_diary_invalid_json_skipped(tmp_path, debug_on):
    """非法 JSON 的日记被跳过。"""
    base = _base(tmp_path)
    daily = base / m._USER_DIR / "daily"
    (daily / "diary").mkdir(parents=True)
    (daily / "diary" / "bad.json").write_text("not json", encoding="utf-8")
    m._migrate_daily_diary_layout(base)
    assert (daily / "diary" / "bad.json").exists()


def test_migrate_daily_diary_relative_to_failure(tmp_path, monkeypatch, debug_on):
    """rglob 产出无法相对化的路径时跳过（防御分支）。"""
    base = _base(tmp_path)
    daily = base / m._USER_DIR / "daily"
    daily.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    # source 必须是 aveline/ling，否则会在 scope 过滤处提前 continue，走不到 relative_to
    outside.write_text(json.dumps({"source": "aveline"}, ensure_ascii=False), encoding="utf-8")
    _patch_rglob_to_yield(monkeypatch, "daily", "diary/*.json", outside)
    m._migrate_daily_diary_layout(base)
    assert outside.exists()


# ────────────────────────── _migrate_daily_event_layout ──────────────────────────


def test_migrate_daily_event_missing_dir(tmp_path):
    """user_data/daily 不存在时直接返回。"""
    base = _base(tmp_path)
    m._migrate_daily_event_layout(base)
    assert not (base / m._USER_DIR / "daily").exists()


def test_migrate_daily_event_splits_and_merges(tmp_path):
    """事件按 scope 拆分；目标已存在时做去重合并。"""
    base = _base(tmp_path)
    daily = base / m._USER_DIR / "daily"
    (daily / "events").mkdir(parents=True)
    aveline_line = json.dumps({"source": "aveline"})
    ling_line = json.dumps({"source": "ling"})
    cid_line = json.dumps({"conversation_id": "core_ling"})
    lines = [ling_line, aveline_line, "", "bad json", "{}", "[1, 2]", cid_line]
    (daily / "events" / "e1.jsonl").write_text("\n".join(lines), encoding="utf-8")
    # 预置 aveline 目标，覆盖「已存在」分支与去重逻辑
    aveline_target = base / m._AVELINE_DIR / "daily" / "events" / "e1.jsonl"
    aveline_target.parent.mkdir(parents=True)
    aveline_target.write_text(aveline_line + "\n", encoding="utf-8")
    m._migrate_daily_event_layout(base)
    ling_target = base / m._LING_DIR / "daily" / "events" / "e1.jsonl"
    assert ling_target.exists()
    ling_out = ling_target.read_text(encoding="utf-8").splitlines()
    assert ling_line in ling_out
    assert cid_line in ling_out
    aveline_out = aveline_target.read_text(encoding="utf-8").splitlines()
    # 去重：aveline_line 只出现一次
    assert aveline_out.count(aveline_line) == 1
    assert "bad json" in aveline_out
    assert "{}" in aveline_out
    assert "[1, 2]" in aveline_out


def test_migrate_daily_event_single_scope_bucket(tmp_path):
    """只有一个 scope 有事件时，另一个空桶走 continue 分支。"""
    base = _base(tmp_path)
    daily = base / m._USER_DIR / "daily"
    (daily / "events").mkdir(parents=True)
    (daily / "events" / "e2.jsonl").write_text(
        json.dumps({"source": "aveline"}) + "\n", encoding="utf-8"
    )
    m._migrate_daily_event_layout(base)
    assert (base / m._AVELINE_DIR / "daily" / "events" / "e2.jsonl").exists()
    assert not (base / m._LING_DIR / "daily" / "events" / "e2.jsonl").exists()


def test_migrate_daily_event_read_failure(tmp_path, debug_on):
    """events/*.jsonl 是目录导致读取失败时走兜底分支。"""
    base = _base(tmp_path)
    daily = base / m._USER_DIR / "daily"
    (daily / "events" / "bad.jsonl").mkdir(parents=True)
    m._migrate_daily_event_layout(base)
    assert (daily / "events" / "bad.jsonl").is_dir()


def test_migrate_daily_event_relative_to_failure(tmp_path, monkeypatch, debug_on):
    """rglob 产出无法相对化的路径时跳过（防御分支）。"""
    base = _base(tmp_path)
    daily = base / m._USER_DIR / "daily"
    daily.mkdir(parents=True)
    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}", encoding="utf-8")
    _patch_rglob_to_yield(monkeypatch, "daily", "events/*.jsonl", outside)
    m._migrate_daily_event_layout(base)
    assert outside.exists()


# ────────────────────────── _migrate_misplaced_memory_files ──────────────────────────


def test_migrate_misplaced_memory_missing_root(tmp_path):
    """aveline memories 不存在时直接返回。"""
    base = _base(tmp_path)
    m._migrate_misplaced_memory_files(base)
    assert not (base / m._AVELINE_DIR / "memories").exists()


def test_migrate_misplaced_memory_moves_by_pattern(tmp_path, debug_on):
    """peer_* 归 dual_role，persona/scope ling 文件归 ling，其余保持不动。"""
    base = _base(tmp_path)
    aveline_memories = base / m._AVELINE_DIR / "memories"
    aveline_memories.mkdir(parents=True)
    (aveline_memories / "peer_ling_conv_weighted.json").write_text("x", encoding="utf-8")
    (aveline_memories / "peer_aveline_conv_short.json").write_text("x", encoding="utf-8")
    (aveline_memories / "private_1__persona__ling_love.json").write_text("x", encoding="utf-8")
    (aveline_memories / "private_2__scope__ling.json").write_text("x", encoding="utf-8")
    (aveline_memories / "plain_conv.json").write_text("x", encoding="utf-8")
    # 目录形式的 .json 应被 is_file 检查跳过
    (aveline_memories / "dir.json").mkdir()
    m._migrate_misplaced_memory_files(base)
    dual_memories = base / "dual_role" / "memories"
    ling_memories = base / m._LING_DIR / "memories"
    assert (dual_memories / "peer_ling_conv_weighted.json").exists()
    assert (dual_memories / "peer_aveline_conv_short.json").exists()
    assert (ling_memories / "private_1__persona__ling_love.json").exists()
    assert (ling_memories / "private_2__scope__ling.json").exists()
    assert (aveline_memories / "plain_conv.json").exists()
    assert (aveline_memories / "dir.json").is_dir()


def test_migrate_misplaced_memory_conflict_keeps_larger(tmp_path, debug_on):
    """目标已存在时：源更小则删源，源更大则替换目标。"""
    base = _base(tmp_path)
    aveline_memories = base / m._AVELINE_DIR / "memories"
    dual_memories = base / "dual_role" / "memories"
    aveline_memories.mkdir(parents=True)
    dual_memories.mkdir(parents=True)

    (aveline_memories / "peer_ling_small.json").write_text("ab", encoding="utf-8")
    (dual_memories / "peer_ling_small.json").write_text("0123456789", encoding="utf-8")

    (aveline_memories / "peer_ling_big.json").write_text("0123456789", encoding="utf-8")
    (dual_memories / "peer_ling_big.json").write_text("ab", encoding="utf-8")

    m._migrate_misplaced_memory_files(base)

    # 源更小 -> 删除源，保留更大的目标
    assert not (aveline_memories / "peer_ling_small.json").exists()
    assert (dual_memories / "peer_ling_small.json").read_text(encoding="utf-8") == "0123456789"
    # 源更大 -> 删除目标，源被移过去
    assert not (aveline_memories / "peer_ling_big.json").exists()
    assert (dual_memories / "peer_ling_big.json").read_text(encoding="utf-8") == "0123456789"


def test_migrate_misplaced_memory_relative_to_failure(tmp_path, monkeypatch):
    """rglob 产出无法相对化的路径时跳过（防御分支）。"""
    base = _base(tmp_path)
    aveline_memories = base / m._AVELINE_DIR / "memories"
    aveline_memories.mkdir(parents=True)
    outside = tmp_path / "peer_ling_outside.json"
    outside.write_text("x", encoding="utf-8")
    _patch_rglob_to_yield(monkeypatch, "memories", "*.json", outside)
    m._migrate_misplaced_memory_files(base)
    assert outside.exists()


# ────────────────────────── _migrate_role_layout ──────────────────────────


def test_migrate_role_layout_moves_background_circle(tmp_path):
    """组合迁移：把 user_data/background_circle 归到 dual_role。"""
    base = _base(tmp_path)
    legacy_bg = base / m._USER_DIR / "background_circle"
    (legacy_bg / "b.json").parent.mkdir(parents=True)
    (legacy_bg / "b.json").write_text("{}", encoding="utf-8")
    m._migrate_role_layout(base)
    assert (base / "dual_role" / "background_circle" / "b.json").exists()
    assert not legacy_bg.exists()


# ────────────────────────── _migrate_legacy_layout ──────────────────────────


def test_migrate_legacy_layout_missing(tmp_path):
    """旧版目录不存在时直接返回。"""
    m._migrate_legacy_layout(tmp_path)
    assert not (tmp_path / "companion_data").exists()


def test_migrate_legacy_layout_moves_mapped_and_misc(tmp_path):
    """已映射项归位，未映射项进 legacy_misc，最后删除旧根。"""
    project_root = tmp_path
    legacy = project_root / m._LEGACY_BASE_NAME
    (legacy / "daily").mkdir(parents=True)
    (legacy / "daily" / "d.json").write_text("d", encoding="utf-8")
    (legacy / "reminders.json").write_text("[]", encoding="utf-8")
    (legacy / "unknown.txt").write_text("u", encoding="utf-8")
    (legacy / "aveline_life").mkdir()
    (legacy / "aveline_life" / "life.json").write_text("l", encoding="utf-8")
    m._migrate_legacy_layout(project_root)
    base = project_root / m._BASE_NAME
    assert (base / m._USER_DIR / "daily" / "d.json").exists()
    assert (base / m._USER_DIR / "reminders.json").exists()
    assert (base / m._USER_DIR / "legacy_misc" / "unknown.txt").exists()
    assert (base / m._AVELINE_DIR / "aveline_life" / "life.json").exists()
    assert not legacy.exists()


def test_migrate_legacy_layout_rmdir_failure(tmp_path, debug_on):
    """目录→文件冲突导致旧根删不掉时走兜底分支。"""
    project_root = tmp_path
    legacy = project_root / m._LEGACY_BASE_NAME
    (legacy / "daily").mkdir(parents=True)
    (legacy / "daily" / "d.json").write_text("d", encoding="utf-8")
    # 预置目标为文件，使 daily 目录无法被移动
    target = project_root / m._BASE_NAME / m._USER_DIR / "daily"
    target.parent.mkdir(parents=True)
    target.write_text("blocker", encoding="utf-8")
    m._migrate_legacy_layout(project_root)
    assert legacy.exists()
    assert target.read_text(encoding="utf-8") == "blocker"


# ────────────────────────── _migrate_self_meals_from_user_records ──────────────────────────


def _write_record(base: Path, y: str, mo: str, d: str, meals) -> Path:
    """在 user_data/daily_records/<y>/<mo>/<d>/ 下写一个 daily_record.json。"""
    rec_dir = base / m._USER_DIR / "daily_records" / y / mo / d
    rec_dir.mkdir(parents=True, exist_ok=True)
    rec = rec_dir / "daily_record.json"
    rec.write_text(json.dumps({"meals": meals}, ensure_ascii=False), encoding="utf-8")
    return rec


def test_self_meals_missing_records(tmp_path):
    """daily_records 不存在时直接返回。"""
    base = _base(tmp_path)
    m._migrate_self_meals_from_user_records(base)
    assert not (base / m._USER_DIR / "daily_records").exists()


def test_self_meals_classifies_and_splits(tmp_path):
    """各类进食记录按前缀分流到 user / aveline / ling。"""
    base = _base(tmp_path)
    rec = _write_record(
        base,
        "2024",
        "01",
        "15",
        [
            {"content": "自主进食(ling):鱼"},
            {"content": "自主进食:米饭"},
            {"content": "投喂(ling):x"},
            {"content": "投喂:y"},
            {"content": "普通餐"},
            "notdict",
        ],
    )
    m._migrate_self_meals_from_user_records(base)
    remaining = json.loads(rec.read_text(encoding="utf-8"))
    assert remaining["meals"] == [{"content": "普通餐"}]
    aveline = base / m._AVELINE_DIR / "life_records" / "2024" / "01" / "15" / "daily_record.json"
    ling = base / m._LING_DIR / "life_records" / "2024" / "01" / "15" / "daily_record.json"
    a_payload = json.loads(aveline.read_text(encoding="utf-8"))
    l_payload = json.loads(ling.read_text(encoding="utf-8"))
    assert a_payload["date"] == "2024-01-15"
    assert {x["content"] for x in a_payload["meals"]} == {"自主进食:米饭", "投喂:y"}
    assert {x["content"] for x in l_payload["meals"]} == {"自主进食(ling):鱼", "投喂(ling):x"}


def test_self_meals_skips_empty_and_non_list(tmp_path):
    """meals 非列表或为空时跳过；没有自主进食项时也跳过。"""
    base = _base(tmp_path)
    rec_dir = base / m._USER_DIR / "daily_records" / "2024" / "07" / "01"
    rec_dir.mkdir(parents=True)
    (rec_dir / "daily_record.json").write_text(
        json.dumps({"meals": "bad"}, ensure_ascii=False), encoding="utf-8"
    )
    _write_record(base, "2024", "07", "02", [])
    _write_record(base, "2024", "07", "03", [{"content": "普通"}])
    m._migrate_self_meals_from_user_records(base)
    assert not (base / m._AVELINE_DIR / "life_records").exists()
    assert not (base / m._LING_DIR / "life_records").exists()


def test_self_meals_invalid_json_skipped(tmp_path, debug_on):
    """非法 JSON 的 daily_record.json 被跳过。"""
    base = _base(tmp_path)
    rec_dir = base / m._USER_DIR / "daily_records" / "2024" / "08" / "01"
    rec_dir.mkdir(parents=True)
    (rec_dir / "daily_record.json").write_text("not json", encoding="utf-8")
    m._migrate_self_meals_from_user_records(base)
    assert (rec_dir / "daily_record.json").read_text(encoding="utf-8") == "not json"


def test_self_meals_aveline_target_parse_failure(tmp_path, debug_on):
    """aveline 目标已存在但内容非法时，用默认 payload 重建。"""
    base = _base(tmp_path)
    _write_record(base, "2024", "02", "20", [{"content": "自主进食:面包"}])
    target = base / m._AVELINE_DIR / "life_records" / "2024" / "02" / "20" / "daily_record.json"
    target.parent.mkdir(parents=True)
    target.write_text("broken", encoding="utf-8")
    m._migrate_self_meals_from_user_records(base)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["date"] == "2024-02-20"
    assert payload["meals"] == [{"content": "自主进食:面包"}]


def test_self_meals_aveline_target_meals_not_list(tmp_path):
    """aveline 目标已存在但 meals 不是列表时，重置为列表再追加。"""
    base = _base(tmp_path)
    _write_record(base, "2024", "03", "10", [{"content": "自主进食:蛋"}])
    target = base / m._AVELINE_DIR / "life_records" / "2024" / "03" / "10" / "daily_record.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"date": "2024-03-10", "meals": "bad"}), encoding="utf-8")
    m._migrate_self_meals_from_user_records(base)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["meals"] == [{"content": "自主进食:蛋"}]


def test_self_meals_aveline_target_append_no_duplicate(tmp_path):
    """aveline 目标已有同一条目时不重复追加。"""
    base = _base(tmp_path)
    _write_record(base, "2024", "03", "11", [{"content": "自主进食:蛋"}])
    target = base / m._AVELINE_DIR / "life_records" / "2024" / "03" / "11" / "daily_record.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps({"date": "2024-03-11", "meals": [{"content": "自主进食:蛋"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    m._migrate_self_meals_from_user_records(base)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["meals"] == [{"content": "自主进食:蛋"}]


def test_self_meals_ling_target_parse_failure(tmp_path, debug_on):
    """ling 目标已存在但内容非法时，用默认 payload 重建。"""
    base = _base(tmp_path)
    _write_record(base, "2024", "04", "05", [{"content": "自主进食(ling):草"}])
    target = base / m._LING_DIR / "life_records" / "2024" / "04" / "05" / "daily_record.json"
    target.parent.mkdir(parents=True)
    target.write_text("broken", encoding="utf-8")
    m._migrate_self_meals_from_user_records(base)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["date"] == "2024-04-05"
    assert payload["meals"] == [{"content": "自主进食(ling):草"}]


def test_self_meals_ling_target_meals_not_list(tmp_path):
    """ling 目标已存在但 meals 不是列表时，重置为列表再追加。"""
    base = _base(tmp_path)
    _write_record(base, "2024", "05", "12", [{"content": "自主进食(ling):草"}])
    target = base / m._LING_DIR / "life_records" / "2024" / "05" / "12" / "daily_record.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"date": "2024-05-12", "meals": "bad"}), encoding="utf-8")
    m._migrate_self_meals_from_user_records(base)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["meals"] == [{"content": "自主进食(ling):草"}]


def test_self_meals_source_write_failure(tmp_path, monkeypatch):
    """源记录写回失败时跳过，不产生任何目标文件。"""
    base = _base(tmp_path)
    rec = _write_record(base, "2024", "06", "18", [{"content": "自主进食:米饭"}])
    real_write_text = Path.write_text

    def fake_write_text(self, *args, **kwargs):
        if self.name == "daily_record.json" and m._USER_DIR in str(self):
            raise OSError("simulated source write failure")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fake_write_text)
    m._migrate_self_meals_from_user_records(base)
    assert not (base / m._AVELINE_DIR / "life_records").exists()
    assert rec.exists()


def test_self_meals_aveline_target_write_failure(tmp_path, monkeypatch):
    """aveline 目标写入失败时走警告分支。"""
    base = _base(tmp_path)
    _write_record(base, "2024", "06", "19", [{"content": "自主进食:米饭"}])
    real_write_text = Path.write_text

    def fake_write_text(self, *args, **kwargs):
        if "life_records" in str(self) and m._AVELINE_DIR in str(self):
            raise OSError("simulated aveline write failure")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fake_write_text)
    m._migrate_self_meals_from_user_records(base)
    target = base / m._AVELINE_DIR / "life_records" / "2024" / "06" / "19" / "daily_record.json"
    assert not target.exists()


def test_self_meals_ling_target_write_failure(tmp_path, monkeypatch):
    """ling 目标写入失败时走警告分支。"""
    base = _base(tmp_path)
    _write_record(base, "2024", "06", "20", [{"content": "自主进食(ling):草"}])
    real_write_text = Path.write_text

    def fake_write_text(self, *args, **kwargs):
        if "life_records" in str(self) and m._LING_DIR in str(self):
            raise OSError("simulated ling write failure")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fake_write_text)
    m._migrate_self_meals_from_user_records(base)
    target = base / m._LING_DIR / "life_records" / "2024" / "06" / "20" / "daily_record.json"
    assert not target.exists()


# ────────────────────────── _is_ling_persona_name ──────────────────────────


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Ling", True),
        ("ling", True),
        ("LING", True),
        ("ling", True),
        ("wangling", True),
        ("  ling  ", True),
        ("aveline", False),
        ("", False),
        (None, False),
    ],
)
def test_is_ling_persona_name(name, expected):
    """识别Ling相关的 persona 名。"""
    assert m._is_ling_persona_name(name) is expected


# ────────────────────────── _migrate_persona_export_layout ──────────────────────────


def test_migrate_persona_export_missing_root(tmp_path):
    """旧 persona_data 不存在时直接返回。"""
    base = _base(tmp_path)
    m._migrate_persona_export_layout(base)
    assert not (base / m._LING_DIR / "persona_data").exists()


def test_migrate_persona_export_renames(tmp_path):
    """Ling persona 归 ling，七濑 Aveline 归 aveline。"""
    base = _base(tmp_path)
    old_root = base / m._AVELINE_DIR / "persona_data"
    (old_root / "Ling").mkdir(parents=True)
    (old_root / "Ling" / "p.json").write_text("{}", encoding="utf-8")
    (old_root / "aveline").mkdir()
    (old_root / "aveline" / "a.json").write_text("{}", encoding="utf-8")
    (old_root / "七濑 Aveline").mkdir()
    (old_root / "七濑 Aveline" / "q.json").write_text("{}", encoding="utf-8")
    m._migrate_persona_export_layout(base)
    ling_root = base / m._LING_DIR / "persona_data"
    assert (ling_root / "ling" / "p.json").exists()
    assert not (ling_root / "Ling").exists()
    assert (old_root / "aveline" / "a.json").exists()
    assert (old_root / "aveline" / "q.json").exists()
    assert not (old_root / "七濑 Aveline").exists()


# ────────────────────────── _migrate_core_memory_layout ──────────────────────────


def test_migrate_core_memory_missing_base(tmp_path):
    """base 不存在时直接返回。"""
    base = tmp_path / "nope"
    m._migrate_core_memory_layout(base)
    assert not base.exists()


def test_migrate_core_memory_merges(tmp_path):
    """旧 memory/ 合并进 memories/core_memory/，非目录项被跳过。"""
    base = _base(tmp_path)
    (base / "notes.txt").write_text("n", encoding="utf-8")
    legacy = base / m._AVELINE_DIR / "memory"
    (legacy / "archive").mkdir(parents=True)
    (legacy / "archive" / "old.md").write_text("o", encoding="utf-8")
    (legacy / "2024-01-01.md").write_text("d", encoding="utf-8")
    # 没有 memory 子目录的角色目录应被跳过
    (base / m._LING_DIR).mkdir()
    m._migrate_core_memory_layout(base)
    target = base / m._AVELINE_DIR / "memories" / "core_memory"
    assert (target / "archive" / "old.md").exists()
    assert (target / "2024-01-01.md").exists()
    assert not legacy.exists()
    assert (base / "notes.txt").exists()


def test_migrate_core_memory_move_failure(tmp_path):
    """目标父路径被文件占据导致移动失败时走警告分支。"""
    base = _base(tmp_path)
    legacy = base / m._AVELINE_DIR / "memory"
    legacy.mkdir(parents=True)
    (legacy / "x.md").write_text("x", encoding="utf-8")
    # memories 是文件，mkdir 会失败
    (base / m._AVELINE_DIR / "memories").write_text("blocker", encoding="utf-8")
    m._migrate_core_memory_layout(base)
    assert legacy.exists()
    assert (legacy / "x.md").exists()


# ────────────────────────── run_all_migrations ──────────────────────────


def test_run_all_migrations_end_to_end(tmp_path):
    """整体跑一遍：旧版目录搬迁 + 核心记忆合并。"""
    project_root = tmp_path
    base = project_root / m._BASE_NAME
    legacy = project_root / m._LEGACY_BASE_NAME
    (legacy / "daily").mkdir(parents=True)
    (legacy / "daily" / "d.json").write_text("d", encoding="utf-8")
    legacy_memory = base / m._AVELINE_DIR / "memory"
    legacy_memory.mkdir(parents=True)
    (legacy_memory / "m.md").write_text("m", encoding="utf-8")

    m.run_all_migrations(base, project_root)

    assert (base / m._USER_DIR / "daily" / "d.json").exists()
    assert not legacy.exists()
    assert (base / m._AVELINE_DIR / "memories" / "core_memory" / "m.md").exists()
