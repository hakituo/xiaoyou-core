"""验证角色睡觉时主动发晚安消息功能。

验证点：
1. _on_enter_sleeping 在 prev_phase != SLEEPING 时触发晚安主动消息
2. _on_enter_sleeping 在 prev_phase == SLEEPING 时不重复触发
3. 每日去重：同一 role_id 同一天只发一次
4. goodnight_proactive sys_prompt_type 在 prompt_builder 中能正确生成 prompt
5. trigger_character_goodnight 在 active_care 未就绪时优雅返回 False
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


class TestGoodnightProactive(unittest.IsolatedAsyncioTestCase):
    """测试晚安主动消息模块。"""

    def setUp(self):
        """每个测试前重置去重缓存。"""
        from core.services.active_care.goodnight_proactive import reset_sent_cache
        reset_sent_cache()

    async def test_trigger_character_goodnight_when_active_care_not_ready(self):
        """active_care 未就绪时应优雅返回 False。"""
        from core.services.active_care.goodnight_proactive import (
            trigger_character_goodnight,
        )

        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=None,
        ):
            result = await trigger_character_goodnight("aveline")
        self.assertFalse(result)

    async def test_trigger_character_goodnight_delivers_and_marks_sent(self):
        """active_care 就绪且 executor 返回 delivered=True 时应标记已发送。"""
        from core.services.active_care.goodnight_proactive import (
            _has_sent_today,
            trigger_character_goodnight,
        )

        mock_executor = MagicMock()
        mock_executor.trigger_message = AsyncMock(return_value=True)
        mock_ac = MagicMock()
        mock_ac.executor = mock_executor

        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            result = await trigger_character_goodnight("aveline")

        self.assertTrue(result)
        self.assertTrue(_has_sent_today("aveline"))
        mock_executor.trigger_message.assert_awaited_once()
        call_kwargs = mock_executor.trigger_message.call_args.kwargs
        self.assertEqual(call_kwargs["sys_prompt_type"], "goodnight_proactive")
        self.assertEqual(call_kwargs["persona_filename"], "qq/Aveline_QQ_Master.json")
        # 必须传 client_type="qq"，否则 broadcast 不剥离 __persona__ 后缀，
        # 消息只能存离线队列；且 resolve_target_conversation 不会按 persona 路由，
        # 导致 ling 的晚安被错发到 aveline 的会话。
        self.assertEqual(call_kwargs["client_type"], "qq")

    async def test_daily_dedup_skips_second_call(self):
        """同一 role_id 同一天第二次调用应跳过。"""
        from core.services.active_care.goodnight_proactive import (
            trigger_character_goodnight,
        )

        mock_executor = MagicMock()
        mock_executor.trigger_message = AsyncMock(return_value=True)
        mock_ac = MagicMock()
        mock_ac.executor = mock_executor

        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            first = await trigger_character_goodnight("aveline")
            second = await trigger_character_goodnight("aveline")

        self.assertTrue(first)
        self.assertTrue(second)  # 视为成功（已发过）
        # executor 只应被调用一次（第二次被去重跳过）
        self.assertEqual(mock_executor.trigger_message.await_count, 1)

    async def test_different_roles_independent_dedup(self):
        """不同 role_id 的去重相互独立。"""
        from core.services.active_care.goodnight_proactive import (
            trigger_character_goodnight,
        )

        mock_executor = MagicMock()
        mock_executor.trigger_message = AsyncMock(return_value=True)
        mock_ac = MagicMock()
        mock_ac.executor = mock_executor

        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            await trigger_character_goodnight("aveline")
            await trigger_character_goodnight("ling")

        self.assertEqual(mock_executor.trigger_message.await_count, 2)


class TestSleepManagerOnEnterSleeping(unittest.TestCase):
    """测试 SleepManager._on_enter_sleeping 钩子。"""

    def test_skip_when_already_sleeping(self):
        """prev_phase=SLEEPING 时不触发（避免重复发送）。"""
        from core.services.life_simulation.sleep_models import SleepPhase

        with patch(
            "core.services.active_care.goodnight_proactive.trigger_character_goodnight_async"
        ) as mock_trigger:
            from core.services.life_simulation.sleep_manager import SleepManager

            manager = SleepManager.__new__(SleepManager)
            manager._on_enter_sleeping("aveline", SleepPhase.SLEEPING, datetime.now())

        mock_trigger.assert_not_called()

    def test_trigger_when_entering_sleeping_from_other_phase(self):
        """prev_phase=NIGHT_AWAKE 时应触发晚安消息。"""
        from core.services.life_simulation.sleep_models import SleepPhase

        with patch(
            "core.services.active_care.goodnight_proactive.trigger_character_goodnight_async"
        ) as mock_trigger:
            from core.services.life_simulation.sleep_manager import SleepManager

            manager = SleepManager.__new__(SleepManager)
            manager._on_enter_sleeping("aveline", SleepPhase.NIGHT_AWAKE, datetime.now())

        # 默认 is_sleep_again=False（首次入睡场景）
        mock_trigger.assert_called_once_with("aveline", is_sleep_again=False)

    def test_no_exception_when_goodnight_module_unavailable(self):
        """active_care 模块导入失败时不应抛异常。"""
        from core.services.life_simulation.sleep_models import SleepPhase

        with patch(
            "core.services.active_care.goodnight_proactive.trigger_character_goodnight_async",
            side_effect=ImportError("simulated import failure"),
        ):
            from core.services.life_simulation.sleep_manager import SleepManager

            manager = SleepManager.__new__(SleepManager)
            # 不应抛异常
            manager._on_enter_sleeping("aveline", SleepPhase.NIGHT_AWAKE, datetime.now())


class TestGoodnightPromptBuilder(unittest.TestCase):
    """测试 prompt_builder 中 goodnight_proactive sys_prompt_type 处理。"""

    def test_goodnight_proactive_returns_dedicated_template(self):
        """goodnight_proactive sys_prompt_type 应返回专属模板，而非默认 proactive_chat。"""
        from core.services.active_care.prompt.prompt_builder import _build_task_block_dynamic
        from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
            TASK_GOODNIGHT_PROACTIVE_TEMPLATE,
        )

        result = _build_task_block_dynamic(
            sys_prompt_type="goodnight_proactive",
            tod="深夜",
            user_input_mock="[CHARACTER_GOING_TO_SLEEP]",
            reminder_msg=None,
            thought=None,
            specific_instruction=None,
        )

        # 应包含晚安模板的关键标记
        self.assertIn("主动晚安", result)
        self.assertIn("晚安", result)
        # 应与模板内容一致
        self.assertEqual(result, TASK_GOODNIGHT_PROACTIVE_TEMPLATE.format(tod="深夜"))

    def test_sleep_again_proactive_returns_dedicated_template(self):
        """sleep_again_proactive sys_prompt_type 应返回睡回去专属模板。"""
        from core.services.active_care.prompt.prompt_builder import _build_task_block_dynamic
        from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
            TASK_SLEEP_AGAIN_PROACTIVE_TEMPLATE,
        )

        result = _build_task_block_dynamic(
            sys_prompt_type="sleep_again_proactive",
            tod="凌晨3点",
            user_input_mock="[CHARACTER_SLEEP_AGAIN]",
            reminder_msg=None,
            thought=None,
            specific_instruction=None,
        )

        # 应包含睡回去模板的关键标记
        self.assertIn("半夜睡回去", result)
        self.assertIn("睡回去", result)
        # 应与模板内容一致
        self.assertEqual(result, TASK_SLEEP_AGAIN_PROACTIVE_TEMPLATE.format(tod="凌晨3点"))

    def test_goodnight_proactive_template_has_semantic_redline(self):
        """goodnight_proactive 模板必须包含『语义红线』约束，防止 LLM 生成指责用户不睡的内容。

        背景：07-15 23:00 aveline 和 23:30 ling 都生成了"说了晚安又不睡"这种
        语义错误的晚安消息（不是角色自己要睡，反而像在指责用户）。
        根因是 AVELINE_TONE_REFERENCE 全是"傲娇指责用户不睡"风格，
        LLM 把"晚安"+"傲娇"+"指责用户不睡"三者融合，生成了语义错误的内容。
        修复方案是在模板中加【语义红线】明确禁止这类内容。
        """
        from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
            TASK_GOODNIGHT_PROACTIVE_TEMPLATE,
            TASK_SLEEP_AGAIN_PROACTIVE_TEMPLATE,
        )

        # 两个模板都必须包含语义红线约束
        for template in (
            TASK_GOODNIGHT_PROACTIVE_TEMPLATE,
            TASK_SLEEP_AGAIN_PROACTIVE_TEMPLATE,
        ):
            self.assertIn("语义红线", template, "模板必须包含『语义红线』约束")
            self.assertIn("说了晚安又不睡", template, "模板必须明确禁止『说了晚安又不睡』")
            self.assertIn("指责用户不睡", template, "模板必须明确禁止『指责用户不睡』")
            # 必须明确表达"角色自己要睡"的语义
            self.assertIn("角色", template, "模板必须明确『角色』本人要睡的语义")


class TestSleepAgainScenario(unittest.IsolatedAsyncioTestCase):
    """测试半夜睡回去场景。"""

    def setUp(self):
        from core.services.active_care.goodnight_proactive import reset_sent_cache
        reset_sent_cache()

    async def test_sleep_again_uses_sleep_again_sys_prompt_type(self):
        """is_sleep_again=True 时应使用 sleep_again_proactive sys_prompt_type。"""
        from core.services.active_care.goodnight_proactive import (
            trigger_character_goodnight,
        )

        mock_executor = MagicMock()
        mock_executor.trigger_message = AsyncMock(return_value=True)
        mock_ac = MagicMock()
        mock_ac.executor = mock_executor

        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            result = await trigger_character_goodnight("aveline", is_sleep_again=True)

        self.assertTrue(result)
        mock_executor.trigger_message.assert_awaited_once()
        call_kwargs = mock_executor.trigger_message.call_args.kwargs
        self.assertEqual(call_kwargs["sys_prompt_type"], "sleep_again_proactive")
        self.assertIn("睡回去", call_kwargs["specific_instruction"])
        # 半夜睡回去同样必须传 client_type="qq"，确保消息能实时送达 QQ
        self.assertEqual(call_kwargs["client_type"], "qq")

    async def test_sleep_again_not_blocked_by_daily_dedup(self):
        """半夜睡回去不受首次入睡的每日去重限制。"""
        from core.services.active_care.goodnight_proactive import (
            _mark_sent,
            trigger_character_goodnight,
        )

        # 模拟首次入睡已发过（标记每日去重）
        _mark_sent("aveline")

        mock_executor = MagicMock()
        mock_executor.trigger_message = AsyncMock(return_value=True)
        mock_ac = MagicMock()
        mock_ac.executor = mock_executor

        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            # 半夜睡回去应该照常发送，不被每日去重拦住
            result = await trigger_character_goodnight("aveline", is_sleep_again=True)

        self.assertTrue(result)
        mock_executor.trigger_message.assert_awaited_once()

    async def test_sleep_again_cooldown_prevents_rapid_resend(self):
        """半夜睡回去冷却期内应跳过第二次发送。"""
        from core.services.active_care.goodnight_proactive import (
            _mark_sleep_again_sent,
            trigger_character_goodnight,
        )

        # 模拟刚发过睡回去消息（在冷却期内）
        _mark_sleep_again_sent("aveline")

        mock_executor = MagicMock()
        mock_executor.trigger_message = AsyncMock(return_value=True)
        mock_ac = MagicMock()
        mock_ac.executor = mock_executor

        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            result = await trigger_character_goodnight("aveline", is_sleep_again=True)

        # 冷却期内视为成功（已发过），但不应再调用 executor
        self.assertTrue(result)
        mock_executor.trigger_message.assert_not_awaited()


class TestSleepManagerSleepAgainHook(unittest.TestCase):
    """测试 SleepManager 在半夜睡回去场景下的 hook 调用。"""

    def test_on_enter_sleeping_with_is_sleep_again_passes_flag(self):
        """_on_enter_sleeping(is_sleep_again=True) 应传递 is_sleep_again 给 trigger。"""
        from core.services.life_simulation.sleep_models import SleepPhase

        with patch(
            "core.services.active_care.goodnight_proactive.trigger_character_goodnight_async"
        ) as mock_trigger:
            from core.services.life_simulation.sleep_manager import SleepManager

            manager = SleepManager.__new__(SleepManager)
            manager._on_enter_sleeping(
                "aveline", SleepPhase.NIGHT_AWAKE, datetime.now(),
                is_sleep_again=True,
            )

        mock_trigger.assert_called_once_with("aveline", is_sleep_again=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
