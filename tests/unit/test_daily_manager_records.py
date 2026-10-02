"""DailyActivityManager 记录层单测（日期/路径/锁/读写/record_*）。

覆盖模块级 ``_parse_health_clock_minutes`` / ``split_health_entries``，
以及日期归一化、文件路径、``_with_record_lock`` 文件锁、
记录默认值/规范化/压缩/读写与全部 ``record_*`` / ``upsert_meal``。

约定：
- 所有文件 IO 落在 ``tmp_path``，绝不触碰真实 companion_data/。
- 时间全部用受控时钟（patch 模块内 now_str/today_str/get_current_time）。
"""

import json
from datetime import datetime

import pytest

from core.services.daily import manager as manager_mod
from core.services.daily.manager import (
    DailyActivityManager,
    _parse_health_clock_minutes,
    split_health_entries,
)

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


# ────────────────────────── 模块级函数 ──────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("09:30", 570),
        ("0:05", 5),
        ("23:59", 1439),
        (" 08：15 ", 495),  # 前后空白 + 全角冒号
    ],
)
def test_parse_health_clock_minutes_valid(raw, expected):
    assert _parse_health_clock_minutes(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [None, "", "abc", "9:5", "24:00", "12:60", "12:00:00"],
)
def test_parse_health_clock_minutes_invalid(raw):
    assert _parse_health_clock_minutes(raw) is None


def test_split_health_entries_empty_and_non_dict():
    # 空输入与非 dict 元素都被过滤
    assert split_health_entries(None) == ([], [])
    assert split_health_entries([]) == ([], [])
    assert split_health_entries(["not-a-dict", 3]) == ([], [])


def test_split_health_entries_uses_current_time_when_now_missing(monkeypatch):
    # now 缺省时走模块内 get_current_time
    monkeypatch.setattr(manager_mod, "get_current_time", lambda: datetime(2026, 4, 7, 12, 0))
    fresh, earlier = split_health_entries([{"symptom": "头痛", "time": "11:30"}])
    assert fresh == ["头痛（11:30）"]
    assert earlier == []


def test_split_health_entries_skips_blank_symptom():
    fresh, earlier = split_health_entries(
        [{"symptom": "   ", "time": "10:00"}, {"symptom": "咳嗽", "time": "10:00"}],
        now=datetime(2026, 4, 7, 12, 0),
    )
    assert fresh == ["咳嗽（10:00）"]
    assert earlier == []


def test_split_health_entries_missing_time_is_fresh():
    fresh, earlier = split_health_entries(
        [{"symptom": "感冒"}], now=datetime(2026, 4, 7, 12, 0)
    )
    assert fresh == ["感冒"]
    assert earlier == []


def test_split_health_entries_fresh_and_earlier_split():
    fresh, earlier = split_health_entries(
        [
            {"symptom": "胃痛", "time": "11:00"},  # 1 小时前 → 当前
            {"symptom": "恶心", "time": "01:00"},  # 11 小时前 → 较早
        ],
        now=datetime(2026, 4, 7, 12, 0),
    )
    assert fresh == ["胃痛（11:00）"]
    assert earlier == ["恶心（01:00，约11小时前）"]


def test_split_health_entries_wraps_negative_age_across_midnight():
    # 记录时刻晚于当前 → 跨零点回绕，按刚记录处理
    fresh, earlier = split_health_entries(
        [{"symptom": "失眠", "time": "23:50"}], now=datetime(2026, 4, 7, 0, 10)
    )
    assert fresh == ["失眠（23:50）"]
    assert earlier == []


# ────────────────────────── 日期 / 路径 / 锁 ──────────────────────────


def test_normalize_date(manager):
    # 缺省/空白 → 今天；合法 → 归一化；非法 → 回落今天
    assert manager._normalize_date() == FIXED_TODAY
    assert manager._normalize_date("") == FIXED_TODAY
    assert manager._normalize_date("   ") == FIXED_TODAY
    assert manager._normalize_date("2026-4-7") == "2026-04-07"
    assert manager._normalize_date("2026/04/07") == FIXED_TODAY


def test_record_paths(manager, tmp_path):
    # 旧平铺路径 / 旧月路径 / 锁路径
    assert manager._get_legacy_file_path("2026-04-07") == str(tmp_path / "2026-04-07.json")
    assert manager._get_previous_month_path("2026-04-07") == str(
        tmp_path / "2026" / "04" / "2026-04-07.json"
    )
    assert manager._get_lock_path("2026-04-07") == str(
        tmp_path / "2026" / "4" / "7" / "daily_record.json.lock"
    )


def test_get_file_path_creates_day_dir(manager, tmp_path):
    got = manager._get_file_path("2026-04-07")
    assert got == str(tmp_path / "2026" / "4" / "7" / "daily_record.json")
    assert (tmp_path / "2026" / "4" / "7").is_dir()


def test_with_record_lock_normal_exit(manager):
    entered = []
    with manager._with_record_lock("2026-04-07"):
        entered.append(True)
    assert entered == [True]


def test_with_record_lock_without_filelock_still_yields(manager, monkeypatch):
    monkeypatch.setattr(manager_mod, "FileLock", None)
    entered = []
    with manager._with_record_lock("2026-04-07"):
        entered.append(True)
    assert entered == [True]


class _FakeTimeout(Exception):
    """模拟 filelock.Timeout。"""


class _TimeoutLock:
    def __init__(self, path, timeout=None):
        self.path = path

    def __enter__(self):
        raise _FakeTimeout("locked")

    def __exit__(self, *exc):
        return False


def test_with_record_lock_timeout_raises(manager, monkeypatch):
    monkeypatch.setattr(manager_mod, "FileLock", _TimeoutLock)
    monkeypatch.setattr(manager_mod, "FileLockTimeout", _FakeTimeout)
    with pytest.raises(_FakeTimeout):
        with manager._with_record_lock("2026-04-07", timeout=0.01):
            pass


class _BoomLock:
    def __init__(self, path, timeout=None):
        self.path = path

    def __enter__(self):
        raise RuntimeError("io-error")

    def __exit__(self, *exc):
        return False


def test_with_record_lock_other_exception_propagates(manager, monkeypatch):
    monkeypatch.setattr(manager_mod, "FileLock", _BoomLock)
    with pytest.raises(RuntimeError):
        with manager._with_record_lock("2026-04-07"):
            pass


def test_get_previous_date_valid(manager):
    assert manager._get_previous_date("2026-04-07") == "2026-04-06"


def test_get_previous_date_invalid_falls_back_to_now(manager, monkeypatch):
    monkeypatch.setattr(manager_mod, "get_current_time", lambda: datetime(2026, 5, 10, 8, 0))
    assert manager._get_previous_date("bad-date") == "2026-05-09"


def test_resolve_sleep_record_date_uses_current_time(manager):
    # 未传 now_dt → 用模块内 get_current_time（12 点 → 当天）
    assert manager._resolve_sleep_record_date() == FIXED_TODAY


def test_resolve_sleep_record_date_early_morning_goes_previous_day(manager):
    assert manager._resolve_sleep_record_date(now_dt=datetime(2026, 4, 7, 3, 0)) == "2026-04-06"


def test_resolve_sleep_record_date_daytime_keeps_today(manager):
    assert manager._resolve_sleep_record_date(now_dt=datetime(2026, 4, 7, 14, 0)) == FIXED_TODAY


def test_resolve_sleep_record_date_honours_time_str_hour(manager):
    # time_str 23:30 覆盖当前 3 点 → 归当天
    got = manager._resolve_sleep_record_date("23:30", now_dt=datetime(2026, 4, 7, 3, 0))
    assert got == FIXED_TODAY


def test_resolve_sleep_record_date_invalid_time_str_ignored(manager):
    # 非法 time_str 不改变 hour，仍按当前 3 点归前一天
    got = manager._resolve_sleep_record_date("abc", now_dt=datetime(2026, 4, 7, 3, 0))
    assert got == "2026-04-06"


# ────────────────────── 默认值 / 规范化 / 压缩 / 读写 ──────────────────────


def test_default_record_shape(manager):
    rec = manager._default_record("2026-04-07")
    assert rec["date"] == "2026-04-07"
    assert rec["sleep_cycle"] == {
        "sleep": None,
        "wakeup": None,
        "duration": None,
        "sleep_source": None,
        "sleep_recorded_at": None,
        "wakeup_source": None,
        "wakeup_recorded_at": None,
    }
    assert rec["meals"] == []
    assert rec["study"] == {"sessions": [], "summary": ""}
    assert rec["activities"] == []
    assert rec["summary"] == ""


def test_normalize_record_from_legacy_schedule(manager):
    out = manager._normalize_record(
        {"schedule": {"sleep": "22:00", "wakeup": "07:00"}}, "2026-04-07"
    )
    assert "schedule" not in out
    assert out["sleep_cycle"]["sleep"] == "22:00"
    assert out["sleep_cycle"]["wakeup"] == "07:00"
    assert out["sleep_cycle"]["duration"] is None


def test_normalize_record_legacy_schedule_not_dict(manager):
    out = manager._normalize_record({"schedule": "garbage"}, "2026-04-07")
    assert out["sleep_cycle"]["sleep"] is None
    assert out["sleep_cycle"]["wakeup"] is None


def test_normalize_record_adds_default_sleep_cycle(manager):
    out = manager._normalize_record({"meals": []}, "2026-04-07")
    assert out["sleep_cycle"]["sleep"] is None
    assert out["date"] == "2026-04-07"


def test_normalize_record_non_dict_sleep_cycle_replaced(manager):
    out = manager._normalize_record({"sleep_cycle": ["bad"]}, "2026-04-07")
    assert out["sleep_cycle"]["sleep"] is None
    assert out["sleep_cycle"]["wakeup"] is None


def test_normalize_record_keeps_known_sleep_cycle_fields(manager):
    out = manager._normalize_record(
        {"sleep_cycle": {"sleep": "23:00", "wakeup": "08:00", "unknown": 1}},
        "2026-04-07",
    )
    assert out["sleep_cycle"]["sleep"] == "23:00"
    assert out["sleep_cycle"]["wakeup"] == "08:00"
    assert "unknown" not in out["sleep_cycle"]


def test_normalize_record_sanitizes_containers(manager):
    out = manager._normalize_record(
        {
            "meals": "not-a-list",
            "study": "not-a-dict",
            "activities": "not-a-list",
            "health": "not-a-list",
            "mood": 12345,
        },
        "2026-04-07",
    )
    assert out["meals"] == []
    assert out["study"] == {"sessions": [], "summary": ""}
    assert out["activities"] == []
    assert out["health"] == []
    assert out["mood"] is None
    assert out["summary"] == ""


def test_normalize_record_study_sessions_not_list(manager):
    out = manager._normalize_record({"study": {"sessions": "bad"}}, "2026-04-07")
    assert out["study"]["sessions"] == []


def test_normalize_record_none_data(manager):
    out = manager._normalize_record(None, "2026-04-07")
    assert out["date"] == "2026-04-07"
    assert out["meals"] == []


def test_compact_record(manager):
    # 空段落被剔除，有内容则保留
    empty = manager._compact_record(
        {"date": "2026-04-07", "health": [], "mood": None, "summary": "  "}
    )
    assert "health" not in empty and "mood" not in empty and "summary" not in empty
    kept = manager._compact_record(
        {"health": [{"symptom": "x"}], "mood": {"mood": "happy"}, "summary": "ok"}
    )
    assert kept["health"] == [{"symptom": "x"}]
    assert kept["mood"] == {"mood": "happy"}
    assert kept["summary"] == "ok"


def test_load_record_missing_returns_default(manager):
    rec = manager._load_record("2026-04-07")
    assert rec["date"] == "2026-04-07"
    assert rec["meals"] == []


def test_load_record_reads_existing_file(manager):
    path = manager._get_file_path("2026-04-07")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"date": "2026-04-07", "meals": [{"type": "lunch", "content": "面"}]}, f)
    rec = manager._load_record("2026-04-07")
    assert rec["meals"] == [{"type": "lunch", "content": "面"}]


def test_load_record_falls_back_to_previous_month_path(manager, tmp_path):
    # 主路径不存在 → 回退到旧的 root/YYYY/MM/{date}.json
    legacy_dir = tmp_path / "2026" / "04"
    legacy_dir.mkdir(parents=True)
    with open(legacy_dir / "2026-04-07.json", "w", encoding="utf-8") as f:
        json.dump({"date": "2026-04-07", "summary": "from-month-path"}, f)
    rec = manager._load_record("2026-04-07")
    assert rec["summary"] == "from-month-path"


def test_load_record_falls_back_to_legacy_path(manager, tmp_path):
    # 主路径与月路径都不存在 → 回退到 root/{date}.json
    with open(tmp_path / "2026-04-07.json", "w", encoding="utf-8") as f:
        json.dump({"date": "2026-04-07", "summary": "from-legacy"}, f)
    rec = manager._load_record("2026-04-07")
    assert rec["summary"] == "from-legacy"


def test_load_record_corrupt_json_returns_default(manager):
    path = manager._get_file_path("2026-04-07")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ not json ")
    rec = manager._load_record("2026-04-07")
    assert rec["date"] == "2026-04-07"
    assert rec["meals"] == []


def test_get_record_and_save_record_roundtrip(manager):
    manager._save_record({"date": "2026-04-07", "summary": "keep"}, "2026-04-07")
    assert manager.get_record("2026-04-07")["summary"] == "keep"


def test_save_record_error_is_logged(manager):
    # set 无法 JSON 序列化 → 走 except 分支且不抛出
    manager._save_record({"date": "2026-04-07", "summary": {"a"}}, "2026-04-07")
    # 落盘失败 → 读取仍是默认记录
    assert manager._load_record("2026-04-07")["summary"] == ""


# ────────────────────────── record_* / upsert_meal ──────────────────────────


def test_record_meal_appends_with_timestamp(manager):
    msg = manager.record_meal("breakfast", "粥")
    assert msg == "已记录饮食: breakfast - 粥"
    meals = manager.get_record("2026-04-07")["meals"]
    assert meals == [{"type": "breakfast", "content": "粥", "time": "12:00"}]


def test_record_drink_appends(manager):
    msg = manager.record_drink("drink", "水 300ml")
    assert msg == "已记录饮品: 水 300ml"
    meals = manager.get_record("2026-04-07")["meals"]
    assert meals[0]["type"] == "drink"
    assert meals[0]["time"] == "12:00"


def test_upsert_meal_replaces_existing(manager):
    manager.record_meal("breakfast", "旧")
    msg = manager.upsert_meal("breakfast", "新", "08:30")
    assert msg == "已校正饮食: breakfast - 新"
    meals = manager.get_record("2026-04-07")["meals"]
    assert len(meals) == 1
    assert meals[0] == {"type": "breakfast", "content": "新", "time": "08:30"}


def test_upsert_meal_appends_when_absent(manager):
    manager.record_meal("breakfast", "粥")
    manager.upsert_meal("lunch", "面")
    meals = manager.get_record("2026-04-07")["meals"]
    assert [m["type"] for m in meals] == ["breakfast", "lunch"]
    assert meals[1]["time"] == "12:00"


def test_upsert_meal_handles_non_list_meals(manager, monkeypatch):
    # _load_record 被规范化保证 meals 为 list，故直接打桩喂坏结构
    saved = []
    monkeypatch.setattr(manager, "_load_record", lambda *a, **k: {"date": "2026-04-07", "meals": "bad"})
    monkeypatch.setattr(manager, "_save_record", lambda data, *a, **k: saved.append(data))
    manager.upsert_meal("dinner", "饭")
    assert saved[0]["meals"] == [{"type": "dinner", "content": "饭", "time": "12:00"}]


def test_upsert_meal_skips_non_dict_items(manager):
    # 非 dict 项排在匹配项之后，才会真正走到 continue 分支
    path = manager._get_file_path("2026-04-07")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"date": "2026-04-07", "meals": [{"type": "breakfast", "content": "旧"}, "junk"]}, f)
    manager.upsert_meal("breakfast", "新")
    meals = manager.get_record("2026-04-07")["meals"]
    assert meals[0] == {"type": "breakfast", "content": "新", "time": "12:00"}
    assert meals[1] == "junk"


def test_upsert_meal_defaults_type_and_content(manager):
    msg = manager.upsert_meal("", "  ")
    assert msg == "已校正饮食: meal - "
    meals = manager.get_record("2026-04-07")["meals"]
    assert meals[0]["type"] == "meal"
    assert meals[0]["content"] == ""


def test_record_study_appends(manager):
    msg = manager.record_study("数学", "做了 10 题")
    assert msg == "已记录学习: 数学"
    sessions = manager.get_record("2026-04-07")["study"]["sessions"]
    assert sessions == [{"topic": "数学", "content": "做了 10 题", "time": "12:00"}]


def test_record_activity_appends(manager):
    msg = manager.record_activity("game", "打游戏")
    assert msg == "已记录活动: 打游戏"
    acts = manager.get_record("2026-04-07")["activities"]
    assert acts == [{"type": "game", "content": "打游戏", "time": "12:00"}]


def test_record_health_appends(manager):
    msg = manager.record_health("胃痛", "吃了药")
    assert msg == "已记录健康状态: 胃痛"
    health = manager.get_record("2026-04-07")["health"]
    assert health == [{"symptom": "胃痛", "detail": "吃了药", "time": "12:00"}]


def test_record_mood_sets_dict(manager):
    msg = manager.record_mood("开心", "因为天气好")
    assert msg == "已记录心情: 开心"
    mood = manager.get_record("2026-04-07")["mood"]
    assert mood == {"mood": "开心", "detail": "因为天气好", "time": "12:00"}


def test_record_methods_write_under_tmp_root(manager, tmp_path):
    # 断言所有写入都发生在 tmp_path 下，未触碰真实数据目录
    manager.record_meal("lunch", "面")
    written = list(tmp_path.rglob("daily_record.json"))
    assert len(written) == 1
    assert str(written[0]).startswith(str(tmp_path))


def test_manager_root_dir_is_patched_root(manager, tmp_path):
    assert manager.root_dir == str(tmp_path)
    assert tmp_path.is_dir()
