"""验证背单词评分语义迁移（legacy/current 双 schema + FSRS 重建）。

覆盖点：
1. legacy / current 映射与 cutoff 边界
2. rebuild 确定性、旧 schema 自动重建、FSRS 状态存取
3. numerous 类案例：旧 3,4,4,4,4 不得被解释成 Good,Easy,Easy,Easy,Easy
4. 新卡首次评分不 double-count
5. quiz 自动判分 = Good
6. Again/Hard 的 daily retry 行为
7. 迁移脚本：dry-run 不写文件、apply 自动备份、幂等、可回滚

用法（项目根目录）：
    .\\venv_core\\Scripts\\python.exe tests\\scripts\\study\\verify_vocab_rating_migration.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fsrs import Card, Rating  # noqa: E402

from core.tools.study.english import fsrs_scheduler as fsrs  # noqa: E402
from core.tools.study.english.fsrs_scheduler import (  # noqa: E402
    LEGACY_RATING_CUTOFF,
    create_daily_scheduler,
    fsrs_card_from_progress,
    historical_quality_to_rating,
    legacy_quality_to_rating,
    quality_to_rating,
    rebuild_fsrs_card_from_history,
    save_fsrs_to_progress,
)

BEFORE = LEGACY_RATING_CUTOFF - 86400 * 30
AFTER = LEGACY_RATING_CUTOFF + 1
_PASSED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name} 失败 {detail}")
    _PASSED.append(name)
    print(f"  [PASS] {name}{(' | ' + detail) if detail else ''}")


def history(qualities, start: float, step: float = 86400.0):
    return [
        {"timestamp": start + i * step, "quality": q}
        for i, q in enumerate(qualities)
    ]


def replay_with_current_semantics(events):
    """复现 2026-09-01 那次迁移的错误：忽略事件时间，统一套用当前 App 语义。"""
    scheduler = create_daily_scheduler()
    card = Card()
    for event in sorted(events, key=lambda e: e["timestamp"]):
        reviewed = scheduler.review_card(
            card,
            quality_to_rating(event["quality"]),
            review_datetime=datetime.fromtimestamp(event["timestamp"], timezone.utc),
        )
        card = reviewed[0] if isinstance(reviewed, tuple) else reviewed
    return card


# ---------------------------------------------------------------------------


def verify_mapping() -> None:
    check(
        "legacy 映射 1/2→Again、3→Hard、4→Good、5→Easy",
        [
            legacy_quality_to_rating(1),
            legacy_quality_to_rating(2),
            legacy_quality_to_rating(3),
            legacy_quality_to_rating(4),
            legacy_quality_to_rating(5),
        ]
        == [Rating.Again, Rating.Again, Rating.Hard, Rating.Good, Rating.Easy],
    )
    check(
        "current 映射 1→Again、2→Hard、3→Good、4→Easy",
        [
            quality_to_rating(1),
            quality_to_rating(2),
            quality_to_rating(3),
            quality_to_rating(4),
        ]
        == [Rating.Again, Rating.Hard, Rating.Good, Rating.Easy],
    )
    check(
        "cutoff 边界：quality=4 前 Good 后 Easy",
        historical_quality_to_rating(4, LEGACY_RATING_CUTOFF - 1) == Rating.Good
        and historical_quality_to_rating(4, LEGACY_RATING_CUTOFF) == Rating.Easy,
    )


def verify_rebuild() -> None:
    data = {"history": history([3, 4, 4, 4, 4], BEFORE, 86400 * 3)}
    first = rebuild_fsrs_card_from_history(data)
    second = rebuild_fsrs_card_from_history(data)
    check(
        "rebuild 确定性",
        (
            first.stability,
            first.difficulty,
            first.due,
            first.last_review,
        )
        == (
            second.stability,
            second.difficulty,
            second.due,
            second.last_review,
        ),
    )

    # numerous 类案例
    wrong = replay_with_current_semantics(data["history"])
    check(
        "numerous 类案例：修正后 stability 更低",
        first.stability < wrong.stability,
        f"corrected={first.stability:.3f} wrong={wrong.stability:.3f}",
    )
    check(
        "numerous 类案例：修正后 difficulty 更高",
        first.difficulty > wrong.difficulty,
        f"corrected={first.difficulty:.4f} wrong={wrong.difficulty:.4f}",
    )
    check(
        "numerous 类案例：修正后 due 更早",
        first.due < wrong.due,
        f"相差 {(wrong.due - first.due).total_seconds() / 86400:.1f} 天",
    )

    # 旧 schema 自动重建
    old = {
        "history": history([3, 4, 4, 4, 4], BEFORE, 86400 * 3),
        "fsrs_schema_version": 2,
        "fsrs_state": 2,
        "fsrs_step": None,
        "fsrs_stability": 123.604,
        "fsrs_difficulty": 1.0,
        "fsrs_due": BEFORE + 86400 * 200,
        "fsrs_last_review": BEFORE + 86400 * 12,
    }
    rebuilt = fsrs_card_from_progress(old)
    check(
        "旧 schema（v2 高估状态）自动重建",
        abs(rebuilt.stability - first.stability) < 1e-9
        and rebuilt.difficulty > 1.0,
        f"stability 123.604 → {rebuilt.stability:.3f}",
    )

    # FSRS 状态存取
    store_data: dict = {"history": history([3, 4], AFTER, 86400)}
    card = rebuild_fsrs_card_from_history(store_data)
    save_fsrs_to_progress(store_data, card)
    restored = fsrs_card_from_progress(store_data)
    check(
        "FSRS 状态保存/恢复一致",
        restored.stability == card.stability
        and restored.difficulty == card.difficulty
        and restored.due == card.due
        and restored.last_review == card.last_review,
    )


def verify_no_double_count() -> None:
    fixed = AFTER + 86400 * 30
    when = datetime.fromtimestamp(fixed, timezone.utc)
    single = create_daily_scheduler().review_card(
        Card(), Rating.Good, review_datetime=when
    )[0]
    doubled = create_daily_scheduler().review_card(
        rebuild_fsrs_card_from_history({"history": [{"timestamp": fixed, "quality": 3}]}),
        Rating.Good,
        review_datetime=when,
    )[0]
    check(
        "确认 double-count 现象存在（difficulty 被额外下调）",
        doubled.difficulty < single.difficulty,
        f"single={single.difficulty:.4f} doubled={doubled.difficulty:.4f}",
    )

    store = _FakeStore()
    with (
        patch.object(fsrs.time, "time", return_value=fixed),
        _patched_side_effects(),
    ):
        fsrs.apply_progress(store, "apple", 3)
    data = store.progress["apple"]
    check(
        "新卡首次 Good 与「只应用一次」完全一致",
        abs(data["fsrs_stability"] - single.stability) < 1e-9
        and abs(data["fsrs_difficulty"] - single.difficulty) < 1e-9
        and abs(data["fsrs_due"] - single.due.timestamp()) < 1e-6,
        f"stability={data['fsrs_stability']:.4f}",
    )
    check("history 只记录一次", len(data["history"]) == 1)


def verify_quiz_and_retry() -> None:
    from core.tools.study.english import quiz as quiz_mod

    store = _FakeStore()
    question = {
        "type": "dictation",
        "word": "apple",
        "answer": "apple",
        "word_data": {"word": "apple"},
    }
    with _patched_side_effects() as (daily, book):
        quiz_mod.check_quiz_answer(store, question, "apple")
    quality = store.progress["apple"]["history"][-1]["quality"]
    source = store.progress["apple"]["history"][-1]["source"]
    check(
        "quiz 答对 = Good(3) 且带 source=quiz",
        quality == 3 and source == fsrs.SOURCE_QUIZ,
    )
    with _patched_side_effects() as (daily, book):
        quiz_mod.check_quiz_answer(store, question, "orange")
    check(
        "quiz 答错 = Again(1)",
        store.progress["apple"]["history"][-1]["quality"] == 1,
    )

    # Again 一定重试
    store = _FakeStore()
    with _patched_side_effects() as (daily, book):
        result = fsrs.apply_progress(store, "apple", 1)
    check(
        "Again → 第二天 daily retry",
        result["daily_retry"] is True and daily.unknown == ["apple"],
    )

    # 成熟卡片 Hard 不再重试
    store = _FakeStore()
    with _patched_side_effects():
        for _ in range(4):
            fsrs.apply_progress(store, "apple", 4)
    with _patched_side_effects() as (daily, book):
        result = fsrs.apply_progress(store, "apple", 2)
    check(
        "Hard（卡片已稳定）→ 不进 daily retry",
        result["daily_retry"] is False and daily.unknown == [],
        f"stability={store.progress['apple']['fsrs_stability']:.2f}",
    )

    # 新词 Hard 仍然脆弱 → 重试
    store = _FakeStore()
    with _patched_side_effects() as (daily, book):
        result = fsrs.apply_progress(store, "apple", 2)
    check(
        "Hard（新词/低 stability）→ 第二天 daily retry",
        result["daily_retry"] is True and daily.unknown == ["apple"],
        f"stability={store.progress['apple']['fsrs_stability']:.2f}",
    )


class _FakeStore:
    def __init__(self):
        self.progress: dict = {}
        self.saved = 0

    def _ensure_loaded(self):
        return None

    def save_progress(self):
        self.saved += 1


class _FakeDailyLog:
    def __init__(self):
        self.unknown: list[str] = []
        self.removed: list[str] = []

    def remove(self, word):
        self.removed.append(word)

    def mark_unknown(self, word, date=None):
        self.unknown.append(word)


class _FakeUnfamiliarBook:
    def __init__(self):
        self.unknown: list[str] = []
        self.known: list[str] = []

    def mark_unknown(self, word):
        self.unknown.append(word)
        return {"unknown_count": len(self.unknown)}

    def mark_known(self, word):
        self.known.append(word)
        return {"unknown_count": 0}


class _patched_side_effects:
    """隔离 daily 生词日志与 unfamiliar 生词本的真实文件写入。"""

    def __init__(self):
        self.daily = _FakeDailyLog()
        self.book = _FakeUnfamiliarBook()
        self._handles = []

    def __enter__(self):
        self._handles.append(
            patch(
                "core.tools.study.english.daily_word_log.get_daily_word_log",
                return_value=self.daily,
            )
        )
        self._handles.append(
            patch(
                "core.tools.study.english.unfamiliar_word_book.get_unfamiliar_word_book",
                return_value=self.book,
            )
        )
        for handle in self._handles:
            handle.start()
        return self.daily, self.book

    def __exit__(self, *exc):
        for handle in self._handles:
            handle.stop()
        return False


def _load_migration_module():
    path = (
        PROJECT_ROOT
        / "scripts"
        / "maintenance"
        / "migrate_vocab_fsrs_history.py"
    )
    spec = importlib.util.spec_from_file_location("migrate_vocab_fsrs_history", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_migration_tool() -> None:
    module = _load_migration_module()
    progress = {
        "numerous": {
            "reps": 5,
            "interval": 120.0,
            "easiness": 2.5,
            "next_review": 0,
            "history": history([3, 4, 4, 4, 4], BEFORE, 86400 * 3),
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
            "history": history([4], AFTER, 86400),
        },
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        path = tmp_path / "vocab_progress.json"
        path.write_text(json.dumps(progress), encoding="utf-8")
        before_text = path.read_text(encoding="utf-8")

        # dry-run 不写文件
        with patch.object(sys, "argv", ["prog", "--progress", str(path)]):
            module.main()
        check(
            "dry-run 不写文件",
            path.read_text(encoding="utf-8") == before_text
            and not list(tmp_path.glob("*rating_migration*")),
        )

        # apply 自动备份
        with patch.object(sys, "argv", ["prog", "--progress", str(path), "--apply"]):
            module.main()
        backups = list(tmp_path.glob("vocab_progress.pre_rating_migration_*.bak.json"))
        applied = json.loads(path.read_text(encoding="utf-8"))
        check("apply 自动生成备份", len(backups) == 1, backups[0].name if backups else "")
        check(
            "apply 写入 rating_migration_version",
            applied["numerous"]["rating_migration_version"]
            == fsrs.RATING_MIGRATION_VERSION,
        )
        check(
            "history 与 easiness 原样保留",
            applied["numerous"]["history"] == progress["numerous"]["history"]
            and applied["numerous"]["easiness"] == 2.5
            and applied["numerous"]["reps"] == 5,
        )
        check(
            "numerous 被修正（stability 下降 / difficulty 上升）",
            applied["numerous"]["fsrs_stability"] < 123.604
            and applied["numerous"]["fsrs_difficulty"] > 1.0,
            f"stability={applied['numerous']['fsrs_stability']:.3f} "
            f"difficulty={applied['numerous']['fsrs_difficulty']:.4f}",
        )

        # 幂等
        with patch.object(sys, "argv", ["prog", "--progress", str(path), "--apply"]):
            module.main()
        twice = json.loads(path.read_text(encoding="utf-8"))
        check("第二次 apply 幂等（结果不变）", twice == applied)

        # 回滚
        with patch.object(sys, "argv", ["prog", "--progress", str(path), "--rollback"]):
            module.main()
        restored = json.loads(path.read_text(encoding="utf-8"))
        check(
            "回滚恢复迁移前状态",
            "rating_migration_version" not in restored["numerous"],
        )


def verify_real_data_preview() -> None:
    """对真实进度文件做一次只读预览：可完整重建，且重跑结果与现状态一致。"""
    real = PROJECT_ROOT / "output" / "user_data" / "vocab_progress.json"
    if not real.exists():
        print("  [SKIP] 未找到真实进度文件，跳过真实数据预览")
        return
    module = _load_migration_module()
    progress = json.loads(real.read_text(encoding="utf-8"))
    now = time.time()

    expected = sum(
        1
        for data in progress.values()
        if isinstance(data, dict) and data.get("history")
    )
    rebuilt, stats = module.rebuild_progress(progress, now, force=True)
    check(
        "真实数据预览：legacy 事件存在且全部卡片可重建",
        stats["legacy_events"] > 0 and stats["rebuilt_cards"] == expected,
        f"legacy={stats['legacy_events']} / rebuilt={stats['rebuilt_cards']}/{expected}",
    )

    drift = [
        word
        for word, data in progress.items()
        if isinstance(data, dict)
        and data.get("history")
        and (
            abs(float(data.get("fsrs_stability") or 0) - float(rebuilt[word]["fsrs_stability"]))
            > 1e-6
            or abs(float(data.get("fsrs_difficulty") or 0) - float(rebuilt[word]["fsrs_difficulty"]))
            > 1e-6
            or abs(float(data.get("fsrs_due") or 0) - float(rebuilt[word]["fsrs_due"]))
            > 1e-6
        )
    ]
    check(
        "真实数据重跑与现状态完全一致（确定性 + 幂等）",
        not drift,
        f"stability 均值 {stats['stability']['new_mean']}, "
        f"difficulty 均值 {stats['difficulty']['new_mean']}",
    )

    _, second_stats = module.rebuild_progress(progress, now)
    check(
        "真实数据二次运行自动跳过（已迁移）",
        second_stats["rebuilt_cards"] == 0
        and second_stats["skipped_already_migrated"] == expected,
    )


def main() -> int:
    print("=" * 60)
    print("背单词评分语义迁移验证")
    print("=" * 60)
    print(f"cutoff: {fsrs.LEGACY_RATING_CUTOFF_ISO} (UTC ts={LEGACY_RATING_CUTOFF:.0f})")
    verify_mapping()
    verify_rebuild()
    verify_no_double_count()
    verify_quiz_and_retry()
    verify_migration_tool()
    verify_real_data_preview()
    print("=" * 60)
    print(f"全部通过：{len(_PASSED)} 项")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
