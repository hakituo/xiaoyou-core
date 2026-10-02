"""study streak「按天直取」改造的确定性回归。

旧实现每次 workspace 快照都会 `daily_records/**/*.json` 全历史 rglob 并逐个
`json.load`，只为建一个"哪天有学习"的集合，成本随历史线性增长。新实现从今天
往回逐日直取 `daily_records/YYYY/M/D/daily_record.json`，streak 断了就停。

时间相关断言全部用固定 `now`，不依赖真实时间流逝。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.services.daily import manager as daily_manager_module
from core.services.workspace import service as workspace_service

_FIXED_NOW = datetime(2026, 9, 17, 12, 0, 0)


@pytest.fixture
def records_root(tmp_path, monkeypatch):
    root = tmp_path / "daily_records"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        daily_manager_module,
        "get_daily_manager",
        lambda: type("M", (), {"root_dir": str(root)})(),
    )
    monkeypatch.setattr(workspace_service, "get_current_time", lambda: _FIXED_NOW)
    return root


def _write_record(root: Path, day: datetime, sessions: list) -> None:
    day_dir = root / str(day.year) / str(day.month) / str(day.day)
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "daily_record.json").write_text(
        json.dumps(
            {
                "date": day.strftime("%Y-%m-%d"),
                "study": {"sessions": sessions},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _streak() -> int:
    return asyncio.run(workspace_service.WorkspaceService()._get_study_streak_days())


def test_counts_consecutive_days_from_today(records_root):
    for offset in range(3):
        _write_record(records_root, _FIXED_NOW - timedelta(days=offset), [{"id": offset}])
    assert _streak() == 3


def test_today_without_study_is_zero(records_root):
    for offset in range(1, 4):
        _write_record(records_root, _FIXED_NOW - timedelta(days=offset), [{"id": offset}])
    assert _streak() == 0


def test_gap_stops_the_streak(records_root):
    _write_record(records_root, _FIXED_NOW, [{"id": 0}])
    _write_record(records_root, _FIXED_NOW - timedelta(days=1), [{"id": 1}])
    # 第 3 天缺记录 → 只算 2 天
    _write_record(records_root, _FIXED_NOW - timedelta(days=3), [{"id": 3}])
    assert _streak() == 2


def test_empty_sessions_file_breaks_the_streak(records_root):
    _write_record(records_root, _FIXED_NOW, [{"id": 0}])
    _write_record(records_root, _FIXED_NOW - timedelta(days=1), [])
    _write_record(records_root, _FIXED_NOW - timedelta(days=2), [{"id": 2}])
    assert _streak() == 1


def test_corrupt_record_breaks_the_streak(records_root):
    _write_record(records_root, _FIXED_NOW, [{"id": 0}])
    day_dir = (
        records_root
        / str((_FIXED_NOW - timedelta(days=1)).year)
        / str((_FIXED_NOW - timedelta(days=1)).month)
        / str((_FIXED_NOW - timedelta(days=1)).day)
    )
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "daily_record.json").write_text("{not json", encoding="utf-8")
    assert _streak() == 1


def test_legacy_flat_layout_still_counted(records_root):
    (records_root / "2026-09-17.json").write_text(
        json.dumps({"date": "2026-09-17", "study": {"sessions": [{"id": 0}]}}),
        encoding="utf-8",
    )
    assert _streak() == 1


def test_no_full_tree_scan(records_root, monkeypatch):
    """核心断言：不再对整个 daily_records 树做 rglob。"""
    for offset in range(5):
        _write_record(records_root, _FIXED_NOW - timedelta(days=offset), [{"id": offset}])

    def fail_rglob(*_args, **_kwargs):
        raise AssertionError("study streak 不应再做全树 rglob")

    monkeypatch.setattr(Path, "rglob", fail_rglob)
    monkeypatch.setattr(Path, "glob", fail_rglob)
    assert _streak() == 5


def test_missing_directory_is_zero(records_root):
    assert _streak() == 0
