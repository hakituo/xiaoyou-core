# -*- coding: utf-8 -*-
"""验证背单词模块（分级词书 + 全量释义兜底），供本地手动运行。

用法（在项目根）：
    .\\venv_core\\Scripts\\python.exe tests\\scripts\\study\\verify_vocab_optimization.py

检查项：
1. 词书可加载，无 [经][机][医][化] 等方括号领域标签残留
2. 典型多义词（light/bear/well）释义完整
3. get_review_overview 可跑通（streak/memory_curve 非空）
4. Facade 各 API 正常
5. 用户 daily 手动记的跨级别词（inhibit/payroll/overthrow 等）复习释义兜底命中
6. 分级词书文件存在、词量合理、词书列表固定顺序且不含全量总表
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from core.tools.study.english.vocabulary_manager import get_vocabulary_manager

# 用户实际在背、但原词书（zk∪gk∪cet4）里缺失的词（多为 cet6/考研/托福标签或无标签）
CROSS_LEVEL_WORDS = [
    "inhibit", "payroll", "overthrow", "ozone", "penalty",
    "glossy", "paradox", "loophole", "outskirts", "peril",
]
# 期望的分级词书文件（列表顺序即词书选择页展示顺序）
LEVEL_BOOKS = [
    "CET4-顺序.json",
    "CET6-顺序.json",
    "考研-顺序.json",
    "托福-顺序.json",
    "雅思-顺序.json",
    "GRE-顺序.json",
]
MASTER_FILE = "CET-全量.json"


def check_wordbook_clean(vm) -> list:
    problems = []
    # 通过 get_stats 触发加载
    vm.get_stats()
    for word in ["light", "bear", "well", "bank"]:
        info = vm.get_word_info(word)
        if not info:
            problems.append(f"缺少词: {word}")
            continue
        for t in info.get("translations", []):
            if "[" in t.get("type", "") or "[" in t.get("translation", ""):
                problems.append(f"{word} 释义残留方括号: {t}")
    return problems


def check_cross_level_fallback(vm) -> list:
    """跨级别词（当前词书未收录）应通过全量释义总表兜底命中。"""
    problems = []
    for word in CROSS_LEVEL_WORDS:
        info = vm.get_word_info(word)
        if not info:
            problems.append(f"跨级别词未兜底命中: {word}")
            continue
        trans = info.get("translations", [])
        if not trans or not trans[0].get("translation"):
            problems.append(f"{word} 兜底命中但无释义")
    return problems


def check_level_books(vm) -> list:
    problems = []
    words_dir = vm.store.words_dir
    # 文件存在
    for name in LEVEL_BOOKS + [MASTER_FILE]:
        path = os.path.join(words_dir, name)
        if not os.path.exists(path):
            problems.append(f"词书文件缺失: {name}")
    # 词量合理：CET6 严格包含 CET4（四级基础∪六级新增），全量总表覆盖所有分级书
    counts = {}
    for name in LEVEL_BOOKS + [MASTER_FILE]:
        path = os.path.join(words_dir, name)
        if os.path.exists(path):
            try:
                counts[name] = len(json.load(open(path, encoding="utf-8")))
            except Exception as e:
                problems.append(f"词书文件解析失败 {name}: {e}")
    if counts.get("CET4-顺序.json", 0) <= 0:
        problems.append("CET4 词书为空")
    if counts.get("CET6-顺序.json", 0) <= counts.get("CET4-顺序.json", 10**9):
        problems.append("CET6 词书应包含 CET4 且词量更大")
    for name in LEVEL_BOOKS:
        if counts.get(MASTER_FILE, 0) <= counts.get(name, 10**9):
            problems.append(f"全量总表词数应大于 {name}: {counts}")
    # 词书列表：固定顺序、不含全量总表
    stats = vm.get_stats()
    books = stats.get("available_word_files", [])
    if books != LEVEL_BOOKS:
        problems.append(f"词书列表应为 {LEVEL_BOOKS}，实际 {books}")
    if MASTER_FILE in books:
        problems.append("全量释义总表不应出现在词书选择列表")
    return problems


def check_review_overview(vm) -> list:
    problems = []
    ov = vm.get_review_overview()
    if "streak_days" not in ov:
        problems.append("overview 缺 streak_days")
    if "memory_curve" not in ov:
        problems.append("overview 缺 memory_curve")
    else:
        non_zero = [c for c in ov["memory_curve"] if c.get("retention", 0) > 0]
        if not non_zero:
            problems.append("memory_curve 全为 0")
    if "due_today_count" not in ov:
        problems.append("overview 缺 due_today_count")
    return problems


def check_daily_words_runs(store) -> list:
    """验证 get_daily_words 可跑通（真实只读数据，不污染 daily 文件）。"""
    from core.tools.study.english import quiz

    problems = []
    try:
        words = quiz.get_daily_words(store, limit=5)
        if not isinstance(words, list):
            problems.append("get_daily_words 返回非 list")
    except Exception as e:
        problems.append(f"get_daily_words 异常: {e}")
    return problems


def check_daily_flow() -> list:
    """验证复习流转：quality<=2（不会）写入当天 daily 文件；quality>=3（会）从旧记录移除。

    使用临时 daily 目录 + 临时进度文件，不污染真实数据。
    """
    import shutil
    import tempfile
    from core.tools.study.english import daily_word_log as dwl_mod
    from core.tools.study.english import unfamiliar_word_book as uwb_mod
    from core.tools.study.english.daily_word_log import DailyWordLogManager
    from core.tools.study.english.unfamiliar_word_book import UnfamiliarWordBook
    from core.tools.study.english.fsrs_scheduler import apply_progress
    from core.tools.study.english.loader import VocabDataStore

    problems = []
    tmp_root = tempfile.mkdtemp(prefix="vocab_daily_flow_")
    try:
        # 临时 store（真实词书 + 临时进度），临时 daily 目录
        store = VocabDataStore(progress_path=os.path.join(tmp_root, "progress.json"))
        mgr = DailyWordLogManager(base_dir=os.path.join(tmp_root, "daily"))
        unfamiliar = UnfamiliarWordBook(
            file_path=os.path.join(tmp_root, "unfamiliar_word.txt")
        )
        old = dwl_mod.get_daily_word_log
        old_unfamiliar = uwb_mod.get_unfamiliar_word_book
        dwl_mod.get_daily_word_log = lambda: mgr
        uwb_mod.get_unfamiliar_word_book = lambda: unfamiliar
        try:
            # 昨天文件里有词
            mgr.mark_unknown("apple", date="2026/08/14")
            mgr.mark_unknown("banana", date="2026/08/14")

            # quality=3 会：移除旧记录，且不写入今天文件
            apply_progress(store, "apple", 3)
            words_14 = mgr.get_words_for_date("2026/08/14")
            if any(w["word"].lower() == "apple" for w in words_14):
                problems.append("quality>=3 后旧记录未移除")
            today = mgr._get_today_str()
            if any(w["word"].lower() == "apple" for w in mgr.get_words_for_date(today)):
                problems.append("quality>=3 不应写入今天文件")

            # quality=1 不会：移除旧记录 + 写入今天文件（明天复习优先）
            apply_progress(store, "banana", 1)
            words_14 = mgr.get_words_for_date("2026/08/14")
            if any(w["word"].lower() == "banana" for w in words_14):
                problems.append("quality<=2 后旧记录未移除")
            if not any(w["word"].lower() == "banana" for w in mgr.get_words_for_date(today)):
                problems.append("quality<=2 未写入今天文件")
        finally:
            dwl_mod.get_daily_word_log = old
            uwb_mod.get_unfamiliar_word_book = old_unfamiliar
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    return problems


def main() -> int:
    vm = get_vocabulary_manager()
    store = vm.store
    problems = []
    problems += check_wordbook_clean(vm)
    problems += check_cross_level_fallback(vm)
    problems += check_level_books(vm)
    problems += check_review_overview(vm)
    problems += check_daily_words_runs(store)
    problems += check_daily_flow()

    if problems:
        print("失败项:")
        for p in problems:
            print("  -", p)
        return 1
    print("全部通过: 词书干净、跨级别词兜底命中、分级词书完整、overview 正常、复习取词可跑通、daily 复习流转正确")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
