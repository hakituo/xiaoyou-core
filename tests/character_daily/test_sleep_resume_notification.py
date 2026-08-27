"""验证夜间被叫醒后重新去睡的主动消息补发。"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
    _notify_sleep_resume_message,
)


@pytest.mark.asyncio
async def test_notify_sleep_resume_message_when_returning_to_sleep():
    """静默后决定继续睡时，应主动补一条消息。"""
    mock_aveline_service = MagicMock()
    mock_aveline_service.dispatch_proactive_message = AsyncMock(
        return_value={"delivered": True}
    )
    mock_active_care_service = MagicMock()
    mock_active_care_service.storage = MagicMock()
    mock_active_care_service.on_assistant_message_sent = AsyncMock()

    with patch(
        "core.core_engine.service_singletons.get_aveline_service",
        return_value=mock_aveline_service,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_active_care_service,
    ), patch(
        "core.services.active_care.core.persona_resolver.PersonaResolver.resolve_persona_filename_static",
        return_value="qq/Aveline_QQ_Master.json",
    ):
        await _notify_sleep_resume_message(
            cid="private_10001__persona__aveline_qq_master",
            role_id="aveline",
            before_summary={"phase": "night_awake"},
            after_summary={"phase": "sleeping", "nightmare_level": "none"},
        )

    mock_aveline_service.dispatch_proactive_message.assert_awaited_once()
    call_kwargs = mock_aveline_service.dispatch_proactive_message.await_args.kwargs
    assert call_kwargs["target_conversation_id"] == (
        "private_10001__persona__aveline_qq_master"
    )
    assert "继续睡" in call_kwargs["content"]
    mock_active_care_service.on_assistant_message_sent.assert_awaited_once()
    notify_kwargs = mock_active_care_service.on_assistant_message_sent.await_args.kwargs
    assert notify_kwargs["persona_filename"] == "qq/Aveline_QQ_Master.json"
    assert abs(notify_kwargs["timestamp"] - time.time()) < 5


@pytest.mark.asyncio
async def test_notify_sleep_resume_message_when_sleep_later():
    """决定一会儿再睡时，也应给用户一个交代。"""
    mock_aveline_service = MagicMock()
    mock_aveline_service.dispatch_proactive_message = AsyncMock(
        return_value={"delivered": True}
    )

    with patch(
        "core.core_engine.service_singletons.get_aveline_service",
        return_value=mock_aveline_service,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=None,
    ):
        await _notify_sleep_resume_message(
            cid="private_10001__persona__aveline_qq_master",
            role_id="aveline",
            before_summary={"phase": "night_awake"},
            after_summary={"phase": "sleep_later", "nightmare_level": "none"},
        )

    call_kwargs = mock_aveline_service.dispatch_proactive_message.await_args.kwargs
    assert "等会儿再去睡" in call_kwargs["content"]


@pytest.mark.asyncio
async def test_no_resume_message_when_staying_awake():
    """如果决定继续熬夜，就不应误发重新入睡消息。"""
    mock_aveline_service = MagicMock()
    mock_aveline_service.dispatch_proactive_message = AsyncMock(
        return_value={"delivered": True}
    )

    with patch(
        "core.core_engine.service_singletons.get_aveline_service",
        return_value=mock_aveline_service,
    ):
        await _notify_sleep_resume_message(
            cid="private_10001__persona__aveline_qq_master",
            role_id="aveline",
            before_summary={"phase": "night_awake"},
            after_summary={"phase": "stay_up_late", "nightmare_level": "none"},
        )

    mock_aveline_service.dispatch_proactive_message.assert_not_awaited()
