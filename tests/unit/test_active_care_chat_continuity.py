"""Active Care 与普通聊天时间线连续性回归测试。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch


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


class TestOverlapPersonaKey(TestCase):
    def test_filename_and_scope_share_same_overlap_key(self) -> None:
        from core.services.active_care.core.overlap_guard import OverlapGuard

        guard = OverlapGuard(SimpleNamespace())
        guard.get_guard_seconds = MagicMock(return_value=600)

        guard.record_attempt("core_aveline.json", 1000.0)

        self.assertIn("aveline", guard._last_trigger_ts_by_persona)
        self.assertNotIn("core_aveline.json", guard._last_trigger_ts_by_persona)
        self.assertFalse(guard.check("proactive_chat", 1050.0, "aveline"))


class TestFreshnessGuard(TestCase):
    @staticmethod
    def _build_dispatcher(*, recent_ts: float, trigger_ts: float):
        from core.services.active_care.core.message_dispatcher import MessageDispatcher

        executor = SimpleNamespace(
            context=_RecentContext(recent_ts),
            storage=_Storage(),
            _last_trigger_ts_by_persona={"aveline": trigger_ts},
            consecutive_non_responses={},
        )
        return MessageDispatcher(executor)

    def test_new_user_message_invalidates_chat_candidate(self) -> None:
        dispatcher = self._build_dispatcher(recent_ts=120.0, trigger_ts=110.0)

        reason = dispatcher._get_stale_chat_reason(
            sys_prompt_type="proactive_chat",
            target_conversation_id="private_1__persona__core_aveline",
            context={"last_user_ts_raw": 100.0},
            trigger_started_ts=110.0,
            persona_filename="core_aveline.json",
        )

        self.assertTrue(reason.startswith("user_message_advanced:"))

    def test_new_main_chat_reply_invalidates_chat_candidate(self) -> None:
        dispatcher = self._build_dispatcher(recent_ts=100.0, trigger_ts=130.0)

        reason = dispatcher._get_stale_chat_reason(
            sys_prompt_type="good_morning_proactive",
            target_conversation_id="private_1__persona__core_aveline",
            context={"last_user_ts_raw": 100.0},
            trigger_started_ts=110.0,
            persona_filename="core_aveline.json",
        )

        self.assertTrue(reason.startswith("assistant_timeline_advanced:"))

    def test_hard_reminder_is_not_cancelled_by_chat_freshness(self) -> None:
        dispatcher = self._build_dispatcher(recent_ts=120.0, trigger_ts=130.0)

        reason = dispatcher._get_stale_chat_reason(
            sys_prompt_type="reminder",
            target_conversation_id="private_1__persona__core_aveline",
            context={"last_user_ts_raw": 100.0},
            trigger_started_ts=110.0,
            persona_filename="core_aveline.json",
        )

        self.assertEqual(reason, "")


class TestStaleDispatch(IsolatedAsyncioTestCase):
    async def test_stale_candidate_has_no_dispatch_or_nonresponse_side_effect(self) -> None:
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
            "proactive_chat",
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

        self.assertFalse(delivered)
        service.dispatch_proactive_message.assert_not_awaited()
        dispatcher.update_non_response_count.assert_not_awaited()


class TestGenerationSideEffects(IsolatedAsyncioTestCase):
    async def test_pre_generated_reply_is_not_persisted_before_dispatch(self) -> None:
        from core.services.active_care.core.generation_pipeline import GenerationPipeline

        persist_fallback = AsyncMock()
        executor = SimpleNamespace(
            _message_dispatcher=SimpleNamespace(
                persist_proactive_message_fallback=persist_fallback,
            )
        )
        pipeline = GenerationPipeline(executor)

        result = await pipeline.get_or_generate_response(
            aveline_service=SimpleNamespace(),
            reply_text="候选消息",
            thought="test",
            context={},
            sys_prompt="",
            model_user_input="",
            target_conversation_id="private_1__persona__core_aveline",
        )

        self.assertEqual(result["content"], "候选消息")
        persist_fallback.assert_not_awaited()


class TestGoodMorningContinuity(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from core.services.active_care.good_morning_proactive import reset_sent_cache

        reset_sent_cache()

    async def test_active_chat_consumes_wakeup_greeting_without_extra_message(self) -> None:
        from core.services.active_care.good_morning_proactive import (
            _has_sent_today,
            trigger_character_good_morning,
        )

        executor = SimpleNamespace(trigger_message=AsyncMock(return_value=True))
        active_care_service = SimpleNamespace(executor=executor, context=MagicMock())

        with (
            patch(
                "core.services.active_care.core.qq_connection_resolver.can_send_proactive_message",
                return_value=True,
            ),
            patch(
                "core.services.active_care.core.service.get_active_care_service",
                return_value=active_care_service,
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
            result = await trigger_character_good_morning("aveline")

        self.assertTrue(result)
        self.assertTrue(_has_sent_today("aveline"))
        executor.trigger_message.assert_not_awaited()

    def test_stay_up_recovery_does_not_claim_just_woke_up(self) -> None:
        from core.services.active_care.good_morning_proactive import (
            _build_specific_instruction,
        )

        fixed_now = datetime(2026, 9, 17, 8, 30, 0)
        with patch(
            "core.services.active_care.good_morning_proactive.get_current_time",
            return_value=fixed_now,
        ):
            instruction = _build_specific_instruction(
                "aveline",
                is_stay_up_recovery=True,
            )

        self.assertIn("熬夜阶段结束", instruction)
        self.assertIn("不要说『刚醒』", instruction)
        self.assertIn("不要询问用户昨晚睡没睡", instruction)
        self.assertNotIn("熬夜后刚醒过来", instruction)
