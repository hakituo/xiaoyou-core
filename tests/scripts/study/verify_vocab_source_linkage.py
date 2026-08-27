# -*- coding: utf-8 -*-
"""验证词汇双来源与 App 错题/unfamiliar 联动。

用法（项目根目录）：
    .\venv_core\Scripts\python.exe tests\scripts\study\verify_vocab_source_linkage.py

所有写操作都落在临时目录，不修改真实词汇数据。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


class _FakeStore:
    """满足调度与错题统计所需的最小词汇存储。"""

    def __init__(self) -> None:
        self.progress: Dict[str, Dict[str, Any]] = {}
        self.saved = False

    def _ensure_loaded(self) -> None:
        return None

    def save_progress(self) -> None:
        self.saved = True

    def get_word_info(self, word: str) -> Optional[Dict[str, Any]]:
        return {
            "word": word,
            "translations": [{"type": "n.", "translation": f"{word}-释义"}],
        }


def _write_word_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def verify_sources(temp_root: Path) -> None:
    """默认读取昨天 daily；both 必须分区返回两套真实结果。"""
    from core.services.study.dispatch import ToolDispatcher
    from core.tools.study.english import daily_word_log as daily_module
    from core.tools.study.english import unfamiliar_word_book as unfamiliar_module
    from core.tools.study.english.daily_word_log import DailyWordLogManager
    from core.tools.study.english.unfamiliar_word_book import UnfamiliarWordBook

    daily_dir = temp_root / "daily"
    _write_word_file(
        daily_dir / "2026" / "08" / "24.txt",
        "proportion 1\nremedy 1\nprobe 1\n",
    )
    unfamiliar_path = temp_root / "unfamiliar_word.txt"
    _write_word_file(unfamiliar_path, "contrast 5\nconduct 3\n")

    daily = DailyWordLogManager(base_dir=str(daily_dir))
    daily._get_today_str = lambda: "2026/08/25"
    unfamiliar = UnfamiliarWordBook(file_path=str(unfamiliar_path))
    original_daily = daily_module._instance
    original_unfamiliar = unfamiliar_module._instance
    daily_module._instance = daily
    unfamiliar_module._instance = unfamiliar
    try:
        dispatcher = ToolDispatcher(SimpleNamespace(base_dir=str(temp_root)))

        default_result = dispatcher.dispatch(
            "english",
            "word_quiz",
            {"action": "quiz", "count": 5, "priority": "high_count"},
        )
        assert default_result["source"] == "daily"
        assert default_result["scope"] == {
            "date": "2026/08/24",
            "mode": "yesterday_default",
        }
        assert default_result["dates_with_words"] == ["2026/08/24"]
        assert {item["word"] for item in default_result["words"]} == {
            "proportion",
            "remedy",
            "probe",
        }

        both_result = dispatcher.dispatch(
            "english",
            "word_quiz",
            {
                "action": "quiz",
                "source": "both",
                "count": 5,
                "priority": "high_count",
            },
        )
        assert both_result["source"] == "both"
        assert both_result["sources"]["daily"]["source"] == "daily"
        assert both_result["sources"]["unfamiliar"]["source"] == "unfamiliar"
        assert both_result["sources"]["unfamiliar"]["words"][0]["word"] == "contrast"

        invalid = dispatcher.dispatch(
            "english",
            "word_quiz",
            {"action": "quiz", "source": "unknown"},
        )
        assert invalid["status"] == "error"
    finally:
        daily_module._instance = original_daily
        unfamiliar_module._instance = original_unfamiliar


def verify_app_linkage(temp_root: Path) -> None:
    """App 评分更新 unfamiliar，错题 API 合并两侧计数且不重复累加。"""
    from core.tools.study.english import daily_word_log as daily_module
    from core.tools.study.english import fsrs_scheduler
    from core.tools.study.english import unfamiliar_word_book as unfamiliar_module
    from core.tools.study.english import stats
    from core.tools.study.english.daily_word_log import DailyWordLogManager
    from core.tools.study.english.unfamiliar_word_book import UnfamiliarWordBook

    daily = DailyWordLogManager(base_dir=str(temp_root / "review_daily"))
    daily._get_today_str = lambda: "2026/08/25"
    unfamiliar = UnfamiliarWordBook(
        file_path=str(temp_root / "review_unfamiliar_word.txt")
    )
    original_daily = daily_module._instance
    original_unfamiliar = unfamiliar_module._instance
    original_fsrs_available = fsrs_scheduler._FSRS_AVAILABLE
    daily_module._instance = daily
    unfamiliar_module._instance = unfamiliar
    fsrs_scheduler._FSRS_AVAILABLE = False
    try:
        store = _FakeStore()
        wrong = fsrs_scheduler.apply_progress(store, "apple", 1)
        assert wrong["daily_synced"] is True
        assert wrong["unfamiliar_synced"] is True
        assert wrong["unfamiliar_unknown_count"] == 1
        assert unfamiliar.list_words() == [{"word": "apple", "unknown_count": 1}]

        correct = fsrs_scheduler.apply_progress(store, "apple", 4)
        assert correct["unfamiliar_unknown_count"] == 0

        # 构造历史错误 2 次 + AI 生词本计数 1 次，合并展示应取 max=2，
        # 而不是错误地相加成 3。
        store.progress["apple"]["history"] = [
            {"timestamp": 1.0, "quality": 1},
            {"timestamp": 2.0, "quality": 2},
        ]
        merged = stats.get_mistakes(
            store,
            limit=20,
            unfamiliar_words=[
                {"word": "apple", "unknown_count": 1},
                {"word": "contrast", "unknown_count": 5},
            ],
        )
        by_word = {item["word"]: item for item in merged}
        assert by_word["apple"]["error_count"] == 2
        assert by_word["apple"]["sources"] == ["progress", "unfamiliar"]
        assert by_word["contrast"]["error_count"] == 5
        assert by_word["contrast"]["sources"] == ["unfamiliar"]

        from core.services.study.dispatch import ToolDispatcher

        linked_pool = stats.get_linked_unfamiliar_words(
            store,
            unfamiliar_words=[{"word": "contrast", "unknown_count": 5}],
        )
        fake_manager = SimpleNamespace(
            get_linked_unfamiliar_words=lambda: linked_pool,
        )
        dispatcher = ToolDispatcher(
            SimpleNamespace(base_dir=str(temp_root), vocab_manager=fake_manager)
        )
        ai_result = dispatcher.dispatch(
            "english",
            "word_quiz",
            {
                "action": "quiz",
                "source": "unfamiliar",
                "count": 2,
                "priority": "high_count",
            },
        )
        assert ai_result["linked_with_app_mistakes"] is True
        assert ai_result["words"][0]["word"] == "contrast"
        assert ai_result["words"][1]["word"] == "apple"
        assert ai_result["words"][1]["progress_error_count"] == 2
    finally:
        daily_module._instance = original_daily
        unfamiliar_module._instance = original_unfamiliar
        fsrs_scheduler._FSRS_AVAILABLE = original_fsrs_available


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="vocab_source_linkage_") as tmp:
        temp_root = Path(tmp)
        verify_sources(temp_root)
        verify_app_linkage(temp_root)
    print("[ALL PASS] 双来源可区分，daily 默认读取昨天，App 错题与 unfamiliar 已联动")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
