"""验证 DailyWordLogManager 与 word_quiz 的 source=daily 路径

使用临时目录，不污染真实 data/study_data/English/Words/daily/

运行：
    venv_core\\scripts\\python.exe tests\\scripts\\study\\verify_daily_word_log.py
"""
from __future__ import annotations

import os
import random
import shutil
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _make_manager_with_today(today_str: str):
    """构造一个 DailyWordLogManager，并 monkey-patch 今天的日期

    返回 (manager, tmp_base_dir)
    """
    from core.tools.study.english import daily_word_log as dwl_module

    tmp_base = tempfile.mkdtemp(prefix="daily_word_test_")

    manager = dwl_module.DailyWordLogManager(base_dir=tmp_base)

    # 替换 _get_today_str 让测试可控
    manager._get_today_str = staticmethod(lambda: today_str)
    # 也要替换类方法版（被 _find_latest_date_containing 等用到）
    # 实际上 _get_today_str 是 staticmethod，实例属性会覆盖类属性
    # 但 staticmethod 不能直接赋给实例，需要用 lambda
    manager._get_today_str = lambda: today_str

    return manager, tmp_base


def _write_daily_file(base_dir: str, date_str: str, content: str):
    """直接写一个日期文件"""
    normalized = date_str.replace("-", "/")
    parts = normalized.split("/")
    path = os.path.join(base_dir, *parts) + ".txt"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_date_to_path():
    """日期转路径正确（支持 / 和 - 分隔）"""
    from core.tools.study.english.daily_word_log import DailyWordLogManager

    m = DailyWordLogManager(base_dir="C:/tmp/words")
    assert m._date_to_path("2026/08/05") == os.path.join(
        "C:/tmp/words", "2026", "08", "05.txt"
    )
    assert m._date_to_path("2026-08-05") == os.path.join(
        "C:/tmp/words", "2026", "08", "05.txt"
    )
    print("[OK] test_date_to_path")


def test_ensure_today_file_creates_dir_and_file():
    """ensure_today_file 自动创建目录和空文件"""
    manager, tmp = _make_manager_with_today("2026/08/05")
    try:
        path = manager.ensure_today_file()
        assert os.path.exists(path), f"文件未创建：{path}"
        # 目录结构正确
        assert path.endswith(os.path.join("2026", "08", "05.txt"))
        # 再次调用幂等
        path2 = manager.ensure_today_file()
        assert path == path2
        print("[OK] test_ensure_today_file_creates_dir_and_file")
    finally:
        shutil.rmtree(tmp)


def test_list_dates_descending():
    """列出所有日期，降序"""
    manager, tmp = _make_manager_with_today("2026/08/10")
    try:
        _write_daily_file(tmp, "2026/08/05", "apple\n")
        _write_daily_file(tmp, "2026/08/08", "banana\n")
        _write_daily_file(tmp, "2026/08/01", "cherry\n")
        # 写一个非日期文件，应该被忽略
        _write_daily_file(tmp, "2026/08/README", "ignore me\n")

        dates = manager.list_dates()
        assert dates == ["2026/08/08", "2026/08/05", "2026/08/01"], f"实际：{dates}"
        print("[OK] test_list_dates_descending")
    finally:
        shutil.rmtree(tmp)


def test_get_words_for_date_with_date_field():
    """读取某天的单词，每条带 date 字段"""
    manager, tmp = _make_manager_with_today("2026/08/05")
    try:
        _write_daily_file(tmp, "2026/08/05", "apple\nbanana 2\n")
        words = manager.get_words_for_date("2026/08/05")
        assert len(words) == 2
        assert all(w["date"] == "2026/08/05" for w in words)
        word_map = {w["word"]: w["unknown_count"] for w in words}
        assert word_map["apple"] == 0
        assert word_map["banana"] == 2
        print("[OK] test_get_words_for_date_with_date_field")
    finally:
        shutil.rmtree(tmp)


def test_get_recent_dates():
    """最近 N 天日期列表"""
    manager, _ = _make_manager_with_today("2026/08/10")
    try:
        dates = manager.get_recent_dates(3)
        assert dates == ["2026/08/10", "2026/08/09", "2026/08/08"], f"实际：{dates}"
        print("[OK] test_get_recent_dates")
    finally:
        pass  # 没创建文件，不用清理


def test_get_words_for_recent_days():
    """读取最近 N 天的单词（跨多天）"""
    manager, tmp = _make_manager_with_today("2026/08/10")
    try:
        _write_daily_file(tmp, "2026/08/10", "apple\n")
        _write_daily_file(tmp, "2026/08/09", "banana 1\n")
        _write_daily_file(tmp, "2026/08/05", "cherry 3\n")  # 超出 3 天范围
        _write_daily_file(tmp, "2026/08/01", "date_word\n")  # 超出范围

        words = manager.get_words_for_recent_days(days=3)
        # 应该包含 08/10、08/09、08/08 三天的，08/05 不在内
        word_map = {w["word"]: w for w in words}
        assert "apple" in word_map
        assert "banana" in word_map
        assert "cherry" not in word_map, "08/05 应在 3 天范围外"
        assert "date_word" not in word_map

        # 每个词应有对应 date
        assert word_map["apple"]["date"] == "2026/08/10"
        assert word_map["banana"]["date"] == "2026/08/09"
        print("[OK] test_get_words_for_recent_days")
    finally:
        shutil.rmtree(tmp)


def test_quiz_high_count_cross_days():
    """high_count 跨多天按 count 降序"""
    manager, tmp = _make_manager_with_today("2026/08/10")
    try:
        _write_daily_file(tmp, "2026/08/10", "apple 1\n")
        _write_daily_file(tmp, "2026/08/09", "banana 5\n")
        _write_daily_file(tmp, "2026/08/08", "cherry 3\n")
        # 7 天范围 = 08/10 ~ 08/04，08/03 才算超出
        _write_daily_file(tmp, "2026/08/03", "old_word 9\n")  # 超出 7 天范围

        random.seed(42)
        words = manager.quiz(count=2, days=7, priority="high_count")
        # 应该抽到 banana(5) 和 cherry(3)，apple(1) 排后
        word_counts = {w["word"]: w["unknown_count"] for w in words}
        assert "banana" in word_counts, f"banana 应在抽到的词里：{word_counts}"
        assert "cherry" in word_counts, f"cherry 应在抽到的词里：{word_counts}"
        assert "old_word" not in word_counts, "超出 7 天的不应被抽到"
        print("[OK] test_quiz_high_count_cross_days")
    finally:
        shutil.rmtree(tmp)


def test_quiz_specified_date():
    """指定 date 时只抽那天"""
    manager, tmp = _make_manager_with_today("2026/08/10")
    try:
        _write_daily_file(tmp, "2026/08/10", "apple\n")
        _write_daily_file(tmp, "2026/08/09", "banana\ncherry\n")

        # 指定 08/09
        words = manager.quiz(count=5, date="2026/08/09", priority="random")
        word_set = {w["word"] for w in words}
        assert word_set == {"banana", "cherry"}, f"应只抽 08/09 的词，实际：{word_set}"

        # 用 - 分隔也行
        words = manager.quiz(count=5, date="2026-08-09", priority="random")
        assert {w["word"] for w in words} == {"banana", "cherry"}

        # 指定不存在的日期
        words = manager.quiz(count=5, date="2020/01/01", priority="random")
        assert words == []
        print("[OK] test_quiz_specified_date")
    finally:
        shutil.rmtree(tmp)


def test_quiz_new_priority():
    """new 优先抽 count=0 的"""
    manager, tmp = _make_manager_with_today("2026/08/10")
    try:
        _write_daily_file(tmp, "2026/08/10", "apple 0\nbanana 3\ncherry 0\n")
        random.seed(0)
        words = manager.quiz(count=2, priority="new")
        for w in words:
            assert w["unknown_count"] == 0, f"new 应抽未测验词，实际 count={w['unknown_count']}"
        print("[OK] test_quiz_new_priority")
    finally:
        shutil.rmtree(tmp)


def test_mark_unknown_existing_in_recent_date():
    """mark_unknown 已存在的词：在最近出现该词的那天 +1"""
    manager, tmp = _make_manager_with_today("2026/08/10")
    try:
        _write_daily_file(tmp, "2026/08/08", "apple 1\n")
        _write_daily_file(tmp, "2026/08/10", "banana 2\n")

        # apple 在 08/08，应该改 08/08 那天
        result = manager.mark_unknown("apple")
        assert result["unknown_count"] == 2, f"apple 应 1->2，实际 {result['unknown_count']}"
        assert result["date"] == "2026/08/08", f"应写回 08/08，实际 {result['date']}"

        # 验证文件
        path_0808 = os.path.join(tmp, "2026", "08", "08.txt")
        content = _read_file(path_0808)
        assert "apple 2" in content
        print("[OK] test_mark_unknown_existing_in_recent_date")
    finally:
        shutil.rmtree(tmp)


def test_mark_unknown_picks_latest_when_multiple_dates():
    """词在多天都有，选最近的那天改"""
    manager, tmp = _make_manager_with_today("2026/08/10")
    try:
        _write_daily_file(tmp, "2026/08/05", "apple 1\n")
        _write_daily_file(tmp, "2026/08/08", "apple 2\n")  # 更近的
        _write_daily_file(tmp, "2026/08/10", "banana\n")

        result = manager.mark_unknown("apple")
        assert result["date"] == "2026/08/08", f"应选最近的 08/08，实际 {result['date']}"
        assert result["unknown_count"] == 3, f"应 2->3，实际 {result['unknown_count']}"

        # 08/05 的 apple 应保持不变
        path_0805 = os.path.join(tmp, "2026", "08", "05.txt")
        assert "apple 1" in _read_file(path_0805)
        print("[OK] test_mark_unknown_picks_latest_when_multiple_dates")
    finally:
        shutil.rmtree(tmp)


def test_mark_unknown_new_word_appends_to_today():
    """mark_unknown 新词（任何日期都没有）：追加到今天的文件"""
    manager, tmp = _make_manager_with_today("2026/08/10")
    try:
        _write_daily_file(tmp, "2026/08/08", "apple\n")

        # cherry 在所有日期都没有
        result = manager.mark_unknown("cherry")
        assert result["added"] is True
        assert result["unknown_count"] == 1
        assert result["date"] == "2026/08/10", f"新词应追加到今天，实际 {result['date']}"

        # 今天的文件应该被创建并包含 cherry 1
        path_today = os.path.join(tmp, "2026", "08", "10.txt")
        assert os.path.exists(path_today), "今天的文件应被自动创建"
        assert "cherry 1" in _read_file(path_today)
        print("[OK] test_mark_unknown_new_word_appends_to_today")
    finally:
        shutil.rmtree(tmp)


def test_mark_unknown_specified_date():
    """指定 date 时只改那个文件，即使词在其他日期更近"""
    manager, tmp = _make_manager_with_today("2026/08/10")
    try:
        _write_daily_file(tmp, "2026/08/05", "apple 1\n")
        _write_daily_file(tmp, "2026/08/08", "apple 5\n")

        # 指定改 08/05
        result = manager.mark_unknown("apple", date="2026/08/05")
        assert result["date"] == "2026/08/05"
        assert result["unknown_count"] == 2, f"08/05 的 apple 应 1->2，实际 {result['unknown_count']}"

        # 08/08 的 apple 应保持 5 不变
        path_0808 = os.path.join(tmp, "2026", "08", "08.txt")
        assert "apple 5" in _read_file(path_0808)
        print("[OK] test_mark_unknown_specified_date")
    finally:
        shutil.rmtree(tmp)


def test_mark_known_decrement():
    """mark_known：-1，最低 0"""
    manager, tmp = _make_manager_with_today("2026/08/10")
    try:
        _write_daily_file(tmp, "2026/08/08", "apple 3\nbanana 1\ncherry 0\n")

        r = manager.mark_known("apple")
        assert r["unknown_count"] == 2
        r = manager.mark_known("banana")
        assert r["unknown_count"] == 0
        r = manager.mark_known("cherry")
        assert r["unknown_count"] == 0  # 已经是 0
        r = manager.mark_known("notexist")
        assert r["unknown_count"] == 0
        assert r["date"] is None
        print("[OK] test_mark_known_decrement")
    finally:
        shutil.rmtree(tmp)


def test_stats_recent_days():
    """stats 字段正确"""
    manager, tmp = _make_manager_with_today("2026/08/10")
    try:
        _write_daily_file(tmp, "2026/08/10", "apple 1\nbanana 0\n")
        _write_daily_file(tmp, "2026/08/09", "cherry 5\n")
        # 7 天范围 = 08/10 ~ 08/04，08/03 才算超出
        _write_daily_file(tmp, "2026/08/03", "old 3\n")  # 超出 7 天

        stats = manager.stats(days=7)
        assert stats["status"] == "success"
        # 7 天范围内：08/10 + 08/09 共 3 个词，08/03 不算
        assert stats["total_words"] == 3, f"7 天内 3 个词，实际 {stats['total_words']}"
        assert stats["untested_words"] == 1, f"未测验 1 个（banana），实际 {stats['untested_words']}"
        assert stats["struggling_words"] == 1, f"count>=2 的 1 个（cherry），实际 {stats['struggling_words']}"
        assert stats["max_unknown_count"] == 5
        assert "2026/08/10" in stats["dates_with_words"]
        assert "2026/08/09" in stats["dates_with_words"]
        assert stats["days_covered"] == 7
        assert stats["latest_date"] == "2026/08/10"
        assert stats["earliest_date"] == "2026/08/03"
        assert stats["total_history_dates"] == 3
        print("[OK] test_stats_recent_days")
    finally:
        shutil.rmtree(tmp)


def test_dispatcher_daily_source():
    """端到端：通过 ToolDispatcher 调用 word_quiz source=daily"""
    from core.services.study.dispatch import ToolDispatcher
    from core.tools.study.english import daily_word_log as dwl_module

    tmp_base = tempfile.mkdtemp(prefix="daily_disp_test_")
    # 创建一个伪 today
    today_str = "2026/08/10"
    _write_daily_file(tmp_base, "2026/08/10", "apple 1\nbanana 0\n")

    # monkey-patch 单例
    orig_instance = dwl_module._instance
    new_manager = dwl_module.DailyWordLogManager(base_dir=tmp_base)
    new_manager._get_today_str = lambda: today_str
    dwl_module._instance = new_manager

    try:
        class _FakeSvc:
            def __init__(self):
                self.base_dir = tmp_base

        dispatcher = ToolDispatcher(_FakeSvc())

        # quiz daily
        result = dispatcher.dispatch(
            "english", "word_quiz",
            {
                "action": "quiz",
                "source": "daily",
                "count": 5,
                "priority": "high_count",
                "date": "2026/08/10",
            },
        )
        assert result["status"] == "success"
        assert len(result["words"]) == 2
        # apple(1) 优先于 banana(0)
        assert result["words"][0]["word"] == "apple"

        # stats daily
        result = dispatcher.dispatch(
            "english", "word_quiz",
            {"action": "stats", "source": "daily", "days": 7},
        )
        assert result["status"] == "success"
        assert result["total_words"] == 2
        assert result["struggling_words"] == 0  # apple(1) 不算

        # mark_unknown daily
        result = dispatcher.dispatch(
            "english", "word_quiz",
            {"action": "mark_unknown", "source": "daily", "word": "banana"},
        )
        assert result["status"] == "success"
        assert result["data"]["unknown_count"] == 1
        assert result["data"]["date"] == "2026/08/10"

        # mark_known daily 指定 date
        result = dispatcher.dispatch(
            "english", "word_quiz",
            {"action": "mark_known", "source": "daily", "word": "apple", "date": "2026/08/10"},
        )
        assert result["status"] == "success"
        assert result["data"]["unknown_count"] == 0

        # source/date/days 缺省时读取昨天的 daily，且结果明确标注来源
        result = dispatcher.dispatch(
            "english", "word_quiz",
            {"action": "stats"},
        )
        assert result["status"] == "success"
        assert result["source"] == "daily"
        assert result["scope"] == {
            "date": "2026/08/09",
            "mode": "yesterday_default",
        }
        print("[OK] test_dispatcher_daily_source")
    finally:
        dwl_module._instance = orig_instance
        shutil.rmtree(tmp_base)


def test_empty_directory_returns_empty():
    """目录不存在或为空时返回空列表"""
    manager, tmp = _make_manager_with_today("2026/08/10")
    try:
        # 不创建任何文件
        assert manager.list_dates() == []
        assert manager.get_words_for_recent_days(7) == []
        assert manager.quiz(count=5) == []
        stats = manager.stats(days=7)
        assert stats["total_words"] == 0
        assert stats["struggling_words"] == 0
        print("[OK] test_empty_directory_returns_empty")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    test_date_to_path()
    test_ensure_today_file_creates_dir_and_file()
    test_list_dates_descending()
    test_get_words_for_date_with_date_field()
    test_get_recent_dates()
    test_get_words_for_recent_days()
    test_quiz_high_count_cross_days()
    test_quiz_specified_date()
    test_quiz_new_priority()
    test_mark_unknown_existing_in_recent_date()
    test_mark_unknown_picks_latest_when_multiple_dates()
    test_mark_unknown_new_word_appends_to_today()
    test_mark_unknown_specified_date()
    test_mark_known_decrement()
    test_stats_recent_days()
    test_dispatcher_daily_source()
    test_empty_directory_returns_empty()
    print("\n[ALL PASS] DailyWordLogManager 与 word_quiz source=daily 路径验证通过")
