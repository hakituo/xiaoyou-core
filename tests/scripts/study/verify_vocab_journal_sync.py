# -*- coding: utf-8 -*-
"""验证 App 词汇会话会落入日记读取的每日学习记录。

用法（项目根目录）：
    .\venv_core\Scripts\python.exe tests\scripts\study\verify_vocab_journal_sync.py
"""

from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeVocabManager:
    def update_word_progress(self, word: str, quality: int) -> dict:
        return {"word": word, "quality": quality}


class _FakeDailyManager:
    def __init__(self) -> None:
        self.recorded: list[tuple[str, str]] = []
        self.requested_dates: list[str] = []

    def record_study(self, topic: str, content: str) -> None:
        self.recorded.append((topic, content))

    def get_record(self, date_str: str) -> dict:
        self.requested_dates.append(date_str)
        return {
            "study": {
                "sessions": [
                    {"topic": "英语词汇", "content": "完成一次词汇复习"}
                ]
            }
        }


class _FakeDailyTracker:
    def __init__(self) -> None:
        self.recorded: list[dict] = []

    def record_session(self, **kwargs) -> None:
        self.recorded.append(kwargs)


def main() -> int:
    from core.services.study.service import StudyService

    service = StudyService()
    service._vocab_enabled = True
    service._vocab_manager = _FakeVocabManager()
    tracker = _FakeDailyTracker()
    service._daily_tracker = tracker
    daily = _FakeDailyManager()

    with patch("core.services.study.service.get_daily_manager", return_value=daily):
        service.start_session()
        service.submit_word_review("apple", 4)
        service.submit_word_review("apple", 1)
        service.submit_word_review("banana", 3)
        result = service.end_session()

        assert result["words_reviewed"] == 3
        assert result["unique_words_reviewed"] == 2
        assert result["correct_count"] == 2
        assert len(daily.recorded) == 1
        assert daily.recorded[0][0] == "英语词汇"
        assert "评分 3 次" in daily.recorded[0][1]
        assert "涉及 2 个单词" in daily.recorded[0][1]
        assert len(tracker.recorded) == 1

        # 重复结束同一会话不能重复记账。
        assert service.end_session() == {}
        assert len(daily.recorded) == 1

        service.get_dictionary_stats = lambda: {}
        service.get_session_stats = lambda: {}
        digest = service.get_daily_study_summary_data("2026-08-23")
        assert daily.requested_dates == ["2026-08-23"]
        assert digest["overview"]["total_sessions"] == 1

    summary_context = (
        ROOT / "core/services/journal/summary_context.py"
    ).read_text(encoding="utf-8")
    plan_service = (
        ROOT / "core/services/journal/plan_service.py"
    ).read_text(encoding="utf-8")
    app_config = (ROOT / "config/yaml/app.yaml").read_text(encoding="utf-8")
    assert 'dt.strftime("%Y-%m-%d")' in summary_context
    assert 'yesterday.strftime("%Y-%m-%d")' in plan_service
    assert "llm_plan:\n    enabled: false" in app_config

    print("验证通过：词汇会话只记一次，日记按目标日期读取，角色计划 LLM 已关闭。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
