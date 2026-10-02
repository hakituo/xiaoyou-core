"""验证手机 App 端能收到 Active Care 主动消息（含角色睡回去告别）。

回归场景：把角色叫醒后她又睡回去，后端生成并"已送达"了告别消息，
但安卓端一条通知都没有。

根因：App 连接注册的 user_id（默认 mobile_user）与 QQ 传输端的
user_id（private_<QQ号>）不属于同一命名空间，主动消息只按主人 uid
广播时 App 永远匹配不上，消息落进 App 不会来清空的离线队列。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings_life import LifeSimulationSettings  # noqa: E402
from core.services.active_care.core import conversation_resolver as cr  # noqa: E402
from core.services.aveline import proactive_messaging  # noqa: E402


def _conn(user_id: str, platform: str = "unknown", client_id: str = ""):
    return SimpleNamespace(
        user_id=user_id,
        platform=platform,
        client_id=client_id,
        websocket=None,
    )


def verify_app_delivery_switch_default() -> None:
    """App 投递开关默认开启，且能在 app.yaml 里被显式关掉。"""
    field = LifeSimulationSettings.model_fields["active_care_app_delivery_enabled"]
    assert field.default is True, "App 端投递必须默认开启"

    assert cr.APP_DELIVERY_ENABLED is True, (
        "conversation_resolver 未开启 App 投递，主动消息仍只走 QQ"
    )


def verify_app_uids_picked_up() -> None:
    """App 客户端要被识别为投递目标，QQ 传输端不能重复投递。"""
    connections = [
        _conn("mobile_user"),
        _conn("private_10001", platform="qq"),
        _conn("shared__persona__aveline"),
    ]
    manager = SimpleNamespace(
        connections={id(c): c for c in connections},
        is_user_online=lambda uid: any(c.user_id == uid for c in connections),
    )

    with patch(
        "core.interfaces.websocket.websocket_manager.get_websocket_manager",
        return_value=manager,
    ):
        uids = cr.get_online_app_client_user_ids(exclude="private_10001")

    assert uids == ["mobile_user"], uids


async def verify_sleep_again_reaches_app() -> None:
    """角色睡回去的告别消息，在 QQ 与 App 同时在线时要两边都收到。"""
    sent: list[tuple[str, dict]] = []

    async def _broadcast(payload, user_id=None, **_kwargs):
        sent.append((str(user_id), dict(payload)))
        return True

    connections = [_conn("mobile_user")]
    manager = SimpleNamespace(
        connections={id(c): c for c in connections},
        is_user_online=lambda uid: uid in {"mobile_user", "private_10001"},
        broadcast=AsyncMock(side_effect=_broadcast),
    )
    service = SimpleNamespace(append_proactive_message=AsyncMock(return_value=None))

    with patch(
        "core.interfaces.websocket.websocket_manager.get_websocket_manager",
        return_value=manager,
    ):
        result = await proactive_messaging.dispatch_proactive_message(
            service,
            target_conversation_id="private_10001__persona__core_aveline",
            content="困了，我先继续睡啦",
            client_type="qq",
            original_primary_conversation_id="private_10001",
            extra_payload={"persona_filename": "core_aveline.json"},
        )

    assert result["delivered"] is True
    targets = [uid for uid, _ in sent]
    assert "private_10001" in targets, "QQ 主广播丢失"
    assert "mobile_user" in targets, "App 客户端没收到睡回去消息"

    app_payload = next(p for uid, p in sent if uid == "mobile_user")
    assert app_payload["type"] == "proactive_message"
    assert app_payload["content"] == "困了，我先继续睡啦"
    # client_type=app 用于绕开 QQ 角色定向过滤，否则 App 连接会被过滤掉
    assert app_payload["client_type"] == "app"
    # App 靠 persona_filename 归档到 web_{persona_filename} 会话，缺了就上不了屏
    assert app_payload["persona_filename"] == "core_aveline.json"


async def verify_dispatcher_carries_persona_filename() -> None:
    """分发层必须把 persona_filename 塞进 extra_payload 随消息下发。"""
    from datetime import datetime

    from core.services.active_care.core.executor import ActiveCareExecutor
    from core.services.active_care.core.message_dispatcher import MessageDispatcher

    executor = ActiveCareExecutor.__new__(ActiveCareExecutor)
    executor.hardware_intent_resolver = SimpleNamespace(
        determine=lambda *_a, **_k: SimpleNamespace(to_dict=lambda: {})
    )
    executor.state_persistence = SimpleNamespace(
        persist_proactive_message=AsyncMock(return_value=None)
    )
    executor.storage = SimpleNamespace(
        increment_proactive_count=AsyncMock(return_value=None)
    )
    service = SimpleNamespace(
        dispatch_proactive_message=AsyncMock(return_value={"delivered": True})
    )

    delivered = await MessageDispatcher(executor).dispatch_message(
        service,
        {"content": "困了，我先继续睡啦", "tts_text": "困了，我先继续睡啦", "message_type": "text"},
        "sleep_again_proactive",
        None,
        "private_10001__persona__core_aveline",
        "private_10001",
        "qq",
        "qq",
        "thought",
        {"proactive_state": {}},
        0.0,
        datetime.now(),
        persona_filename="core_aveline.json",
    )

    assert delivered is True
    kwargs = service.dispatch_proactive_message.await_args.kwargs
    extra = kwargs["extra_payload"] or {}
    assert extra.get("persona_filename") == "core_aveline.json"
    # 角色显示名随 payload 下发（本地无注册表数据时允许为空串）
    assert "role_name" in extra and isinstance(extra["role_name"], str)


async def verify_switch_off_keeps_qq_only() -> None:
    """开关关闭时退回只投 QQ，App 不再收到（保留应急回滚能力）。"""
    sent: list[tuple[str, dict]] = []

    async def _broadcast(payload, user_id=None, **_kwargs):
        sent.append((str(user_id), dict(payload)))
        return True

    connections = [_conn("mobile_user")]
    manager = SimpleNamespace(
        connections={id(c): c for c in connections},
        is_user_online=lambda uid: True,
        broadcast=AsyncMock(side_effect=_broadcast),
    )
    service = SimpleNamespace(append_proactive_message=AsyncMock(return_value=None))

    original = cr.APP_DELIVERY_ENABLED
    cr.APP_DELIVERY_ENABLED = False
    try:
        with patch(
            "core.interfaces.websocket.websocket_manager.get_websocket_manager",
            return_value=manager,
        ):
            await proactive_messaging.dispatch_proactive_message(
                service,
                target_conversation_id="private_10001__persona__core_aveline",
                content="晚安",
                client_type="qq",
                original_primary_conversation_id="private_10001",
            )
    finally:
        cr.APP_DELIVERY_ENABLED = original

    assert [uid for uid, _ in sent] == ["private_10001"], sent


async def main() -> int:
    verify_app_delivery_switch_default()
    verify_app_uids_picked_up()
    await verify_sleep_again_reaches_app()
    await verify_dispatcher_carries_persona_filename()
    await verify_switch_off_keeps_qq_only()
    print("PASS: Active Care 主动消息可投递到手机 App（睡回去告别已覆盖）")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
