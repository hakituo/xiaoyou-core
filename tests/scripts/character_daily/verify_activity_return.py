"""验证角色从临时聊天回归原活动的统一消息模块。

验证点：
1. build_return_instruction 能分别构建 work / sleep 两种回归文案
2. build_return_decision_hint 能为用户回复注入正确的决策提示
3. send_activity_return_message 在 Active Care 未就绪时优雅返回
4. send_activity_return_message 成功发送后会记录 pending_return 状态
5. pending_return 在 grace 等待期内可查询，过期/解决后不可查询
6. schedule_activity_return 能按 window_seconds - lead_seconds 调度异步任务
7. schedule_activity_return 会取消同一会话的旧调度任务
8. handle_user_reply_during_return 在等待期内回复时延长窗口并重新调度
9. cancel_scheduled_return 能取消已调度的回归消息任务
10. 通用模块同时服务 /打断 后的 work 回归和半夜 sleep 回归两个场景
11. 半夜睡回去场景允许 conversation_id 为空，此时发送消息但不记录 pending
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


class TestActivityReturnInstruction(unittest.TestCase):
    """测试回归文案与决策提示构建。"""

    def test_build_work_return_instruction(self):
        """work 场景文案应明确提到回去继续做什么。"""
        from core.services.character_daily.activity_return import build_return_instruction

        instruction = build_return_instruction("aveline", "studying", "work")
        self.assertIn("回去继续学习", instruction)
        self.assertIn("刚才被用户打断", instruction)

    def test_build_sleep_return_instruction(self):
        """sleep 场景文案应包含睡回去的告别语义。"""
        from core.services.character_daily.activity_return import build_return_instruction

        instruction = build_return_instruction("aveline", "sleeping", "sleep")
        self.assertIn("睡回去", instruction)
        self.assertIn("不要再发", instruction)

    def test_build_work_return_decision_hint(self):
        """work 场景决策提示应引导 LLM 判断用户是否想继续聊。"""
        from core.services.character_daily.activity_return import build_return_decision_hint

        hint = build_return_decision_hint("studying", "work")
        self.assertIn("学习", hint)
        self.assertIn("继续聊", hint)
        self.assertIn("去做事", hint)

    def test_build_sleep_return_decision_hint(self):
        """sleep 场景决策提示应引导 LLM 判断是否需要再醒一会儿。"""
        from core.services.character_daily.activity_return import build_return_decision_hint

        hint = build_return_decision_hint("sleeping", "sleep")
        self.assertIn("睡回去", hint)
        self.assertIn("再醒一会儿", hint)


class TestSendActivityReturnMessage(unittest.IsolatedAsyncioTestCase):
    """测试发送回归消息与 pending 状态管理。"""

    def setUp(self):
        from core.services.character_daily.activity_return import reset_all_pending_returns

        reset_all_pending_returns()

    def _mock_active_care(self, delivered: bool = True):
        mock_executor = MagicMock()
        mock_executor.trigger_message = AsyncMock(return_value=delivered)
        mock_ac = MagicMock()
        mock_ac.executor = mock_executor
        return mock_ac, mock_executor

    async def test_send_when_active_care_not_ready(self):
        """Active Care 未就绪时应返回 delivered=False 且不抛异常。"""
        from core.services.character_daily.activity_return import (
            send_activity_return_message,
        )

        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=None,
        ):
            result = await send_activity_return_message(
                conversation_id="cid_test",
                role_id="aveline",
                activity="studying",
                return_type="work",
            )

        self.assertFalse(result["delivered"])

    async def test_send_success_sets_pending_return(self):
        """发送成功后会话应进入 pending_return 等待期。"""
        from core.services.character_daily.activity_return import (
            get_pending_return,
            send_activity_return_message,
        )

        mock_ac, mock_executor = self._mock_active_care(delivered=True)
        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            result = await send_activity_return_message(
                conversation_id="cid_pending",
                role_id="aveline",
                activity="studying",
                return_type="work",
                source="unit_test",
            )

        self.assertTrue(result["delivered"])
        mock_executor.trigger_message.assert_awaited_once()
        call_kwargs = mock_executor.trigger_message.call_args.kwargs
        self.assertEqual(call_kwargs["sys_prompt_type"], "activity_return_proactive")
        self.assertEqual(call_kwargs["persona_filename"], "qq/Aveline_QQ_Master.json")
        self.assertEqual(call_kwargs["client_type"], "qq")
        self.assertIn("specific_instruction", call_kwargs)

        pending = get_pending_return("cid_pending")
        self.assertIsNotNone(pending)
        self.assertEqual(pending["role_id"], "aveline")
        self.assertEqual(pending["activity"], "studying")
        self.assertEqual(pending["return_type"], "work")

    async def test_send_failed_no_pending(self):
        """发送失败时不应留下 pending 状态。"""
        from core.services.character_daily.activity_return import (
            get_pending_return,
            send_activity_return_message,
        )

        mock_ac, _ = self._mock_active_care(delivered=False)
        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            result = await send_activity_return_message(
                conversation_id="cid_fail",
                role_id="aveline",
                activity="studying",
                return_type="work",
            )

        self.assertFalse(result["delivered"])
        self.assertIsNone(get_pending_return("cid_fail"))

    async def test_pending_expires_after_grace_period(self):
        """pending_return 超过 grace 等待期后应不可见。"""
        from core.services.character_daily.activity_return import (
            get_pending_return,
            send_activity_return_message,
        )

        mock_ac, _ = self._mock_active_care(delivered=True)
        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            await send_activity_return_message(
                conversation_id="cid_expire",
                role_id="aveline",
                activity="studying",
                return_type="work",
            )

        self.assertIsNotNone(get_pending_return("cid_expire"))

        # 将 grace_expire_ts 推到过去以模拟过期
        from core.services.character_daily.activity_return.state import (
            _lock,
            _pending_returns,
        )

        with _lock:
            _pending_returns["cid_expire"].grace_expire_ts = time.time() - 1.0

        self.assertIsNone(get_pending_return("cid_expire"))

    def test_resolve_and_clear_pending_return(self):
        """resolve_pending_return 与 clear_pending_return 应正确维护状态。"""
        import asyncio
        from core.services.character_daily.activity_return import (
            get_pending_return,
            resolve_pending_return,
            clear_pending_return,
            send_activity_return_message,
        )

        async def _run():
            mock_ac, _ = self._mock_active_care(delivered=True)
            with patch(
                "core.services.active_care.core.service.get_active_care_service",
                return_value=mock_ac,
            ):
                await send_activity_return_message(
                    conversation_id="cid_resolve",
                    role_id="aveline",
                    activity="studying",
                    return_type="work",
                )

            self.assertIsNotNone(get_pending_return("cid_resolve"))
            resolved = resolve_pending_return("cid_resolve", "leave")
            self.assertIsNotNone(resolved)
            self.assertTrue(resolved.resolved)
            self.assertEqual(resolved.decision, "leave")

            # 解决后 get_pending_return 应返回 None
            self.assertIsNone(get_pending_return("cid_resolve"))

            clear_pending_return("cid_resolve")

        asyncio.run(_run())


class TestScheduleActivityReturn(unittest.IsolatedAsyncioTestCase):
    """测试异步调度与取消。"""

    def setUp(self):
        from core.services.character_daily.activity_return import reset_all_pending_returns
        from core.services.character_daily.interrupt_window import (
            clear_manual_interrupt_window,
        )

        reset_all_pending_returns()
        clear_manual_interrupt_window("cid_schedule")
        clear_manual_interrupt_window("cid_reschedule")

    async def asyncTearDown(self):
        from core.services.character_daily.activity_return import cancel_scheduled_return
        from core.services.character_daily.interrupt_window import (
            clear_manual_interrupt_window,
        )

        await cancel_scheduled_return("cid_schedule")
        await cancel_scheduled_return("cid_reschedule")
        clear_manual_interrupt_window("cid_schedule")
        clear_manual_interrupt_window("cid_reschedule")

    async def test_schedule_triggers_return_message(self):
        """schedule_activity_return 应在 window_seconds - lead_seconds 后触发 send_activity_return_message。"""
        from core.services.character_daily.activity_return import (
            schedule_activity_return,
            cancel_scheduled_return,
        )
        from core.services.character_daily.interrupt_window import (
            activate_manual_interrupt_window,
        )

        activate_manual_interrupt_window(
            conversation_id="cid_schedule",
            role_id="aveline",
            activity="studying",
            window_seconds=2.0,
        )

        mock_send = AsyncMock(return_value={"delivered": True})
        with patch(
            "core.services.character_daily.activity_return.core.send_activity_return_message",
            new=mock_send,
        ):
            result = await schedule_activity_return(
                conversation_id="cid_schedule",
                role_id="aveline",
                activity="studying",
                return_type="work",
                window_seconds=2.0,
                lead_seconds=1.0,
                source="unit_test_schedule",
            )

            self.assertTrue(result["scheduled"])
            self.assertAlmostEqual(result["delay_seconds"], 1.0, places=2)

            # 等待任务触发
            await asyncio.wait_for(result["task"], timeout=3.0)
            mock_send.assert_awaited_once()
            call_kwargs = mock_send.call_args.kwargs
            self.assertEqual(call_kwargs["conversation_id"], "cid_schedule")
            self.assertEqual(call_kwargs["role_id"], "aveline")
            self.assertEqual(call_kwargs["activity"], "studying")
            self.assertEqual(call_kwargs["return_type"], "work")
            self.assertEqual(call_kwargs["source"], "unit_test_schedule")
            await cancel_scheduled_return("cid_schedule")

    async def test_schedule_cancels_previous_task(self):
        """重新调度同一会话时应取消之前的任务。"""
        from core.services.character_daily.activity_return import schedule_activity_return
        from core.services.character_daily.interrupt_window import (
            activate_manual_interrupt_window,
        )

        activate_manual_interrupt_window(
            conversation_id="cid_schedule",
            role_id="aveline",
            activity="studying",
            window_seconds=5.0,
        )

        mock_send = AsyncMock(return_value={"delivered": True})
        with patch(
            "core.services.character_daily.activity_return.core.send_activity_return_message",
            new=mock_send,
        ):
            first = await schedule_activity_return(
                conversation_id="cid_schedule",
                role_id="aveline",
                activity="studying",
                return_type="work",
                window_seconds=5.0,
                lead_seconds=1.0,
            )
            first_task = first["task"]
            self.assertFalse(first_task.done())

            second = await schedule_activity_return(
                conversation_id="cid_schedule",
                role_id="aveline",
                activity="studying",
                return_type="work",
                window_seconds=5.0,
                lead_seconds=1.0,
            )

        # 旧任务应被取消
        await asyncio.sleep(0.1)
        self.assertTrue(first_task.cancelled())
        self.assertIsNotNone(second["task"])


class TestHandleUserReplyDuringReturn(unittest.IsolatedAsyncioTestCase):
    """测试用户在回归消息等待期内回复时的窗口延长与重新调度。"""

    def setUp(self):
        from core.services.character_daily.activity_return import reset_all_pending_returns
        from core.services.character_daily.interrupt_window import (
            clear_manual_interrupt_window,
        )

        reset_all_pending_returns()
        clear_manual_interrupt_window("cid_reschedule")

    async def asyncTearDown(self):
        from core.services.character_daily.activity_return import cancel_scheduled_return
        from core.services.character_daily.interrupt_window import (
            clear_manual_interrupt_window,
        )

        await cancel_scheduled_return("cid_reschedule")
        clear_manual_interrupt_window("cid_reschedule")

    async def test_reply_extends_window_and_reschedules(self):
        """用户回复在等待期内应延长窗口并重新调度回归消息。"""
        from core.services.character_daily.activity_return import (
            handle_user_reply_during_return,
            send_activity_return_message,
        )
        from core.services.character_daily.interrupt_window import (
            activate_manual_interrupt_window,
            get_manual_interrupt_window,
        )

        # 先激活一个 3 秒的窗口并发送回归消息
        activate_manual_interrupt_window(
            conversation_id="cid_reschedule",
            role_id="aveline",
            activity="studying",
            window_seconds=3.0,
        )
        original_window = get_manual_interrupt_window(
            conversation_id="cid_reschedule", role_id="aveline"
        )
        self.assertIsNotNone(original_window)
        original_expire = float(original_window["expire_ts"])

        mock_ac, _ = self._mock_active_care(delivered=True)
        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            await send_activity_return_message(
                conversation_id="cid_reschedule",
                role_id="aveline",
                activity="studying",
                return_type="work",
                source="unit_test",
            )

            result = await handle_user_reply_during_return(
                conversation_id="cid_reschedule",
                user_message="再聊会嘛",
            )

        self.assertTrue(result["handled"])
        self.assertTrue(result["extended"])
        self.assertIn("学习", result["hint"])

        updated_window = get_manual_interrupt_window(
            conversation_id="cid_reschedule", role_id="aveline"
        )
        self.assertIsNotNone(updated_window)
        self.assertGreater(
            float(updated_window["expire_ts"]),
            original_expire,
            "窗口应在用户回复后被延长",
        )

    async def test_reply_outside_grace_not_handled(self):
        """等待期外回复不应被处理。"""
        from core.services.character_daily.activity_return import (
            handle_user_reply_during_return,
        )

        result = await handle_user_reply_during_return(
            conversation_id="cid_no_pending",
            user_message="再聊会",
        )
        self.assertFalse(result["handled"])
        self.assertFalse(result["extended"])

    def _mock_active_care(self, delivered: bool = True):
        mock_executor = MagicMock()
        mock_executor.trigger_message = AsyncMock(return_value=delivered)
        mock_ac = MagicMock()
        mock_ac.executor = mock_executor
        return mock_ac, mock_executor


class TestSleepScenarioIntegration(unittest.IsolatedAsyncioTestCase):
    """测试 sleep 回归场景能复用同一套接口。"""

    def setUp(self):
        from core.services.character_daily.activity_return import reset_all_pending_returns

        reset_all_pending_returns()

    async def test_sleep_return_uses_dedicated_prompt(self):
        """半夜睡回去场景应使用 sleep_again_proactive prompt 并进入 pending。"""
        from core.services.character_daily.activity_return import (
            get_pending_return,
            send_activity_return_message,
        )

        mock_ac, mock_executor = self._mock_active_care(delivered=True)
        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            result = await send_activity_return_message(
                conversation_id="cid_sleep",
                role_id="aveline",
                activity="sleeping",
                return_type="sleep",
                source="unit_test_sleep",
                sys_prompt_type="sleep_again_proactive",
                user_input_mock="[CHARACTER_SLEEP_AGAIN]",
                thought="character_aveline_sleep_again_by_recovery",
            )

        self.assertTrue(result["delivered"])
        call_kwargs = mock_executor.trigger_message.call_args.kwargs
        self.assertEqual(call_kwargs["sys_prompt_type"], "sleep_again_proactive")
        self.assertEqual(call_kwargs["user_input_mock"], "[CHARACTER_SLEEP_AGAIN]")

        pending = get_pending_return("cid_sleep")
        self.assertIsNotNone(pending)
        self.assertEqual(pending["return_type"], "sleep")

    async def test_sleep_return_without_conversation_id(self):
        """半夜睡回去场景可能无法提供 conversation_id，此时应发送但不记录 pending。"""
        from core.services.character_daily.activity_return import (
            get_pending_return,
            send_activity_return_message,
        )

        mock_ac, mock_executor = self._mock_active_care(delivered=True)
        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            result = await send_activity_return_message(
                conversation_id="",
                role_id="aveline",
                activity="sleeping",
                return_type="sleep",
                source="sleep_manager_sleep_again",
                sys_prompt_type="sleep_again_proactive",
                user_input_mock="[CHARACTER_SLEEP_AGAIN]",
                thought="character_aveline_sleep_again_by_recovery",
            )

        self.assertTrue(result["delivered"])
        mock_executor.trigger_message.assert_awaited_once()
        self.assertIsNone(get_pending_return(""))

    def _mock_active_care(self, delivered: bool = True):
        mock_executor = MagicMock()
        mock_executor.trigger_message = AsyncMock(return_value=delivered)
        mock_ac = MagicMock()
        mock_ac.executor = mock_executor
        return mock_ac, mock_executor


if __name__ == "__main__":
    unittest.main()
