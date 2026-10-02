"""验证用户手动编辑历史 daily 文件后，当天复习安排会刷新补录新词。

覆盖三点契约：
1. 用户直接改 daily/YYYY/MM/DD.txt 加词 -> 新词进入当天最终复习队列；
2. 已完成（今天已复习过）的词不会被补录回来；
3. 系统自身的复习标记写入（mark_unknown）仍不触发同日补位，
   保持"当天固定批次背空后不链式翻下一批"的既有行为。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.tools.study.english import daily_word_log as daily_module  # noqa: E402
from core.tools.study.english import quiz  # noqa: E402
from core.tools.study.english.daily_word_log import (  # noqa: E402
    DailyWordLogManager,
)
from core.tools.study.english.loader import VocabDataStore  # noqa: E402


def _names(items) -> list[str]:
    return [str(item.get("word") or "").strip().lower() for item in items]


def main() -> int:
    problems: list[str] = []
    temp_root = tempfile.mkdtemp(prefix="verify_vocab_manual_refresh_")
    old_daily_instance = daily_module._instance
    try:
        manager = DailyWordLogManager(base_dir=os.path.join(temp_root, "daily"))
        manager._get_today_str = lambda: "2026/08/31"
        day_30 = manager._date_to_path("2026/08/30")
        os.makedirs(os.path.dirname(day_30), exist_ok=True)
        with open(day_30, "w", encoding="utf-8") as file:
            file.write("alpha\nbeta\n")

        store = VocabDataStore(
            progress_path=os.path.join(temp_root, "vocab_progress.json")
        )
        store._ensure_loaded()
        store.progress = {}
        daily_module._instance = manager

        first = quiz.get_daily_words(store, limit=0)
        if _names(first) != ["alpha", "beta"]:
            problems.append(f"初始每日队列错误: {_names(first)}")

        # --- 1. 用户手动往历史 daily 文件追加单词（绕过管理器直接写文件）---
        with open(day_30, "a", encoding="utf-8") as file:
            file.write("gamma\n")
        second = quiz.get_daily_words(store, limit=0)
        second_names = _names(second)
        if second_names != ["alpha", "beta", "gamma"]:
            problems.append(f"手动加词后当天队列未刷新: {second_names}")

        # 重复读取必须稳定，不能反复重排或重复追加
        third = quiz.get_daily_words(store, limit=0)
        if _names(third) != second_names:
            problems.append(f"手动加词后队列不稳定: {_names(third)}")

        # --- 2. 已完成项不会因为刷新被拉回 ---
        reviewed_at = time.time()
        store.progress["alpha"] = {
            "reps": 2,
            "interval": 3,
            "easiness": 2.5,
            "next_review": reviewed_at + 86400 * 3,
            "fsrs_due": reviewed_at + 86400 * 3,
            "fsrs_last_review": reviewed_at,
            "history": [{"timestamp": reviewed_at, "quality": 4}],
        }
        fourth = quiz.get_daily_words(store, limit=0)
        fourth_names = _names(fourth)
        if "alpha" in fourth_names:
            problems.append(f"已复习完成的词被重新拉回: {fourth_names}")
        if "gamma" not in fourth_names:
            problems.append(f"刷新后手动加的词丢失: {fourth_names}")

        # --- 3. 系统自身写入仍不补位（保持固定批次语义）---
        manager.mark_unknown("delta", date="2026/08/29")
        fifth = quiz.get_daily_words(store, limit=0)
        if "delta" in _names(fifth):
            problems.append(f"系统写入触发了同日补位: {_names(fifth)}")
    finally:
        daily_module._instance = old_daily_instance
        shutil.rmtree(temp_root, ignore_errors=True)

    if problems:
        print("验证失败:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("验证通过: 手动编辑 daily 文件后当天复习队列会补录新词，系统写入不补位")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
