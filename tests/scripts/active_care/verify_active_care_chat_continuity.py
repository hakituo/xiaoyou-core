"""验证 Active Care 不再把旧时间线主动消息插回正在进行的聊天。

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\active_care\\verify_active_care_chat_continuity.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _check(condition: bool, message: str) -> bool:
    prefix = "PASS" if condition else "FAIL"
    print(f"[{prefix}] {message}")
    return condition


class _RecentContext:
    def __init__(self, timestamp: float) -> None:
        self.timestamp = timestamp

    def get_recent_user_message(self, conversation_id: str) -> dict:
        _ = conversation_id
        return {"content": "最新用户消息", "timestamp": self.timestamp}


class _Storage:
    @staticmethod
    def resolve_scope_from_persona_filename(persona_filename: str) -> str:
        _ = persona_filename
        return "aveline"


def verify_overlap_scope_unified() -> bool:
    from core.services.active_care.core.overlap_guard import OverlapGuard

    guard = OverlapGuard(SimpleNamespace())
    guard.get_guard_seconds = MagicMock(return_value=600)
    guard.record_attempt("core_aveline.json", 1000.0)
    return _check(
        "aveline" in guard._last_trigger_ts_by_persona
        and "core_aveline.json" not in guard._last_trigger_ts_by_persona
        and not guard.check("proactive_chat", 1050.0, "aveline"),
        "persona 文件名与稳定 scope 共用同一 overlap 时间线",
    )


def verify_freshness_guard() -> bool:
    from core.services.active_care.core.message_dispatcher import MessageDispatcher

    executor = SimpleNamespace(
        context=_RecentContext(120.0),
        storage=_Storage(),
        _last_trigger_ts_by_persona={"aveline": 110.0},
        consecutive_non_responses={},
    )
    dispatcher = MessageDispatcher(executor)
    reason = dispatcher._get_stale_chat_reason(
        sys_prompt_type="proactive_chat",
        target_conversation_id="private_1__persona__core_aveline",
        context={"last_user_ts_raw": 100.0},
        trigger_started_ts=110.0,
        persona_filename="core_aveline.json",
    )
    reminder_reason = dispatcher._get_stale_chat_reason(
        sys_prompt_type="reminder",
        target_conversation_id="private_1__persona__core_aveline",
        context={"last_user_ts_raw": 100.0},
        trigger_started_ts=110.0,
        persona_filename="core_aveline.json",
    )
    return _check(
        reason.startswith("user_message_advanced:") and reminder_reason == "",
        "新用户消息会淘汰闲聊 candidate，但真实 reminder 不被误取消",
    )


async def verify_stale_dispatch_has_no_side_effect() -> bool:
    from core.services.active_care.core.message_dispatcher import MessageDispatcher

    executor = SimpleNamespace(
        context=_RecentContext(120.0),
        storage=_Storage(),
        _last_trigger_ts_by_persona={"aveline": 110.0},
        consecutive_non_responses={},
    )
    dispatcher = MessageDispatcher(executor)
    dispatcher.update_non_response_count = AsyncMock()
    service = SimpleNamespace(dispatch_proactive_message=AsyncMock())

    delivered = await dispatcher.dispatch_message(
        service,
        {"content": "旧时间线消息", "message_type": "text"},
        "good_morning_proactive",
        None,
        "private_1__persona__core_aveline",
        "private_1",
        "qq",
        "qq",
        None,
        {"last_user_ts_raw": 100.0},
        110.0,
        datetime(2026, 9, 17, 8, 0, 0),
        persona_filename="core_aveline.json",
    )

    return _check(
        not delivered
        and service.dispatch_proactive_message.await_count == 0
        and dispatcher.update_non_response_count.await_count == 0,
        "过期 candidate 在真正 dispatch 前被静默丢弃且不推进非响应计数",
    )


async def verify_active_chat_suppresses_good_morning() -> bool:
    from core.services.active_care.good_morning_proactive import (
        _has_sent_today,
        reset_sent_cache,
        trigger_character_good_morning,
    )

    reset_sent_cache()
    executor = SimpleNamespace(trigger_message=AsyncMock(return_value=True))
    ac = SimpleNamespace(executor=executor, context=MagicMock())

    with (
        patch(
            "core.services.active_care.core.qq_connection_resolver.can_send_proactive_message",
            return_value=True,
        ),
        patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=ac,
        ),
        patch(
            "core.services.active_care.good_morning_proactive._resolve_persona_filename",
            return_value="core_aveline.json",
        ),
        patch(
            "core.services.active_care.good_morning_proactive._is_user_actively_chatting",
            new=AsyncMock(return_value=True),
        ),
    ):
        handled = await trigger_character_good_morning("aveline")

    return _check(
        handled
        and _has_sent_today("aveline")
        and executor.trigger_message.await_count == 0,
        "角色起床节点撞上当前活跃聊天时由主聊天承载，不额外插一条早安",
    )


def verify_stay_up_instruction() -> bool:
    from core.services.active_care.good_morning_proactive import (
        _build_specific_instruction,
    )

    with patch(
        "core.services.active_care.good_morning_proactive.get_current_time",
        return_value=datetime(2026, 9, 17, 8, 30, 0),
    ):
        text = _build_specific_instruction("aveline", is_stay_up_recovery=True)

    return _check(
        "熬夜阶段结束" in text
        and "不要说『刚醒』" in text
        and "不要询问用户昨晚睡没睡" in text
        and "熬夜后刚醒过来" not in text,
        "熬夜恢复不会伪装成刚睡醒，也不会反推用户昨晚睡眠",
    )


async def main() -> int:
    results = [
        verify_overlap_scope_unified(),
        verify_freshness_guard(),
        await verify_stale_dispatch_has_no_side_effect(),
        await verify_active_chat_suppresses_good_morning(),
        verify_stay_up_instruction(),
    ]
    passed = sum(bool(item) for item in results)
    print(f"\n结果：{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
