"""验证 UnfamiliarWordBook 与 word_quiz 调度路径

使用临时文件，不污染真实的 data/study_data/English/Words/unfamiliar_word.txt

运行：
    venv_core\\scripts\\python.exe tests\\scripts\\study\\verify_unfamiliar_word_book.py
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
from pathlib import Path

# 确保项目根在 sys.path
ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _make_book(content: str) -> "tuple":
    """在临时文件上构造一个 UnfamiliarWordBook，返回 (book, tmp_path)"""
    from core.tools.study.english.unfamiliar_word_book import UnfamiliarWordBook

    fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="unfamiliar_test_")
    os.close(fd)
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
    return UnfamiliarWordBook(file_path=tmp_path), tmp_path


def _read_raw(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_parse_mixed_format():
    """混合格式：纯单词、带数字、空行、尾随空格、重复词"""
    content = (
        "absorb                                          \n"  # 尾随空格
        "absurd\n"
        "comprehensive 2\n"
        "comprise 1\n"
        "\n"  # 空行
        "conduct 3\n"
        "garage\n"
        "garage 5\n"  # 重复词，应合并取 5
        "contrast 5\n"
    )
    book, tmp = _make_book(content)
    try:
        words = book.list_words()
        # 8 个非空行，但 garage 重复，去重后 7 个
        assert len(words) == 7, f"期望 7 个词，实际 {len(words)}: {words}"

        word_map = {w["word"]: w["unknown_count"] for w in words}
        assert word_map["absorb"] == 0, "absorb 无计数"
        assert word_map["comprehensive"] == 2
        assert word_map["comprise"] == 1
        assert word_map["conduct"] == 3
        assert word_map["garage"] == 5, f"重复词应取较大值 5，实际 {word_map['garage']}"
        assert word_map["contrast"] == 5
        print("[OK] test_parse_mixed_format")
    finally:
        os.unlink(tmp)


def test_quiz_priority_high_count():
    """high_count 优先抽不认识次数多的"""
    content = "apple 1\nbanana 5\ncherry 3\ndate 0\nelder 2\n"
    book, tmp = _make_book(content)
    try:
        random.seed(42)
        words = book.quiz(count=3, priority="high_count")
        # 候选池是前 count*3=9（全部 5 个），按 count 降序排前 3*3
        # 但只有 5 个词，pool 全部，再随机抽 3
        assert len(words) == 3, f"期望抽 3 个，实际 {len(words)}"
        # 至少有一个 count>=2 的（因为前 3*3=9 池子里按 count 降序，前几个都是高 count）
        counts = [w["unknown_count"] for w in words]
        assert max(counts) >= 2, f"high_count 应优先高计数，实际抽到 {counts}"
        print("[OK] test_quiz_priority_high_count")
    finally:
        os.unlink(tmp)


def test_quiz_priority_new():
    """new 优先抽未测验过的（count=0）"""
    content = "apple 1\nbanana 0\ncherry 0\ndate 3\n"
    book, tmp = _make_book(content)
    try:
        random.seed(0)
        words = book.quiz(count=2, priority="new")
        assert len(words) == 2
        # 应该都来自 count=0 的池子
        for w in words:
            assert w["unknown_count"] == 0, f"new 应抽未测验词，实际 count={w['unknown_count']}"
        print("[OK] test_quiz_priority_new")
    finally:
        os.unlink(tmp)


def test_quiz_priority_random():
    """random 完全随机"""
    content = "apple\nbanana\ncherry\ndate\n"
    book, tmp = _make_book(content)
    try:
        words = book.quiz(count=2, priority="random")
        assert len(words) == 2
        print("[OK] test_quiz_priority_random")
    finally:
        os.unlink(tmp)


def test_quiz_specified_word():
    """指定 word 时直接返回该词"""
    content = "apple\nbanana\ncherry\n"
    book, tmp = _make_book(content)
    try:
        words = book.quiz(word="banana")
        assert len(words) == 1
        assert words[0]["word"] == "banana"
        # 大小写不敏感
        words = book.quiz(word="BANANA")
        assert len(words) == 1
        assert words[0]["word"] == "banana"
        # 不存在的词
        words = book.quiz(word="notexist")
        assert words == []
        print("[OK] test_quiz_specified_word")
    finally:
        os.unlink(tmp)


def test_mark_unknown_existing():
    """mark_unknown 已存在词：count+1，写回文件"""
    content = "apple 2\nbanana\n\ncherry 1\n"
    book, tmp = _make_book(content)
    try:
        result = book.mark_unknown("apple")
        assert result["unknown_count"] == 3, f"apple 应 2->3，实际 {result['unknown_count']}"
        assert result["added"] is False

        # 验证文件写回：apple 行变成 "apple 3\n"，其他行保留
        raw = _read_raw(tmp)
        lines = raw.split("\n")
        # content 末尾有 \n，split 后最后一个是空串
        assert "apple 3" in lines[0], f"第1行应为 'apple 3'，实际 '{lines[0]}'"
        assert lines[1] == "banana", f"第2行应保持 'banana'，实际 '{lines[1]}'"
        assert lines[2] == "", f"第3行应保持空行，实际 '{lines[2]}'"
        assert lines[3] == "cherry 1", f"第4行应保持 'cherry 1'，实际 '{lines[3]}'"
        print("[OK] test_mark_unknown_existing")
    finally:
        os.unlink(tmp)


def test_mark_unknown_new_word():
    """mark_unknown 新词：追加到文件末尾"""
    content = "apple\nbanana\n"
    book, tmp = _make_book(content)
    try:
        result = book.mark_unknown("cherry")
        assert result["unknown_count"] == 1
        assert result["added"] is True

        # 验证追加
        raw = _read_raw(tmp)
        assert raw.endswith("cherry 1\n"), f"末尾应追加 'cherry 1\\n'，实际：{raw!r}"

        # 再次 list 应包含新词
        words = book.list_words()
        word_map = {w["word"]: w["unknown_count"] for w in words}
        assert word_map["cherry"] == 1
        print("[OK] test_mark_unknown_new_word")
    finally:
        os.unlink(tmp)


def test_mark_known_decrement():
    """mark_known：count-1，最低 0"""
    content = "apple 3\nbanana 1\ncherry 0\n"
    book, tmp = _make_book(content)
    try:
        # 3 -> 2
        r = book.mark_known("apple")
        assert r["unknown_count"] == 2

        # 1 -> 0
        r = book.mark_known("banana")
        assert r["unknown_count"] == 0

        # 0 -> 0（不低于 0）
        r = book.mark_known("cherry")
        assert r["unknown_count"] == 0

        # 不存在的词：返回 0，不追加
        r = book.mark_known("notexist")
        assert r["unknown_count"] == 0
        assert r["added"] is False
        words = book.list_words()
        assert all(w["word"] != "notexist" for w in words)

        # banana 行写回应为 "banana"（count=0 时不带数字）
        raw = _read_raw(tmp)
        lines = raw.split("\n")
        assert lines[1] == "banana", f"banana count=0 应写回 'banana'，实际 '{lines[1]}'"
        print("[OK] test_mark_known_decrement")
    finally:
        os.unlink(tmp)


def test_stats():
    """stats 字段正确"""
    content = "apple 1\nbanana 5\ncherry 0\ndate 0\nelder 3\n"
    book, tmp = _make_book(content)
    try:
        stats = book.stats()
        assert stats["status"] == "success"
        assert stats["total_words"] == 5
        assert stats["untested_words"] == 2, f"未测验词 2 个，实际 {stats['untested_words']}"
        # count>=2 的：banana(5)、elder(3)，共 2 个
        assert stats["struggling_words"] == 2, f"count>=2 的 2 个，实际 {stats['struggling_words']}"
        assert stats["max_unknown_count"] == 5
        assert stats["current_dictionary"] == "unfamiliar_word.txt"
        print("[OK] test_stats")
    finally:
        os.unlink(tmp)


def test_dispatcher_integration():
    """端到端：通过 ToolDispatcher 调用 word_quiz

    直接构造 ToolDispatcher，注入一个伪 study_service（只需 base_dir 属性）
    """
    from core.services.study.dispatch import ToolDispatcher

    class _FakeSvc:
        def __init__(self, base_dir):
            self.base_dir = base_dir

    # 因为 _handle_word_quiz 内部用的是全局单例 get_unfamiliar_word_book()，
    # 我们 monkey-patch 单例指向临时文件
    from core.tools.study.english import unfamiliar_word_book as uwb_module

    content = "apple 1\nbanana 2\ncherry 0\n"
    fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="unfamiliar_disp_")
    os.close(fd)
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)

    # 保存原始单例
    orig_instance = uwb_module._instance
    uwb_module._instance = uwb_module.UnfamiliarWordBook(file_path=tmp_path)

    try:
        svc = _FakeSvc(base_dir=os.path.dirname(tmp_path))
        dispatcher = ToolDispatcher(svc)

        # quiz
        result = dispatcher.dispatch(
            "english", "word_quiz",
            {
                "action": "quiz",
                "source": "unfamiliar",
                "count": 2,
                "priority": "high_count",
            },
        )
        assert result["status"] == "success"
        assert len(result["words"]) == 2

        # stats
        result = dispatcher.dispatch(
            "english", "word_quiz", {"action": "stats", "source": "unfamiliar"}
        )
        assert result["status"] == "success"
        assert result["total_words"] == 3
        # count>=2 的只有 banana(2)，apple(1) 和 cherry(0) 不算
        assert result["struggling_words"] == 1, f"struggling 应为 1，实际 {result['struggling_words']}"

        # mark_unknown
        result = dispatcher.dispatch(
            "english", "word_quiz",
            {"action": "mark_unknown", "source": "unfamiliar", "word": "cherry"},
        )
        assert result["status"] == "success"
        assert result["data"]["unknown_count"] == 1

        # mark_known
        result = dispatcher.dispatch(
            "english", "word_quiz",
            {"action": "mark_known", "source": "unfamiliar", "word": "banana"},
        )
        assert result["status"] == "success"
        assert result["data"]["unknown_count"] == 1

        # 不支持的 action
        result = dispatcher.dispatch(
            "english", "word_quiz", {"action": "bogus", "source": "unfamiliar"}
        )
        assert result["status"] == "error"

        # 缺 word
        result = dispatcher.dispatch(
            "english", "word_quiz",
            {"action": "mark_unknown", "source": "unfamiliar"},
        )
        assert result["status"] == "error"

        print("[OK] test_dispatcher_integration")
    finally:
        uwb_module._instance = orig_instance
        os.unlink(tmp_path)


def test_cache_invalidation_after_write():
    """写操作后缓存失效，下次读取看到新数据"""
    content = "apple 1\n"
    book, tmp = _make_book(content)
    try:
        # 首次加载缓存
        assert book.list_words()[0]["unknown_count"] == 1
        # mark_unknown 应使缓存失效
        book.mark_unknown("apple")
        # 再次读取应是 2
        assert book.list_words()[0]["unknown_count"] == 2
        print("[OK] test_cache_invalidation_after_write")
    finally:
        os.unlink(tmp)


def test_external_file_change_detected():
    """外部修改文件后，缓存基于 mtime 自动刷新"""
    content = "apple 1\n"
    book, tmp = _make_book(content)
    try:
        assert book.list_words()[0]["unknown_count"] == 1
        # 外部直接改文件
        import time
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("apple 9\n")
        # 确保 mtime 变化（Windows 文件系统精度可能不够，sleep 一下）
        time.sleep(0.05)
        os.utime(tmp, None)
        assert book.list_words()[0]["unknown_count"] == 9, "外部修改应被 mtime 检测到"
        print("[OK] test_external_file_change_detected")
    finally:
        os.unlink(tmp)


if __name__ == "__main__":
    test_parse_mixed_format()
    test_quiz_priority_high_count()
    test_quiz_priority_new()
    test_quiz_priority_random()
    test_quiz_specified_word()
    test_mark_unknown_existing()
    test_mark_unknown_new_word()
    test_mark_known_decrement()
    test_stats()
    test_cache_invalidation_after_write()
    test_external_file_change_detected()
    test_dispatcher_integration()
    print("\n[ALL PASS] UnfamiliarWordBook 与 word_quiz 调度路径验证通过")
