"""验证 Active Care 不会用旧词汇数量催促已完成的任务。

运行：
    .\venv_core\Scripts\python.exe tests\scripts\active_care\verify_vocab_status_guard.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.agents.chat_agent_components.persona_system.prompt.components.user_bio import (  # noqa: E402
    build_study_context_for_active_care,
)
from core.services.active_care.postprocess.event_target_guard import (  # noqa: E402
    enforce_vocabulary_status,
)
from core.tools.study.english import daily_word_log as daily_word_log_module  # noqa: E402
from core.tools.study.english import vocabulary_manager as vocabulary_manager_module  # noqa: E402
from core.tools.study.english.daily_word_log import DailyWordLogManager  # noqa: E402
from core.tools.study.english.loader import VocabDataStore  # noqa: E402
from core.tools.study.english.stats import get_today_review_status  # noqa: E402


def verify_realtime_status() -> dict:
    """临时数据中完成两词后，剩余量必须为 0，未掌握量必须为 1。"""
    old_daily_instance = daily_word_log_module._instance
    with tempfile.TemporaryDirectory(prefix="active_care_vocab_status_") as temp_dir:
        temp_root = Path(temp_dir)
        daily_manager = DailyWordLogManager(base_dir=str(temp_root / "daily"))
        daily_word_log_module._instance = daily_manager
        try:
            now = time.time()
            store = VocabDataStore(progress_path=str(temp_root / "progress.json"))
            store._loaded = True
            store.progress = {
                "alpha": {
                    "history": [{"timestamp": now - 10, "quality": 4}],
                    "fsrs_due": now + 86400,
                    "next_review": now + 86400,
                },
                "beta": {
                    "history": [{"timestamp": now - 5, "quality": 1}],
                    "fsrs_due": now + 86400,
                    "next_review": now + 86400,
                },
            }
            daily_manager.mark_unknown("beta")
            status = get_today_review_status(store, daily_record={})
        finally:
            daily_word_log_module._instance = old_daily_instance

    assert status["reviewed_words"] == 2, status
    assert status["unresolved_words"] == 1, status
    assert status["remaining_words"] == 0, status
    assert status["completed"] is True, status
    return status


def verify_explicit_completion_wins_over_dynamic_queue() -> dict:
    """会话结束后队列再次出现词，也不能把今日状态改回未完成。"""
    old_daily_instance = daily_word_log_module._instance
    with tempfile.TemporaryDirectory(prefix="active_care_vocab_completion_") as temp_dir:
        temp_root = Path(temp_dir)
        daily_manager = DailyWordLogManager(base_dir=str(temp_root / "daily"))
        daily_word_log_module._instance = daily_manager
        try:
            now = time.time()
            store = VocabDataStore(progress_path=str(temp_root / "progress.json"))
            store._loaded = True
            store.dictionary = [
                {"word": "alpha", "translations": []},
                {"word": "gamma", "translations": []},
            ]
            store.progress = {
                "alpha": {
                    "history": [{"timestamp": now - 10, "quality": 4}],
                    "fsrs_due": now + 86400,
                    "next_review": now + 86400,
                },
                "gamma": {
                    "history": [{"timestamp": now - 86400, "quality": 4}],
                    "fsrs_due": now - 1,
                    "next_review": now - 1,
                },
            }
            record = {
                "study": {
                    "sessions": [
                        {
                            "topic": "英语词汇",
                            "content": "完成词汇复习：评分 2 次，涉及 1 个单词",
                            "time": "22:36",
                        }
                    ]
                }
            }
            status = get_today_review_status(store, daily_record=record)
        finally:
            daily_word_log_module._instance = old_daily_instance

    assert status["remaining_words"] == 1, status
    assert status["completed"] is True, status
    assert status["completion_source"] == "daily_study_session", status
    assert status["completed_at"] == "22:36", status
    return status


def verify_prompt_anchor(status: dict) -> None:
    """学习上下文必须明确给出完成态，并声明其优先级高于旧历史。"""

    class _FakeVocabularyManager:
        @staticmethod
        def get_today_review_status() -> dict:
            return status

    old_getter = vocabulary_manager_module.get_vocabulary_manager
    vocabulary_manager_module.get_vocabulary_manager = lambda: _FakeVocabularyManager()
    try:
        context = build_study_context_for_active_care()
    finally:
        vocabulary_manager_module.get_vocabulary_manager = old_getter

    assert "英语单词今日任务已明确完成" in context, context
    if int(status.get("remaining_words") or 0) > 0:
        assert "这不代表原任务没做完" in context, context
        assert "禁止据此继续催促" in context, context
    else:
        assert "当前待复习0个" in context, context
    assert "优先于昨日日记和聊天历史" in context, context
    assert "禁止再追问背完没有" in context, context


def verify_send_guard(status: dict) -> None:
    """旧数字催促要被纠正，正确的完成陈述和无关内容保持原样。"""
    stale = "背单词背得怎么样了？34个呢，别又拖到半夜。"
    corrected = enforce_vocabulary_status(stale, status)
    assert "已经背完" in corrected, corrected
    if int(status.get("unresolved_words") or 0) > 0:
        assert "没掌握" in corrected, corrected
    assert "34" not in corrected, corrected

    valid = "今天复习了2个单词，辛苦啦。"
    assert enforce_vocabulary_status(valid, status) == valid

    unrelated = "今天写代码写得怎么样了？"
    assert enforce_vocabulary_status(unrelated, status) == unrelated

    incomplete = {
        "completed": False,
        "remaining_words": 67,
        "unresolved_words": 0,
    }
    pending = enforce_vocabulary_status("34个单词今天背完没。", incomplete)
    assert pending == "67个单词今天背完没。", pending


def main() -> int:
    status = verify_realtime_status()
    verify_prompt_anchor(status)
    verify_send_guard(status)
    dynamic_status = verify_explicit_completion_wins_over_dynamic_queue()
    verify_prompt_anchor(dynamic_status)
    verify_send_guard(dynamic_status)
    print("PASS: Active Care 使用实时词汇完成态，并拦截旧数量催促")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
