"""验证角色起床时主动发起床问候消息功能。

验证点：
1. _on_enter_waking_up 在 prev_phase != WAKING_UP 时触起床问候主动消息
2. _on_enter_waking_up 在 prev_phase == WAKING_UP 时不重复触发
3. 服务延迟重启场景：now 距 wake_dt 超过 30 分钟时仍应触发（去重由 good_morning_proactive 负责）
4. 熬夜后白天恢复清醒场景（is_stay_up_recovery=True）
5. 每日去重：同一 role_id 同一天只发一次
6. good_morning_proactive sys_prompt_type 在 prompt_builder 中能正确生成 prompt
7. trigger_character_good_morning 在 active_care 未就绪时优雅返回 False
8. 必须传 client_type="qq"，避免重蹈晚安消息未送达 QQ 的 bug
9. 时间感知：下午醒来时 specific_instruction 不应要求"早安"，应使用"下午好"等
10. specific_instruction 必须被拼接到 prompt_builder 的输出中
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


class TestGoodMorningProactive(unittest.IsolatedAsyncioTestCase):
    """测试起床问候主动消息模块。"""

    def setUp(self):
        """每个测试前重置去重缓存。"""
        from core.services.active_care.good_morning_proactive import reset_sent_cache
        reset_sent_cache()

    async def test_trigger_character_good_morning_when_active_care_not_ready(self):
        """active_care 未就绪时应优雅返回 False。"""
        from core.services.active_care.good_morning_proactive import (
            trigger_character_good_morning,
        )

        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=None,
        ):
            result = await trigger_character_good_morning("aveline")

        self.assertFalse(result)

    async def test_trigger_character_good_morning_delivers_and_marks_sent(self):
        """active_care 就绪且 executor 返回 delivered=True 时应标记已发送。"""
        from core.services.active_care.good_morning_proactive import (
            _has_sent_today,
            trigger_character_good_morning,
        )

        mock_executor = MagicMock()
        mock_executor.trigger_message = AsyncMock(return_value=True)
        mock_ac = MagicMock()
        mock_ac.executor = mock_executor

        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            result = await trigger_character_good_morning("aveline")

        self.assertTrue(result)
        self.assertTrue(_has_sent_today("aveline"))
        mock_executor.trigger_message.assert_awaited_once()
        call_kwargs = mock_executor.trigger_message.call_args.kwargs
        self.assertEqual(call_kwargs["sys_prompt_type"], "good_morning_proactive")
        self.assertEqual(call_kwargs["persona_filename"], "qq/Aveline_QQ_Master.json")
        self.assertEqual(call_kwargs["user_input_mock"], "[CHARACTER_JUST_WOKE_UP]")
        # 必须传 client_type="qq"，避免重蹈晚安消息未送达 QQ 的 bug
        # （broadcast 不剥离 __persona__ 后缀 → 找不到连接 → 只能存离线队列）
        self.assertEqual(call_kwargs["client_type"], "qq")

    async def test_daily_dedup_skips_second_call(self):
        """同一 role_id 同一天第二次调用应跳过。"""
        from core.services.active_care.good_morning_proactive import (
            trigger_character_good_morning,
        )

        mock_executor = MagicMock()
        mock_executor.trigger_message = AsyncMock(return_value=True)
        mock_ac = MagicMock()
        mock_ac.executor = mock_executor

        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            first = await trigger_character_good_morning("aveline")
            second = await trigger_character_good_morning("aveline")

        self.assertTrue(first)
        self.assertTrue(second)  # 视为成功（已发过）
        # executor 只应被调用一次（第二次被去重跳过）
        self.assertEqual(mock_executor.trigger_message.await_count, 1)

    async def test_different_roles_independent_dedup(self):
        """不同 role_id 的去重相互独立。"""
        from core.services.active_care.good_morning_proactive import (
            trigger_character_good_morning,
        )

        mock_executor = MagicMock()
        mock_executor.trigger_message = AsyncMock(return_value=True)
        mock_ac = MagicMock()
        mock_ac.executor = mock_executor

        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            await trigger_character_good_morning("aveline")
            await trigger_character_good_morning("ling")

        self.assertEqual(mock_executor.trigger_message.await_count, 2)
        # 验证 ling 用了正确的 persona_filename
        second_call = mock_executor.trigger_message.call_args_list[1].kwargs
        self.assertEqual(second_call["persona_filename"], "qq/Ling_QQ_Master.json")

    async def test_stay_up_recovery_uses_fatigued_instruction(self):
        """is_stay_up_recovery=True 时 specific_instruction 应体现疲惫感。"""
        from core.services.active_care.good_morning_proactive import (
            trigger_character_good_morning,
        )

        mock_executor = MagicMock()
        mock_executor.trigger_message = AsyncMock(return_value=True)
        mock_ac = MagicMock()
        mock_ac.executor = mock_executor

        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            await trigger_character_good_morning("aveline", is_stay_up_recovery=True)

        call_kwargs = mock_executor.trigger_message.call_args.kwargs
        self.assertIn("熬夜", call_kwargs["specific_instruction"])
        self.assertIn("疲惫", call_kwargs["specific_instruction"])
        # thought 也应体现熬夜恢复
        self.assertIn("stay_up", call_kwargs["thought"])

    async def test_normal_wakeup_instruction_references_sleep_summary(self):
        """is_stay_up_recovery=False 时 specific_instruction 应引用睡眠摘要。"""
        from core.services.active_care.good_morning_proactive import (
            trigger_character_good_morning,
        )

        mock_executor = MagicMock()
        mock_executor.trigger_message = AsyncMock(return_value=True)
        mock_ac = MagicMock()
        mock_ac.executor = mock_executor

        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            await trigger_character_good_morning("aveline", is_stay_up_recovery=False)

        call_kwargs = mock_executor.trigger_message.call_args.kwargs
        self.assertIn("睡眠摘要", call_kwargs["specific_instruction"])
        self.assertIn("waking_up_by_schedule", call_kwargs["thought"])


class TestSleepManagerOnEnterWakingUp(unittest.TestCase):
    """测试 SleepManager._on_enter_waking_up 钩子。"""

    def test_skip_when_already_waking_up(self):
        """prev_phase=WAKING_UP 时不触发（避免重复发送）。"""
        from core.services.life_simulation.sleep_models import SleepPhase

        with patch(
            "core.services.active_care.good_morning_proactive.trigger_character_good_morning_async"
        ) as mock_trigger:
            from core.services.life_simulation.sleep_manager import SleepManager

            manager = SleepManager.__new__(SleepManager)
            now = datetime.now()
            wake_dt = now - timedelta(minutes=5)
            manager._on_enter_waking_up(
                "aveline", SleepPhase.WAKING_UP, now, wake_dt,
            )

        mock_trigger.assert_not_called()

    def test_trigger_when_entering_waking_up_from_sleeping(self):
        """prev_phase=SLEEPING 时应触发早安消息（不再有 30 分钟窗口限制）。"""
        from core.services.life_simulation.sleep_models import SleepPhase

        with patch(
            "core.services.active_care.good_morning_proactive.trigger_character_good_morning_async"
        ) as mock_trigger:
            from core.services.life_simulation.sleep_manager import SleepManager

            manager = SleepManager.__new__(SleepManager)
            now = datetime.now()
            wake_dt = now - timedelta(minutes=5)  # 5 分钟前起床
            manager._on_enter_waking_up(
                "aveline", SleepPhase.SLEEPING, now, wake_dt,
                is_stay_up_recovery=False,
            )

        mock_trigger.assert_called_once_with("aveline", is_stay_up_recovery=False)

    def test_trigger_even_when_delay_exceeds_30_minutes(self):
        """服务延迟重启场景：now 距 wake_dt 超过 30 分钟时仍应触发早安消息。

        原设计有 30 分钟窗口保护，但实际服务不是 24/7 运行，用户上午才启动服务时，
        wake_dt 已过去数小时，导致早安消息被全部跳过。现改为只用每日去重作为保护，
        去重逻辑由 good_morning_proactive._sent_today 按 role_id 维度负责。
        """
        from core.services.life_simulation.sleep_models import SleepPhase

        with patch(
            "core.services.active_care.good_morning_proactive.trigger_character_good_morning_async"
        ) as mock_trigger:
            from core.services.life_simulation.sleep_manager import SleepManager

            manager = SleepManager.__new__(SleepManager)
            now = datetime.now()
            # 模拟服务下午才启动，wake_dt 是早上 7 点，now 是下午 2 点（已过 7 小时）
            wake_dt = now - timedelta(hours=7)
            manager._on_enter_waking_up(
                "aveline", SleepPhase.SLEEPING, now, wake_dt,
            )

        # 即使延迟超过 30 分钟也应触发，去重交给 good_morning_proactive 处理
        mock_trigger.assert_called_once_with("aveline", is_stay_up_recovery=False)

    def test_trigger_when_stay_up_recovery(self):
        """熬夜后白天恢复清醒（is_stay_up_recovery=True）应触发。"""
        from core.services.life_simulation.sleep_models import SleepPhase

        with patch(
            "core.services.active_care.good_morning_proactive.trigger_character_good_morning_async"
        ) as mock_trigger:
            from core.services.life_simulation.sleep_manager import SleepManager

            manager = SleepManager.__new__(SleepManager)
            now = datetime.now()
            wake_dt = now - timedelta(minutes=10)
            manager._on_enter_waking_up(
                "aveline", SleepPhase.STAY_UP_LATE, now, wake_dt,
                is_stay_up_recovery=True,
            )

        mock_trigger.assert_called_once_with("aveline", is_stay_up_recovery=True)

    def test_no_exception_when_good_morning_module_unavailable(self):
        """active_care 模块导入失败时不应抛异常。"""
        from core.services.life_simulation.sleep_models import SleepPhase

        with patch(
            "core.services.active_care.good_morning_proactive.trigger_character_good_morning_async",
            side_effect=ImportError("simulated import failure"),
        ):
            from core.services.life_simulation.sleep_manager import SleepManager

            manager = SleepManager.__new__(SleepManager)
            now = datetime.now()
            wake_dt = now - timedelta(minutes=5)
            # 不应抛异常
            manager._on_enter_waking_up(
                "aveline", SleepPhase.SLEEPING, now, wake_dt,
            )


class TestGoodMorningPromptBuilder(unittest.TestCase):
    """测试 prompt_builder 中 good_morning_proactive sys_prompt_type 处理。"""

    def test_good_morning_proactive_returns_dedicated_template(self):
        """good_morning_proactive sys_prompt_type 应返回专属模板，而非默认 proactive_chat。"""
        from core.services.active_care.prompt.prompt_builder import _build_task_block_dynamic
        from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
            TASK_GOOD_MORNING_PROACTIVE_TEMPLATE,
        )

        result = _build_task_block_dynamic(
            sys_prompt_type="good_morning_proactive",
            tod="早上7点",
            user_input_mock="[CHARACTER_JUST_WOKE_UP]",
            reminder_msg=None,
            thought=None,
            specific_instruction=None,
        )

        # 应包含起床问候模板的关键标记
        self.assertIn("起床问候", result)
        # 应与模板内容一致（无 specific_instruction 时只返回模板）
        self.assertEqual(result, TASK_GOOD_MORNING_PROACTIVE_TEMPLATE.format(tod="早上7点"))

    def test_good_morning_proactive_appends_specific_instruction(self):
        """specific_instruction 必须被拼接到模板后，否则时间感知/疲惫感提示丢失。"""
        from core.services.active_care.prompt.prompt_builder import _build_task_block_dynamic

        result = _build_task_block_dynamic(
            sys_prompt_type="good_morning_proactive",
            tod="下午2点",
            user_input_mock="[CHARACTER_JUST_WOKE_UP]",
            reminder_msg=None,
            thought=None,
            specific_instruction="现在是下午（14:00），用『下午好』或表达睡过头的感觉，不要用早安",
        )

        # specific_instruction 内容必须出现在结果中
        self.assertIn("下午好", result)
        self.assertIn("不要用早安", result)


class TestGoodMorningTimeAwareness(unittest.TestCase):
    """测试 _build_specific_instruction 的时间感知逻辑。"""

    def test_morning_uses_zao_an(self):
        """早晨（5-10点）醒来应要求使用早安。"""
        from core.services.active_care.good_morning_proactive import _get_wake_greeting_context

        period, greeting = _get_wake_greeting_context(7)
        self.assertEqual(period, "早晨")
        self.assertIn("早安", greeting)

    def test_noon_avoids_zao_an(self):
        """中午（11-13点）醒来不应要求早安，应用『刚醒/午安』。"""
        from core.services.active_care.good_morning_proactive import _get_wake_greeting_context

        period, greeting = _get_wake_greeting_context(12)
        self.assertEqual(period, "中午")
        self.assertIn("不要用早安", greeting)

    def test_afternoon_avoids_zao_an(self):
        """下午（13-17点）醒来不应要求早安，应用『下午好』。"""
        from core.services.active_care.good_morning_proactive import _get_wake_greeting_context

        # 13:47 属于下午时段（与 time_utils.get_time_period 一致：13 <= hour < 18）
        period, greeting = _get_wake_greeting_context(13)
        self.assertEqual(period, "下午")
        self.assertIn("下午好", greeting)
        self.assertIn("不要用早安", greeting)

    def test_evening_avoids_zao_an(self):
        """傍晚及以后（18+）醒来不应要求早安，应用『傍晚好』。"""
        from core.services.active_care.good_morning_proactive import _get_wake_greeting_context

        period, greeting = _get_wake_greeting_context(19)
        self.assertEqual(period, "傍晚以后")
        self.assertIn("傍晚好", greeting)
        self.assertIn("不要用早安", greeting)


if __name__ == "__main__":
    unittest.main()
