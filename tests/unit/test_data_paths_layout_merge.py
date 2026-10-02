"""单元测试：core/utils/data/data_paths.py —— 目录搬迁 / 布局迁移。

覆盖 data_paths.py 自带的迁移实现：递归合并搬运、active_care 归位、
聊天记录分桶、日记分桶、事件拆分合并、role 组合迁移。

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
    """让指定目录名的 rglob(pattern) 返回一个「不属于该目录」的外部路径。

    用于构造 relative_to 失败这一防御分支（真实文件系统不会产生这种结果）。
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
    dst = tmp_path / "dst" / "x"
    dp._move_path_merge(tmp_path / "no_such", dst)
    assert not dst.parent.exists()


def test_move_path_merge_dst_missing_moves(tmp_path):
    """目标不存在时直接移动。"""
    src = tmp_path / "a" / "f.txt"
    src.parent.mkdir(parents=True)
    src.write_text("hello", encoding="utf-8")
    dst = tmp_path / "b" / "deep" / "f.txt"
    dp._move_path_merge(src, dst)
    assert dst.read_text(encoding="utf-8") == "hello"
    assert not src.exists()


def test_move_path_merge_conflicts_keep_both(tmp_path):
    """文件→文件、文件→目录、目录→文件三种冲突均原样保留。"""
    f1 = tmp_path / "s.txt"
    f1.write_text("src", encoding="utf-8")
    f2 = tmp_path / "d.txt"
    f2.write_text("dst", encoding="utf-8")
    dp._move_path_merge(f1, f2)
    assert (f1.read_text(encoding="utf-8"), f2.read_text(encoding="utf-8")) == ("src", "dst")

    d = tmp_path / "d"
    d.mkdir()
    dp._move_path_merge(f1, d)
    assert f1.exists() and d.is_dir()

    sub = tmp_path / "s"
    sub.mkdir()
    (sub / "c.txt").write_text("c", encoding="utf-8")
    dp._move_path_merge(sub, f2)
    assert (sub / "c.txt").exists()


def test_move_path_merge_dirs_merge_recursively(tmp_path):
    """目录→目录时递归合并，随后删除源目录。"""
    src = tmp_path / "s"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "a.txt").write_text("a", encoding="utf-8")
    (src / "top.txt").write_text("t", encoding="utf-8")
    dst = tmp_path / "d"
    dst.mkdir()
    dp._move_path_merge(src, dst)
    assert (dst / "sub" / "a.txt").read_text(encoding="utf-8") == "a"
    assert (dst / "top.txt").read_text(encoding="utf-8") == "t"
    assert not src.exists()


def test_move_path_merge_rmdir_failure_logs(tmp_path, debug_on):
    """子项冲突未被搬走时 rmdir 失败走兜底日志分支，且不抛异常。"""
    src = tmp_path / "s"
    src.mkdir()
    (src / "conflict.txt").write_text("src", encoding="utf-8")
    dst = tmp_path / "d"
    dst.mkdir()
    (dst / "conflict.txt").write_text("dst", encoding="utf-8")
    dp._move_path_merge(src, dst)
    assert (src / "conflict.txt").read_text(encoding="utf-8") == "src"


# ────────────────────────── _scope_to_chat_history_root ──────────────────────────


@pytest.mark.parametrize(
    ("scope", "dir_name"),
    [
        ("user", dp._USER_DIR),
        ("ling", dp._LING_DIR),
        ("xiaolu", dp._XIAOLU_DIR),
        ("dual_role", dp._AVELINE_DIR),
        ("aveline", dp._AVELINE_DIR),
    ],
)
def test_scope_to_chat_history_root_builtin(tmp_path, scope, dir_name):
    """各内置 scope 映射到对应角色目录（dual_role 归 aveline）。"""
    base = tmp_path / "companion_data"
    assert dp._scope_to_chat_history_root(base, scope) == (base / dir_name / "chat_history").resolve()


def test_scope_to_chat_history_root_invalid_falls_back(tmp_path):
    """非法 scope 归 aveline。"""
    base = tmp_path / "companion_data"
    assert dp._scope_to_chat_history_root(base, "not_a_scope") == (
        base / dp._AVELINE_DIR / "chat_history"
    ).resolve()


def test_scope_to_chat_history_root_dynamic(tmp_path, monkeypatch):
    """动态 scope 使用其 {scope}_data 目录名。"""
    monkeypatch.setattr(dp, "_get_role_scopes", lambda: {"aveline", "custom_role"})
    base = tmp_path / "companion_data"
    assert dp._scope_to_chat_history_root(base, "custom_role") == (
        base / "custom_role_data" / "chat_history"
    ).resolve()


# ────────────────────────── _migrate_active_care_layout ──────────────────────────


def test_migrate_active_care_layout_missing_root(tmp_path):
    """旧 active_care 根不存在时直接返回。"""
    base = _base(tmp_path)
    dp._migrate_active_care_layout(base)
    assert not (base / "active_care").exists()


def test_migrate_active_care_layout_moves_roles(tmp_path):
    """aveline / ling 子目录分别归位并删除旧根。"""
    base = _base(tmp_path)
    (base / "active_care" / "aveline").mkdir(parents=True)
    (base / "active_care" / "aveline" / "a.json").write_text("a", encoding="utf-8")
    (base / "active_care" / "ling").mkdir(parents=True)
    (base / "active_care" / "ling" / "l.json").write_text("l", encoding="utf-8")
    dp._migrate_active_care_layout(base)
    assert (base / dp._AVELINE_DIR / "active_care" / "a.json").exists()
    assert (base / dp._LING_DIR / "active_care" / "l.json").exists()
    assert not (base / "active_care").exists()


def test_migrate_active_care_layout_rmdir_failure(tmp_path, debug_on):
    """存在无法识别的残留子目录时旧根删除失败走兜底分支。"""
    base = _base(tmp_path)
    (base / "active_care" / "aveline").mkdir(parents=True)
    (base / "active_care" / "misc").mkdir(parents=True)
    dp._migrate_active_care_layout(base)
    assert (base / "active_care" / "misc").is_dir()


# ────────────────────────── _migrate_user_chat_history_layout ──────────────────────────


def test_migrate_user_chat_history_missing_dir(tmp_path):
    """user_data/chat_history 不存在时直接返回。"""
    base = _base(tmp_path)
    dp._migrate_user_chat_history_layout(base)
    assert not (base / dp._USER_DIR / "chat_history").exists()


def test_migrate_user_chat_history_buckets_and_removes_index(tmp_path):
    """按 scope 分桶移动 jsonl，并删除 index.json。"""
    base = _base(tmp_path)
    user_chat = base / dp._USER_DIR / "chat_history"
    (user_chat / "Ling").mkdir(parents=True)
    (user_chat / "Ling" / "c1.jsonl").write_text("{}", encoding="utf-8")
    (user_chat / "other").mkdir(parents=True)
    (user_chat / "other" / "c2.jsonl").write_text("{}", encoding="utf-8")
    (user_chat / "index.json").write_text("[]", encoding="utf-8")
    dp._migrate_user_chat_history_layout(base)
    assert (base / dp._LING_DIR / "chat_history" / "Ling" / "c1.jsonl").exists()
    assert (base / dp._AVELINE_DIR / "chat_history" / "other" / "c2.jsonl").exists()
    assert not (user_chat / "index.json").exists()


def test_migrate_user_chat_history_relative_to_failure(tmp_path, monkeypatch, debug_on):
    """rglob 产出无法相对化的路径时跳过而非崩溃。"""
    base = _base(tmp_path)
    (base / dp._USER_DIR / "chat_history").mkdir(parents=True)
    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}", encoding="utf-8")
    _patch_rglob_to_yield(monkeypatch, "chat_history", "*.jsonl", outside)
    dp._migrate_user_chat_history_layout(base)
    assert outside.exists()


def test_migrate_user_chat_history_index_unlink_failure(tmp_path, debug_on):
    """index.json 是目录导致 unlink 失败时走兜底分支。"""
    base = _base(tmp_path)
    (base / dp._USER_DIR / "chat_history" / "index.json").mkdir(parents=True)
    dp._migrate_user_chat_history_layout(base)
    assert (base / dp._USER_DIR / "chat_history" / "index.json").is_dir()


# ────────────────────────── _migrate_daily_diary_layout ──────────────────────────


def test_migrate_daily_diary_missing_dir(tmp_path):
    """user_data/daily 不存在时直接返回。"""
    base = _base(tmp_path)
    dp._migrate_daily_diary_layout(base)
    assert not (base / dp._USER_DIR / "daily").exists()


def test_migrate_daily_diary_buckets_by_scope(tmp_path):
    """按 source 把日记分到 aveline / ling，并跳过非角色 scope。"""
    base = _base(tmp_path)
    diary = base / dp._USER_DIR / "daily" / "diary"
    diary.mkdir(parents=True)
    (diary / "a.json").write_text(json.dumps({"source": "aveline"}), encoding="utf-8")
    (diary / "l.json").write_text(json.dumps({"source": "ling"}), encoding="utf-8")
    (diary / "u.json").write_text(json.dumps({"source": "unknown_user"}), encoding="utf-8")
    dp._migrate_daily_diary_layout(base)
    assert (base / dp._AVELINE_DIR / "daily" / "diary" / "a.json").exists()
    assert (base / dp._LING_DIR / "daily" / "diary" / "l.json").exists()
    assert (diary / "u.json").exists()


def test_migrate_daily_diary_invalid_json_skipped(tmp_path, debug_on):
    """非法 JSON 的日记被跳过。"""
    base = _base(tmp_path)
    diary = base / dp._USER_DIR / "daily" / "diary"
    diary.mkdir(parents=True)
    (diary / "bad.json").write_text("not json", encoding="utf-8")
    dp._migrate_daily_diary_layout(base)
    assert (diary / "bad.json").exists()


def test_migrate_daily_diary_relative_to_failure(tmp_path, monkeypatch, debug_on):
    """rglob 产出无法相对化的路径时跳过（source 需为角色否则提前 continue）。"""
    base = _base(tmp_path)
    (base / dp._USER_DIR / "daily").mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"source": "aveline"}), encoding="utf-8")
    _patch_rglob_to_yield(monkeypatch, "daily", "diary/*.json", outside)
    dp._migrate_daily_diary_layout(base)
    assert outside.exists()


