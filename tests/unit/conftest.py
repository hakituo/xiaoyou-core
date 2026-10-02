"""tests/unit 共享 fixture。

``study_sandbox`` 把学习系统全部本地状态隔离到 pytest 的临时目录，
避免测试污染用户真实的 ``D:\\AI\\Study``（含背单词进度、薄弱点、每日记录）。
"""
from __future__ import annotations

import pytest


def _reset_singletons() -> None:
    """重置学习系统全部单例，避免跨用例复用上一个沙箱的路径与内存状态。"""
    from core.services.study import (
        concept_state,
        daily_tracker,
        learning_event,
        resources,
        student_state,
        study_library,
        subject_registry,
        teaching_orchestrator,
        weakness_tracker,
    )

    concept_state.ConceptStateManager._instance = None
    learning_event.LearningEventStore._instance = None
    resources.ResourceRegistry._instance = None
    weakness_tracker.WeaknessTracker._instance = None
    student_state.StudentStateManager._instance = None
    teaching_orchestrator.TeachingOrchestrator._instance = None
    subject_registry._registry = None
    study_library.StudyLibraryIndex._instance = None

    # 每日总结调度入口的进程内补写状态（按日期去重）
    from core.services.journal import daily_summary_dispatch

    daily_summary_dispatch.reset_backfill_state()

    dt = daily_tracker.DailyTracker
    if dt._instance is not None:
        dt._instance._cache.clear()
    dt._instance = None


@pytest.fixture(autouse=True)
def _reset_current_channel():
    """还原「当前渠道」ContextVar。

    ``ChatAgent.stream_chat`` 会按 platform 设置它；pytest 用例共用同一个 context，
    不还原就会把上一个用例的渠道带进下一个（表现为历史消息凭空多出「（来自QQ）」）。
    """
    from core.utils.data.chat_channel import reset_current_platform, set_current_platform

    token = set_current_platform("")
    yield
    reset_current_platform(token)


@pytest.fixture()
def study_sandbox(tmp_path, monkeypatch):
    """把学习系统状态根目录指向临时目录，并重置相关单例。"""
    from core.services.study import paths

    root = tmp_path / "study"
    (root / ".state").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "get_study_root", lambda: root)

    _reset_singletons()
    yield root
    _reset_singletons()
