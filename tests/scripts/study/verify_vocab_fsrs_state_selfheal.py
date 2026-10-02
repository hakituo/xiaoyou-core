# -*- coding: utf-8 -*-
"""验证 FSRS 卡片状态「落后于 history」时能自动按历史重建。

背景（2026-09-13）：后端运行环境一度缺 fsrs 库，apply_progress 回退到 SM-2，
只写 history / next_review，fsrs_* 停在旧值。装回 fsrs 后若继续信任这份落盘
状态，缺失期间的评分会被永久忽略（卡片从旧状态续算，到期日偏近）。

修复：fsrs_scheduler.state_lags_behind_history() 检测到「history 里存在晚于
fsrs_last_review 的评分事件」时，fsrs_card_from_progress 改为按 history 全量
重建（replay 确定性，重复执行幂等）。

用法（项目根）：
    .\\venv_core\\Scripts\\python.exe tests\\scripts\\study\\verify_vocab_fsrs_state_selfheal.py
    .\\venv_core\\Scripts\\python.exe tests\\scripts\\study\\verify_vocab_fsrs_state_selfheal.py --real

``--real`` 只读取真实进度文件做统计，不写任何真实数据。
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.tools.study.english import (  # noqa: E402
    daily_word_log as daily_word_log_module,
)
from core.tools.study.english import (  # noqa: E402
    unfamiliar_word_book as unfamiliar_module,
)
from core.tools.study.english.daily_word_log import DailyWordLogManager  # noqa: E402
from core.tools.study.english.fsrs_scheduler import (  # noqa: E402
    apply_progress,
    fsrs_card_from_progress,
    latest_review_timestamp,
    rebuild_fsrs_card_from_history,
    save_fsrs_to_progress,
    state_lags_behind_history,
)

DAY = 86400.0


class _FakeStore:
    """最小 store 替身，只保存内存进度，不落盘。"""

    def __init__(self, progress: dict):
        self.progress = progress
        self.saved = 0

    def _ensure_loaded(self):
        return None

    def save_progress(self):
        self.saved += 1


class _FakeUnfamiliarBook:
    def mark_unknown(self, word):
        return {"word": word, "unknown_count": 1, "added": True}

    def mark_known(self, word):
        return {"word": word, "unknown_count": 0, "added": False}


def _isolate_side_effects():
    """把 daily 日志与生词本隔离掉，避免验证脚本写真实数据。"""
    import tempfile

    tmp_dir = tempfile.mkdtemp(prefix="vocab_selfheal_")
    fake_log = DailyWordLogManager(base_dir=os.path.join(tmp_dir, "daily"))
    original_log = daily_word_log_module.get_daily_word_log
    original_book = unfamiliar_module.get_unfamiliar_word_book
    daily_word_log_module.get_daily_word_log = lambda: fake_log
    unfamiliar_module.get_unfamiliar_word_book = lambda: _FakeUnfamiliarBook()
    return original_log, original_book, tmp_dir


def _history(qualities, start: float, step: float = DAY):
    return [
        {"timestamp": start + i * step, "quality": q, "source": "manual_review"}
        for i, q in enumerate(qualities)
    ]


def _stale_state_data(now: float) -> dict:
    """fsrs_* 停留在 10 天前，history 里却有一直到昨天的评分。"""
    history = _history([3, 3, 3], now - 30 * DAY, step=10 * DAY)
    data = {
        "reps": len(history),
        "interval": 0.01,
        "easiness": 2.5,
        "next_review": now - DAY,
        "history": history,
    }
    stale_card = rebuild_fsrs_card_from_history(data, until=now - 40 * DAY)
    save_fsrs_to_progress(data, stale_card)
    # 再补两条「fsrs 缺失期间」才发生的评分（只有 history 被写入）
    data["history"].extend(_history([3], now - 2 * DAY))
    return data


def check_lagging_state_is_rebuilt() -> list[str]:
    problems: list[str] = []
    now = time.time()
    data = _stale_state_data(now)

    if not state_lags_behind_history(data):
        return ["状态明显落后于 history，state_lags_behind_history 却返回 False"]

    card = fsrs_card_from_progress(data)
    expected = rebuild_fsrs_card_from_history(data)
    if card.stability != expected.stability or card.due != expected.due:
        problems.append(
            f"落后状态没有被重建：stability={card.stability} due={card.due}"
        )
    if card.last_review is None:
        problems.append("重建后 last_review 为空")
    elif abs(card.last_review.timestamp() - latest_review_timestamp(data)) > 1:
        problems.append(
            "重建后 last_review 与 history 末次评分时间不一致："
            f"{card.last_review.timestamp()} vs {latest_review_timestamp(data)}"
        )
    return problems


def check_healthy_state_is_not_rebuilt() -> list[str]:
    """状态与 history 同步时不能重建（否则每次复习都重放全量历史）。"""
    now = time.time()
    data = {"history": _history([3, 4], now - 5 * DAY)}
    card = rebuild_fsrs_card_from_history(data)
    save_fsrs_to_progress(data, card)
    frozen_stability = data["fsrs_stability"]

    if state_lags_behind_history(data):
        return ["状态与 history 同步，state_lags_behind_history 却返回 True"]
    restored = fsrs_card_from_progress(data)
    if restored.stability != frozen_stability:
        return [f"同步状态被误重建：stability {frozen_stability} → {restored.stability}"]
    return []


def check_apply_progress_heals_once() -> list[str]:
    """apply_progress 之后状态必须追上 history，且第二次不再触发重建。"""
    problems: list[str] = []
    now = time.time()
    data = _stale_state_data(now)
    store = _FakeStore({"lag": data})

    apply_progress(store, "lag", 3)
    if state_lags_behind_history(data):
        problems.append("apply_progress 之后状态仍落后于 history（自愈未生效）")
    if store.saved == 0:
        problems.append("apply_progress 没有触发落盘")

    first = fsrs_card_from_progress(data)
    second = fsrs_card_from_progress(data)
    if (first.stability, first.due) != (second.stability, second.due):
        problems.append("自愈后重复读取结果不一致（replay 不幂等）")
    return problems


def check_real() -> list[str]:
    real_progress = os.path.join(ROOT, "output", "user_data", "vocab_progress.json")
    if not os.path.exists(real_progress):
        return [f"真实进度文件不存在: {real_progress}"]
    with open(real_progress, encoding="utf-8") as f:
        progress = json.load(f)

    lagging = [w for w, d in progress.items() if state_lags_behind_history(d)]
    print(f"真实数据：{len(lagging)}/{len(progress)} 个词的 FSRS 状态落后于 history"
          f"（下次复习时会自动按 history 重建）")
    for word in lagging[:5]:
        d = progress[word]
        old_due = d.get("fsrs_due") or 0
        new_due = rebuild_fsrs_card_from_history(d).due.timestamp()
        print(f"  {word}: due {time.strftime('%m-%d', time.localtime(old_due))}"
              f" → {time.strftime('%m-%d', time.localtime(new_due))}")
    return []


def main() -> int:
    original_log, original_book, tmp_dir = _isolate_side_effects()
    try:
        problems = check_lagging_state_is_rebuilt()
        problems += check_healthy_state_is_not_rebuilt()
        problems += check_apply_progress_heals_once()
        if "--real" in sys.argv:
            problems += check_real()
    finally:
        daily_word_log_module.get_daily_word_log = original_log
        unfamiliar_module.get_unfamiliar_word_book = original_book
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)

    if problems:
        print("验证失败:")
        for p in problems:
            print("  -", p)
        return 1
    print("验证通过：落后状态按 history 重建、同步状态不重建、自愈后幂等")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
