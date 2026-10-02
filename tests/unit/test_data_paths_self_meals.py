"""单元测试：core/utils/data/data_paths.py —— 自主进食迁移与人设导出归位。

覆盖：从 user_data/daily_records 拆出 aveline/ling 的自主进食记录
（分类、去重、目标已存在/非法/非列表、读写失败兜底），以及
persona_data 旧目录重命名与 persona 名识别。

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


def _write_record(base: Path, y: str, mo: str, d: str, meals) -> Path:
    """在 user_data/daily_records/<y>/<mo>/<d>/ 下写一个 daily_record.json。"""
    rec_dir = base / dp._USER_DIR / "daily_records" / y / mo / d
    rec_dir.mkdir(parents=True, exist_ok=True)
    rec = rec_dir / "daily_record.json"
    rec.write_text(json.dumps({"meals": meals}, ensure_ascii=False), encoding="utf-8")
    return rec


def _life_record(base: Path, role_dir: str, y: str, mo: str, d: str) -> Path:
    """返回角色 life_records 下某天的 daily_record.json 路径。"""
    return base / role_dir / "life_records" / y / mo / d / "daily_record.json"


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
    assert dp._is_ling_persona_name(name) is expected


# ────────────────────────── _migrate_persona_export_layout ──────────────────────────


def test_migrate_persona_export_missing_root(tmp_path):
    """旧 persona_data 不存在时直接返回。"""
    base = _base(tmp_path)
    dp._migrate_persona_export_layout(base)
    assert not (base / dp._LING_DIR / "persona_data").exists()


def test_migrate_persona_export_renames(tmp_path):
    """Ling persona 归 ling，七濑 Aveline 归 aveline，其余留在原地。"""
    base = _base(tmp_path)
    old_root = base / dp._AVELINE_DIR / "persona_data"
    (old_root / "Ling").mkdir(parents=True)
    (old_root / "Ling" / "p.json").write_text("{}", encoding="utf-8")
    (old_root / "aveline").mkdir()
    (old_root / "aveline" / "a.json").write_text("{}", encoding="utf-8")
    (old_root / "七濑 Aveline").mkdir()
    (old_root / "七濑 Aveline" / "q.json").write_text("{}", encoding="utf-8")
    dp._migrate_persona_export_layout(base)
    ling_root = base / dp._LING_DIR / "persona_data"
    assert (ling_root / "ling" / "p.json").exists()
    assert not (ling_root / "Ling").exists()
    assert (old_root / "aveline" / "a.json").exists()
    assert (old_root / "aveline" / "q.json").exists()
    assert not (old_root / "七濑 Aveline").exists()


# ────────────────────────── _migrate_self_meals_from_user_records ──────────────────────────


def test_self_meals_missing_records(tmp_path):
    """daily_records 不存在时直接返回。"""
    base = _base(tmp_path)
    dp._migrate_self_meals_from_user_records(base)
    assert not (base / dp._USER_DIR / "daily_records").exists()


def test_self_meals_classifies_and_splits(tmp_path):
    """各类进食记录按前缀分流到 user / aveline / ling（非 dict 项被丢弃）。"""
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
    dp._migrate_self_meals_from_user_records(base)
    assert json.loads(rec.read_text(encoding="utf-8"))["meals"] == [{"content": "普通餐"}]
    a = json.loads(_life_record(base, dp._AVELINE_DIR, "2024", "01", "15").read_text(encoding="utf-8"))
    l = json.loads(_life_record(base, dp._LING_DIR, "2024", "01", "15").read_text(encoding="utf-8"))
    assert a["date"] == "2024-01-15"
    assert {x["content"] for x in a["meals"]} == {"自主进食:米饭", "投喂:y"}
    assert {x["content"] for x in l["meals"]} == {"自主进食(ling):鱼", "投喂(ling):x"}


def test_self_meals_skips_empty_non_list_and_no_self(tmp_path):
    """meals 非列表/为空、或没有自主进食项时均跳过。"""
    base = _base(tmp_path)
    rec_dir = base / dp._USER_DIR / "daily_records" / "2024" / "07" / "01"
    rec_dir.mkdir(parents=True)
    (rec_dir / "daily_record.json").write_text(json.dumps({"meals": "bad"}), encoding="utf-8")
    _write_record(base, "2024", "07", "02", [])
    _write_record(base, "2024", "07", "03", [{"content": "普通"}])
    dp._migrate_self_meals_from_user_records(base)
    assert not (base / dp._AVELINE_DIR / "life_records").exists()
    assert not (base / dp._LING_DIR / "life_records").exists()


def test_self_meals_invalid_json_skipped(tmp_path, debug_on):
    """非法 JSON 的 daily_record.json 被跳过。"""
    base = _base(tmp_path)
    rec_dir = base / dp._USER_DIR / "daily_records" / "2024" / "08" / "01"
    rec_dir.mkdir(parents=True)
    (rec_dir / "daily_record.json").write_text("not json", encoding="utf-8")
    dp._migrate_self_meals_from_user_records(base)
    assert (rec_dir / "daily_record.json").read_text(encoding="utf-8") == "not json"


def test_self_meals_target_rebuild_and_reset(tmp_path, debug_on):
    """目标已存在但内容非法 → 用默认 payload 重建；meals 非列表 → 重置后追加。"""
    base = _base(tmp_path)
    _write_record(base, "2024", "02", "20", [{"content": "自主进食:面包"}])
    broken = _life_record(base, dp._AVELINE_DIR, "2024", "02", "20")
    broken.parent.mkdir(parents=True)
    broken.write_text("broken", encoding="utf-8")
    _write_record(base, "2024", "03", "10", [{"content": "自主进食:蛋"}])
    not_list = _life_record(base, dp._AVELINE_DIR, "2024", "03", "10")
    not_list.parent.mkdir(parents=True)
    not_list.write_text(json.dumps({"date": "2024-03-10", "meals": "bad"}), encoding="utf-8")
    dp._migrate_self_meals_from_user_records(base)
    rebuilt = json.loads(broken.read_text(encoding="utf-8"))
    assert rebuilt["date"] == "2024-02-20"
    assert rebuilt["meals"] == [{"content": "自主进食:面包"}]
    assert json.loads(not_list.read_text(encoding="utf-8"))["meals"] == [{"content": "自主进食:蛋"}]


def test_self_meals_aveline_append_no_duplicate(tmp_path):
    """aveline 目标已有同一条目时不重复追加。"""
    base = _base(tmp_path)
    _write_record(base, "2024", "03", "11", [{"content": "自主进食:蛋"}])
    target = _life_record(base, dp._AVELINE_DIR, "2024", "03", "11")
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps({"date": "2024-03-11", "meals": [{"content": "自主进食:蛋"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    dp._migrate_self_meals_from_user_records(base)
    assert json.loads(target.read_text(encoding="utf-8"))["meals"] == [{"content": "自主进食:蛋"}]


def test_self_meals_ling_target_rebuild_and_reset(tmp_path, debug_on):
    """ling 目标非法 → 重建；meals 非列表 → 重置后追加。"""
    base = _base(tmp_path)
    _write_record(base, "2024", "04", "05", [{"content": "自主进食(ling):草"}])
    broken = _life_record(base, dp._LING_DIR, "2024", "04", "05")
    broken.parent.mkdir(parents=True)
    broken.write_text("broken", encoding="utf-8")
    _write_record(base, "2024", "05", "12", [{"content": "自主进食(ling):叶"}])
    not_list = _life_record(base, dp._LING_DIR, "2024", "05", "12")
    not_list.parent.mkdir(parents=True)
    not_list.write_text(json.dumps({"date": "2024-05-12", "meals": "bad"}), encoding="utf-8")
    dp._migrate_self_meals_from_user_records(base)
    rebuilt = json.loads(broken.read_text(encoding="utf-8"))
    assert rebuilt["date"] == "2024-04-05"
    assert rebuilt["meals"] == [{"content": "自主进食(ling):草"}]
    assert json.loads(not_list.read_text(encoding="utf-8"))["meals"] == [{"content": "自主进食(ling):叶"}]


def test_self_meals_source_write_failure(tmp_path, monkeypatch):
    """源记录写回失败时跳过，不产生任何目标文件。"""
    base = _base(tmp_path)
    rec = _write_record(base, "2024", "06", "18", [{"content": "自主进食:米饭"}])
    real_write_text = Path.write_text

    def fake_write_text(self, *args, **kwargs):
        if self.name == "daily_record.json" and dp._USER_DIR in str(self):
            raise OSError("simulated source write failure")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fake_write_text)
    dp._migrate_self_meals_from_user_records(base)
    assert rec.exists()
    assert not (base / dp._AVELINE_DIR / "life_records").exists()


@pytest.mark.parametrize("role_dir", [dp._AVELINE_DIR, dp._LING_DIR])
def test_self_meals_target_write_failure(tmp_path, monkeypatch, role_dir):
    """角色目标写入失败时走警告分支，不留下目标文件。"""
    base = _base(tmp_path)
    content = "自主进食:米饭" if role_dir == dp._AVELINE_DIR else "自主进食(ling):草"
    _write_record(base, "2024", "06", "20", [{"content": content}])
    real_write_text = Path.write_text

    def fake_write_text(self, *args, **kwargs):
        if "life_records" in str(self) and role_dir in str(self):
            raise OSError("simulated target write failure")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fake_write_text)
    dp._migrate_self_meals_from_user_records(base)
    assert not _life_record(base, role_dir, "2024", "06", "20").exists()
