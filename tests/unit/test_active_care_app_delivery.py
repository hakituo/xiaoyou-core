"""Active Care 主动消息对手机 App / Web 客户端的补投。

回归背景：手机 App 连接时上报的 user_id（默认 mobile_user）与 QQ 传输端
的 user_id（private_<QQ号>）不在同一命名空间。主动消息一直只按主人 uid
广播，App 连接永远匹配不到，消息落进 App 不会来清空的离线队列，表现为
"后端日志显示已送达，但手机一条 active care 都收不到"（含角色睡回去的
告别消息）。
"""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from core.services.active_care.core import conversation_resolver as cr


def _conn(user_id: str, platform: str = "unknown", client_id: str = ""):
    return SimpleNamespace(
        user_id=user_id,
        platform=platform,
        client_id=client_id,
        websocket=None,
    )


def _ws_manager(connections):
    def _is_online(uid: str) -> bool:
        return any(c.user_id == uid for c in connections)

    return SimpleNamespace(
        connections={id(c): c for c in connections},
        is_user_online=_is_online,
    )


@pytest.mark.asyncio
async def test_app_client_uids_exclude_qq_transport(monkeypatch):
    """App/Web 客户端要被识别出来，QQ 传输端不能混进来（避免重复投递）。"""
    monkeypatch.setattr(cr, "APP_DELIVERY_ENABLED", True)
    manager = _ws_manager(
        [
            _conn("mobile_user"),
            _conn("private_10001", platform="qq"),
            _conn("shared__persona__aveline"),
            _conn("user_ab12", platform="web"),
        ]
    )

    with patch(
        "core.interfaces.websocket.websocket_manager.get_websocket_manager",
        return_value=manager,
    ):
        uids = cr.get_online_app_client_user_ids(exclude="private_10001")

    assert uids == ["mobile_user", "user_ab12"]


@pytest.mark.asyncio
async def test_app_client_uids_skip_client_id_prefixed_qq(monkeypatch):
    """带 qq_ 前缀 client_id 的连接属于 QQ 传输端，即使 uid 看起来像 App。"""
    monkeypatch.setattr(cr, "APP_DELIVERY_ENABLED", True)
    manager = _ws_manager([_conn("mobile_user", client_id="qq_aveline_1")])

    with patch(
        "core.interfaces.websocket.websocket_manager.get_websocket_manager",
        return_value=manager,
    ):
        assert cr.get_online_app_client_user_ids() == []


@pytest.mark.asyncio
async def test_app_client_uids_respects_switch(monkeypatch):
    """开关关闭时退回"只投 QQ"，不返回任何 App 客户端。"""
    monkeypatch.setattr(cr, "APP_DELIVERY_ENABLED", False)
    manager = _ws_manager([_conn("mobile_user")])

    with patch(
        "core.interfaces.websocket.websocket_manager.get_websocket_manager",
        return_value=manager,
    ):
        assert cr.get_online_app_client_user_ids() == []


@pytest.mark.asyncio
async def test_find_online_primary_can_fall_back_to_app_uid(monkeypatch):
    """主会话是 persona 抽象会话且离线时，App 客户端可作为投递目标。"""
    monkeypatch.setattr(cr, "APP_DELIVERY_ENABLED", True)
    manager = _ws_manager([_conn("mobile_user")])
    candidates = ["private_10001__persona__core_aveline", "mobile_user"]

    with patch(
        "core.interfaces.websocket.websocket_manager.get_websocket_manager",
        return_value=manager,
    ):
        fallback = cr._find_online_primary_for_persona(
            candidates, "private_10001__persona__core_aveline", "aveline"
        )

    assert fallback == "mobile_user"


@pytest.mark.asyncio
async def test_dispatch_proactive_message_replays_to_app_client(monkeypatch):
    """主动消息除主广播外，必须补投一份给在线的 App 客户端。"""
    from core.services.aveline import proactive_messaging

    monkeypatch.setattr(cr, "APP_DELIVERY_ENABLED", True)
    sent = []

    async def _broadcast(payload, user_id=None, **_kwargs):
        sent.append((user_id, dict(payload)))
        return True

    manager = SimpleNamespace(
        connections={
            "app": _conn("mobile_user"),
        },
        is_user_online=lambda uid: uid == "mobile_user",
        broadcast=AsyncMock(side_effect=_broadcast),
    )
    service = SimpleNamespace(
        append_proactive_message=AsyncMock(return_value=None),
    )

    with patch(
        "core.interfaces.websocket.websocket_manager.get_websocket_manager",
        return_value=manager,
    ):
        result = await proactive_messaging.dispatch_proactive_message(
            service,
            target_conversation_id="private_10001__persona__core_aveline",
            content="我先去睡啦",
            client_type="qq",
            original_primary_conversation_id="private_10001",
        )

    assert result["delivered"] is True
    targets = [uid for uid, _ in sent]
    assert targets == ["private_10001", "mobile_user"]

    app_payload = sent[-1][1]
    # client_type 改为 app 以绕开 QQ 角色定向过滤，否则 App 连接会被过滤掉
    assert app_payload["client_type"] == "app"
    assert app_payload["content"] == "我先去睡啦"


@pytest.mark.asyncio
async def test_dispatch_message_carries_persona_filename():
    """人设文件名必须随 payload 下发，App 靠它把消息归档到对应角色会话。"""
    from datetime import datetime

    from core.services.active_care.core.message_dispatcher import MessageDispatcher

    from core.services.active_care.core.executor import ActiveCareExecutor

    executor = ActiveCareExecutor.__new__(ActiveCareExecutor)
    # 用 __new__ 绕过 __init__ 造桩，需自行补上 dispatch 路径会读的属性；
    # consecutive_non_responses 由 ActiveCareExecutor.__init__ 初始化（per-persona 计数）。
    executor.consecutive_non_responses = {}
    executor.hardware_intent_resolver = SimpleNamespace(
        determine=lambda *_a, **_k: SimpleNamespace(to_dict=lambda: {})
    )
    executor.state_persistence = SimpleNamespace(
        persist_proactive_message=AsyncMock(return_value=None)
    )
    executor.storage = SimpleNamespace(
        increment_proactive_count=AsyncMock(return_value=None)
    )

    aveline_service = SimpleNamespace(
        dispatch_proactive_message=AsyncMock(return_value={"delivered": True})
    )

    delivered = await MessageDispatcher(executor).dispatch_message(
        aveline_service,
        {"content": "困了，我先继续睡啦", "tts_text": "困了，我先继续睡啦", "message_type": "text"},
        "sleep_again_proactive",
        None,
        "private_10001__persona__core_aveline",
        "private_10001",
        "qq",
        "qq",
        "thought",
        {"proactive_state": {}},
        time.time(),
        datetime.now(),
        persona_filename="core_aveline.json",
    )

    assert delivered is True
    kwargs = aveline_service.dispatch_proactive_message.await_args.kwargs
    extra = kwargs["extra_payload"] or {}
    assert extra.get("persona_filename") == "core_aveline.json"
    # 角色显示名随 payload 下发（测试环境无注册表数据时允许为空串）
    assert "role_name" in extra and isinstance(extra["role_name"], str)
