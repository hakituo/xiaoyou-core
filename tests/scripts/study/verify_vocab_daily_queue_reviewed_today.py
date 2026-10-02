# -*- coding: utf-8 -*-
"""验证「当天背过的词必须立刻从今日队列消失」。

背景（2026-09-13）：后端实际运行环境缺 fsrs 库，``apply_progress`` 回退到
SM-2，只写 ``next_review``，``fsrs_due`` / ``fsrs_last_review`` 一直停留在旧值。
``quiz.get_daily_words`` 当时只看 ``fsrs_last_review``，于是今天背过的词仍被判
成「已到期且今天没背过」，用户刷新后今日单词依旧是满的。

修复口径：以 history 里最后一条评分事件（append-only 证据）与 ``fsrs_last_review``
取最新，作为「最近一次复习时间」。

用法（项目根）：
    .\\venv_core\\Scripts\\python.exe tests\\scripts\\study\\verify_vocab_daily_queue_reviewed_today.py
    .\\venv_core\\Scripts\\python.exe tests\\scripts\\study\\verify_vocab_daily_queue_reviewed_today.py --real

``--real`` 会把真实进度文件复制到临时目录做一次只读演练，报告「今天已评分的词
里还有多少仍会留在今日队列」（不写任何真实数据文件）。
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.tools.study.english import quiz as vocab_quiz  # noqa: E402
from core.tools.study.english import stats as vocab_stats  # noqa: E402
from core.tools.study.english import (  # noqa: E402
    daily_word_log as daily_word_log_module,
)
from core.tools.study.english.daily_word_log import DailyWordLogManager  # noqa: E402
from core.tools.study.english.loader import VocabDataStore  # noqa: E402


def _isolate_daily_log(tmp_dir: str):
    """把 daily 日志根目录重定向到临时目录，避免验证脚本污染真实数据。"""
    fake_dir = os.path.join(tmp_dir, "daily")
    os.makedirs(fake_dir, exist_ok=True)
    fake_log = DailyWordLogManager(base_dir=fake_dir)
    original = daily_word_log_module.get_daily_word_log
    daily_word_log_module.get_daily_word_log = lambda: fake_log
    return original


def _build_store(tmp_dir: str, progress: dict, words: list[str]) -> VocabDataStore:
    dict_path = os.path.join(tmp_dir, "words", "CET4.json")
    os.makedirs(os.path.dirname(dict_path), exist_ok=True)
    with open(dict_path, "w", encoding="utf-8") as f:
        json.dump(
            [
                {"word": w, "translations": [{"type": "n.", "translation": f"{w} 释义"}]}
                for w in words
            ],
            f,
            ensure_ascii=False,
        )
    progress_path = os.path.join(tmp_dir, "user_data", "vocab_progress.json")
    os.makedirs(os.path.dirname(progress_path), exist_ok=True)
    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False)
    return VocabDataStore(dictionary_path=dict_path, progress_path=progress_path)


def _make_entry(due_offset_days: float, last_review_offset_days: float,
                event_offsets_days: list[float]) -> dict:
    """构造一条进度记录。

    ``last_review_offset_days`` 模拟 fsrs_* 字段停留在旧日期（fsrs 缺失时不更新），
    ``event_offsets_days`` 模拟 history 里真实发生的评分时间。
    """
    now = time.time()
    day = 86400.0
    return {
        "reps": len(event_offsets_days),
        "interval": 0.01,
        "easiness": 2.5,
        "next_review": now + due_offset_days * day,
        "fsrs_due": now + due_offset_days * day,
        "fsrs_last_review": now + last_review_offset_days * day,
        "fsrs_state": 2,
        "fsrs_step": None,
        "fsrs_stability": 1.0,
        "fsrs_difficulty": 5.0,
        "fsrs_schema_version": 3,
        "history": [
            {"timestamp": now + offset * day, "quality": 3, "source": "manual_review"}
            for offset in event_offsets_days
        ],
    }


def check_synthetic(tmp_dir: str) -> list[str]:
    """合成数据：今天背过的词必须出队，今天没背的到期词必须保留。"""
    problems: list[str] = []
    progress = {
        # 今天背过（history 有今天事件），但 fsrs_* 停留在两天前：修复前会残留
        "alpha": _make_entry(due_offset_days=-1, last_review_offset_days=-2,
                             event_offsets_days=[-0.01]),
        # 今天没背过、已到期：必须仍在队列
        "beta": _make_entry(due_offset_days=-1, last_review_offset_days=-3,
                            event_offsets_days=[-3]),
        # 未到期：不能出现
        "gamma": _make_entry(due_offset_days=+5, last_review_offset_days=-1,
                             event_offsets_days=[-1]),
        # 今天背过且明天才到期：修复前后都应出队（回归保护）
        "delta": _make_entry(due_offset_days=+1, last_review_offset_days=-2,
                             event_offsets_days=[-0.02]),
    }
    store = _build_store(tmp_dir, progress, list(progress.keys()))
    result = vocab_quiz.get_daily_words(store, 0)
    got = {item["word"] for item in result}

    if "alpha" in got:
        problems.append(
            "今天背过的 alpha 仍留在今日队列（fsrs_* 未更新时 history 证据没有被采纳）"
        )
    if "beta" not in got:
        problems.append("今天没背过且已到期的 beta 被错误剔除")
    if "gamma" in got:
        problems.append("未到期的 gamma 出现在今日队列")
    if "delta" in got:
        problems.append("今天背过的 delta 出现在今日队列")

    try:
        # 显式传空的当日记录：避免读真实生活记录里的「完成词汇复习」，
        # 保证这里只校验 FSRS 队列口径本身。
        status = vocab_stats.get_today_review_status(store, daily_record={})
        remaining = status.get("remaining_words")
        if remaining != len(got):
            problems.append(
                f"今日复习状态 remaining_words={remaining} 与队列长度 {len(got)} 不一致"
            )
        if status.get("completed"):
            problems.append("队列中仍有 beta 未完成，completed 不应为 True")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"读取今日复习状态失败: {exc}")

    print(f"合成用例队列结果: {sorted(got)}（预期仅含 beta）")
    return problems


def check_real(tmp_dir: str) -> list[str]:
    """真实进度只读演练：报告今天已评分的词里还有多少残留。"""
    real_progress = os.path.join(ROOT, "output", "user_data", "vocab_progress.json")
    if not os.path.exists(real_progress):
        return [f"真实进度文件不存在: {real_progress}"]

    staged = os.path.join(tmp_dir, "real_user_data")
    os.makedirs(staged, exist_ok=True)
    shutil.copy(real_progress, os.path.join(staged, "vocab_progress.json"))

    with open(real_progress, encoding="utf-8") as f:
        progress = json.load(f)
    store = VocabDataStore(
        dictionary_path=os.path.join(
            ROOT, "data", "study_data", "English", "Words", "CET-全量.json"
        ),
        progress_path=os.path.join(staged, "vocab_progress.json"),
    )
    store._ensure_loaded()

    today_start = datetime.datetime.now().replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp()
    reviewed_today = {
        word.lower()
        for word, data in progress.items()
        if any(
            float(e.get("timestamp", 0) or 0) >= today_start
            for e in (data.get("history", []) or [])
            if isinstance(e, dict)
        )
    }
    queue = {str(item.get("word") or "").lower()
             for item in vocab_quiz.get_daily_words(store, 0)}
    left = sorted(reviewed_today & queue)
    print(f"真实数据：今天已评分 {len(reviewed_today)} 词，今日队列 {len(queue)} 词，"
          f"残留 {len(left)} 词")
    if left:
        print("  残留示例:", ", ".join(left[:10]))
        return [f"今天已评分的词仍有 {len(left)} 个留在今日队列"]
    return []


def main() -> int:
    tmp_dir = tempfile.mkdtemp(prefix="vocab_daily_queue_")
    original_getter = _isolate_daily_log(tmp_dir)
    try:
        problems = check_synthetic(tmp_dir)
        if "--real" in sys.argv:
            problems.extend(check_real(tmp_dir))
    finally:
        daily_word_log_module.get_daily_word_log = original_getter
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if problems:
        print("验证失败:")
        for p in problems:
            print("  -", p)
        return 1
    print("验证通过：当天背过的词已从今日队列剔除，未背的到期词保留")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
