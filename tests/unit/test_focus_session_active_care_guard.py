# -*- coding: utf-8 -*-
"""正式 FocusSession 与 Active Care 的边界测试。"""

from core.services.active_care.cadence.cadence_guard import CadenceGuard


def test_formal_focus_session_blocks_general_active_care(monkeypatch):
    guard = CadenceGuard(settings=object())
    monkeypatch.setattr(
        CadenceGuard,
        "_formal_focus_session_active",
        staticmethod(lambda: True),
    )

    verdict = guard.evaluate(
        now=1000.0,
        chosen_action="share_thought",
        proactive_state={},
    )

    assert verdict.allowed is False
    assert verdict.reason == "formal_focus_session_active"


def test_formal_focus_session_keeps_hard_events_available(monkeypatch):
    guard = CadenceGuard(settings=object())
    monkeypatch.setattr(
        CadenceGuard,
        "_formal_focus_session_active",
        staticmethod(lambda: True),
    )

    for intent in ("reminder", "notification_assistant", "focus_nudge"):
        verdict = guard.evaluate(
            now=1000.0,
            chosen_action=intent,
            proactive_state={},
        )
        assert verdict.allowed is True, intent


def test_manual_focus_policy_is_unchanged_without_formal_session(monkeypatch):
    """没有正式 FocusSession 时，本守卫不替代原 reduced_mode=focus 软策略。"""
    guard = CadenceGuard(settings=object())
    monkeypatch.setattr(
        CadenceGuard,
        "_formal_focus_session_active",
        staticmethod(lambda: False),
    )

    verdict = guard.evaluate(
        now=1000.0,
        chosen_action="share_thought",
        proactive_state={},
    )

    assert verdict.allowed is True
