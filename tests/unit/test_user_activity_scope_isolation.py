# -*- coding: utf-8 -*-
"""单元测试：用户活跃判定必须按角色隔离。

回归 2026-09-18 的事故：用户一整天在跟 aveline 聊天，ling 却在
08:01:02 / 09:37:55 两次主动发「要上课了先回去了」——因为
``_is_user_in_conversation`` 遍历了全局活跃表，任一角色活跃就让所有角色
判成「用户正在聊天」。

详见 docs/important/ACTIVE_CARE_REPLY_CONTINUITY_PLAN.md R6。
"""

from __future__ import annotations

import time

import pytest

from core.services.active_care.peer_chat.user_activity import (
    UserActivityTracker,
    resolve_role_scope,
)


class _FakeStorage:
    """不碰真实磁盘的假 storage。"""

    def __init__(self) -> None:
        self.state: dict = {}

    async def save_proactive_state(self, updates, immediate=False, scope=None):  # noqa: ANN001
        self.state.update(updates)
        return self.state

    async def get_proactive_state(self, scope=None):  # noqa: ANN001
        return dict(self.state)


def _tracker(**kwargs) -> UserActivityTracker:
    return UserActivityTracker(_FakeStorage(), **kwargs)


def test_other_role_activity_does_not_leak():
    """用户在跟 aveline 聊天，ling 不能被判成「用户正在聊天」。"""
    tracker = _tracker()
    tracker._activity_ts["web_role_aveline"] = time.time()

    assert tracker.is_active_for_scope("aveline", 300.0) is True
    assert tracker.is_active_for_scope("ling", 300.0) is False


def test_same_role_activity_detected():
    """用户确实在跟 ling 聊天时要能判出来。"""
    tracker = _tracker()
    tracker._activity_ts["web_role_ling"] = time.time()

    assert tracker.is_active_for_scope("ling", 300.0) is True
    assert tracker.is_active_for_scope("aveline", 300.0) is False


@pytest.mark.parametrize(
    "cid",
    [
        "web_role_ling",
        "shared__persona__core_ling",
        "private_1__persona__core_ling",
        "shared__scope__ling",
    ],
)
def test_all_cid_forms_resolve_to_same_role(cid):
    """四种会话 ID 形态都要归到 ling。"""
    tracker = _tracker()
    tracker._activity_ts[cid] = time.time()

    assert tracker.is_active_for_scope("ling", 300.0) is True


@pytest.mark.parametrize("cid", ["group_123456", "web_role_3f2a1b9c"])
def test_unresolvable_cid_counts_for_nobody(cid):
    """群聊 / 哈希兜底会话不归任何角色（宁可少发，也不能串角色）。"""
    tracker = _tracker()
    tracker._activity_ts[cid] = time.time()

    assert tracker.is_active_for_scope("ling", 300.0) is False
    assert tracker.is_active_for_scope("aveline", 300.0) is False


def test_window_boundary_and_empty_scope():
    """窗口边界；scope 为空时不做全局兜底。"""
    tracker = _tracker()

    tracker._activity_ts["web_role_ling"] = time.time() - 299.0
    assert tracker.is_active_for_scope("ling", 300.0) is True

    tracker._activity_ts["web_role_ling"] = time.time() - 301.0
    assert tracker.is_active_for_scope("ling", 300.0) is False

    tracker._activity_ts["web_role_ling"] = time.time()
    assert tracker.is_active_for_scope("", 300.0) is False


def test_is_active_anywhere_keeps_global_semantics():
    """全局判定保留给 AI 间互聊门禁，不能因为按角色过滤而被一起砍掉。"""
    tracker = _tracker()
    tracker._activity_ts["web_role_aveline"] = time.time()

    assert tracker.is_active_anywhere(300.0) is True

    tracker._activity_ts["web_role_aveline"] = time.time() - 400
    assert tracker.is_active_anywhere(300.0) is False


def test_activity_transition_delegates_with_role():
    """告别消息判定走按角色过滤，role_id 为空时不退回全局遍历。"""
    from core.services.character_daily.activity_transition import _is_user_in_conversation

    tracker = _tracker()
    tracker._activity_ts["web_role_aveline"] = time.time()

    class _Stub:
        def is_user_recently_active_for_scope(self, scope, window_seconds):
            return tracker.is_active_for_scope(scope, window_seconds)

    stub = _Stub()
    assert _is_user_in_conversation(stub, 300.0, "ling") is False
    assert _is_user_in_conversation(stub, 300.0, "aveline") is True
    assert _is_user_in_conversation(stub, 300.0, "") is False
    assert _is_user_in_conversation(None, 300.0, "ling") is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ling", "ling"),
        ("core_ling", "ling"),
        ("web_role_ling", "ling"),
        ("shared__persona__core_ling", "ling"),
        ("aveline", "aveline"),
        ("core_aveline.json", "aveline"),
    ],
)
def test_resolve_role_scope(raw, expected):
    assert resolve_role_scope(raw) == expected
