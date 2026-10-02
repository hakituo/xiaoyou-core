"""DailyActivityManager 统计与摘要单测。

覆盖 ``_infer_schedule_pattern`` / ``_time_to_minutes`` / ``_minutes_to_time`` /
``_time_median`` / ``_time_range`` / ``get_today_summary`` / ``get_daily_manager``。

约定：时间全部受控（patch 模块内 today_str/get_current_time），
``_load_record`` 与 ``render_device_sleep_line`` 按用例打桩，不落真实文件。
"""

from datetime import datetime

import pytest

from core.services.daily import manager as manager_mod
from core.services.daily.manager import DailyActivityManager

FIXED_NOW = datetime(2026, 4, 7, 12, 0, 0)
FIXED_TODAY = "2026-04-07"


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """数据根目录指向 tmp_path 的 manager，时间全部固定，单例前后清理。"""
    monkeypatch.setattr(manager_mod, "get_user_daily_records_dir", lambda: tmp_path)
    monkeypatch.setattr(manager_mod, "today_str", lambda: FIXED_TODAY)
    monkeypatch.setattr(
        manager_mod, "now_str", lambda fmt="%Y-%m-%d %H:%M:%S": FIXED_NOW.strftime(fmt)
    )
    monkeypatch.setattr(manager_mod, "get_current_time", lambda: FIXED_NOW)
    manager_mod._daily_manager_factory.reset()
    yield DailyActivityManager()
    manager_mod._daily_manager_factory.reset()


@pytest.fixture
def summary_manager(manager, monkeypatch):
    """get_today_summary 专用：默认关掉设备行与作息规律，避免干扰断言。"""
    monkeypatch.setattr(manager_mod, "render_device_sleep_line", lambda: "")
    monkeypatch.setattr(manager, "_infer_schedule_pattern", lambda *a, **k: "")
    return manager


def _summary(manager, record, monkeypatch=None):
    """把 _load_record 打桩为固定记录后取摘要。"""
    manager._load_record = lambda *a, **k: record
    return manager.get_today_summary()


# ────────────────────────── _infer_schedule_pattern ──────────────────────────


def test_infer_schedule_pattern_empty_when_no_records(manager, monkeypatch):
    monkeypatch.setattr(manager, "_load_record", lambda *a, **k: {})
    assert manager._infer_schedule_pattern() == ""


def test_infer_schedule_pattern_with_wakeup_and_sleep(manager, monkeypatch):
    records = {
        "2026-04-06": {"sleep_cycle": {"wakeup": "07:00", "sleep": "23:00"}},
        "2026-04-05": {"sleep_cycle": {"wakeup": "07:30", "sleep": "23:30"}},
        "2026-04-04": {"sleep_cycle": {"wakeup": "07:00", "sleep": "22:30"}},
    }
    monkeypatch.setattr(manager, "_load_record", lambda d, *a, **k: records.get(d, {}))
    out = manager._infer_schedule_pattern()
    assert out.startswith("【用户作息规律】")
    assert out.endswith("（仅供参考，不是今天的实际时间）")
    assert "用户通常起床: 07:00（07:00~07:30）" in out
    assert "用户通常入睡: 23:00（22:30~23:30）" in out


def test_infer_schedule_pattern_uses_legacy_schedule(manager, monkeypatch):
    records = {"2026-04-06": {"schedule": {"wakeup": "06:00", "sleep": "22:00"}}}
    monkeypatch.setattr(manager, "_load_record", lambda d, *a, **k: records.get(d, {}))
    out = manager._infer_schedule_pattern()
    assert "用户通常起床: 06:00" in out
    assert "用户通常入睡: 22:00" in out


def test_infer_schedule_pattern_wakeup_only(manager, monkeypatch):
    monkeypatch.setattr(
        manager, "_load_record", lambda *a, **k: {"sleep_cycle": {"wakeup": "07:00"}}
    )
    out = manager._infer_schedule_pattern()
    assert "用户通常起床" in out
    assert "入睡" not in out


# ────────────────────────── 时间工具 ──────────────────────────


def test_time_to_minutes_valid(manager):
    assert manager._time_to_minutes("09:30") == 570


def test_time_to_minutes_invalid_returns_zero(manager):
    assert manager._time_to_minutes("abc") == 0  # ValueError
    assert manager._time_to_minutes("12") == 0  # IndexError


def test_minutes_to_time_and_wraps(manager):
    assert manager._minutes_to_time(570) == "09:30"
    assert manager._minutes_to_time(24 * 60 + 30) == "00:30"  # 取模回绕


def test_time_median_empty(manager):
    assert manager._time_median([]) == ""


def test_time_median_odd_and_even(manager):
    assert manager._time_median(["07:00", "07:30", "08:00"]) == "07:30"  # 奇数取中位
    assert manager._time_median(["07:00", "08:00"]) == "07:30"  # 偶数取均值


def test_time_median_normalizes_late_sleeps(manager):
    # 多数 >12:00、少量 <06:00 → 后者 +24h 归一化
    assert manager._time_median(["23:30", "23:50", "00:30"]) == "23:50"


def test_time_range_short_input(manager):
    assert manager._time_range([]) == ""
    assert manager._time_range(["07:00"]) == ""


def test_time_range_normal(manager):
    assert manager._time_range(["07:00", "08:30"]) == "（07:00~08:30）"


def test_time_range_normalizes_late(manager):
    assert manager._time_range(["23:30", "23:50", "00:30"]) == "（23:30~00:30）"


# ────────────────────────── get_today_summary ──────────────────────────


def test_today_summary_sleep_and_wakeup_with_duration(summary_manager):
    out = _summary(
        summary_manager,
        {"sleep_cycle": {"sleep": "22:30", "wakeup": "07:00", "duration": "8h30m"}},
    )
    assert out.splitlines()[0] == "【用户今日画像】"
    assert "- 用户睡眠: 22:30 → 07:00 (8h30m)" in out


def test_today_summary_sleep_and_wakeup_without_duration(summary_manager):
    out = _summary(summary_manager, {"sleep_cycle": {"sleep": "22:30", "wakeup": "07:00"}})
    assert "- 用户睡眠: 22:30 → 07:00" in out
    assert "8h" not in out


def test_today_summary_wakeup_only(summary_manager):
    out = _summary(summary_manager, {"sleep_cycle": {"wakeup": "07:00"}})
    assert "- 用户起床: 07:00" in out


def test_today_summary_sleep_only(summary_manager):
    out = _summary(summary_manager, {"sleep_cycle": {"sleep": "22:30"}})
    assert "- 用户睡眠: 22:30" in out


def test_today_summary_falls_back_to_previous_night(summary_manager, monkeypatch):
    def fake_load(date_str=None, *a, **k):
        if date_str == "2026-04-06":
            return {"sleep_cycle": {"sleep": "23:15"}}
        return {}

    monkeypatch.setattr(summary_manager, "_load_record", fake_load)
    out = summary_manager.get_today_summary()
    assert "- 用户昨晚睡觉: 23:15" in out


def test_today_summary_includes_device_sleep_line(manager, monkeypatch):
    monkeypatch.setattr(manager, "_infer_schedule_pattern", lambda *a, **k: "")
    monkeypatch.setattr(manager_mod, "render_device_sleep_line", lambda: "- 设备实测睡眠行")
    monkeypatch.setattr(manager, "_load_record", lambda *a, **k: {})
    out = manager.get_today_summary()
    assert "- 设备实测睡眠行" in out


def test_today_summary_appends_schedule_pattern(manager, monkeypatch):
    monkeypatch.setattr(manager_mod, "render_device_sleep_line", lambda: "")
    monkeypatch.setattr(manager, "_infer_schedule_pattern", lambda *a, **k: "【用户作息规律】X")
    monkeypatch.setattr(manager, "_load_record", lambda *a, **k: {})
    out = manager.get_today_summary()
    assert "【用户作息规律】X" in out


def test_today_summary_meals_with_food_and_drink(summary_manager):
    out = _summary(
        summary_manager,
        {
            "meals": [
                {"type": "breakfast", "content": "粥"},
                {"type": "drink", "content": "喝水500ml"},
            ]
        },
    )
    assert "- 用户三餐: breakfast(粥); 饮水: 500ml" in out


def test_today_summary_no_meals(summary_manager):
    out = _summary(summary_manager, {"meals": []})
    # 2026-10-01：去掉「（需要关注）」—— 那半句被模型读成指令，导致反复催饭。
    # 现在常驻块只留事实；「该问一句吃了没」降级成 agenda_injections 里优先级最低的候选。
    assert "- 用户三餐: 无记录" in out
    assert "需要关注" not in out


def test_today_summary_drink_without_digits(summary_manager):
    out = _summary(summary_manager, {"meals": [{"type": "drink", "content": "水"}]})
    assert "- 用户三餐: 无正餐记录" in out
    assert "饮水" not in out


def test_today_summary_study_sessions(summary_manager):
    out = _summary(
        summary_manager,
        {"study": {"sessions": [{"topic": "数学"}, {"topic": "英语"}, {"topic": "数学"}]}},
    )
    assert "- 用户学习: " in out
    assert "(3 次)" in out
    assert "数学" in out


def test_today_summary_activities(summary_manager):
    out = _summary(
        summary_manager,
        {"activities": [{"content": "打游戏"}, {"content": "散步"}]},
    )
    assert "- 用户活动: 打游戏, 散步" in out


def test_today_summary_health_fresh_and_earlier(summary_manager):
    # get_current_time = 12:00：11:00 属当前，01:00 属较早
    out = _summary(
        summary_manager,
        {
            "health": [
                {"symptom": "胃痛", "time": "11:00"},
                {"symptom": "恶心", "time": "01:00"},
            ]
        },
    )
    assert "- 用户健康: 胃痛（11:00）" in out
    assert "- 用户健康（较早记录，可能已缓解）: 恶心（01:00，约11小时前）" in out
    assert "不要据此询问病情" in out


def test_today_summary_mood_dict(summary_manager):
    out = _summary(summary_manager, {"mood": {"mood": "开心", "detail": "天气好"}})
    assert "- 用户心情: 开心 (天气好)" in out


def test_today_summary_mood_str(summary_manager):
    out = _summary(summary_manager, {"mood": "平静"})
    assert "- 用户心情: 平静" in out


def test_today_summary_minimal_record(summary_manager):
    # 空记录只产出标题与三餐缺省行，不崩
    out = _summary(summary_manager, {})
    assert out.splitlines()[0] == "【用户今日画像】"
    assert "- 用户三餐: 无记录" in out


# ────────────────────────── get_daily_manager ──────────────────────────


def test_get_daily_manager_returns_singleton(manager):
    first = manager_mod.get_daily_manager()
    second = manager_mod.get_daily_manager()
    assert isinstance(first, DailyActivityManager)
    assert first is second
    assert first.root_dir == manager.root_dir


def test_get_daily_manager_reset_creates_new_instance(manager):
    first = manager_mod.get_daily_manager()
    manager_mod._daily_manager_factory.reset()
    second = manager_mod.get_daily_manager()
    assert first is not second
