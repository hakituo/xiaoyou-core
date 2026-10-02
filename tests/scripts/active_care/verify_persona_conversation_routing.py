"""离线验证 App 主动消息按角色选会话，无模型调用或消息投递。"""

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.services.active_care.core import conversation_resolver as cr
from core.services.active_care.core.conversation_router import ConversationRouter


async def verify():
    storage = SimpleNamespace(_recent_user_message_cache={
        "web_role_aveline": {"timestamp": 300},
        "web_role_ling": {"timestamp": 100},
    })

    async def resolve(persona_filename=""):
        return await cr.resolve_primary_conversation_id(storage, persona_filename)

    storage.resolve_scope_from_conversation_id = lambda cid: cid.removeprefix("web_role_")
    storage.set_runtime_scope = lambda _scope: None
    router = ConversationRouter(SimpleNamespace(
        storage=storage, context=SimpleNamespace(resolve_primary_conversation_id=resolve),
    ))
    with patch.object(cr, "_candidate_cids_cache", []), patch.object(
        cr, "_candidate_cids_cache_ts", 0.0,
    ), patch.object(cr, "_primary_cid_cache_dict", {}), patch.object(
        cr, "get_active_conversation_ids_from_ws", AsyncMock(return_value=[]),
    ), patch.object(cr, "get_recent_conversation_ids_from_session_manager", AsyncMock(return_value=[])), patch.object(
        cr, "get_recent_conversation_ids_from_chat_history", AsyncMock(return_value=[]),
    ), patch.object(cr, "get_current_persona_token", return_value="core_aveline"):
        for role in ("aveline", "ling", "ling"):
            target, original, _ = await router.resolve_target_conversation("websocket", f"core_{role}.json")
            assert target == original == f"web_role_{role}"
            print(f"PASS: {role} 使用自己的历史和归档，缓存命中也不串角色")


if __name__ == "__main__":
    asyncio.run(verify())
