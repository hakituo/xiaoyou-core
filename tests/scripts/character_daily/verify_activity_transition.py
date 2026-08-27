"""验证活动自然切换时的告别消息逻辑。

验证点：
1. _classify_transition 正确分类活动切换方向
   - 从可聊天切到忙碌 → "to_busy"
   - 从可聊天切到睡觉 → "none"（交给 sleep_manager 处理）
   - 从忙碌切到空闲 → "none"
   - 相同活动 → "none"
2. _is_user_in_conversation 正确判断用户是否在聊天
3. _should_send_farewell 去重逻辑（冷却期内不重复发）
4. build_activity_start_farewell_instruction 文案包含活动动词
5. build_sleep_during_chat_farewell_instruction 文案包含告别/顺延判断
6. check_and_send_farewell_on_transition 在用户不在聊天时跳过
7. check_and_send_farewell_on_transition 在 disabled 时不发送
8. check_and_send_farewell_on_transition 在满足条件时发送告别消息
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


class TestClassifyTransition(unittest.TestCase):
    """测试活动切换方向分类。"""

    def test_idle_to_studying_is_to_busy(self):
        """从空闲切到学习应为 to_busy。"""
        from core.services.character_daily.activity_transition import _classify_transition
        from core.services.character_daily.activity_model import ActivityType

        result = _classify_transition(ActivityType.IDLE, ActivityType.STUDYING)
        self.assertEqual(result, "to_busy")

    def test_phone_scrolling_to_cooking_is_to_busy(self):
        """从刷手机切到做饭应为 to_busy。"""
        from core.services.character_daily.activity_transition import _classify_transition
        from core.services.character_daily.activity_model import ActivityType

        result = _classify_transition(ActivityType.PHONE_SCROLLING, ActivityType.COOKING)
        self.assertEqual(result, "to_busy")

    def test_idle_to_sleeping_is_none(self):
        """从空闲切到睡觉应为 none（交给 sleep_manager 处理）。"""
        from core.services.character_daily.activity_transition import _classify_transition
        from core.services.character_daily.activity_model import ActivityType

        result = _classify_transition(ActivityType.IDLE, ActivityType.SLEEPING)
        self.assertEqual(result, "none")

    def test_studying_to_idle_is_none(self):
        """从忙碌切到空闲应为 none（不需要告别）。"""
        from core.services.character_daily.activity_transition import _classify_transition
        from core.services.character_daily.activity_model import ActivityType

        result = _classify_transition(ActivityType.STUDYING, ActivityType.IDLE)
        self.assertEqual(result, "none")

    def test_same_activity_is_none(self):
        """相同活动应为 none。"""
        from core.services.character_daily.activity_transition import _classify_transition
        from core.services.character_daily.activity_model import ActivityType

        result = _classify_transition(ActivityType.IDLE, ActivityType.IDLE)
        self.assertEqual(result, "none")

    def test_idle_to_reading_is_none(self):
        """从空闲切到看书（可聊天活动）应为 none。"""
        from core.services.character_daily.activity_transition import _classify_transition
        from core.services.character_daily.activity_model import ActivityType

        result = _classify_transition(ActivityType.IDLE, ActivityType.READING)
        self.assertEqual(result, "none")

    def test_gaming_to_exercising_is_to_busy(self):
        """从打游戏切到运动应为 to_busy。"""
        from core.services.character_daily.activity_transition import _classify_transition
        from core.services.character_daily.activity_model import ActivityType

        result = _classify_transition(ActivityType.GAMING, ActivityType.EXERCISING)
        self.assertEqual(result, "to_busy")


class TestIsUserInConversation(unittest.TestCase):
    """测试用户是否在聊天的判断。"""

    def test_no_scheduler_returns_false(self):
        """scheduler 为 None 时返回 False。"""
        from core.services.character_daily.activity_transition import _is_user_in_conversation

        self.assertFalse(_is_user_in_conversation(None, 300.0))

    def test_user_recently_active_returns_true(self):
        """用户最近发过消息返回 True。"""
        from core.services.character_daily.activity_transition import _is_user_in_conversation

        scheduler = MagicMock()
        scheduler._last_user_activity_ts = {"cid1": time.time() - 60}
        self.assertTrue(_is_user_in_conversation(scheduler, 300.0))

    def test_user_inactive_returns_false(self):
        """用户超过窗口未发消息返回 False。"""
        from core.services.character_daily.activity_transition import _is_user_in_conversation

        scheduler = MagicMock()
        scheduler._last_user_activity_ts = {"cid1": time.time() - 400}
        self.assertFalse(_is_user_in_conversation(scheduler, 300.0))

    def test_empty_activity_ts_returns_false(self):
        """没有活跃记录返回 False。"""
        from core.services.character_daily.activity_transition import _is_user_in_conversation

        scheduler = MagicMock()
        scheduler._last_user_activity_ts = {}
        self.assertFalse(_is_user_in_conversation(scheduler, 300.0))


class TestShouldSendFarewell(unittest.TestCase):
    """测试告别消息去重逻辑。"""

    def setUp(self):
        from core.services.character_daily.activity_transition import reset_farewell_state
        reset_farewell_state()

    def tearDown(self):
        from core.services.character_daily.activity_transition import reset_farewell_state
        reset_farewell_state()

    def test_first_send_returns_true(self):
        """首次发送返回 True。"""
        from core.services.character_daily.activity_transition import _should_send_farewell
        from core.services.character_daily.activity_model import ActivityType
        from core.services.character_daily.config import ReplyPolicyConfig

        config = ReplyPolicyConfig()
        self.assertTrue(
            _should_send_farewell("aveline", ActivityType.STUDYING, "to_busy", config)
        )

    def test_cooldown_prevents_resend(self):
        """冷却期内同活动不重复发。"""
        from core.services.character_daily.activity_transition import (
            _mark_farewell_sent,
            _should_send_farewell,
        )
        from core.services.character_daily.activity_model import ActivityType
        from core.services.character_daily.config import ReplyPolicyConfig

        config = ReplyPolicyConfig()
        _mark_farewell_sent("aveline", ActivityType.STUDYING)
        self.assertFalse(
            _should_send_farewell("aveline", ActivityType.STUDYING, "to_busy", config)
        )

    def test_different_activity_allows_send(self):
        """不同活动不受冷却影响。"""
        from core.services.character_daily.activity_transition import (
            _mark_farewell_sent,
            _should_send_farewell,
        )
        from core.services.character_daily.activity_model import ActivityType
        from core.services.character_daily.config import ReplyPolicyConfig

        config = ReplyPolicyConfig()
        _mark_farewell_sent("aveline", ActivityType.STUDYING)
        # 切换到做饭，应该允许发
        self.assertTrue(
            _should_send_farewell("aveline", ActivityType.COOKING, "to_busy", config)
        )

    def test_none_type_never_sends(self):
        """none 类型不发送。"""
        from core.services.character_daily.activity_transition import _should_send_farewell
        from core.services.character_daily.activity_model import ActivityType
        from core.services.character_daily.config import ReplyPolicyConfig

        config = ReplyPolicyConfig()
        self.assertFalse(
            _should_send_farewell("aveline", ActivityType.STUDYING, "none", config)
        )


class TestInstructionBuilders(unittest.TestCase):
    """测试告别 instruction 构建。"""

    def test_build_activity_start_farewell_instruction(self):
        """活动开始告别 instruction 应包含活动动词。"""
        from core.services.character_daily.activity_return.instruction import (
            build_activity_start_farewell_instruction,
        )

        instruction = build_activity_start_farewell_instruction("aveline", "studying")
        self.assertIn("学习", instruction)
        self.assertIn("聊天", instruction)
        self.assertIn("告别", instruction)

    def test_build_sleep_during_chat_farewell_instruction(self):
        """聊天中入睡 instruction 应包含告别/顺延判断。"""
        from core.services.character_daily.activity_return.instruction import (
            build_sleep_during_chat_farewell_instruction,
        )

        instruction = build_sleep_during_chat_farewell_instruction("aveline")
        self.assertIn("睡觉", instruction)
        self.assertIn("聊天", instruction)
        self.assertIn("顺延", instruction)
        self.assertIn("晚安", instruction)


class TestCheckAndSendFarewell(unittest.TestCase):
    """测试完整的检测与发送流程。"""

    def setUp(self):
        from core.services.character_daily.activity_transition import reset_farewell_state
        reset_farewell_state()

    def tearDown(self):
        from core.services.character_daily.activity_transition import reset_farewell_state
        reset_farewell_state()

    def test_disabled_config_skips(self):
        """配置禁用时跳过。"""
        from core.services.character_daily.activity_transition import (
            check_and_send_farewell_on_transition,
        )
        from core.services.character_daily.activity_model import ActivityType
        from core.services.character_daily.config import ReplyPolicyConfig

        config = ReplyPolicyConfig(activity_transition_farewell_enabled=False)
        engine = MagicMock()

        result = asyncio.get_event_loop().run_until_complete(
            check_and_send_farewell_on_transition(
                engine=engine,
                role_id="aveline",
                prev_activity=ActivityType.IDLE,
                new_activity=ActivityType.STUDYING,
                config=config,
            )
        )
        self.assertFalse(result)

    def test_none_transition_skips(self):
        """none 切换类型跳过。"""
        from core.services.character_daily.activity_transition import (
            check_and_send_farewell_on_transition,
        )
        from core.services.character_daily.activity_model import ActivityType
        from core.services.character_daily.config import ReplyPolicyConfig

        config = ReplyPolicyConfig()
        engine = MagicMock()

        result = asyncio.get_event_loop().run_until_complete(
            check_and_send_farewell_on_transition(
                engine=engine,
                role_id="aveline",
                prev_activity=ActivityType.STUDYING,
                new_activity=ActivityType.IDLE,
                config=config,
            )
        )
        self.assertFalse(result)

    def test_user_not_in_conversation_skips(self):
        """用户不在聊天时跳过。"""
        from core.services.character_daily.activity_transition import (
            check_and_send_farewell_on_transition,
        )
        from core.services.character_daily.activity_model import ActivityType
        from core.services.character_daily.config import ReplyPolicyConfig

        config = ReplyPolicyConfig()
        engine = MagicMock()
        engine._peer_chat_scheduler = None  # 无 scheduler → 用户不在聊天

        result = asyncio.get_event_loop().run_until_complete(
            check_and_send_farewell_on_transition(
                engine=engine,
                role_id="aveline",
                prev_activity=ActivityType.IDLE,
                new_activity=ActivityType.STUDYING,
                config=config,
            )
        )
        self.assertFalse(result)

    def test_sends_farewell_when_user_in_conversation(self):
        """用户在聊天时发送告别消息。"""
        from core.services.character_daily.activity_transition import (
            check_and_send_farewell_on_transition,
        )
        from core.services.character_daily.activity_model import ActivityType
        from core.services.character_daily.config import ReplyPolicyConfig

        config = ReplyPolicyConfig()
        engine = MagicMock()
        scheduler = MagicMock()
        scheduler._last_user_activity_ts = {"cid1": time.time() - 60}
        engine._peer_chat_scheduler = scheduler

        with patch(
            "core.services.character_daily.activity_transition._send_farewell_message",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_send:
            result = asyncio.get_event_loop().run_until_complete(
                check_and_send_farewell_on_transition(
                    engine=engine,
                    role_id="aveline",
                    prev_activity=ActivityType.IDLE,
                    new_activity=ActivityType.STUDYING,
                    config=config,
                )
            )
            self.assertTrue(result)
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            self.assertEqual(call_args[0][0], "aveline")
            self.assertEqual(call_args[0][1], ActivityType.STUDYING)
            self.assertEqual(call_args[0][2], "to_busy")


class TestSendFarewellMessage(unittest.TestCase):
    """测试告别消息发送。"""

    def setUp(self):
        from core.services.character_daily.activity_transition import reset_farewell_state
        reset_farewell_state()

    def tearDown(self):
        from core.services.character_daily.activity_transition import reset_farewell_state
        reset_farewell_state()

    def test_active_care_not_ready_returns_false(self):
        """Active Care 未就绪时返回 False。"""
        from core.services.character_daily.activity_transition import _send_farewell_message
        from core.services.character_daily.activity_model import ActivityType

        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=None,
        ):
            result = asyncio.get_event_loop().run_until_complete(
                _send_farewell_message("aveline", ActivityType.STUDYING, "to_busy")
            )
            self.assertFalse(result)

    def test_successful_send_marks_state(self):
        """发送成功后标记去重状态。"""
        from core.services.character_daily.activity_transition import (
            _last_farewell,
            _send_farewell_message,
        )
        from core.services.character_daily.activity_model import ActivityType

        mock_ac = MagicMock()
        mock_ac.executor = MagicMock()
        mock_ac.executor.trigger_message = AsyncMock(return_value=True)

        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            result = asyncio.get_event_loop().run_until_complete(
                _send_farewell_message("aveline", ActivityType.STUDYING, "to_busy")
            )
            self.assertTrue(result)
            self.assertIn("aveline", _last_farewell)
            self.assertEqual(_last_farewell["aveline"]["activity"], "studying")


if __name__ == "__main__":
    unittest.main(verbosity=2)
