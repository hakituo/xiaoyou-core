"""健康记录的时效标注单测（2026-09-17）。

背景：health 记录原本只渲染症状名、丢掉 time，导致凌晨 00:09 记下的「恶心」
到晚上 19:50 仍被当成「用户现在还难受」，四个角色都据此询问病情。
修复后渲染会带上记录时刻，并把超出新鲜窗口的条目单独标为「较早记录」。
"""

from datetime import datetime
from unittest.mock import patch

import pytest

from core.services.daily.manager import (
    HEALTH_FRESH_WINDOW_HOURS,
    DailyActivityManager,
    split_health_entries,
)


@pytest.fixture
def manager(tmp_path):
    """构造不落真实数据的 manager（records 目录指向 tmp_path）。"""
    with patch(
        "core.services.daily.manager.get_user_daily_records_dir",
        return_value=tmp_path,
    ):
        yield DailyActivityManager()


def test_fresh_entry_keeps_clock_only():
    fresh, earlier = split_health_entries(
        [{"symptom": "恶心", "time": "00:09"}], now=datetime(2026, 9, 17, 2, 0)
    )
    assert fresh == ["恶心（00:09）"]
    assert earlier == []


def test_stale_entry_marked_earlier_with_hours():
    fresh, earlier = split_health_entries(
        [{"symptom": "恶心", "time": "00:09"}], now=datetime(2026, 9, 17, 20, 30)
    )
    assert fresh == []
    assert earlier == ["恶心（00:09，约20小时前）"]


def test_window_boundary_is_inclusive():
    """恰好窗口长度算「当前」，超出一分钟即算「较早」。"""
    on_edge, _ = split_health_entries(
        [{"symptom": "头晕", "time": "10:00"}],
        now=datetime(2026, 9, 17, 10 + HEALTH_FRESH_WINDOW_HOURS, 0),
    )
    assert on_edge == ["头晕（10:00）"]

    past_edge, earlier = split_health_entries(
        [{"symptom": "头晕", "time": "10:00"}],
        now=datetime(2026, 9, 17, 10 + HEALTH_FRESH_WINDOW_HOURS, 1),
    )
    assert past_edge == []
    assert len(earlier) == 1


def test_missing_time_stays_fresh():
    fresh, earlier = split_health_entries(
        [{"symptom": "感冒"}], now=datetime(2026, 9, 17, 20, 0)
    )
    assert fresh == ["感冒"]
    assert earlier == []


def test_invalid_time_and_blank_entries_are_skipped():
    fresh, earlier = split_health_entries(
        [
            {"symptom": "  "},
            "not-a-dict",
            {"symptom": "头晕", "time": "25:99"},
        ],
        now=datetime(2026, 9, 17, 20, 0),
    )
    assert fresh == ["头晕"]
    assert earlier == []


def test_clock_skew_treated_as_just_recorded():
    """记录时刻晚于当前（跨零点/时钟漂移）按刚记录处理，不判成较早。"""
    fresh, earlier = split_health_entries(
        [{"symptom": "恶心", "time": "23:50"}], now=datetime(2026, 9, 17, 0, 5)
    )
    assert fresh == ["恶心（23:50）"]
    assert earlier == []


def test_empty_health_returns_empty():
    assert split_health_entries([]) == ([], [])
    assert split_health_entries(None) == ([], [])


def test_today_summary_marks_stale_health_and_warns_model(manager):
    record = {
        "date": "2026-09-17",
        "health": [{"symptom": "恶心", "detail": "", "time": "00:09"}],
    }
    with patch.object(manager, "_load_record", return_value=record), patch(
        "core.services.daily.manager.get_current_time",
        return_value=datetime(2026, 9, 17, 20, 30),
    ):
        summary = manager.get_today_summary()

    assert "较早记录，可能已缓解" in summary
    assert "恶心（00:09，约20小时前）" in summary
    assert "不要据此询问病情" in summary


def test_today_summary_keeps_fresh_health_as_current(manager):
    record = {
        "date": "2026-09-17",
        "health": [{"symptom": "胃痛", "detail": "", "time": "19:30"}],
    }
    with patch.object(manager, "_load_record", return_value=record), patch(
        "core.services.daily.manager.get_current_time",
        return_value=datetime(2026, 9, 17, 20, 30),
    ):
        summary = manager.get_today_summary()

    assert "用户健康: 胃痛（19:30）" in summary
    assert "较早记录" not in summary
