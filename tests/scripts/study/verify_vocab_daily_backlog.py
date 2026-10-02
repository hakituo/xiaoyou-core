"""验证每日词汇固定批次、历史补漏与 FSRS 合并契约。"""

from __future__ import annotations

import datetime
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


def main() -> int:
    problems: list[str] = []
    temp_root = tempfile.mkdtemp(prefix="verify_vocab_daily_backlog_")
    old_daily_instance = daily_module._instance
    try:
        manager = DailyWordLogManager(base_dir=os.path.join(temp_root, "daily"))
        manager._get_today_str = lambda: "2026/08/31"
        day_28 = manager._date_to_path("2026/08/28")
        os.makedirs(os.path.dirname(day_28), exist_ok=True)
        with open(day_28, "w", encoding="utf-8") as file:
            file.write("# 手动记录\ngloom\nscale\nscarce\nkeen\n")
        manager.mark_unknown("proverb", date="2026/08/30")

        store = VocabDataStore(
            progress_path=os.path.join(temp_root, "vocab_progress.json")
        )
        store._ensure_loaded()
        # 与上面固定的模拟日期保持一致，避免测试随真实日期漂移。
        yesterday = datetime.datetime(2026, 8, 30, 12, 0, 0)
        store.progress = {}
        for due_word in ("miracle", "outset", "maintain"):
            store.progress[due_word] = {
                "reps": 1,
                "interval": 1,
                "easiness": 2.5,
                "next_review": time.time() - 60,
                "history": [
                    {"timestamp": yesterday.timestamp(), "quality": 4}
                ],
            }
        store.progress["proverb"] = {
            "reps": 1,
            "interval": 1,
            "easiness": 2.5,
            "next_review": time.time() - 60,
            "history": [
                {"timestamp": yesterday.timestamp(), "quality": 1}
            ],
        }

        daily_module._instance = manager
        words = quiz.get_daily_words(store, limit=0)
        names = [item.get("word", "").lower() for item in words]
        sources = [item.get("review_source") for item in words]

        expected_names = [
            "proverb",
            "miracle",
            "outset",
            "maintain",
            "gloom",
            "scale",
            "scarce",
            "keen",
        ]
        if names != expected_names:
            problems.append(f"历史补漏与 FSRS 合并顺序错误: {names}")
        if sources != ["daily_backlog"] + ["fsrs"] * 3 + [
            "daily_backlog"
        ] * 4:
            problems.append(f"复习来源标记错误: {sources}")
        if any(str(item.get("word", "")).startswith("#") for item in words):
            problems.append("注释行进入了每日复习批次")

        # 重复读取必须返回同一批，不得继续翻出别的旧词。
        second = quiz.get_daily_words(store, limit=0)
        second_names = [item.get("word", "").lower() for item in second]
        if second_names != names:
            problems.append(f"同日重复读取批次不稳定: {second_names}")

        # 锁定后新增的候选不能在同一天动态补位。
        manager.mark_unknown("later_word", date="2026/08/29")
        reviewed_now = time.time()
        for name in names:
            progress = store.progress.setdefault(
                name,
                {
                    "reps": 1,
                    "interval": 1,
                    "easiness": 2.5,
                    "next_review": 0,
                    "history": [],
                },
            )
            progress.setdefault("history", []).append(
                {"timestamp": reviewed_now, "quality": 4}
            )
            progress["fsrs_last_review"] = reviewed_now
        after_complete = quiz.get_daily_words(store, limit=0)
        if after_complete:
            problems.append(
                "完成最终队列后仍同日追加未入选词: "
                + str([item.get("word") for item in after_complete])
            )
    finally:
        daily_module._instance = old_daily_instance
        shutil.rmtree(temp_root, ignore_errors=True)

    if problems:
        print("验证失败:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("验证通过: 每日全量固定队列、优先级、去重与同日不补位均正确")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
