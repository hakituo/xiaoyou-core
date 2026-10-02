"""DailyActivityManager 睡眠相关单测。

覆盖 ``_calc_sleep_duration`` / ``_update_sleep_cycle_duration`` /
``record_wakeup`` / ``record_sleep`` / ``update_sleep_cycle`` 与模块级
``render_device_sleep_line``。

约定：时间全部受控（patch 模块内 now_str/get_current_time，或直接传 now_dt），
文件 IO 落在 tmp_path。
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


# ────────────────────────── _calc_sleep_duration ──────────────────────────


@pytest.mark.parametrize(
    "sleep_time, wakeup_time, expected",
    [
        ("22:00", "07:00", "9h"),          # 整点小时
        ("23:30", "07:15", "7h45m"),       # 时 + 分
        ("01:00", "09:00", "8h"),          # 凌晨睡、上午起（跨天）
        ("22:00", "23:00", "1h"),          # 恰好 1h 下限
        ("06:00", "22:00", "16h"),         # 恰好 16h 上限
    ],
)
def test_calc_sleep_duration_valid(manager, sleep_time, wakeup_time, expected):
    assert manager._calc_sleep_duration(sleep_time, wakeup_time) == expected


@pytest.mark.parametrize(
    "sleep_time, wakeup_time",
    [
        ("22:00", "22:30"),   # 30 分钟 < 1h
        ("22:00", "22:00"),   # 0 分钟
        ("20:00", "18:00"),   # 跨天 22h > 16h
    ],
)
def test_calc_sleep_duration_out_of_range_returns_none(manager, sleep_time, wakeup_time):
    assert manager._calc_sleep_duration(sleep_time, wakeup_time) is None


def test_calc_sleep_duration_bad_format_returns_none(manager):
    assert manager._calc_sleep_duration("abc", "07:00") is None


def test_calc_sleep_duration_none_input_returns_none(manager):
    # None.split → AttributeError，被吞掉返回 None
    assert manager._calc_sleep_duration(None, "07:00") is None


def test_update_sleep_cycle_duration_sets_value(manager):
    data = {"sleep_cycle": {"sleep": "22:00", "wakeup": "07:00"}}
    manager._update_sleep_cycle_duration(data)
    assert data["sleep_cycle"]["duration"] == "9h"


def test_update_sleep_cycle_duration_noop_when_incomplete(manager):
    data = {"sleep_cycle": {"sleep": "22:00"}}
    manager._update_sleep_cycle_duration(data)
    assert "duration" not in data["sleep_cycle"]


# ────────────────────────── record_wakeup ──────────────────────────


def test_record_wakeup_defaults_to_now_and_inferred_source(manager):
    msg = manager.record_wakeup()
    assert msg == "Recorded wakeup: 12:00 (chat_inferred, 2026-04-07)"
    sc = manager.get_record("2026-04-07")["sleep_cycle"]
    assert sc["wakeup"] == "12:00"
    assert sc["wakeup_source"] == "chat_inferred"


def test_record_wakeup_explicit_time(manager):
    msg = manager.record_wakeup("07:30")
    assert msg == "Recorded wakeup: 07:30 (chat_explicit_time, 2026-04-07)"


def test_record_wakeup_explicit_target_date(manager):
    msg = manager.record_wakeup("08:00", target_date="2026-03-01")
    assert msg == "Recorded wakeup: 08:00 (chat_explicit_time, 2026-03-01)"


def test_record_wakeup_blank_source_falls_back(manager):
    msg = manager.record_wakeup("07:00", source="   ")
    assert msg == "Recorded wakeup: 07:00 (chat_explicit_time, 2026-04-07)"


def test_record_wakeup_keeps_more_reliable_existing(manager):
    manager._save_record(
        {"date": "2026-04-07", "sleep_cycle": {"wakeup": "06:30", "wakeup_source": "user_manual"}},
        "2026-04-07",
    )
    msg = manager.record_wakeup("08:00")
    assert msg == "Kept existing wakeup: 06:30 (user_manual)"


def test_record_wakeup_keeps_existing_chat_value(manager):
    # 同优先级、同属聊天来源、值不同 → 保持原值，防止多轮对话漂移
    manager._save_record(
        {"date": "2026-04-07", "sleep_cycle": {"wakeup": "06:30", "wakeup_source": "chat_inferred"}},
        "2026-04-07",
    )
    msg = manager.record_wakeup("08:00", source="chat_inferred")
    assert msg == "Kept existing wakeup: 06:30 (chat_inferred)"


def test_record_wakeup_same_chat_value_records(manager):
    manager._save_record(
        {"date": "2026-04-07", "sleep_cycle": {"wakeup": "06:30", "wakeup_source": "chat_inferred"}},
        "2026-04-07",
    )
    msg = manager.record_wakeup("06:30", source="chat_inferred")
    assert msg == "Recorded wakeup: 06:30 (chat_inferred, 2026-04-07)"


def test_record_wakeup_equal_non_chat_priority_records(manager):
    # 非聊天来源同优先级不触发「保持原值」，直接覆盖
    manager._save_record(
        {"date": "2026-04-07", "sleep_cycle": {"wakeup": "06:30", "wakeup_source": "samsung_health"}},
        "2026-04-07",
    )
    msg = manager.record_wakeup("07:00", source="samsung_health")
    assert msg == "Recorded wakeup: 07:00 (samsung_health, 2026-04-07)"


def test_record_wakeup_force_overrides_priority(manager):
    manager._save_record(
        {"date": "2026-04-07", "sleep_cycle": {"wakeup": "06:30", "wakeup_source": "user_manual"}},
        "2026-04-07",
    )
    msg = manager.record_wakeup("09:00", force=True)
    assert msg == "Recorded wakeup: 09:00 (chat_explicit_time, 2026-04-07)"


def test_record_wakeup_updates_duration_when_sleep_known(manager):
    manager._save_record(
        {"date": "2026-04-07", "sleep_cycle": {"sleep": "23:00", "sleep_source": "chat_explicit_time"}},
        "2026-04-07",
    )
    manager.record_wakeup("07:00")
    assert manager.get_record("2026-04-07")["sleep_cycle"]["duration"] == "8h"


# ────────────────────────── record_sleep ──────────────────────────


def test_record_sleep_uses_now_dt_when_no_time(manager):
    msg = manager.record_sleep(now_dt=datetime(2026, 4, 7, 23, 15))
    assert msg == "Recorded sleep: 23:15 (chat_explicit_time, 2026-04-07)"


def test_record_sleep_uses_current_time_when_no_now(manager):
    msg = manager.record_sleep()
    assert msg == "Recorded sleep: 12:00 (chat_explicit_time, 2026-04-07)"


def test_record_sleep_early_morning_goes_previous_day(manager):
    msg = manager.record_sleep("02:00", now_dt=datetime(2026, 4, 7, 2, 30))
    assert msg == "Recorded sleep: 02:00 (chat_explicit_time, 2026-04-06)"


def test_record_sleep_explicit_target_date(manager):
    msg = manager.record_sleep("22:00", target_date="2026-04-01")
    assert msg == "Recorded sleep: 22:00 (chat_explicit_time, 2026-04-01)"


def test_record_sleep_explicit_source(manager):
    msg = manager.record_sleep("22:00", target_date="2026-04-07", source="samsung_health")
    assert msg == "Recorded sleep: 22:00 (samsung_health, 2026-04-07)"


def test_record_sleep_keeps_more_reliable_existing(manager):
    manager._save_record(
        {"date": "2026-04-07", "sleep_cycle": {"sleep": "23:00", "sleep_source": "samsung_health"}},
        "2026-04-07",
    )
    msg = manager.record_sleep("21:00", target_date="2026-04-07")
    assert msg == "Kept existing sleep: 23:00 (samsung_health)"


def test_record_sleep_rejects_suspicious_daytime_overwrite(manager):
    manager._save_record(
        {"date": "2026-04-07", "sleep_cycle": {"sleep": "22:00", "sleep_source": "chat_explicit_time"}},
        "2026-04-07",
    )
    msg = manager.record_sleep("07:00", target_date="2026-04-07")
    assert msg == "Kept existing sleep time: 22:00 (ignored suspicious daytime value 07:00)"


def test_record_sleep_overwrites_with_new_night_value(manager):
    manager._save_record(
        {"date": "2026-04-07", "sleep_cycle": {"sleep": "22:00", "sleep_source": "chat_explicit_time"}},
        "2026-04-07",
    )
    msg = manager.record_sleep("23:30", target_date="2026-04-07")
    assert msg == "Recorded sleep: 23:30 (chat_explicit_time, 2026-04-07)"


def test_record_sleep_handles_unparsable_existing(manager):
    manager._save_record(
        {"date": "2026-04-07", "sleep_cycle": {"sleep": "late", "sleep_source": "chat_explicit_time"}},
        "2026-04-07",
    )
    msg = manager.record_sleep("22:00", target_date="2026-04-07")
    assert msg == "Recorded sleep: 22:00 (chat_explicit_time, 2026-04-07)"


def test_record_sleep_same_value_rewrites(manager):
    manager._save_record(
        {"date": "2026-04-07", "sleep_cycle": {"sleep": "22:00", "sleep_source": "chat_explicit_time"}},
        "2026-04-07",
    )
    msg = manager.record_sleep("22:00", target_date="2026-04-07")
    assert msg == "Recorded sleep: 22:00 (chat_explicit_time, 2026-04-07)"


def test_record_sleep_force_overrides_priority(manager):
    manager._save_record(
        {"date": "2026-04-07", "sleep_cycle": {"sleep": "23:00", "sleep_source": "samsung_health"}},
        "2026-04-07",
    )
    msg = manager.record_sleep("21:00", target_date="2026-04-07", force=True)
    assert msg == "Recorded sleep: 21:00 (chat_explicit_time, 2026-04-07)"


def test_record_sleep_updates_duration_when_wakeup_known(manager):
    manager._save_record(
        {"date": "2026-04-07", "sleep_cycle": {"wakeup": "07:00", "wakeup_source": "user_manual"}},
        "2026-04-07",
    )
    manager.record_sleep("23:00", target_date="2026-04-07")
    assert manager.get_record("2026-04-07")["sleep_cycle"]["duration"] == "8h"


# ────────────────────────── update_sleep_cycle ──────────────────────────


def test_update_sleep_cycle_requires_a_field(manager):
    assert manager.update_sleep_cycle() == "未提供修改字段，sleep/wakeup 至少需要一个"


def test_update_sleep_cycle_with_target_date(manager):
    msg = manager.update_sleep_cycle("22:30", "07:00", target_date="2026-04-07")
    assert msg == "已修正作息记录 (2026-04-07): sleep=22:30, wakeup=07:00"
    sc = manager.get_record("2026-04-07")["sleep_cycle"]
    assert sc["sleep"] == "22:30"
    assert sc["sleep_source"] == "user_manual"
    assert sc["wakeup"] == "07:00"
    assert sc["duration"] == "8h30m"


def test_update_sleep_cycle_resolves_date_from_sleep_time(manager):
    # 02:00 属熬夜 → 归前一天
    msg = manager.update_sleep_cycle(sleep_time="02:00")
    assert msg == "已修正作息记录 (2026-04-06): sleep=02:00"


def test_update_sleep_cycle_wakeup_only_defaults_today(manager):
    msg = manager.update_sleep_cycle(wakeup_time="08:00")
    assert msg == "已修正作息记录 (2026-04-07): wakeup=08:00"


def test_update_sleep_cycle_rebuilds_non_dict_sleep_cycle(manager, monkeypatch):
    # _load_record 规范化后 sleep_cycle 必为 dict，故打桩喂坏结构
    saved = []
    monkeypatch.setattr(
        manager, "_load_record", lambda *a, **k: {"date": "2026-04-07", "sleep_cycle": "bad"}
    )
    monkeypatch.setattr(manager, "_save_record", lambda data, *a, **k: saved.append(data))
    msg = manager.update_sleep_cycle("22:00", target_date="2026-04-07")
    assert msg == "已修正作息记录 (2026-04-07): sleep=22:00"
    assert saved[0]["sleep_cycle"]["sleep"] == "22:00"
    assert saved[0]["sleep_cycle"]["wakeup"] is None


# ────────────────────────── render_device_sleep_line ──────────────────────────

STORE_TARGET = "core.services.health_sync.store.read_latest_sleep_window"


def test_render_device_sleep_line_empty_when_no_window(monkeypatch):
    monkeypatch.setattr(STORE_TARGET, lambda: None)
    assert manager_mod.render_device_sleep_line() == ""


def test_render_device_sleep_line_same_day(monkeypatch):
    monkeypatch.setattr(
        STORE_TARGET,
        lambda: {
            "start": datetime(2026, 4, 7, 23, 0),
            "end": datetime(2026, 4, 7, 23, 50),
            "sleep_minutes": 40,
            "sleep_score": 82,
        },
    )
    monkeypatch.setattr(manager_mod, "get_current_time", lambda: datetime(2026, 4, 8, 1, 0))
    line = manager_mod.render_device_sleep_line()
    assert line == (
        "- 用户睡眠（三星健康实测，优先于聊天推断）: "
        "04-07 23:00 → 23:50（50m，实际睡眠 0h40m，得分 82）"
    )


def test_render_device_sleep_line_cross_day_with_hours(monkeypatch):
    monkeypatch.setattr(
        STORE_TARGET,
        lambda: {
            "start": datetime(2026, 4, 7, 23, 30),
            "end": datetime(2026, 4, 8, 7, 15),
            "sleep_minutes": 450,
            "sleep_score": 82.6,
        },
    )
    monkeypatch.setattr(manager_mod, "get_current_time", lambda: datetime(2026, 4, 8, 9, 0))
    line = manager_mod.render_device_sleep_line()
    assert "04-07 23:30 → 04-08 07:15" in line
    assert "（7h45m，实际睡眠 7h30m，得分 83）" in line


def test_render_device_sleep_line_skips_stale_window(monkeypatch):
    monkeypatch.setattr(
        STORE_TARGET,
        lambda: {
            "start": datetime(2026, 4, 1, 23, 0),
            "end": datetime(2026, 4, 2, 7, 0),
            "sleep_minutes": 0,
            "sleep_score": None,
        },
    )
    monkeypatch.setattr(manager_mod, "get_current_time", lambda: datetime(2026, 4, 8, 9, 0))
    assert manager_mod.render_device_sleep_line() == ""


def test_render_device_sleep_line_skips_future_window(monkeypatch):
    monkeypatch.setattr(
        STORE_TARGET,
        lambda: {
            "start": datetime(2026, 4, 7, 23, 0),
            "end": datetime(2026, 4, 8, 10, 0),
            "sleep_minutes": 0,
            "sleep_score": None,
        },
    )
    monkeypatch.setattr(manager_mod, "get_current_time", lambda: datetime(2026, 4, 8, 5, 0))
    assert manager_mod.render_device_sleep_line() == ""


def test_render_device_sleep_line_handles_bad_fields(monkeypatch):
    # sleep_minutes / sleep_score 是脏字段 → 不拖垮整行
    monkeypatch.setattr(
        STORE_TARGET,
        lambda: {
            "start": datetime(2026, 4, 7, 23, 0),
            "end": datetime(2026, 4, 8, 7, 0),
            "sleep_minutes": "abc",
            "sleep_score": "n/a",
        },
    )
    monkeypatch.setattr(manager_mod, "get_current_time", lambda: datetime(2026, 4, 8, 9, 0))
    line = manager_mod.render_device_sleep_line()
    assert line.endswith("（8h0m）")


def test_render_device_sleep_line_ignores_reported_over_span(monkeypatch):
    monkeypatch.setattr(
        STORE_TARGET,
        lambda: {
            "start": datetime(2026, 4, 7, 23, 0),
            "end": datetime(2026, 4, 8, 7, 0),
            "sleep_minutes": 600,
            "sleep_score": None,
        },
    )
    monkeypatch.setattr(manager_mod, "get_current_time", lambda: datetime(2026, 4, 8, 9, 0))
    line = manager_mod.render_device_sleep_line()
    assert "实际睡眠" not in line
    assert line.endswith("（8h0m）")


def test_render_device_sleep_line_swallows_exception(monkeypatch):
    def _boom():
        raise RuntimeError("snapshot broken")

    monkeypatch.setattr(STORE_TARGET, _boom)
    assert manager_mod.render_device_sleep_line() == ""
