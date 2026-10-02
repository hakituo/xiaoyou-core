"""背单词 FSRS 评分语义迁移回归测试。

覆盖：
- legacy / current 两套 quality → Rating 映射与 cutoff 边界
- rebuild 确定性、旧 schema 自动重建、FSRS 状态存取
- numerous 类场景（旧历史 3,4,4,4,4 必须按 Hard,Good,Good,Good,Good 回放）
- 新卡首次评分不 double-count
- quiz 自动判分 = Good
- Again / Hard 的 daily retry 行为
- 迁移脚本：幂等、dry-run 不写文件、apply 自动备份
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from core.tools.study.english import fsrs_scheduler as fsrs
from core.tools.study.english.fsrs_scheduler import (
    LEGACY_RATING_CUTOFF,
    RATING_MIGRATION_VERSION,
    apply_progress,
    create_daily_scheduler,
    event_is_lapse,
    fsrs_card_from_progress,
    historical_quality_to_rating,
    legacy_quality_to_rating,
    normalize_source,
    quality_to_rating,
    rebuild_fsrs_card_from_history,
    save_fsrs_to_progress,
    should_retry_tomorrow,
)
from fsrs import Card, Rating

# cutoff 前后各取一个明确时间点（Asia/Shanghai）。
# BEFORE 需留足跨度，保证整段历史都落在 cutoff 之前（numerous 真实历史
# 是 2026-08-13 ~ 2026-08-30，全部早于 2026-09-01）。
BEFORE = LEGACY_RATING_CUTOFF - 86400 * 30
AFTER = LEGACY_RATING_CUTOFF + 1


# ---------------------------------------------------------------------------
# 1. 评分映射
# ---------------------------------------------------------------------------


def test_legacy_mapping_before_cutoff():
    """cutoff 前：1/2→Again、3→Hard、4→Good、5→Easy。"""
    assert legacy_quality_to_rating(1) == Rating.Again
    assert legacy_quality_to_rating(2) == Rating.Again
    assert legacy_quality_to_rating(3) == Rating.Hard
    assert legacy_quality_to_rating(4) == Rating.Good
    assert legacy_quality_to_rating(5) == Rating.Easy

    assert historical_quality_to_rating(1, BEFORE) == Rating.Again
    assert historical_quality_to_rating(2, BEFORE) == Rating.Again
    assert historical_quality_to_rating(3, BEFORE) == Rating.Hard
    assert historical_quality_to_rating(4, BEFORE) == Rating.Good
    assert historical_quality_to_rating(5, BEFORE) == Rating.Easy


def test_current_mapping_after_cutoff():
    """cutoff 后（当前 App 契约）：1→Again、2→Hard、3→Good、4→Easy。"""
    assert quality_to_rating(1) == Rating.Again
    assert quality_to_rating(2) == Rating.Hard
    assert quality_to_rating(3) == Rating.Good
    assert quality_to_rating(4) == Rating.Easy

    assert historical_quality_to_rating(1, AFTER) == Rating.Again
    assert historical_quality_to_rating(2, AFTER) == Rating.Hard
    assert historical_quality_to_rating(3, AFTER) == Rating.Good
    assert historical_quality_to_rating(4, AFTER) == Rating.Easy


def test_cutoff_boundary():
    """cutoff 边界：早于 cutoff 用旧语义，等于/晚于 cutoff 用新语义。"""
    # 关键回归：quality=4 在边界两侧分别是 Good 与 Easy
    assert historical_quality_to_rating(4, LEGACY_RATING_CUTOFF - 1) == Rating.Good
    assert historical_quality_to_rating(4, LEGACY_RATING_CUTOFF) == Rating.Easy
    assert historical_quality_to_rating(3, LEGACY_RATING_CUTOFF - 1) == Rating.Hard
    assert historical_quality_to_rating(3, LEGACY_RATING_CUTOFF) == Rating.Good
    # 缺失时间戳按旧语义（更保守，不会把历史评分放大成 Easy）
    assert historical_quality_to_rating(4, None) == Rating.Good


def test_quality_to_rating_has_no_history_compat():
    """当前 API 映射函数不得掺入历史兼容逻辑。"""
    assert quality_to_rating(3) == Rating.Good
    assert quality_to_rating(2) == Rating.Hard
    assert quality_to_rating(0) == Rating.Again
    assert quality_to_rating(5) == Rating.Easy


# ---------------------------------------------------------------------------
# 2. rebuild 行为
# ---------------------------------------------------------------------------


def _history(qualities, start: float, step: int = 86400):
    return [
        {"timestamp": start + i * step, "quality": q}
        for i, q in enumerate(qualities)
    ]


def test_rebuild_is_deterministic():
    data = {"history": _history([3, 4, 4, 4, 4], BEFORE, step=86400 * 3)}
    first = rebuild_fsrs_card_from_history(data)
    second = rebuild_fsrs_card_from_history(data)
    assert first.stability == second.stability
    assert first.difficulty == second.difficulty
    assert first.due == second.due
    assert first.last_review == second.last_review


def test_rebuild_handles_unsorted_history():
    history = _history([4, 3, 4], BEFORE, step=86400 * 2)
    ordered = rebuild_fsrs_card_from_history({"history": history})
    shuffled = rebuild_fsrs_card_from_history(
        {"history": [history[2], history[0], history[1]]}
    )
    assert ordered.stability == shuffled.stability
    assert ordered.due == shuffled.due


def test_numerous_like_case_not_overestimated():
    """numerous 类场景：旧 3,4,4,4,4 必须回放成 Hard,Good,Good,Good,Good。

    错误解释（统一按当前语义 Good,Easy,Easy,Easy,Easy）会明显高估记忆强度。
    """
    history = _history([3, 4, 4, 4, 4], BEFORE, step=86400 * 3)
    data = {"history": history}

    corrected = rebuild_fsrs_card_from_history(data)

    # 复现「错误解释」：忽略事件时间，统一套用当前 App 语义
    wrong_card = Card()
    scheduler = create_daily_scheduler()
    for event in sorted(history, key=lambda e: e["timestamp"]):
        rating = quality_to_rating(event["quality"])
        reviewed = scheduler.review_card(
            wrong_card,
            rating,
            review_datetime=datetime.fromtimestamp(
                event["timestamp"], timezone.utc
            ),
        )
        wrong_card = reviewed[0] if isinstance(reviewed, tuple) else reviewed

    assert corrected.stability < wrong_card.stability
    assert corrected.difficulty > wrong_card.difficulty
    assert corrected.due < wrong_card.due
    # 方向合理的量级校验：错误解释会把间隔推到 100 天以上
    wrong_interval_days = (wrong_card.due - corrected.due).total_seconds() / 86400
    assert wrong_interval_days > 30


def test_new_events_after_cutoff_are_not_migrated():
    """cutoff 之后的新评分不能被误迁移成旧语义。"""
    history = _history([3, 4], AFTER, step=86400)
    card = rebuild_fsrs_card_from_history({"history": history})
    # 3=Good、4=Easy 的连续两次成功，间隔应明显大于 1 天
    assert (card.due - card.last_review).total_seconds() / 86400 > 1


def test_old_schema_is_rebuilt_with_historical_semantics():
    data = {
        "history": _history([3, 4, 4, 4, 4], BEFORE, step=86400 * 3),
        "fsrs_schema_version": 2,
        "fsrs_state": 2,
        "fsrs_step": None,
        "fsrs_stability": 123.6,
        "fsrs_difficulty": 1.0,
        "fsrs_due": BEFORE + 86400 * 200,
        "fsrs_last_review": BEFORE + 86400 * 12,
    }
    card = fsrs_card_from_progress(data)
    expected = rebuild_fsrs_card_from_history(data)
    assert card.stability == pytest.approx(expected.stability)
    assert card.difficulty == pytest.approx(expected.difficulty)
    # 旧的高估状态必须被丢弃
    assert card.stability < 123.6
    assert card.difficulty > 1.0


def test_fsrs_state_roundtrip():
    data: dict = {"history": _history([3, 4], AFTER, step=86400)}
    card = rebuild_fsrs_card_from_history(data)
    save_fsrs_to_progress(data, card)
    assert data["fsrs_schema_version"] == fsrs.FSRS_SCHEMA_VERSION
    assert data["next_review"] == data["fsrs_due"]

    restored = fsrs_card_from_progress(data)
    assert int(restored.state) == int(card.state)
    assert restored.stability == pytest.approx(card.stability)
    assert restored.difficulty == pytest.approx(card.difficulty)
    assert restored.due == card.due
    assert restored.last_review == card.last_review


def test_rebuild_until_excludes_current_event():
    """until 参数必须能排除正在处理的那次评分，避免重复计入。"""
    base = _history([3], BEFORE)
    current = {"timestamp": BEFORE + 86400, "quality": 4}
    data = {"history": base + [current]}
    assert rebuild_fsrs_card_from_history(data).last_review is not None
    partial = rebuild_fsrs_card_from_history(data, until=current["timestamp"])
    assert partial.last_review == datetime.fromtimestamp(
        base[0]["timestamp"], timezone.utc
    )


# ---------------------------------------------------------------------------
# 3. apply_progress：double-count / daily retry / source
# ---------------------------------------------------------------------------


class _FakeStore:
    def __init__(self, progress=None):
        self.progress = progress or {}
        self.saved = 0

    def _ensure_loaded(self):
        return None

    def save_progress(self):
        self.saved += 1


class _FakeDailyLog:
    def __init__(self):
        self.unknown = []
        self.removed = []

    def remove(self, word):
        self.removed.append(word)

    def mark_unknown(self, word, date=None):
        self.unknown.append(word)


class _FakeUnfamiliarBook:
    def __init__(self):
        self.unknown = []
        self.known = []

    def mark_unknown(self, word):
        self.unknown.append(word)
        return {"unknown_count": len(self.unknown)}

    def mark_known(self, word):
        self.known.append(word)
        return {"unknown_count": 0}


def _run_apply(store, word, quality, source=None):
    """执行 apply_progress，隔离 daily / unfamiliar 的外部副作用。"""
    daily = _FakeDailyLog()
    book = _FakeUnfamiliarBook()
    with (
        patch(
            "core.tools.study.english.daily_word_log.get_daily_word_log",
            return_value=daily,
        ),
        patch(
            "core.tools.study.english.unfamiliar_word_book.get_unfamiliar_word_book",
            return_value=book,
        ),
    ):
        result = (
            apply_progress(store, word, quality, source)
            if source
            else apply_progress(store, word, quality)
        )
    return result, daily, book


def test_new_card_first_rating_is_not_double_counted(monkeypatch):
    """空的新卡第一次 Good，状态必须与只调用一次 review_card 完全一致。"""
    fixed = AFTER + 86400 * 30
    monkeypatch.setattr(fsrs.time, "time", lambda: fixed)

    store = _FakeStore()
    _run_apply(store, "apple", 3)

    expected_card = create_daily_scheduler().review_card(
        Card(),
        Rating.Good,
        review_datetime=datetime.fromtimestamp(fixed, timezone.utc),
    )[0]
    data = store.progress["apple"]
    assert data["fsrs_stability"] == pytest.approx(expected_card.stability)
    assert data["fsrs_difficulty"] == pytest.approx(expected_card.difficulty)
    assert data["fsrs_due"] == pytest.approx(expected_card.due.timestamp())
    assert data["fsrs_last_review"] == pytest.approx(
        expected_card.last_review.timestamp()
    )
    assert len(data["history"]) == 1


def test_pre_appended_history_double_counts_the_current_rating(monkeypatch):
    """反证 double-count 确实存在：先 append 再恢复 Card 会把本次评分算两遍。

    修复前的顺序是 history.append(当前事件) → fsrs_card_from_progress()
    → 缺失/旧 schema 时 rebuild（第一次计入）→ review_card（第二次计入）。

    两次评分发生在同一时刻，elapsed_days=0，FSRS 的 stability 增量为 0，
    所以影响落在 difficulty 上：难度被额外下调一次，卡片被低估难度。
    """
    fixed = AFTER + 86400 * 30
    monkeypatch.setattr(fsrs.time, "time", lambda: fixed)
    when = datetime.fromtimestamp(fixed, timezone.utc)

    single = create_daily_scheduler().review_card(
        Card(), Rating.Good, review_datetime=when
    )[0]

    buggy_data = {"history": [{"timestamp": fixed, "quality": 3}]}
    rebuilt = rebuild_fsrs_card_from_history(buggy_data)
    doubled = create_daily_scheduler().review_card(
        rebuilt, Rating.Good, review_datetime=when
    )[0]

    assert doubled.difficulty < single.difficulty
    assert doubled.stability == pytest.approx(single.stability)


def test_new_card_first_rating_history_not_applied_twice(monkeypatch):
    """同样的回归：逐条评分累积的结果必须与手动 replay 一致。"""
    fixed = AFTER + 86400 * 60
    monkeypatch.setattr(fsrs.time, "time", lambda: fixed)
    store = _FakeStore()
    for quality in (3, 4):
        _run_apply(store, "banana", quality)

    data = store.progress["banana"]
    replayed = rebuild_fsrs_card_from_history(data)
    assert data["fsrs_stability"] == pytest.approx(replayed.stability)
    assert data["fsrs_due"] == pytest.approx(replayed.due.timestamp())
    assert len(data["history"]) == 2


def test_again_always_retries_tomorrow(monkeypatch):
    monkeypatch.setattr(fsrs.time, "time", lambda: AFTER + 86400 * 30)
    store = _FakeStore()
    result, daily, book = _run_apply(store, "apple", 1)
    assert result["daily_retry"] is True
    assert daily.unknown == ["apple"]
    assert book.unknown == ["apple"]


def test_hard_is_not_treated_as_forgotten_when_stable(monkeypatch):
    """Hard 属于成功回忆：卡片已经稳定时不该进第二天 daily 重试。"""
    monkeypatch.setattr(fsrs.time, "time", lambda: AFTER + 86400 * 30)
    store = _FakeStore()
    # 先打造成熟卡片
    for _ in range(4):
        _run_apply(store, "apple", 4)
    result, daily, book = _run_apply(store, "apple", 2)
    assert result["daily_retry"] is False
    assert daily.unknown == []
    assert book.known == ["apple"]


def test_hard_on_fragile_new_card_retries_tomorrow(monkeypatch):
    """新词判 Hard 仍然脆弱（stability 低于阈值）时保留第二天重看。"""
    monkeypatch.setattr(fsrs.time, "time", lambda: AFTER + 86400 * 30)
    store = _FakeStore()
    result, daily, _book = _run_apply(store, "apple", 2)
    assert store.progress["apple"]["fsrs_stability"] < fsrs.HARD_DAILY_RETRY_STABILITY_DAYS
    assert result["daily_retry"] is True
    assert daily.unknown == ["apple"]


def test_should_retry_tomorrow_matrix():
    fragile = Card()
    fragile.stability = 0.5
    stable = Card()
    stable.stability = 20.0
    assert should_retry_tomorrow(Rating.Again, stable) is True
    assert should_retry_tomorrow(Rating.Hard, fragile) is True
    assert should_retry_tomorrow(Rating.Hard, stable) is False
    assert should_retry_tomorrow(Rating.Good, fragile) is False
    assert should_retry_tomorrow(Rating.Easy, fragile) is False


def test_history_records_source(monkeypatch):
    monkeypatch.setattr(fsrs.time, "time", lambda: AFTER + 86400 * 30)
    store = _FakeStore()
    _run_apply(store, "apple", 3)
    assert store.progress["apple"]["history"][-1]["source"] == fsrs.SOURCE_MANUAL_REVIEW

    _run_apply(store, "apple", 3, source=fsrs.SOURCE_QUIZ)
    assert store.progress["apple"]["history"][-1]["source"] == fsrs.SOURCE_QUIZ

    _run_apply(store, "apple", 3, source="unknown_source")
    assert store.progress["apple"]["history"][-1]["source"] == fsrs.SOURCE_MANUAL_REVIEW


def test_normalize_source():
    assert normalize_source(None) == fsrs.SOURCE_MANUAL_REVIEW
    assert normalize_source("quiz") == fsrs.SOURCE_QUIZ
    assert normalize_source("daily_retry") == fsrs.SOURCE_DAILY_RETRY
    assert normalize_source("same_session_retry") == fsrs.SOURCE_SAME_SESSION_RETRY
    assert normalize_source("ai_unfamiliar_check") == fsrs.SOURCE_AI_UNFAMILIAR_CHECK
    assert normalize_source("nonsense") == fsrs.SOURCE_MANUAL_REVIEW


def test_old_history_without_source_still_works():
    """旧记录没有 source 字段时不能影响调度。"""
    data = {
        "history": [
            {"timestamp": BEFORE, "quality": 4},
            {"timestamp": BEFORE + 86400, "quality": 3},
        ]
    }
    card = rebuild_fsrs_card_from_history(data)
    assert card.last_review is not None
    assert event_is_lapse({"timestamp": BEFORE, "quality": 2}) is True
    assert event_is_lapse({"timestamp": AFTER, "quality": 2}) is False


def test_event_is_lapse_semantics():
    assert event_is_lapse({"timestamp": BEFORE, "quality": 1}) is True
    assert event_is_lapse({"timestamp": BEFORE, "quality": 2}) is True
    assert event_is_lapse({"timestamp": BEFORE, "quality": 3}) is False
    assert event_is_lapse({"timestamp": AFTER, "quality": 1}) is True
    assert event_is_lapse({"timestamp": AFTER, "quality": 2}) is False
    assert event_is_lapse({}) is False


# ---------------------------------------------------------------------------
# 4. quiz 自动判分
# ---------------------------------------------------------------------------


def test_quiz_correct_is_good_not_easy(monkeypatch):
    from core.tools.study.english import quiz as quiz_mod

    fixed = AFTER + 86400 * 30
    monkeypatch.setattr(fsrs.time, "time", lambda: fixed)
    store = _FakeStore()
    question = {
        "type": "dictation",
        "word": "apple",
        "answer": "apple",
        "word_data": {"word": "apple"},
    }
    daily = _FakeDailyLog()
    book = _FakeUnfamiliarBook()
    with (
        patch(
            "core.tools.study.english.daily_word_log.get_daily_word_log",
            return_value=daily,
        ),
        patch(
            "core.tools.study.english.unfamiliar_word_book.get_unfamiliar_word_book",
            return_value=book,
        ),
    ):
        result = quiz_mod.check_quiz_answer(store, question, "apple")
        assert result["is_correct"] is True
    assert store.progress["apple"]["history"][-1]["quality"] == 3
    assert store.progress["apple"]["history"][-1]["source"] == fsrs.SOURCE_QUIZ
    assert quality_to_rating(3) == Rating.Good

    # 答错 = Again
    with (
        patch(
            "core.tools.study.english.daily_word_log.get_daily_word_log",
            return_value=daily,
        ),
        patch(
            "core.tools.study.english.unfamiliar_word_book.get_unfamiliar_word_book",
            return_value=book,
        ),
    ):
        result = quiz_mod.check_quiz_answer(store, question, "orange")
        assert result["is_correct"] is False
    assert store.progress["apple"]["history"][-1]["quality"] == 1
    assert quality_to_rating(1) == Rating.Again


# ---------------------------------------------------------------------------
# 5. 迁移脚本
# ---------------------------------------------------------------------------


def _load_migration_module():
    import importlib.util

    path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "maintenance"
        / "migrate_vocab_fsrs_history.py"
    )
    spec = importlib.util.spec_from_file_location("migrate_vocab_fsrs_history", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sample_progress():
    return {
        "numerous": {
            "reps": 5,
            "interval": 120.0,
            "easiness": 2.5,
            "next_review": 0,
            "history": _history([3, 4, 4, 4, 4], BEFORE, step=86400 * 3),
            "fsrs_state": 2,
            "fsrs_step": None,
            "fsrs_stability": 123.604,
            "fsrs_difficulty": 1.0,
            "fsrs_due": BEFORE + 86400 * 200,
            "fsrs_last_review": BEFORE + 86400 * 12,
            "fsrs_schema_version": 2,
        },
        "fresh": {
            "reps": 1,
            "interval": 1.0,
            "easiness": 2.5,
            "next_review": 0,
            "history": _history([4], AFTER, step=86400),
        },
    }


def test_migration_is_idempotent():
    module = _load_migration_module()
    progress = _sample_progress()
    now = time.time()

    first, stats = module.rebuild_progress(progress, now)
    assert stats["rebuilt_cards"] == 2
    assert stats["legacy_events"] == 5
    assert stats["current_events"] == 1

    second, second_stats = module.rebuild_progress(first, now)
    assert second_stats["rebuilt_cards"] == 0
    assert second_stats["skipped_already_migrated"] == 2
    assert second == first

    # 强制重跑也必须得到完全一致的结果（不会 4→3 再 3→2）
    forced, forced_stats = module.rebuild_progress(first, now, force=True)
    assert forced_stats["rebuilt_cards"] == 2
    assert forced == first


def test_migration_preserves_history_and_compat_fields():
    module = _load_migration_module()
    progress = _sample_progress()
    original_history = json.loads(json.dumps(progress["numerous"]["history"]))
    rebuilt, _stats = module.rebuild_progress(progress, time.time())

    assert rebuilt["numerous"]["history"] == original_history
    assert rebuilt["numerous"]["easiness"] == 2.5
    assert rebuilt["numerous"]["reps"] == 5
    assert rebuilt["numerous"]["rating_migration_version"] == RATING_MIGRATION_VERSION
    assert rebuilt["numerous"]["fsrs_schema_version"] == fsrs.FSRS_SCHEMA_VERSION
    assert rebuilt["numerous"]["fsrs_stability"] < 123.604
    assert rebuilt["numerous"]["fsrs_difficulty"] > 1.0
    assert rebuilt["numerous"]["next_review"] == rebuilt["numerous"]["fsrs_due"]


def test_migration_dry_run_does_not_write(tmp_path):
    module = _load_migration_module()
    path = tmp_path / "vocab_progress.json"
    path.write_text(json.dumps(_sample_progress()), encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    argv = ["prog", "--progress", str(path)]
    with patch.object(sys, "argv", argv):
        assert module.main() == 0

    assert path.read_text(encoding="utf-8") == before
    assert list(tmp_path.glob("*rating_migration*")) == []


def test_migration_apply_creates_backup(tmp_path):
    module = _load_migration_module()
    path = tmp_path / "vocab_progress.json"
    path.write_text(json.dumps(_sample_progress()), encoding="utf-8")

    argv = ["prog", "--progress", str(path), "--apply"]
    with patch.object(sys, "argv", argv):
        assert module.main() == 0

    backups = list(tmp_path.glob("vocab_progress.pre_rating_migration_*.bak.json"))
    assert len(backups) == 1
    applied = json.loads(path.read_text(encoding="utf-8"))
    assert applied["numerous"]["rating_migration_version"] == RATING_MIGRATION_VERSION

    # 回滚
    argv = ["prog", "--progress", str(path), "--rollback"]
    with patch.object(sys, "argv", argv):
        assert module.main() == 0
    restored = json.loads(path.read_text(encoding="utf-8"))
    assert "rating_migration_version" not in restored["numerous"]
