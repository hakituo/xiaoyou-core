"""每日新背单词日志（DailyWordLogManager）单元测试。

覆盖目标：``core/tools/study/english/daily_word_log.py`` 的分支与边界。
设计原则：
- 所有日期都注入固定的「今天」（2026/08/10 +08:00），不依赖真实系统时间；
- 文件 IO 全部落在 ``tmp_path``，不触碰仓库真实 data 目录；
- 随机抽取（quiz）只断言长度与集合关系，不断言具体元素，避免 flaky。
"""
from __future__ import annotations

import datetime
import hashlib
import os

import pytest

from core.tools.study.english import daily_word_log as dword
from core.tools.study.english.daily_word_log import DailyWordLogManager

TZ = datetime.timezone(datetime.timedelta(hours=8))
# 固定「今天」：2026/08/10 12:00 +08:00
TODAY_DT = datetime.datetime(2026, 8, 10, 12, 0, 0, tzinfo=TZ)
TODAY_STR = "2026/08/10"


def _patch_today(monkeypatch, dt: datetime.datetime) -> None:
    """把模块级时钟固定到指定时刻。"""
    monkeypatch.setattr(dword, "get_current_time", lambda: dt)
    monkeypatch.setattr(
        dword,
        "get_current_time_str",
        lambda fmt="%Y-%m-%d %H:%M:%S": dt.strftime(fmt),
    )


def _ts(year: int, month: int, day: int) -> float:
    """构造某天 10:00 +08:00 的 unix 时间戳。"""
    return datetime.datetime(year, month, day, 10, 0, tzinfo=TZ).timestamp()


def _write_day(base_dir: str, date_str: str, content: str) -> str:
    """在 base_dir 下写入某天的 daily 文件，返回路径。"""
    path = os.path.join(base_dir, *date_str.split("/")) + ".txt"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # newline="" 关闭 Windows 的 \n -> \r\n 转换，保证签名断言可预期
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return path


@pytest.fixture()
def mgr(tmp_path, monkeypatch):
    """返回一个 base_dir 隔离、时钟固定为 2026/08/10 的管理器。"""
    m = DailyWordLogManager(base_dir=str(tmp_path / "daily"))
    _patch_today(monkeypatch, TODAY_DT)
    return m


# ----------------------------------------------------------------------
# 1. 单例
# ----------------------------------------------------------------------


def test_get_daily_word_log_is_singleton(monkeypatch):
    """连续两次获取应返回同一实例。"""
    monkeypatch.setattr(dword, "_instance", None)
    first = dword.get_daily_word_log()
    second = dword.get_daily_word_log()
    assert first is second
    assert isinstance(first, DailyWordLogManager)


def test_get_daily_word_log_double_check_inside_lock(monkeypatch):
    """另一线程已在锁内创建实例时，锁内二次检查应直接复用。"""
    sentinel = object()
    monkeypatch.setattr(dword, "_instance", None)

    class _Lock:
        def __enter__(self):
            dword._instance = sentinel
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(dword, "_instance_lock", _Lock())
    assert dword.get_daily_word_log() is sentinel


# ----------------------------------------------------------------------
# 2. 日期与路径工具
# ----------------------------------------------------------------------


def test_normalize_date_and_date_to_path(mgr):
    """连字符/斜杠/空白/空值都应归一化。"""
    assert DailyWordLogManager._normalize_date("2026-08-05") == "2026/08/05"
    assert DailyWordLogManager._normalize_date(" 2026/08/05 ") == "2026/08/05"
    assert DailyWordLogManager._normalize_date(None) == ""
    path = mgr._date_to_path("2026-08-05")
    assert path.endswith(os.path.join("2026", "08", "05.txt"))


def test_get_today_and_yesterday_str(mgr):
    assert mgr._get_today_str() == TODAY_STR
    assert mgr.get_yesterday_str() == "2026/08/09"


def test_get_yesterday_str_month_and_leap_boundaries(monkeypatch, tmp_path):
    """跨月、跨闰年 2 月的昨天计算必须正确。"""
    m = DailyWordLogManager(base_dir=str(tmp_path / "d"))
    _patch_today(monkeypatch, datetime.datetime(2026, 3, 1, 12, 0, tzinfo=TZ))
    assert m.get_yesterday_str() == "2026/02/28"
    _patch_today(monkeypatch, datetime.datetime(2028, 3, 1, 12, 0, tzinfo=TZ))
    assert m.get_yesterday_str() == "2028/02/29"


def test_get_recent_dates_and_zero_days(mgr):
    assert mgr.get_recent_dates(3) == [
        "2026/08/10",
        "2026/08/09",
        "2026/08/08",
    ]
    # days<=0 至少返回今天
    assert mgr.get_recent_dates(0) == ["2026/08/10"]


# ----------------------------------------------------------------------
# 3. list_dates
# ----------------------------------------------------------------------


def test_list_dates_filters_non_daily_entries(mgr):
    base = mgr.base_dir
    _write_day(base, "2026/08/05", "a\n")
    _write_day(base, "2026/08/07", "b\n")
    _write_day(base, "2025/12/31", "c\n")
    os.makedirs(os.path.join(base, "notayear", "08"), exist_ok=True)
    with open(os.path.join(base, "notayear", "08", "01.txt"), "w") as f:
        f.write("x\n")
    os.makedirs(os.path.join(base, "2026", "notamonth"), exist_ok=True)
    with open(os.path.join(base, "2026", "notamonth", "01.txt"), "w") as f:
        f.write("x\n")
    with open(os.path.join(base, "2026", "08", "notes.md"), "w") as f:
        f.write("x\n")
    with open(os.path.join(base, "2026", "08", "xx.txt"), "w") as f:
        f.write("x\n")

    assert mgr.list_dates() == ["2026/08/07", "2026/08/05", "2025/12/31"]


def test_list_dates_missing_base_dir(mgr):
    assert mgr.list_dates() == []


def test_list_dates_oserror_is_swallowed(mgr, monkeypatch):
    os.makedirs(mgr.base_dir, exist_ok=True)

    def _boom(_path):
        raise OSError("boom")

    monkeypatch.setattr(dword.os, "listdir", _boom)
    assert mgr.list_dates() == []


# ----------------------------------------------------------------------
# 4. 复习事件判定
# ----------------------------------------------------------------------


def test_latest_review_event_variants():
    assert DailyWordLogManager._latest_review_event("not-a-dict") is None
    assert DailyWordLogManager._latest_review_event({}) is None
    assert DailyWordLogManager._latest_review_event({"history": "bad"}) is None

    data = {
        "history": [
            "bad",
            {"timestamp": "bad", "quality": 1},
            {"timestamp": 0, "quality": 1},
            {"timestamp": 100.0, "quality": 4, "source": "manual"},
            {"timestamp": 200.0, "quality": 1},
        ]
    }
    latest = DailyWordLogManager._latest_review_event(data)
    assert latest is not None
    assert latest["timestamp"] == 200.0
    assert latest["quality"] == 1


def test_pending_reason_historical_backlog_and_none(mgr):
    """无历史 -> 历史补漏；同日非 lapse -> 已处理；非法日期 -> None。"""
    assert mgr._pending_reason("2026/08/05", {}) == "historical_backlog"
    # 从未进入 progress（history 为空）
    assert (
        mgr._pending_reason("2026/08/05", {"history": []}) == "historical_backlog"
    )

    # daily 记录晚于最后一次复习 -> 历史补漏
    older = {"history": [{"timestamp": _ts(2026, 8, 1), "quality": 4}]}
    assert mgr._pending_reason("2026/08/05", older) == "historical_backlog"

    # 同日 Hard/Good 成功回忆 -> 不再待处理
    same_ok = {"history": [{"timestamp": _ts(2026, 8, 5), "quality": 4}]}
    assert mgr._pending_reason("2026/08/05", same_ok) is None

    # 非法日期 -> None
    assert mgr._pending_reason("not-a-date", same_ok) is None


def test_pending_reason_recent_retry_legacy_and_new_semantics(mgr):
    """同日 Again 判为 recent_retry，且区分新旧评分语义。"""
    # 时间戳早于 LEGACY_RATING_CUTOFF（2026-09-01）：quality<=2 都算 Again
    legacy = {"history": [{"timestamp": _ts(2026, 8, 5), "quality": 2}]}
    assert mgr._pending_reason("2026/08/05", legacy) == "recent_retry"

    # 新语义：quality=2（Hard）不再算 Again
    new_hard = {"history": [{"timestamp": _ts(2026, 9, 10), "quality": 2}]}
    assert mgr._pending_reason("2026/09/10", new_hard) is None

    new_again = {"history": [{"timestamp": _ts(2026, 9, 10), "quality": 1}]}
    assert mgr._pending_reason("2026/09/10", new_again) == "recent_retry"

    assert mgr._is_pending_for_review("2026/09/10", new_again) is True
    assert mgr._is_pending_for_review("2026/09/10", new_hard) is False


# ----------------------------------------------------------------------
# 5. 批次过滤 / 合并
# ----------------------------------------------------------------------


def test_filter_persisted_review_batch(mgr):
    """非法条目、重复、已完成条目都应被过滤。"""
    assert mgr._filter_persisted_review_batch("not-a-list", {}) == []

    entries = [
        "bad",
        None,
        {"word": "", "source_date": "2026/08/01"},
        {"word": "alpha", "source_date": ""},
        {"word": "alpha", "source_date": "2026/08/01", "unknown_count": "3"},
        {"word": "ALPHA", "source_date": "2026/08/02"},  # 重复
        {"word": "beta", "source_date": "2026/08/01"},
    ]
    result = mgr._filter_persisted_review_batch(entries, {})
    assert [r["word"] for r in result] == ["alpha", "beta"]
    assert result[0]["unknown_count"] == 3
    assert result[0]["pending_reason"] == "historical_backlog"

    # 已完成（同日成功复习）的条目被剔除
    progress = {
        "beta": {"history": [{"timestamp": _ts(2026, 8, 1), "quality": 4}]}
    }
    filtered = mgr._filter_persisted_review_batch(entries, progress)
    assert [r["word"] for r in filtered] == ["alpha"]


def test_merge_new_entries_no_change_and_backlog(mgr):
    persisted = [{"word": "a", "pending_reason": "historical_backlog"}]
    # 全部重复 -> 原样返回
    assert (
        mgr._merge_new_entries(
            persisted, [{"word": "A", "pending_reason": "historical_backlog"}]
        )
        == persisted
    )
    # 空 key 被跳过，新历史补漏追加队尾
    merged = mgr._merge_new_entries(
        persisted,
        [
            {"word": "", "pending_reason": "historical_backlog"},
            {"word": "b", "pending_reason": "historical_backlog"},
        ],
    )
    assert [i["word"] for i in merged] == ["a", "b"]


def test_merge_new_entries_recent_retry_ordering(mgr):
    persisted = [
        {"word": "a", "pending_reason": "historical_backlog"},
        {"word": "b", "pending_reason": "recent_retry"},
        {"word": "c", "pending_reason": "historical_backlog"},
    ]
    merged = mgr._merge_new_entries(
        persisted,
        [
            {"word": "d", "pending_reason": "recent_retry"},
            {"word": "e", "pending_reason": "historical_backlog"},
        ],
    )
    # recent_retry 插在最后一个 recent_retry 之后
    assert [i["word"] for i in merged] == ["a", "b", "d", "c", "e"]

    # 已锁定批次内没有 recent_retry 时，新 retry 插到最前面
    merged2 = mgr._merge_new_entries(
        [{"word": "a", "pending_reason": "historical_backlog"}],
        [{"word": "z", "pending_reason": "recent_retry"}],
    )
    assert [i["word"] for i in merged2] == ["z", "a"]


# ----------------------------------------------------------------------
# 6. 批次扫描
# ----------------------------------------------------------------------


def test_scan_review_entries_prioritizes_recent_retry(mgr):
    """recent_retry 必须排在历史补漏之前。"""
    _write_day(mgr.base_dir, "2026/08/01", "old 2\nshared\n")
    _write_day(mgr.base_dir, "2026/08/05", "retry\nshared 5\n")

    progress = {
        "retry": {"history": [{"timestamp": _ts(2026, 8, 5), "quality": 1}]},
    }
    dated = mgr._collect_dated_sources(
        datetime.date(2026, 8, 10)
    )
    entries = mgr._scan_review_entries(progress, dated, 0)
    words = [e["word"] for e in entries]
    assert words[0] == "retry"
    assert entries[0]["pending_reason"] == "recent_retry"
    # shared 在 08/05 先被扫到（新语义下 08/05 的 shared 无历史 -> backlog）
    assert set(words) == {"retry", "old", "shared"}
    assert len(words) == len(set(words))


def test_scan_review_entries_respects_batch_size(mgr):
    """限量批次要在扫描过程中提前截断。"""
    _write_day(mgr.base_dir, "2026/08/01", "a\nb\n")
    _write_day(mgr.base_dir, "2026/08/05", "c\n")
    dated = mgr._collect_dated_sources(datetime.date(2026, 8, 10))

    limited = mgr._scan_review_entries({}, dated, 2)
    assert len(limited) == 2

    # recent_retry 先占满名额时，历史补漏不再补
    progress = {
        "c": {"history": [{"timestamp": _ts(2026, 8, 5), "quality": 1}]},
    }
    retry_first = mgr._scan_review_entries(progress, dated, 1)
    assert [e["word"] for e in retry_first] == ["c"]
    assert retry_first[0]["pending_reason"] == "recent_retry"


def test_scan_review_entries_skips_seen_and_processed(mgr):
    """跨天重复的 recent_retry 只取一次；已处理的词在补漏阶段被跳过。"""
    _write_day(mgr.base_dir, "2026/08/01", "retry\ndone\n")
    _write_day(mgr.base_dir, "2026/08/05", "retry\nsame\n")

    progress = {
        # 08/05 的 retry 刚答错 -> recent_retry；08/01 的 retry 属重复
        "retry": {"history": [{"timestamp": _ts(2026, 8, 5), "quality": 1}]},
        # 08/05 的 same 已成功复习 -> 不待处理（补漏阶段命中 continue）
        "same": {"history": [{"timestamp": _ts(2026, 8, 5), "quality": 4}]},
    }
    dated = mgr._collect_dated_sources(datetime.date(2026, 8, 10))
    entries = mgr._scan_review_entries(progress, dated, 0)
    words = [e["word"] for e in entries]
    assert words.count("retry") == 1
    assert entries[0] == {
        "word": "retry",
        "unknown_count": 0,
        "source_date": "2026/08/05",
        "pending_reason": "recent_retry",
    }
    assert "done" in words
    assert "same" not in words


# ----------------------------------------------------------------------
# 7. get_review_batch
# ----------------------------------------------------------------------


def test_get_review_batch_first_scan_and_persist(mgr):
    _write_day(mgr.base_dir, "2026/08/01", "alpha 2\nbeta\n")
    _write_day(mgr.base_dir, "2026/08/05", "gamma\n")

    entries = mgr.get_review_batch({}, 0)
    assert [e["word"] for e in entries] == ["alpha", "beta", "gamma"]
    assert entries[0]["source_date"] == "2026/08/01"
    # 已落盘
    state = dword.safe_json_load(mgr._review_batch_state_path, default={})
    assert state["version"] == 5
    assert state["review_date"] == TODAY_STR


def test_get_review_batch_limited_reuses_persisted(mgr):
    """限量批次一旦锁定，不再动态追加新候选。"""
    _write_day(mgr.base_dir, "2026/08/01", "alpha\n")
    assert len(mgr.get_review_batch({}, 0)) == 1

    _write_day(mgr.base_dir, "2026/08/03", "delta\n")
    # batch_size>0：直接返回已锁定条目，不吸收 delta
    limited = mgr.get_review_batch({}, 2)
    assert [e["word"] for e in limited] == ["alpha"]


def test_get_review_batch_full_absorbs_manual_edit(mgr):
    """全量批次感知到用户手动新增文件后，把新词补进当天批次。"""
    _write_day(mgr.base_dir, "2026/08/01", "alpha\n")
    assert len(mgr.get_review_batch({}, 0)) == 1

    _write_day(mgr.base_dir, "2026/08/03", "delta\n")
    merged = mgr.get_review_batch({}, 0)
    assert [e["word"] for e in merged] == ["alpha", "delta"]
    assert merged[-1]["pending_reason"] == "historical_backlog"


def test_get_review_batch_full_no_change_returns_persisted(mgr):
    """签名未变时直接返回已锁定批次。"""
    _write_day(mgr.base_dir, "2026/08/01", "alpha\n")
    first = mgr.get_review_batch({}, 0)
    second = mgr.get_review_batch({}, 0)
    assert [e["word"] for e in second] == [e["word"] for e in first]


# ----------------------------------------------------------------------
# 8. 源文件签名
# ----------------------------------------------------------------------


def test_file_signature_missing_and_directory(mgr, tmp_path):
    assert mgr._file_signature(str(tmp_path / "nope.txt")) == ""
    # 目录无法以 rb 打开 -> OSError -> 空串
    assert mgr._file_signature(str(tmp_path)) == ""
    path = _write_day(mgr.base_dir, "2026/08/01", "alpha\n")
    expected = hashlib.sha1(b"alpha\n").hexdigest()
    assert mgr._file_signature(path) == expected


def test_collect_source_signatures(mgr):
    _write_day(mgr.base_dir, "2026/08/01", "alpha\n")
    _write_day(mgr.base_dir, "2026/08/05", "beta\n")
    _write_day(mgr.base_dir, TODAY_STR, "today\n")  # 今天的不采集
    sigs = mgr._collect_source_signatures()
    assert set(sigs) == {"2026/08/01", "2026/08/05"}


def test_collect_source_signatures_bad_today_and_bad_dates(mgr, monkeypatch):
    monkeypatch.setattr(mgr, "_get_today_str", lambda: "garbage")
    assert mgr._collect_source_signatures() == {}

    monkeypatch.setattr(mgr, "_get_today_str", lambda: TODAY_STR)
    monkeypatch.setattr(mgr, "list_dates", lambda: ["bogus", "2026/08/01"])
    _write_day(mgr.base_dir, "2026/08/01", "alpha\n")
    assert set(mgr._collect_source_signatures()) == {"2026/08/01"}


def test_collect_dated_sources_skips_invalid(mgr, monkeypatch):
    _write_day(mgr.base_dir, "2026/08/01", "alpha\n")
    monkeypatch.setattr(
        mgr, "list_dates", lambda: ["bogus", "2026/08/01", TODAY_STR]
    )
    dated = mgr._collect_dated_sources(datetime.date(2026, 8, 10))
    assert dated == [(datetime.date(2026, 8, 1), "2026/08/01")]


def test_sync_source_signatures_three_paths(mgr, monkeypatch):
    path = _write_day(mgr.base_dir, "2026/08/01", "alpha\n")
    sig = mgr._file_signature(path)
    current = {"2026/08/01": sig}

    # 1) 快照一致 -> False
    assert mgr._sync_source_signatures({"source_signatures": dict(current)}) is False

    # 2) 差异全部来自本管理器自写 -> 刷新快照并返回 False
    mgr._self_written = dict(current)
    mgr._update_review_batch_fields  # 存在性
    dword.safe_json_dump(
        {"review_date": TODAY_STR, "entries": []}, mgr._review_batch_state_path
    )
    assert mgr._sync_source_signatures({"source_signatures": {}}) is False
    state = dword.safe_json_load(mgr._review_batch_state_path, default={})
    assert state.get("source_signatures") == current

    # 3) 真外部编辑 -> True
    mgr._self_written = {}
    assert mgr._sync_source_signatures({"source_signatures": {}}) is True


# ----------------------------------------------------------------------
# 9. 自写签名持久化
# ----------------------------------------------------------------------


def test_record_self_write_early_returns(mgr):
    # 空日期 / 文件不存在 -> 不记录
    mgr._record_self_write(None)
    mgr._record_self_write("2026/08/99")
    assert mgr._self_written == {}

    _write_day(mgr.base_dir, "2026/08/01", "alpha\n")
    mgr._record_self_write("2026/08/01")
    assert "2026/08/01" in mgr._self_written


def test_persist_self_write_variants(mgr):
    # 状态不是 dict -> 早退
    mgr._persist_self_write("2026/08/01", "sig")
    # review_date 不匹配 -> 早退
    dword.safe_json_dump(
        {"review_date": "1999/01/01"}, mgr._review_batch_state_path
    )
    mgr._persist_self_write("2026/08/01", "sig")
    state = dword.safe_json_load(mgr._review_batch_state_path, default={})
    assert "self_written_signatures" not in state

    # 正常写入
    dword.safe_json_dump(
        {"review_date": TODAY_STR}, mgr._review_batch_state_path
    )
    mgr._persist_self_write("2026/08/01", "sig")
    state = dword.safe_json_load(mgr._review_batch_state_path, default={})
    assert state["self_written_signatures"] == {"2026/08/01": "sig"}

    # 签名未变 -> 早退（selected_at 不被改写）
    state["selected_at"] = "keep-me"
    dword.safe_json_dump(state, mgr._review_batch_state_path)
    mgr._persist_self_write("2026/08/01", "sig")
    assert (
        dword.safe_json_load(mgr._review_batch_state_path, default={})[
            "selected_at"
        ]
        == "keep-me"
    )


def test_persist_self_write_oserror(mgr, monkeypatch):
    dword.safe_json_dump(
        {"review_date": TODAY_STR}, mgr._review_batch_state_path
    )

    def _boom(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr(dword, "safe_json_dump", _boom)
    mgr._persist_self_write("2026/08/01", "sig")  # 不应抛出
    state = dword.safe_json_load(mgr._review_batch_state_path, default={})
    assert "self_written_signatures" not in state


def test_update_review_batch_fields(mgr):
    # 无状态文件 -> 早退
    mgr._update_review_batch_fields({"x": 1})
    assert not os.path.exists(mgr._review_batch_state_path)

    # review_date 不匹配 -> 早退
    dword.safe_json_dump(
        {"review_date": "1999/01/01", "keep": True}, mgr._review_batch_state_path
    )
    mgr._update_review_batch_fields({"x": 1})
    state = dword.safe_json_load(mgr._review_batch_state_path, default={})
    assert state == {"review_date": "1999/01/01", "keep": True}

    # 正常更新
    dword.safe_json_dump(
        {"review_date": TODAY_STR, "entries": []}, mgr._review_batch_state_path
    )
    mgr._update_review_batch_fields({"x": 1})
    state = dword.safe_json_load(mgr._review_batch_state_path, default={})
    assert state["x"] == 1


def test_update_review_batch_fields_oserror(mgr, monkeypatch):
    dword.safe_json_dump(
        {"review_date": TODAY_STR, "entries": []}, mgr._review_batch_state_path
    )

    def _boom(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr(dword, "safe_json_dump", _boom)
    mgr._update_review_batch_fields({"x": 1})  # 不应抛出
    state = dword.safe_json_load(mgr._review_batch_state_path, default={})
    assert "x" not in state


def test_write_review_batch_state_merges_old_written(mgr):
    _write_day(mgr.base_dir, "2026/08/01", "alpha\n")
    dword.safe_json_dump(
        {
            "review_date": TODAY_STR,
            "self_written_signatures": {"2026/08/01": "s1", 3: "bad"},
        },
        mgr._review_batch_state_path,
    )
    mgr._self_written = {"2026/08/02": "s2"}
    mgr._write_review_batch_state([{"word": "alpha"}], 0, TODAY_STR)

    state = dword.safe_json_load(mgr._review_batch_state_path, default={})
    assert state["version"] == 5
    # JSON 会把 int 键 3 序列化成字符串 "3"，因此它会被保留（已非 int）
    assert state["self_written_signatures"] == {
        "2026/08/01": "s1",
        "3": "bad",
        "2026/08/02": "s2",
    }
    assert state["source_signatures"] == mgr._collect_source_signatures()


def test_write_review_batch_state_oserror(mgr, monkeypatch):
    def _boom(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr(dword, "safe_json_dump", _boom)
    mgr._write_review_batch_state([], 0, TODAY_STR)  # 不应抛出
    assert not os.path.exists(mgr._review_batch_state_path)


# ----------------------------------------------------------------------
# 10. 最终复习队列
# ----------------------------------------------------------------------


def test_normalize_review_queue_entries(mgr):
    assert mgr._normalize_review_queue_entries("bad") == []
    entries = [
        "bad",
        {"word": "", "review_source": "fsrs"},
        {"word": "a", "review_source": "unknown"},
        {"word": "b", "review_source": "fsrs"},
        {"word": "B", "review_source": "fsrs"},  # 重复
        {"word": "c", "review_source": "daily_backlog", "source_date": ""},
    ]
    result = mgr._normalize_review_queue_entries(entries)
    assert [r["word"] for r in result] == ["b", "c"]
    assert result[0]["source_date"] is None
    assert result[1]["source_date"] is None


def test_get_persisted_review_queue_variants(mgr):
    assert mgr.get_persisted_review_queue() is None

    dword.safe_json_dump(
        {"version": 4, "review_date": TODAY_STR, "entries": []},
        mgr._review_queue_state_path,
    )
    assert mgr.get_persisted_review_queue() is None

    dword.safe_json_dump(
        {"version": 5, "review_date": "1999/01/01", "entries": []},
        mgr._review_queue_state_path,
    )
    assert mgr.get_persisted_review_queue() is None

    dword.safe_json_dump(
        {
            "version": 5,
            "review_date": TODAY_STR,
            "entries": [{"word": "a", "review_source": "fsrs"}],
        },
        mgr._review_queue_state_path,
    )
    assert mgr.get_persisted_review_queue() == [
        {"word": "a", "review_source": "fsrs", "source_date": None}
    ]


def test_persist_review_queue_first_and_reuse(mgr):
    entries = [
        {"word": "a", "review_source": "fsrs"},
        {"word": "", "review_source": "fsrs"},
        {"word": "b", "review_source": "daily_backlog", "source_date": "2026-08-01"},
        {"word": "c", "review_source": "nope"},
    ]
    result = mgr.persist_review_queue(entries, 0)
    assert [r["word"] for r in result] == ["a", "b"]
    assert result[1]["source_date"] == "2026/08/01"

    # 二次调用复用已锁定队列
    again = mgr.persist_review_queue([{"word": "z", "review_source": "fsrs"}], 0)
    assert again == result


def test_persist_review_queue_batch_limit_and_race(mgr, monkeypatch):
    entries = [
        {"word": "a", "review_source": "fsrs"},
        {"word": "b", "review_source": "fsrs"},
        {"word": "c", "review_source": "fsrs"},
    ]
    limited = mgr.persist_review_queue(entries, 2)
    assert [r["word"] for r in limited] == ["a", "b"]

    # 模拟「读后另一线程先写入」：get 返回 None，但锁内已有合法状态
    monkeypatch.setattr(mgr, "get_persisted_review_queue", lambda: None)
    raced = mgr.persist_review_queue(entries, 0)
    assert [r["word"] for r in raced] == ["a", "b"]


def test_persist_review_queue_oserror(mgr, monkeypatch):
    def _boom(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr(dword, "safe_json_dump", _boom)
    result = mgr.persist_review_queue(
        [{"word": "a", "review_source": "fsrs"}], 0
    )
    assert [r["word"] for r in result] == ["a"]
    assert not os.path.exists(mgr._review_queue_state_path)


def test_sync_review_queue_creates_when_absent(mgr):
    result = mgr.sync_review_queue(
        [{"word": "a", "review_source": "daily_backlog"}], 0
    )
    assert [r["word"] for r in result] == ["a"]
    assert mgr.get_persisted_review_queue() is not None


def test_sync_review_queue_merges_and_reorders(mgr):
    # 先锁定队列：fsrs a, daily b
    mgr.persist_review_queue(
        [
            {"word": "a", "review_source": "fsrs"},
            {"word": "b", "review_source": "daily_backlog", "source_date": "2026/08/01"},
        ],
        0,
    )
    # a 来源漂移成 daily_backlog；新增 c(daily) 与 d(fsrs)
    synced = mgr.sync_review_queue(
        [
            {"word": "a", "review_source": "daily_backlog", "source_date": "2026/08/02"},
            {"word": "c", "review_source": "daily_backlog"},
            {"word": "d", "review_source": "fsrs"},
            {"word": "", "review_source": "fsrs"},
            {"word": "e", "review_source": "bad"},
        ],
        0,
    )
    words = [r["word"] for r in synced]
    # a 原位替换来源；c 插在最后一个 daily_backlog 之后；d 不新增（已锁定的才同步）
    assert words == ["a", "b", "c"]
    assert synced[0]["review_source"] == "daily_backlog"
    assert synced[0]["source_date"] == "2026/08/02"


def test_sync_review_queue_prepends_when_no_daily_locked(mgr):
    mgr.persist_review_queue(
        [{"word": "a", "review_source": "fsrs"}], 0
    )
    synced = mgr.sync_review_queue(
        [
            {"word": "a", "review_source": "fsrs"},
            {"word": "b", "review_source": "daily_backlog"},
        ],
        0,
    )
    assert [r["word"] for r in synced] == ["b", "a"]


def test_sync_review_queue_unchanged_returns_existing(mgr):
    locked = mgr.persist_review_queue(
        [{"word": "a", "review_source": "fsrs"}], 0
    )
    synced = mgr.sync_review_queue(
        [{"word": "a", "review_source": "fsrs"}], 0
    )
    assert synced == locked


def test_write_review_queue_state_skip_and_write(mgr):
    dword.safe_json_dump(
        {
            "version": 5,
            "review_date": TODAY_STR,
            "entries": [{"word": "a", "review_source": "fsrs"}],
            "selected_at": "keep-me",
        },
        mgr._review_queue_state_path,
    )
    # 与现有规范化结果一致 -> 早退，selected_at 不变
    mgr._write_review_queue_state(
        [{"word": "a", "review_source": "fsrs", "source_date": None}], 0
    )
    state = dword.safe_json_load(mgr._review_queue_state_path, default={})
    assert state["selected_at"] == "keep-me"

    # 内容变化 -> 覆写
    mgr._write_review_queue_state(
        [{"word": "b", "review_source": "daily_backlog", "source_date": None}], 2
    )
    state = dword.safe_json_load(mgr._review_queue_state_path, default={})
    assert state["entries"][0]["word"] == "b"
    assert state["batch_size"] == 2


def test_write_review_queue_state_oserror(mgr, monkeypatch):
    def _boom(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr(dword, "safe_json_dump", _boom)
    mgr._write_review_queue_state([{"word": "a"}], 0)  # 不应抛出
    assert not os.path.exists(mgr._review_queue_state_path)


# ----------------------------------------------------------------------
# 11. 默认复习来源
# ----------------------------------------------------------------------


def test_get_default_review_date_locked_source(mgr):
    dword.safe_json_dump(
        {"review_date": TODAY_STR, "source_date": "2026/08/05"},
        mgr._review_state_path,
    )
    assert mgr.get_default_review_date() == "2026/08/05"


def test_get_default_review_date_invalid_or_future_locked_source(mgr):
    # 非法 source_date -> 落回扫描
    dword.safe_json_dump(
        {"review_date": TODAY_STR, "source_date": "bad"},
        mgr._review_state_path,
    )
    assert mgr.get_default_review_date() == "2026/08/09"

    # source_date >= today -> 落回扫描
    dword.safe_json_dump(
        {"review_date": TODAY_STR, "source_date": TODAY_STR},
        mgr._review_state_path,
    )
    assert mgr.get_default_review_date() == "2026/08/09"


def test_get_default_review_date_picks_latest_non_empty(mgr):
    _write_day(mgr.base_dir, "2026/08/01", "a\n")
    _write_day(mgr.base_dir, "2026/08/05", "b\n")
    _write_day(mgr.base_dir, "2026/08/06", "")  # 空占位文件被跳过
    assert mgr.get_default_review_date() == "2026/08/05"

    state = dword.safe_json_load(mgr._review_state_path, default={})
    assert state["review_date"] == TODAY_STR
    assert state["source_date"] == "2026/08/05"


def test_get_default_review_date_skips_invalid_dates(mgr, monkeypatch):
    _write_day(mgr.base_dir, "2026/08/05", "b\n")
    monkeypatch.setattr(mgr, "list_dates", lambda: ["bogus", "2026/08/05"])
    assert mgr.get_default_review_date() == "2026/08/05"


def test_get_default_review_date_oserror_falls_back(mgr, monkeypatch):
    _write_day(mgr.base_dir, "2026/08/01", "a\n")

    def _boom(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr(dword, "safe_json_dump", _boom)
    # 落盘失败仍返回选中的来源日期
    assert mgr.get_default_review_date() == "2026/08/01"


def test_get_default_review_date_empty_history(mgr):
    assert mgr.get_default_review_date() == "2026/08/09"


# ----------------------------------------------------------------------
# 12. 文件 / 读取
# ----------------------------------------------------------------------


def test_ensure_today_file_is_idempotent(mgr):
    path = mgr.ensure_today_file()
    assert os.path.exists(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write("keep\n")
    again = mgr.ensure_today_file()
    assert again == path
    with open(path, "r", encoding="utf-8") as f:
        assert f.read() == "keep\n"


def test_get_book_for_date_is_cached(mgr):
    _write_day(mgr.base_dir, "2026/08/01", "alpha\n")
    first = mgr._get_book_for_date("2026-08-01")
    second = mgr._get_book_for_date("2026/08/01")
    assert first is second


def test_get_words_for_date_and_recent_days(mgr):
    _write_day(mgr.base_dir, "2026/08/10", "alpha 2\nbeta\n")
    _write_day(mgr.base_dir, "2026/08/09", "gamma\n")

    words = mgr.get_words_for_date("2026-08-10")
    assert [(w["word"], w["unknown_count"], w["date"]) for w in words] == [
        ("alpha", 2, "2026/08/10"),
        ("beta", 0, "2026/08/10"),
    ]

    recent = mgr.get_words_for_recent_days(2)
    assert {w["word"] for w in recent} == {"alpha", "beta", "gamma"}


def test_get_merged_recent_words_sums_counts(mgr):
    _write_day(mgr.base_dir, "2026/08/10", "alpha 2\nbeta\n")
    _write_day(mgr.base_dir, "2026/08/09", "alpha 1\n")
    merged = {w["word"]: w for w in mgr.get_merged_recent_words(2)}
    assert merged["alpha"]["unknown_count"] == 3
    assert merged["alpha"]["occurrence_count"] == 2
    assert merged["alpha"]["dates"] == ["2026/08/10", "2026/08/09"]
    assert merged["beta"]["unknown_count"] == 0
    assert merged["beta"]["occurrence_count"] == 1


def test_get_words_for_all_dates(mgr):
    _write_day(mgr.base_dir, "2026/08/01", "alpha\n")
    _write_day(mgr.base_dir, "2026/08/05", "beta\n")
    words = {w["word"] for w in mgr.get_words_for_all_dates()}
    assert words == {"alpha", "beta"}


# ----------------------------------------------------------------------
# 13. quiz
# ----------------------------------------------------------------------


def test_quiz_empty_and_by_date(mgr):
    assert mgr.quiz(date="2026/08/01") == []

    _write_day(mgr.base_dir, "2026/08/01", "a 3\nb\nc 1\n")
    high = mgr.quiz(count=2, date="2026-08-01", priority="high_count")
    assert [w["word"] for w in high] == ["a", "c"]

    rand = mgr.quiz(count=10, date="2026/08/01", priority="random")
    assert len(rand) == 3
    assert {w["word"] for w in rand} == {"a", "b", "c"}


def test_quiz_priority_new(mgr):
    _write_day(mgr.base_dir, "2026/08/10", "x 2\ny\n")
    new = mgr.quiz(count=5, priority="new")
    assert [w["word"] for w in new] == ["y"]
    assert new[0]["unknown_count"] == 0

    # 没有未测验词时退回全量池
    _write_day(mgr.base_dir, "2026/08/09", "z 4\n")
    os.remove(mgr._date_to_path("2026/08/10"))
    mgr._books.clear()
    fallback = mgr.quiz(count=5, priority="new")
    assert [w["word"] for w in fallback] == ["z"]


def test_quiz_merged_high_count_across_days(mgr):
    _write_day(mgr.base_dir, "2026/08/10", "alpha 2\n")
    _write_day(mgr.base_dir, "2026/08/09", "alpha 1\nbeta 5\n")
    result = mgr.quiz(count=2, days=2, priority="high_count")
    assert result[0]["word"] == "beta"  # 5 > 3
    assert {w["word"] for w in result} == {"alpha", "beta"}


# ----------------------------------------------------------------------
# 14. 标记与移除
# ----------------------------------------------------------------------


def test_find_latest_date_containing(mgr):
    _write_day(mgr.base_dir, "2026/08/01", "alpha\n")
    _write_day(mgr.base_dir, "2026/08/05", "Alpha 2\n")
    assert mgr._find_latest_date_containing("ALPHA") == "2026/08/05"
    assert mgr._find_latest_date_containing("missing") is None


def test_mark_unknown_with_date_and_latest_and_new(mgr):
    result = mgr.mark_unknown("solo", date="2026-08-01")
    assert result["date"] == "2026/08/01"
    assert result["added"] is True

    result2 = mgr.mark_unknown("solo")
    assert result2["date"] == "2026/08/01"
    assert result2["unknown_count"] == 2

    result3 = mgr.mark_unknown("brandnew")
    assert result3["date"] == TODAY_STR
    assert os.path.exists(mgr._date_to_path(TODAY_STR))


def test_mark_known_with_date_and_latest_and_missing(mgr):
    _write_day(mgr.base_dir, "2026/08/01", "alpha 2\n")

    r1 = mgr.mark_known("alpha", date="2026-08-01")
    assert r1["date"] == "2026/08/01"
    assert r1["unknown_count"] == 1

    r2 = mgr.mark_known("alpha")
    assert r2["date"] == "2026/08/01"
    assert r2["unknown_count"] == 0

    r3 = mgr.mark_known("ghost")
    assert r3 == {
        "word": "ghost",
        "unknown_count": 0,
        "added": False,
        "date": None,
    }


def test_remove_with_date_and_latest_and_missing(mgr):
    _write_day(mgr.base_dir, "2026/08/01", "alpha\nbeta\n")

    r1 = mgr.remove("alpha", date="2026-08-01")
    assert r1["date"] == "2026/08/01"
    assert r1["removed"] is True

    r2 = mgr.remove("beta")
    assert r2["date"] == "2026/08/01"
    assert r2["removed"] is True

    r3 = mgr.remove("ghost")
    assert r3 == {"word": "ghost", "removed": False, "date": None}


# ----------------------------------------------------------------------
# 15. stats
# ----------------------------------------------------------------------


def test_stats_recent_window(mgr):
    _write_day(mgr.base_dir, "2026/08/10", "alpha 2\nbeta\n")
    _write_day(mgr.base_dir, "2026/08/09", "alpha 1\ngamma 3\n")
    _write_day(mgr.base_dir, "2026/07/01", "old 9\n")

    stats = mgr.stats(days=7)
    assert stats["status"] == "success"
    assert stats["total_words"] == 3
    assert stats["untested_words"] == 1
    assert stats["struggling_words"] == 2
    assert stats["max_unknown_count"] == 3
    assert stats["dates_with_words"] == ["2026/08/10", "2026/08/09"]
    assert stats["available_word_files"] == [
        "daily/2026/08/10.txt",
        "daily/2026/08/09.txt",
    ]
    assert stats["days_covered"] == 7
    assert stats["total_history_dates"] == 3
    assert stats["earliest_date"] == "2026/07/01"
    assert stats["latest_date"] == "2026/08/10"


def test_stats_empty(mgr):
    stats = mgr.stats(days=7)
    assert stats["total_words"] == 0
    assert stats["max_unknown_count"] == 0
    assert stats["earliest_date"] is None
    assert stats["latest_date"] is None
    assert stats["dates_with_words"] == []
