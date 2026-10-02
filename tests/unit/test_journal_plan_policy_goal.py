from __future__ import annotations

from datetime import date
from pathlib import Path

import core.services.journal.plan_policy as plan_policy


def _write_app(root: Path, text: str) -> None:
    path = root / "config" / "yaml" / "app.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_daily_goal_is_single_capacity_source(monkeypatch, tmp_path: Path) -> None:
    _write_app(
        tmp_path,
        """
study:
  daily_study_goal_minutes: 420
journal_plan:
  planning:
    weekday:
      max_items: 8
      capacity_minutes: 240
      capacity_ratio: 1.0
      windows:
        - { key: morning, start: '08:00', end: '12:00' }
    weekend:
      max_items: 8
      capacity_minutes: 180
      capacity_ratio: 1.0
      windows:
        - { key: morning, start: '08:00', end: '12:00' }
    holiday:
      max_items: 7
      capacity_ratio: 0.8
      windows:
        - { key: morning, start: '08:00', end: '12:00' }
""".strip(),
    )
    monkeypatch.setattr(plan_policy, "get_project_root", lambda: tmp_path)

    settings = plan_policy.load_journal_plan_settings()

    assert settings.daily_goal_minutes == 420
    assert settings.weekday.capacity_minutes == 420
    assert settings.weekend.capacity_minutes == 420
    assert settings.holiday.capacity_minutes == 336
    # 旧 capacity_minutes 即使还残留，也不能再覆盖统一目标。
    assert settings.weekday.capacity_minutes != 240
    assert settings.weekend.capacity_minutes != 180


def test_weekend_no_longer_auto_reduces_study_load(monkeypatch, tmp_path: Path) -> None:
    _write_app(
        tmp_path,
        """
study:
  daily_study_goal_minutes: 420
journal_plan:
  planning:
    weekday: { max_items: 8, capacity_ratio: 1.0 }
    weekend: { max_items: 8, capacity_ratio: 1.0 }
    holiday: { max_items: 8, capacity_ratio: 1.0 }
""".strip(),
    )
    monkeypatch.setattr(plan_policy, "get_project_root", lambda: tmp_path)

    settings = plan_policy.load_journal_plan_settings()

    monday = settings.policy_for(date(2026, 9, 14))
    sunday = settings.policy_for(date(2026, 9, 13))
    assert monday.capacity_minutes == 420
    assert sunday.capacity_minutes == 420


def test_missing_config_falls_back_to_seven_hour_goal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(plan_policy, "get_project_root", lambda: tmp_path)

    settings = plan_policy.load_journal_plan_settings()

    assert settings.daily_goal_minutes == 420
    assert settings.weekday.capacity_minutes == 420
    assert settings.weekend.capacity_minutes == 420
