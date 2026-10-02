#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证手动打断聊天窗口是否能让 busy 状态继续聊天。"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from core.services.character_daily.activity_model import ActivityType
from core.services.character_daily.config import ReplyPolicyConfig
from core.services.character_daily.interrupt_window import (
    activate_manual_interrupt_window,
    clear_manual_interrupt_window,
)
from core.services.character_daily.reply_policy import evaluate_reply_state


async def main() -> int:
    conversation_id = "private_10001__persona__core_ling"
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
                config=ReplyPolicyConfig(enabled=True, manual_interrupt_window_seconds=600.0),
                conversation_id=conversation_id,
            )
    finally:
        clear_manual_interrupt_window(conversation_id)

    print("=== 手动打断聊天窗口验证 ===")
    print(f"should_reply={decision.should_reply}")
    print(f"reason={decision.reason}")

    if not decision.should_reply:
        print("验证失败：busy 状态下的手动打断窗口没有放行回复。")
        return 1
    if "manual_interrupt_window" not in decision.reason:
        print("验证失败：未命中手动打断窗口原因。")
        return 1

    print("验证通过：手动打断后，busy 状态会进入持续聊天窗口。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
