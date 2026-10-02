"""主动关怀的人设、历史和消息归档必须属于同一角色。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.services.active_care.core import conversation_resolver as cr
from core.services.active_care.core.conversation_router import ConversationRouter
from core.services.active_care.core.trigger_preparer import TriggerPreparer


@pytest.fixture
def role_storage(monkeypatch):
    monkeypatch.setattr(cr.time, "time", lambda: 1000.0)
    monkeypatch.setattr(cr, "_candidate_cids_cache", [])
    monkeypatch.setattr(cr, "_candidate_cids_cache_ts", 0.0)
    monkeypatch.setattr(cr, "_primary_cid_cache_dict", {})
    for name in (
        "get_active_conversation_ids_from_ws",
        "get_recent_conversation_ids_from_session_manager",
        "get_recent_conversation_ids_from_chat_history",
    ):
        monkeypatch.setattr(cr, name, AsyncMock(return_value=[]))
    monkeypatch.setattr(cr, "get_current_persona_token", lambda: "core_aveline")
    return SimpleNamespace(_recent_user_message_cache={
        "web_role_ling": {"timestamp": 100, "content": "Ling自己的对话"},
        "web_role_ye": {"timestamp": 200, "content": "叶自己的对话"},
        "web_role_aveline": {"timestamp": 300, "content": "只有Aveline听过的早餐细节"},
        "mobile_user": {"timestamp": 400, "content": "共用投递地址"},
    })


@pytest.mark.parametrize("cid", [
    "web_role_ling", "web_core_ling.json", "shared__persona__core_ling",
    "private_10001__persona__core_ling", "shared__scope__ling",
])
def test_role_aliases_match_current_persona(cid):
    assert cr.is_candidate_matching_current_persona(cid, "core_ling")
    assert not cr.is_candidate_matching_current_persona(cid, "core_aveline")


async def test_candidate_cache_is_filtered_for_each_role(role_storage):
    for role in ("aveline", "ling", "ye", "ling"):
        assert await cr.get_candidate_conversation_ids(role_storage, f"core_{role}.json") == [f"web_role_{role}"]
        assert await cr.resolve_primary_conversation_id(role_storage, f"core_{role}.json") == f"web_role_{role}"


async def test_no_matching_history_uses_own_shared_conversation(role_storage):
    del role_storage._recent_user_message_cache["web_role_ling"]
    assert await cr.get_candidate_conversation_ids(role_storage, "core_ling.json") == []
    assert await cr.resolve_primary_conversation_id(role_storage, "core_ling.json") == "shared__persona__core_ling"


async def test_default_persona_cache_tracks_current_role(role_storage, monkeypatch):
    assert await cr.resolve_primary_conversation_id(role_storage) == "web_role_aveline"
    monkeypatch.setattr(cr, "get_current_persona_token", lambda: "core_ling")
    assert await cr.resolve_primary_conversation_id(role_storage) == "web_role_ling"


async def test_qq_keeps_role_history_and_transport_address_separate():
    resolve = AsyncMock(return_value="web_role_ling")
    executor = SimpleNamespace(
        context=SimpleNamespace(resolve_primary_conversation_id=resolve),
        qq_connection_resolver=SimpleNamespace(get_first_user_id=lambda: "private_10001"),
        storage=SimpleNamespace(
            resolve_scope_from_conversation_id=lambda cid: "ling", set_runtime_scope=lambda scope: None,
        ),
    )
    target, original, client = await ConversationRouter(executor).resolve_target_conversation("qq", "core_ling.json")
    assert (target, original, client) == ("shared__persona__core_ling", "private_10001", "qq")
    resolve.assert_awaited_once_with(persona_filename="core_ling.json")


async def test_trigger_reads_history_for_the_generating_role(role_storage):
    async def resolve(persona_filename=""):
        return await cr.resolve_primary_conversation_id(role_storage, persona_filename)

    seen = []

    async def history(cid, now):
        seen.append(cid)
        return [role_storage._recent_user_message_cache[cid]]

    async def build_context(messages, cid, *args):
        return {"history": messages, "conversation_id": cid}

    executor = SimpleNamespace(
        context=SimpleNamespace(resolve_primary_conversation_id=resolve),
        storage=SimpleNamespace(
            resolve_scope_from_conversation_id=lambda cid: cid.removeprefix("web_role_"),
            set_runtime_scope=lambda scope: seen.append(scope),
        ),
        _morning_pending=SimpleNamespace(inject=lambda *args: ("", [])),
        _context_builder=SimpleNamespace(
            get_history_with_cache=history, build_trigger_context=build_context,
            build_prompt=lambda *args: (SimpleNamespace(prompt="身份", dynamic_prompt=""), "提示"),
        ),
    )
    executor._conversation_router = ConversationRouter(executor)
    prepared = await TriggerPreparer(executor).prepare(
        sys_prompt_type="user_health_reminder", user_input_mock="早餐提醒",
        reminder_msg=None, thought=None, device_context=None, client_type="websocket",
        specific_instruction=None, persona_filename="core_ling.json", now=1000.0,
    )
    assert prepared.target_conversation_id == "web_role_ling"
    assert prepared.original_conversation_id == "web_role_ling"
    assert seen == ["ling", "web_role_ling"]
    assert prepared.context["history"][0]["content"] == "Ling自己的对话"
