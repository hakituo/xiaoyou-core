"""背单词系统回归保护。

通用教学系统（ConceptState / LearningEvent / TeachingOrchestrator）不得触碰
``VocabularyManager -> FSRS/SM-2 -> vocab_progress`` 这条成熟主链。
本文件用「接口存在性 + 行为快照 + 依赖隔离」三层守住这条边界。
"""
from __future__ import annotations

import inspect

from core.services.study.dispatch import ToolDispatcher
from core.services.study.service import StudyService
from core.services.study.session import StudySession


# ----------------------------------------------------------------------
# 1. 单词统计口径不变
# ----------------------------------------------------------------------


def test_word_session_accuracy_is_per_word_not_per_rating():
    """同一单词重复评分不能撑大分母（8/30 正确率被低估的历史问题）。"""
    session = StudySession()
    session.start()
    session.record_word_review("apple", 1)   # Again
    session.record_word_review("apple", 3)   # Good
    session.record_word_review("banana", 4)  # Easy

    stats = session.get_stats()

    assert stats["words_total"] == 2
    assert stats["words_mastered"] == 2
    assert stats["accuracy"] == 100.0
    # 评分次数口径仍单独保留，不参与 accuracy
    assert stats["review_events"] == 3


def test_word_session_end_reports_same_accuracy_as_stats():
    session = StudySession()
    session.start()
    session.record_word_review("apple", 1)
    session.record_word_review("banana", 4)

    stats = session.get_stats()
    ended = session.end()

    assert ended["words_total"] == stats["words_total"] == 2
    assert ended["words_mastered"] == stats["words_mastered"] == 1
    assert ended["accuracy"] == stats["accuracy"] == 50.0


def test_word_session_idle_timeout_still_flushes(monkeypatch):
    """空闲超时仍要把旧会话交回调用方落盘，不能静默丢数据。"""
    session = StudySession()
    session.start()
    session.record_word_review("apple", 3)

    monkeypatch.setattr(session, "_is_expired", lambda: True)
    expired = session.record_word_review("banana", 4)

    assert expired is not None
    assert expired["words_total"] == 1


# ----------------------------------------------------------------------
# 2. StudyService 的词汇公共接口保持稳定
# ----------------------------------------------------------------------


def test_study_service_vocabulary_api_is_intact():
    service = StudyService()
    for name in (
        "get_daily_words",
        "get_new_words",
        "submit_word_review",
        "get_review_overview",
        "get_memory_curve_data",
        "search_dictionary",
        "get_word_list",
        "get_dictionary_stats",
        "switch_vocabulary",
        "add_to_learning",
        "get_mistakes",
        "add_manual_study",
        "get_manual_study_stats",
        "generate_comprehensive_study_plan",
        "get_study_daily_digest",
        "list_tools",
        "run_tool",
        "start_session",
        "end_session",
        "get_session_stats",
    ):
        assert callable(getattr(service, name, None)), f"StudyService 缺少公共接口: {name}"


def test_tool_dispatcher_still_routes_vocabulary_tools():
    class _DummyService:
        base_dir = "."
        vocab_manager = None

    dispatcher = ToolDispatcher(_DummyService())
    assert ("english", "word_quiz") in dispatcher._handlers
    assert ("study_data", "manage") in dispatcher._handlers


# ----------------------------------------------------------------------
# 3. 依赖隔离：教学系统不 import 词库实现
# ----------------------------------------------------------------------


def test_teaching_modules_do_not_depend_on_vocabulary_stack():
    from core.services.study import (
        concept_state,
        evaluation,
        learning_event,
        signal_detector,
        teaching_orchestrator,
    )

    forbidden = ("vocabulary_manager", "fsrs_scheduler", "vocab_progress", "daily_word_log")
    for module in (
        concept_state,
        learning_event,
        evaluation,
        signal_detector,
        teaching_orchestrator,
    ):
        source = inspect.getsource(module)
        for token in forbidden:
            assert token not in source, f"{module.__name__} 不应依赖词库实现: {token}"


def test_teaching_state_files_are_separate_from_vocab_progress(study_sandbox):
    """教学系统的状态文件与词库进度文件必须物理隔离。"""
    from core.services.study.teaching_orchestrator import TeachingOrchestrator

    orch = TeachingOrchestrator()
    orch.record_answer("math", "导数", {"correctness": 0.9, "independent": True})

    state_dir = study_sandbox / ".state"
    assert (state_dir / "concepts.json").exists()

    # 词库进度不属于教学系统状态目录
    assert not (state_dir / "vocab_progress.json").exists()
    assert not (study_sandbox / "vocab_progress.json").exists()


def test_fsrs_scheduler_import_path_is_unchanged():
    from core.tools.study.english.fsrs_scheduler import (  # noqa: F401
        create_daily_scheduler,
        quality_to_rating,
    )
    from core.tools.study.english.vocabulary_manager import (  # noqa: F401
        get_vocabulary_manager,
    )

    assert callable(get_vocabulary_manager)
    assert callable(create_daily_scheduler)
    assert callable(quality_to_rating)
