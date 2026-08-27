"""手动打断聊天窗口测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.services.character_daily.activity_model import ActivityType
from core.services.character_daily.config import ReplyPolicyConfig
from core.services.character_daily.interrupt_window import (
    activate_manual_interrupt_window,
    clear_manual_interrupt_window,
)
from core.services.character_daily.reply_policy import evaluate_reply_state


def _make_reply_config() -> ReplyPolicyConfig:
    return ReplyPolicyConfig(
        enabled=True,
        reply_window_seconds=120.0,
        manual_interrupt_window_seconds=600.0,
    )


@pytest.mark.asyncio
async def test_manual_interrupt_window_allows_busy_chat():
    config = _make_reply_config()
    conversation_id = "private_1__persona__core_ling"
    activate_manual_interrupt_window(
        conversation_id=conversation_id,
        role_id="ling",
        activity=ActivityType.STUDYING.value,
        window_seconds=600.0,
    )

    mock_engine = MagicMock()
    mock_engine.get_current_activity.return_value = ActivityType.STUDYING

    mock_ac = MagicMock()
    mock_ac.storage = MagicMock()
    mock_ac.storage.get_proactive_state = AsyncMock(
        return_value={"last_goodnight_ts": 0.0, "last_goodmorning_ts": 0.0}
    )

    try:
        with patch(
            "core.services.character_daily.engine.get_character_daily_engine",
            return_value=mock_engine,
        ), patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            decision = await evaluate_reply_state(
                role_id="ling",
                config=config,
                conversation_id=conversation_id,
            )
    finally:
        clear_manual_interrupt_window(conversation_id)

    assert decision.should_reply is True
    assert "manual_interrupt_window" in decision.reason
    assert "手动打断后的聊天窗口期" in decision.persona_hint


@pytest.mark.asyncio
async def test_manual_interrupt_window_does_not_bypass_sleeping():
    config = _make_reply_config()
    conversation_id = "private_1__persona__core_ling"
    activate_manual_interrupt_window(
        conversation_id=conversation_id,
        role_id="ling",
        activity=ActivityType.STUDYING.value,
        window_seconds=600.0,
    )

    mock_engine = MagicMock()
    mock_engine.get_current_activity.return_value = ActivityType.SLEEPING
    # reply_policy 检测到 DND 时会调用 refresh_current_activity 强制刷新，
    # mock 时需同步返回相同活动，避免被 MagicMock 占位值干扰判定。
    mock_engine.refresh_current_activity.return_value = ActivityType.SLEEPING

    mock_ac = MagicMock()
    mock_ac.storage = MagicMock()
    mock_ac.storage.get_proactive_state = AsyncMock(
        return_value={"last_goodnight_ts": 3600.0, "last_goodmorning_ts": 0.0}
    )

    try:
        with patch(
            "core.services.character_daily.engine.get_character_daily_engine",
            return_value=mock_engine,
        ), patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ), patch(
            "core.services.character_daily.reply_policy.random.random",
            return_value=0.99,
        ):
            decision = await evaluate_reply_state(
                role_id="ling",
                config=config,
                conversation_id=conversation_id,
            )
    finally:
        clear_manual_interrupt_window(conversation_id)

    assert decision.should_reply is False
    assert "manual_interrupt_window" not in decision.reason
    assert "dnd_sleeping_silent" in decision.reason


@pytest.mark.asyncio
async def test_wake_interrupt_window_allows_waking_up_chat():
    """回归测试：/wake 后 activity 仍为 waking_up（DND）时，
    激活的中断窗口应让角色正常回复，而不是静默累积。

    复现 bug：reply_policy 中断窗口分支曾要求
    `activity not in DO_NOT_DISTURB_ACTIVITIES`，导致 waking_up 被排除，
    /wake 激活的中断窗口形同虚设，消息仍走 DND 静默累积分支。
    """
    config = _make_reply_config()
    conversation_id = "private_10001__persona__aveline_qq_master"
    activate_manual_interrupt_window(
        conversation_id=conversation_id,
        role_id="aveline",
        activity=ActivityType.WAKING_UP.value,
        window_seconds=600.0,
        source="wake_auto_interrupt_dnd",
    )

    mock_engine = MagicMock()
    mock_engine.get_current_activity.return_value = ActivityType.WAKING_UP
    mock_engine.refresh_current_activity.return_value = ActivityType.WAKING_UP

    mock_ac = MagicMock()
    mock_ac.storage = MagicMock()
    mock_ac.storage.get_proactive_state = AsyncMock(
        return_value={"last_goodnight_ts": 0.0, "last_goodmorning_ts": 0.0}
    )

    try:
        with patch(
            "core.services.character_daily.engine.get_character_daily_engine",
            return_value=mock_engine,
        ), patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            decision = await evaluate_reply_state(
                role_id="aveline",
                config=config,
                conversation_id=conversation_id,
            )
    finally:
        clear_manual_interrupt_window(conversation_id)

    assert decision.should_reply is True
    assert "manual_interrupt_window" in decision.reason
