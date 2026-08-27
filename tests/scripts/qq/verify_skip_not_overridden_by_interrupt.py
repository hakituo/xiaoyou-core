#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 /打断 不会覆盖 /skip 创建的 skip_activity=True 长窗口。

复现 2026-07-20 用户反馈的 bug：
1. 用户 /skip 创建窗口（skip=True, 长窗口，覆盖整个活动剩余时间）
2. 用户 /打断 想再加一段时间
3. /打断 旧实现会无条件 activate_manual_interrupt_window，覆盖掉 /skip 的窗口
   导致 skip_activity 变成 False、窗口时间变成 300s（5 分钟）
4. 用户感觉 /skip "跳过不了活动"，因为 /打断 把 /skip 效果重置了

修复后期望：
- /打断 接口在检测到 skip_activity=True 窗口时，返回 action="already_skipped"，
  不覆盖原窗口
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from core.services.character_daily.activity_model import ActivityType
from core.services.character_daily.interrupt_window import (
    clear_manual_interrupt_window,
    get_manual_interrupt_window,
)
from core.services.character_daily.reply_policy import evaluate_reply_state
from core.services.character_daily.config import ReplyPolicyConfig
from routers.v1.life import interrupt_current_activity, skip_current_activity
from routers.v1.life import ActivityInterruptRequest, ActivitySkipRequest


def _make_skip_request(conversation_id: str) -> ActivitySkipRequest:
    return ActivitySkipRequest(
        role_id="ling",
        persona_filename="sensitive/Ling_love.json",
        conversation_id=conversation_id,
        message="QQ命令跳过活动",
    )


def _make_interrupt_request(conversation_id: str) -> ActivityInterruptRequest:
    return ActivityInterruptRequest(
        role_id="ling",
        persona_filename="sensitive/Ling_love.json",
        conversation_id=conversation_id,
        message="QQ命令打断",
    )


async def _run_one(cid: str, label: str) -> tuple[dict, dict]:
    """模拟一次 /skip + /打断 序列，返回两次响应。"""
    # 模拟 engine: 当前活动是 STUDYING，剩余 1800s（30 分钟）
    mock_engine = MagicMock()
    mock_engine.refresh_current_activity.return_value = ActivityType.STUDYING
    mock_engine.get_current_slot_remaining_seconds.return_value = 1800.0
    mock_engine.get_reply_policy_config.return_value = ReplyPolicyConfig(
        enabled=True,
        manual_interrupt_window_seconds=300.0,
    )

    # 模拟 life simulation service: 未在睡
    mock_sim = MagicMock()
    mock_sim.get_sleep_summary.return_value = {"is_sleeping": False, "phase": "fully_awake"}

    try:
        with patch(
            "routers.v1.life._get_character_daily_engine", return_value=mock_engine
        ), patch(
            "routers.v1.life._get_life_simulation_service", return_value=mock_sim
        ), patch(
            "routers.v1.life._resolve_role_scope", return_value="ling"
        ), patch(
            "routers.v1.life.cancel_scheduled_return", new=AsyncMock(return_value=None)
        ), patch(
            "routers.v1.life.schedule_activity_return", new=AsyncMock(return_value={"scheduled": True})
        ):
            skip_resp = await skip_current_activity(_make_skip_request(cid))
            interrupt_resp = await interrupt_current_activity(_make_interrupt_request(cid))
    finally:
        clear_manual_interrupt_window(cid)

    print(f"=== {label} ===")
    print(f"/skip 响应: action={skip_resp.get('action')}, "
          f"remaining={skip_resp.get('remaining_seconds')}s, "
          f"message={skip_resp.get('message')}")
    print(f"/打断 响应: action={interrupt_resp.get('action')}, "
          f"remaining={interrupt_resp.get('remaining_seconds')}s, "
          f"message={interrupt_resp.get('message')}")
    return skip_resp, interrupt_resp


async def _check_reply_allows_chat(cid: str) -> bool:
    """验证 /skip 后聊天能命中 skip=True 窗口。"""
    mock_engine = MagicMock()
    mock_engine.get_current_activity.return_value = ActivityType.STUDYING
    mock_engine.refresh_current_activity.return_value = ActivityType.STUDYING

    mock_ac = MagicMock()
    mock_ac.storage = MagicMock()
    mock_ac.storage.get_proactive_state = AsyncMock(
        return_value={"last_goodnight_ts": 0.0, "last_goodmorning_ts": 0.0}
    )

    with patch(
        "core.services.character_daily.engine.get_character_daily_engine",
        return_value=mock_engine,
    ), patch(
        "core.services.active_care.core.service.get_active_care_service",
        return_value=mock_ac,
    ):
        decision = await evaluate_reply_state(
            role_id="ling",
            config=ReplyPolicyConfig(enabled=True, manual_interrupt_window_seconds=300.0),
            conversation_id=cid,
        )
    return decision.should_reply and "skip=True" in decision.reason


async def main() -> int:
    cid = "private_10001__persona__ling_love"

    print("--- 步骤 1: 验证 /skip + /打断 序列 ---")
    skip_resp, interrupt_resp = await _run_one(cid, "skip 后 interrupt")

    # /skip 应该成功
    if skip_resp.get("action") not in ("skipped", "auto_skipped"):
        print(f"验证失败：/skip 未成功，action={skip_resp.get('action')}")
        return 1

    skip_remaining = skip_resp.get("remaining_seconds") or 0
    if skip_remaining <= 300:
        print(f"验证失败：/skip 窗口时间应该 > 300s（应覆盖整个活动），实际 {skip_remaining}s")
        return 1

    # /打断 应该返回 already_skipped，不覆盖 /skip 的窗口
    if interrupt_resp.get("action") != "already_skipped":
        print(f"验证失败：/打断 应返回 already_skipped，实际 action={interrupt_resp.get('action')}")
        return 1

    # /打断 响应的 remaining 应该等于 /skip 的 remaining（不被覆盖成 300s）
    interrupt_remaining = interrupt_resp.get("remaining_seconds") or 0
    if interrupt_remaining <= 300:
        print(
            f"验证失败：/打断 后窗口时间应该保持 /skip 的长窗口，"
            f"实际 remaining={interrupt_remaining}s（疑似被覆盖为 300s）"
        )
        return 1

    print("--- 步骤 2: 验证 /skip + /打断 后窗口仍为 skip=True ---")
    # 重新跑一次，不清窗口，检查窗口状态
    mock_engine = MagicMock()
    mock_engine.refresh_current_activity.return_value = ActivityType.STUDYING
    mock_engine.get_current_slot_remaining_seconds.return_value = 1800.0
    mock_engine.get_reply_policy_config.return_value = ReplyPolicyConfig(
        enabled=True, manual_interrupt_window_seconds=300.0,
    )
    mock_sim = MagicMock()
    mock_sim.get_sleep_summary.return_value = {"is_sleeping": False, "phase": "fully_awake"}

    try:
        with patch(
            "routers.v1.life._get_character_daily_engine", return_value=mock_engine
        ), patch(
            "routers.v1.life._get_life_simulation_service", return_value=mock_sim
        ), patch(
            "routers.v1.life._resolve_role_scope", return_value="ling"
        ), patch(
            "routers.v1.life.cancel_scheduled_return", new=AsyncMock(return_value=None)
        ), patch(
            "routers.v1.life.schedule_activity_return", new=AsyncMock(return_value={"scheduled": True})
        ):
            await skip_current_activity(_make_skip_request(cid))
            await interrupt_current_activity(_make_interrupt_request(cid))

            # 检查窗口状态
            window = get_manual_interrupt_window(conversation_id=cid, role_id="ling")
            if not window:
                print("验证失败：/skip + /打断 后窗口消失")
                return 1
            if not bool(window.get("skip_activity")):
                print(f"验证失败：/打断 把 /skip 的 skip_activity 标记覆盖为 False，window={window}")
                return 1
            expire_remaining = float(window.get("expire_ts") or 0.0) - __import__("time").time()
            if expire_remaining <= 300:
                print(
                    f"验证失败：/打断 把 /skip 的长窗口覆盖为 300s，"
                    f"实际剩余 {expire_remaining:.1f}s"
                )
                return 1

            # 验证聊天命中
            ok = await _check_reply_allows_chat(cid)
            if not ok:
                print("验证失败：/skip + /打断 后聊天未命中 skip=True 窗口")
                return 1
    finally:
        clear_manual_interrupt_window(cid)

    print("\n验证通过：/打断 不再覆盖 /skip 的窗口，skip_activity 标记和长窗口都被保留。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
