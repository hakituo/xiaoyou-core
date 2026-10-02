"""日记角色 = 注册角色：链路不再硬编码 aveline / ling。"""
from __future__ import annotations

import asyncio
from unittest import mock

import pytest

from core.services.journal.journal_helpers import (
    build_daily_summary_messages,
    format_chat_context,
    format_peer_chat_context,
)


@pytest.fixture
def registered_roles(monkeypatch):
    """把注册角色固定成 aveline + ye（当前 character_runtime.yaml 的内容）。"""
    monkeypatch.setattr(
        "core.character.runtime_roles.get_autonomous_role_ids",
        lambda **_kwargs: frozenset({"aveline", "ye"}),
    )
    return ("aveline", "ye")


def test_diary_personas_come_from_registry(registered_roles):
    from core.services.journal.diary_personas import (
        get_diary_persona_ids,
        get_diary_persona_names,
        is_diary_persona,
    )

    assert get_diary_persona_ids() == registered_roles
    # 角色名统一为无空格的权威名；带空格的「七濑 Aveline」是历史写法，归一化后等价。
    assert get_diary_persona_names() == ("Aveline", "Ye")
    assert is_diary_persona("ye")
    assert not is_diary_persona("ling")  # 未注册的角色不写日记


def test_registry_change_is_picked_up(monkeypatch):
    monkeypatch.setattr(
        "core.character.runtime_roles.get_autonomous_role_ids",
        lambda **_kwargs: frozenset({"ling"}),
    )
    from core.services.journal.diary_personas import get_diary_persona_ids

    assert get_diary_persona_ids() == ("ling",)


def test_each_registered_role_has_its_own_diary_prompt(registered_roles):
    kwargs = dict(
        date_str="2026-09-22",
        diary_context="手记",
        chat_context="直接聊天",
        active_care_context="主动行为",
        user_status_summary="状态",
        study_context="学习",
        daily_context="生活",
        peer_chat_context="室友互动",
        user_diary_context="主人日记",
        character_daily_context="角色节奏",
    )
    aveline = build_daily_summary_messages(**kwargs, persona="aveline")
    ye = build_daily_summary_messages(**kwargs, persona="ye")

    assert aveline[0]["content"] != ye[0]["content"]
    assert "Aveline" in aveline[0]["content"]
    assert "Ye" in ye[0]["content"]
    assert "Ling" not in ye[0]["content"]


def test_unregistered_role_does_not_fall_back_to_another_voice(monkeypatch):
    """注册了但没有专属 prompt 的角色：用通用模板 + 自己的名字，不串别人的语气。"""
    monkeypatch.setattr(
        "core.character.runtime_roles.get_autonomous_role_ids",
        lambda **_kwargs: frozenset({"rushuang"}),
    )
    messages = build_daily_summary_messages(
        date_str="2026-09-22",
        diary_context="手记",
        chat_context="直接聊天",
        active_care_context="主动行为",
        user_status_summary="状态",
        study_context="学习",
        daily_context="生活",
        persona="rushuang",
    )
    system = messages[0]["content"]
    assert "Frost" in system
    assert "Aveline" not in system and "Ling" not in system


def test_chat_context_labels_follow_persona(registered_roles):
    rows = [{"timestamp": 0.0, "role": "user", "content": "在吗"}]

    aveline_text = format_chat_context(rows, persona="aveline")
    assert "[--:--:--] 用户: 在吗" in aveline_text

    ye_text = format_chat_context(rows, persona="ye")
    assert "[--:--:--] 主人: 在吗" in ye_text


def test_peer_context_only_for_roles_with_registered_relation(monkeypatch):
    """没有互识关系的角色（Ye）不该看到别人的互聊记录。"""
    monkeypatch.setattr(
        "core.character.runtime_roles.get_autonomous_role_ids",
        lambda **_kwargs: frozenset({"aveline", "ling"}),
    )
    peer_rows = [{"timestamp": 0.0, "role": "user", "content": "Aveline"}]

    assert format_peer_chat_context(peer_rows, persona="aveline") != ""
    monkeypatch.setattr(
        "core.character.runtime_roles.get_autonomous_role_ids",
        lambda **_kwargs: frozenset({"aveline", "ye"}),
    )
    assert format_peer_chat_context(peer_rows, persona="ye") == ""


def test_nightly_generates_diary_for_every_registered_role(registered_roles):
    from memory.nightly.global_tasks import NightlyGlobalTaskService

    calls: list[str] = []

    class _FakeSummary:
        summary = "角色自己的日记正文"
        stats: dict = {}

    class _FakeJournal:
        async def generate_daily_summary(self, date_str, force=False, persona="aveline", distinct_from=None):
            calls.append(persona)
            return _FakeSummary()

        async def get_plan(self, _date):
            return None

    import datetime

    results: dict = {}

    async def run() -> None:
        service = NightlyGlobalTaskService()
        with mock.patch(
            "core.services.journal.service.get_journal_service",
            return_value=_FakeJournal(),
        ), mock.patch(
            "memory.nightly.global_tasks.is_valid_daily_summary_obj",
            return_value=True,
        ), mock.patch.object(
            NightlyGlobalTaskService,
            "_ensure_diary_file",
            staticmethod(lambda _d: None),
        ), mock.patch.object(
            NightlyGlobalTaskService,
            "_mark_roles_nightly_done",
            staticmethod(lambda _d, _r: None),
        ), mock.patch.object(
            NightlyGlobalTaskService,
            "_review_digital_wellbeing",
            staticmethod(lambda *_a: None),
        ), mock.patch.object(
            NightlyGlobalTaskService,
            "_generate_next_day_plan",
            new=mock.AsyncMock(return_value=None),
        ):
            await service._run_journal_plan_and_wellbeing(
                datetime.date(2026, 9, 22), results
            )

    asyncio.run(run())

    assert calls == ["aveline", "ye"]
    assert "ling" not in calls
    assert results["aveline_daily_summary"] is True
    assert results["ye_daily_summary"] is True
    assert results["daily_summary"] is True
    assert results["diary_personas"] == ["aveline", "ye"]
