"""验证"做事结束主动处理累积消息"和"回归消息 LLM 真判断挽留"两项优化。

验证点：

任务 1（做事结束主动处理累积消息）：
1. _classify_done_transition 正确分类"做事结束"切换
   - BUSY → CHAT_ELIGIBLE 返回 True
   - CHAT_ELIGIBLE → BUSY 返回 False
   - DND → CHAT_ELIGIBLE 返回 False（DND 走 morning_after）
   - 相同活动返回 False
2. append_pending_message 加 role_id 参数后向后兼容（旧调用方式仍可工作）
3. get_pending_by_role_id 正确按 role 过滤累积消息
4. check_and_process_pending_on_activity_done:
   - BUSY → CHAT 触发主动消息
   - CHAT → BUSY 不触发
   - DND 累积被跳过
   - 条数不足时跳过
   - 去重冷却期内不重复触发
   - 发送后清空对应 cid 的累积
   - 配置 disabled 时不触发
5. build_busy_done_active_instruction 输出包含累积消息和活动动词

任务 2（让 LLM 真判断挽留 vs 道别）：
6. _WORK_RETURN_TEMPLATE 包含"挽留"判断关键词，去掉"必须明确提到你要回去"强约束
7. _ACTIVITY_START_FAREWELL_TEMPLATE 包含挽留判断指引
8. build_return_instruction(work) 输出包含挽留判断
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


class TestClassifyDoneTransition(unittest.TestCase):
    """测试"做事结束"切换分类。"""

    def test_busy_to_chat_eligible_is_true(self):
        """从学习切到空闲应为做事结束（True）。"""
        from core.services.character_daily.activity_transition import (
            _classify_done_transition,
        )
        from core.services.character_daily.activity_model import ActivityType

        self.assertTrue(_classify_done_transition(ActivityType.STUDYING, ActivityType.IDLE))
        self.assertTrue(_classify_done_transition(ActivityType.COOKING, ActivityType.READING))

    def test_chat_to_busy_is_false(self):
        """从空闲切到学习不是做事结束（False）。"""
        from core.services.character_daily.activity_transition import (
            _classify_done_transition,
        )
        from core.services.character_daily.activity_model import ActivityType

        self.assertFalse(_classify_done_transition(ActivityType.IDLE, ActivityType.STUDYING))

    def test_dnd_to_chat_is_false(self):
        """从睡觉切到空闲不是"做事结束"（DND 走 morning_after，不在这里处理）。"""
        from core.services.character_daily.activity_transition import (
            _classify_done_transition,
        )
        from core.services.character_daily.activity_model import ActivityType

        self.assertFalse(_classify_done_transition(ActivityType.SLEEPING, ActivityType.IDLE))
        self.assertFalse(_classify_done_transition(ActivityType.NAPPING, ActivityType.IDLE))

    def test_same_activity_is_false(self):
        """相同活动不算切换。"""
        from core.services.character_daily.activity_transition import (
            _classify_done_transition,
        )
        from core.services.character_daily.activity_model import ActivityType

        self.assertFalse(_classify_done_transition(ActivityType.IDLE, ActivityType.IDLE))
        self.assertFalse(_classify_done_transition(ActivityType.STUDYING, ActivityType.STUDYING))


class TestAppendPendingMessageRoleId(unittest.TestCase):
    """测试 append_pending_message 加 role_id 后的查询。"""

    def setUp(self):
        from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
            clear_pending_messages,
        )
        clear_pending_messages("test_cid_aveline")
        clear_pending_messages("test_cid_ling")
        clear_pending_messages("test_cid_no_role")

    def tearDown(self):
        from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
            clear_pending_messages,
        )
        clear_pending_messages("test_cid_aveline")
        clear_pending_messages("test_cid_ling")
        clear_pending_messages("test_cid_no_role")

    def test_get_pending_by_role_id_filters_correctly(self):
        """get_pending_by_role_id 正确按 role 过滤。"""
        from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
            append_pending_message,
            get_pending_by_role_id,
        )

        append_pending_message("test_cid_aveline", "你在干嘛", "studying", "aveline")
        append_pending_message("test_cid_aveline", "今天吃啥", "studying", "aveline")
        append_pending_message("test_cid_ling", "宝，睡了没", "cooking", "ling")

        aveline_pending = get_pending_by_role_id("aveline")
        ling_pending = get_pending_by_role_id("ling")
        unknown_pending = get_pending_by_role_id("unknown_role")

        self.assertEqual(len(aveline_pending), 1)
        self.assertEqual(aveline_pending[0]["cid"], "test_cid_aveline")
        self.assertEqual(len(aveline_pending[0]["messages"]), 2)
        self.assertEqual(aveline_pending[0]["activity"], "studying")

        self.assertEqual(len(ling_pending), 1)
        self.assertEqual(ling_pending[0]["cid"], "test_cid_ling")
        self.assertEqual(ling_pending[0]["activity"], "cooking")

        self.assertEqual(unknown_pending, [])

    def test_get_pending_by_role_id_handles_empty_role(self):
        """空 role_id 返回空列表。"""
        from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
            get_pending_by_role_id,
        )

        self.assertEqual(get_pending_by_role_id(""), [])
        self.assertEqual(get_pending_by_role_id(None), [])

    def test_append_pending_message_backward_compatible(self):
        """不传 role_id 时旧调用方式仍可工作（不会崩）。"""
        from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
            append_pending_message,
            get_pending_messages,
            get_pending_by_role_id,
        )

        # 不传 role_id（旧调用方式）
        append_pending_message("test_cid_no_role", "你好", "studying")
        # 旧接口仍能取到
        self.assertEqual(get_pending_messages("test_cid_no_role"), ["你好"])
        # 按 role 反查时返回空（因为没标 role_id）
        self.assertEqual(get_pending_by_role_id("aveline"), [])


class TestCheckAndProcessPendingOnActivityDone(unittest.TestCase):
    """测试 check_and_process_pending_on_activity_done 主流程。"""

    def setUp(self):
        from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
            _DND_PENDING,
        )
        # 清空整个 _DND_PENDING 避免测试间相互影响
        _DND_PENDING.clear()
        from core.services.character_daily.activity_transition import (
            reset_done_pending_state,
        )
        reset_done_pending_state()
        # 测试专用 cid
        self._test_cids = [
            "test_done_cid_aveline_1",
            "test_done_cid_aveline_2",
            "test_done_cid_ling_1",
            "test_done_cid_dnd_1",
            "test_done_cid_short_1",
        ]

    def tearDown(self):
        from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
            _DND_PENDING,
        )
        _DND_PENDING.clear()
        from core.services.character_daily.activity_transition import (
            reset_done_pending_state,
        )
        reset_done_pending_state()

    def _build_mock_active_care(self, delivered: bool = True):
        """构建一个 mock 的 active_care service。"""
        ac = MagicMock()
        ac.executor = MagicMock()
        ac.executor.trigger_message = AsyncMock(return_value=delivered)
        return ac

    def test_busy_to_chat_triggers_proactive_message(self):
        """BUSY → CHAT 切换应触发主动消息。"""
        from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
            append_pending_message,
        )
        from core.services.character_daily.activity_model import ActivityType
        from core.services.character_daily.activity_transition import (
            check_and_process_pending_on_activity_done,
        )
        from core.services.character_daily.config import ReplyPolicyConfig

        append_pending_message(
            "test_done_cid_aveline_1",
            "你做题累不累",
            "studying",
            "aveline",
        )

        mock_ac = self._build_mock_active_care()
        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ), patch(
            "core.services.character_daily.activity_return.instruction.resolve_persona_filename",
            return_value="qq/Aveline_QQ_Master.json",
        ):
            result = asyncio.run(check_and_process_pending_on_activity_done(
                engine=MagicMock(),
                role_id="aveline",
                prev_activity=ActivityType.STUDYING,
                new_activity=ActivityType.IDLE,
                config=ReplyPolicyConfig(),
            ))

        self.assertEqual(result, 1)
        mock_ac.executor.trigger_message.assert_awaited_once()
        # 验证调用参数
        call_kwargs = mock_ac.executor.trigger_message.call_args.kwargs
        self.assertEqual(call_kwargs["sys_prompt_type"], "activity_return_proactive")
        self.assertEqual(call_kwargs["user_input_mock"], "[BUSY_DONE_PENDING]")
        self.assertEqual(call_kwargs["persona_filename"], "qq/Aveline_QQ_Master.json")
        self.assertTrue(call_kwargs["self_activity"])
        # specific_instruction 包含累积消息内容
        self.assertIn("你做题累不累", call_kwargs["specific_instruction"])

    def test_chat_to_busy_does_not_trigger(self):
        """CHAT → BUSY 切换不应触发。"""
        from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
            append_pending_message,
        )
        from core.services.character_daily.activity_model import ActivityType
        from core.services.character_daily.activity_transition import (
            check_and_process_pending_on_activity_done,
        )
        from core.services.character_daily.config import ReplyPolicyConfig

        append_pending_message("test_done_cid_aveline_1", "嗯", "idle", "aveline")

        mock_ac = self._build_mock_active_care()
        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            result = asyncio.run(check_and_process_pending_on_activity_done(
                engine=MagicMock(),
                role_id="aveline",
                prev_activity=ActivityType.IDLE,
                new_activity=ActivityType.STUDYING,
                config=ReplyPolicyConfig(),
            ))

        self.assertEqual(result, 0)
        mock_ac.executor.trigger_message.assert_not_awaited()

    def test_dnd_pending_skipped(self):
        """DND 期间的累积（activity=sleeping）应被跳过，留给 morning_after 处理。"""
        from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
            append_pending_message,
            get_pending_messages,
        )
        from core.services.character_daily.activity_model import ActivityType
        from core.services.character_daily.activity_transition import (
            check_and_process_pending_on_activity_done,
        )
        from core.services.character_daily.config import ReplyPolicyConfig

        # DND 期间累积（activity=sleeping）
        append_pending_message("test_done_cid_dnd_1", "半夜留言", "sleeping", "aveline")

        mock_ac = self._build_mock_active_care()
        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ), patch(
            "core.services.character_daily.activity_return.instruction.resolve_persona_filename",
            return_value="qq/Aveline_QQ_Master.json",
        ):
            result = asyncio.run(check_and_process_pending_on_activity_done(
                engine=MagicMock(),
                role_id="aveline",
                prev_activity=ActivityType.STUDYING,
                new_activity=ActivityType.IDLE,
                config=ReplyPolicyConfig(),
            ))

        self.assertEqual(result, 0)
        mock_ac.executor.trigger_message.assert_not_awaited()
        # DND 累积不应被清空，留给 morning_after 处理
        self.assertEqual(get_pending_messages("test_done_cid_dnd_1"), ["半夜留言"])

    def test_min_count_filter(self):
        """累积条数少于 min_count 时跳过触发。"""
        from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
            append_pending_message,
            get_pending_messages,
        )
        from core.services.character_daily.activity_model import ActivityType
        from core.services.character_daily.activity_transition import (
            check_and_process_pending_on_activity_done,
        )
        from core.services.character_daily.config import ReplyPolicyConfig

        append_pending_message("test_done_cid_short_1", "嗯", "studying", "aveline")

        # min_count = 2，单条不触发
        config = ReplyPolicyConfig(activity_done_pending_min_count=2)
        mock_ac = self._build_mock_active_care()
        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ), patch(
            "core.services.character_daily.activity_return.instruction.resolve_persona_filename",
            return_value="qq/Aveline_QQ_Master.json",
        ):
            result = asyncio.run(check_and_process_pending_on_activity_done(
                engine=MagicMock(),
                role_id="aveline",
                prev_activity=ActivityType.STUDYING,
                new_activity=ActivityType.IDLE,
                config=config,
            ))

        self.assertEqual(result, 0)
        mock_ac.executor.trigger_message.assert_not_awaited()
        # 累积消息保留
        self.assertEqual(get_pending_messages("test_done_cid_short_1"), ["嗯"])

    def test_cooldown_dedup(self):
        """同 role + 同 prev_activity 在冷却期内不重复触发。"""
        from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
            append_pending_message,
        )
        from core.services.character_daily.activity_model import ActivityType
        from core.services.character_daily.activity_transition import (
            check_and_process_pending_on_activity_done,
        )
        from core.services.character_daily.config import ReplyPolicyConfig

        append_pending_message("test_done_cid_aveline_1", "在吗", "studying", "aveline")

        mock_ac = self._build_mock_active_care()
        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ), patch(
            "core.services.character_daily.activity_return.instruction.resolve_persona_filename",
            return_value="qq/Aveline_QQ_Master.json",
        ):
            config = ReplyPolicyConfig(activity_done_pending_cooldown_seconds=60.0)
            # 第一次触发：应发送
            r1 = asyncio.run(check_and_process_pending_on_activity_done(
                engine=MagicMock(),
                role_id="aveline",
                prev_activity=ActivityType.STUDYING,
                new_activity=ActivityType.IDLE,
                config=config,
            ))
            self.assertEqual(r1, 1)

            # 第二次：累积已被清空，再追加一条再触发，应在冷却期内被跳过
            append_pending_message("test_done_cid_aveline_2", "再问一下", "studying", "aveline")
            r2 = asyncio.run(check_and_process_pending_on_activity_done(
                engine=MagicMock(),
                role_id="aveline",
                prev_activity=ActivityType.STUDYING,
                new_activity=ActivityType.IDLE,
                config=config,
            ))
            self.assertEqual(r2, 0)

    def test_disabled_config_does_not_trigger(self):
        """配置 disabled 时不触发。"""
        from core.interfaces.websocket.adapters.handlers.chat_reply_runtime import (
            append_pending_message,
        )
        from core.services.character_daily.activity_model import ActivityType
        from core.services.character_daily.activity_transition import (
            check_and_process_pending_on_activity_done,
        )
        from core.services.character_daily.config import ReplyPolicyConfig

        append_pending_message("test_done_cid_aveline_1", "在吗", "studying", "aveline")
        config = ReplyPolicyConfig(activity_done_pending_process_enabled=False)
        mock_ac = self._build_mock_active_care()
        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ):
            result = asyncio.run(check_and_process_pending_on_activity_done(
                engine=MagicMock(),
                role_id="aveline",
                prev_activity=ActivityType.STUDYING,
                new_activity=ActivityType.IDLE,
                config=config,
            ))
        self.assertEqual(result, 0)
        mock_ac.executor.trigger_message.assert_not_awaited()


class TestBusyDoneActiveInstruction(unittest.TestCase):
    """测试 build_busy_done_active_instruction 输出。"""

    def test_instruction_contains_messages_and_verbs(self):
        """instruction 应包含累积消息、进行时动词、完成时动词。"""
        from core.services.character_daily.activity_return.instruction import (
            build_busy_done_active_instruction,
        )

        result = build_busy_done_active_instruction(
            role_id="aveline",
            activity="studying",
            pending_messages=["你在干嘛", "今天吃啥"],
        )
        # 包含 role_id
        self.assertIn("aveline", result)
        # 包含进行时动词（学习）
        self.assertIn("学习", result)
        # 包含完成时动词（做完题）
        self.assertIn("做完题", result)
        # 包含每条累积消息
        self.assertIn("你在干嘛", result)
        self.assertIn("今天吃啥", result)
        # 包含消息数
        self.assertIn("2 条消息", result)

    def test_instruction_truncates_long_messages(self):
        """长消息应被截断到 200 字 + 省略号。"""
        from core.services.character_daily.activity_return.instruction import (
            build_busy_done_active_instruction,
        )

        long_msg = "a" * 300
        result = build_busy_done_active_instruction(
            role_id="aveline",
            activity="studying",
            pending_messages=[long_msg],
        )
        self.assertIn("...", result)
        # 截断后长度不超过 200 + 省略号
        self.assertIn("a" * 200 + "...", result)


class TestWorkReturnTemplateRetainsReretention(unittest.TestCase):
    """任务 2：验证回归消息模板让 LLM 真判断挽留 vs 道别。"""

    def test_work_return_template_contains_retention_judgment(self):
        """_WORK_RETURN_TEMPLATE 应包含挽留判断指引。"""
        from core.services.character_daily.activity_return.instruction import (
            _WORK_RETURN_TEMPLATE,
        )
        template = _WORK_RETURN_TEMPLATE
        # 必须包含"挽留"判断关键词
        self.assertIn("挽留", template)
        # 必须包含"再陪一会儿"或"顺延"作为顺延选项
        self.assertTrue(
            "再陪" in template or "顺延" in template or "往后推" in template,
            "template 应包含顺延选项",
        )
        # 必须给出明确挽留示例
        self.assertTrue(
            "再聊会" in template or "别走" in template,
            "template 应给出挽留示例",
        )

    def test_work_return_instruction_includes_judgment_branches(self):
        """build_return_instruction(work) 输出应含挽留判断分支。"""
        from core.services.character_daily.activity_return.instruction import (
            build_return_instruction,
        )

        result = build_return_instruction("aveline", "studying", "work")
        # 应有"如果...挽留"和"如果...没有挽留"两条分支
        self.assertIn("挽留", result)
        self.assertIn("学习", result)  # activity_verb 进行时
        # 应提到"明确提一句要去做什么"作为回去选项的指引（不再是"必须明确提到"的强约束）
        self.assertTrue(
            "明确提到" in result or "明确提一句" in result,
            "回去分支应有明确指引",
        )

    def test_activity_start_farewell_template_has_retention_branch(self):
        """_ACTIVITY_START_FAREWELL_TEMPLATE 应包含挽留判断指引。"""
        from core.services.character_daily.activity_return.instruction import (
            _ACTIVITY_START_FAREWELL_TEMPLATE,
        )
        template = _ACTIVITY_START_FAREWELL_TEMPLATE
        # 应有挽留/还想继续聊的判断分支
        self.assertTrue(
            "挽留" in template or "还想继续聊" in template,
            "template 应包含挽留/还想继续聊判断",
        )
        # 应有"简单回应"/"已道别"作为告别分支
        self.assertTrue(
            "简单回应" in template or "已道别" in template or "聊得差不多" in template,
            "template 应包含告别判断分支",
        )


class TestWorkReturnDecideDefer(unittest.TestCase):
    """任务 3：验证发送"回去做事"前的 LLM 顺延决策。"""

    def _build_mock_ac(self, history):
        """构建带历史上下文的 mock active_care。"""
        ac = MagicMock()
        ac.settings = MagicMock()
        ac.executor = MagicMock()
        context = MagicMock()
        context.get_latest_history_for_conversation = AsyncMock(return_value=history)
        ac.executor.context = context
        return ac

    def _mock_llm(self, raw_response):
        """patch llm.chat 返回指定文本。"""
        llm = MagicMock()
        llm.chat = AsyncMock(return_value=raw_response)
        patch_target = patch(
            "core.llm.get_llm_module",
            return_value=llm,
        )
        return patch_target

    def test_defer_true_when_user_retains(self):
        """LLM 判定 defer=true 时，应顺延（返回 True）。"""
        from core.services.character_daily.activity_return.core import (
            _decide_work_return_should_defer,
        )

        history = [
            {"role": "user", "content": "别走嘛再聊一会"},
            {"role": "assistant", "content": "好呀"},
        ]
        ac = self._build_mock_ac(history)
        with self._mock_llm('{"defer": true, "reason": "用户在挽留"}'):
            result = asyncio.run(_decide_work_return_should_defer(
                ac, "test_cid_defer_1", "aveline", "studying",
            ))
        self.assertTrue(result)

    def test_defer_false_when_user_says_goodbye(self):
        """LLM 判定 defer=false 时，应正常发送（返回 False）。"""
        from core.services.character_daily.activity_return.core import (
            _decide_work_return_should_defer,
        )

        history = [
            {"role": "user", "content": "嗯嗯你去吧拜拜"},
            {"role": "assistant", "content": "那我去啦"},
        ]
        ac = self._build_mock_ac(history)
        with self._mock_llm('{"defer": false, "reason": "用户已道别"}'):
            result = asyncio.run(_decide_work_return_should_defer(
                ac, "test_cid_defer_2", "aveline", "studying",
            ))
        self.assertFalse(result)

    def test_defer_false_on_no_history(self):
        """无历史上下文时回退为正常发送（返回 False）。"""
        from core.services.character_daily.activity_return.core import (
            _decide_work_return_should_defer,
        )

        ac = self._build_mock_ac([])
        result = asyncio.run(_decide_work_return_should_defer(
            ac, "test_cid_defer_3", "aveline", "studying",
        ))
        self.assertFalse(result)

    def test_defer_false_on_llm_error(self):
        """LLM 异常时回退为正常发送（返回 False）。"""
        from core.services.character_daily.activity_return.core import (
            _decide_work_return_should_defer,
        )

        history = [{"role": "user", "content": "嗯"}]
        ac = self._build_mock_ac(history)
        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=RuntimeError("boom"))
        with patch(
            "core.llm.get_llm_module",
            return_value=llm,
        ):
            result = asyncio.run(_decide_work_return_should_defer(
                ac, "test_cid_defer_4", "aveline", "studying",
            ))
        self.assertFalse(result)

    def test_send_work_return_defers_when_user_retains(self):
        """send_activity_return_message 在 LLM 判定挽留时顺延发送。"""
        from core.services.character_daily.activity_return.core import (
            send_activity_return_message,
        )

        mock_ac = self._build_mock_ac([
            {"role": "user", "content": "别走再聊会"},
        ])
        mock_ac.executor.trigger_message = AsyncMock(return_value=True)
        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ), patch(
            "core.services.character_daily.activity_return.core.resolve_persona_filename",
            return_value="qq/Aveline_QQ_Master.json",
        ), self._mock_llm('{"defer": true, "reason": "用户在挽留"}'), patch(
            "core.services.character_daily.interrupt_window.extend_manual_interrupt_window",
            return_value={"expire_ts": 9999999999.0},
        ), patch(
            "core.services.character_daily.activity_return.core.schedule_activity_return",
            new=AsyncMock(),
        ):
            result = asyncio.run(send_activity_return_message(
                conversation_id="test_cid_defer_5",
                role_id="aveline",
                activity="studying",
                return_type="work",
            ))

        self.assertFalse(result["delivered"])
        self.assertEqual(result["reason"], "user_retention_deferred")
        # 顺延时不应真正发送消息
        mock_ac.executor.trigger_message.assert_not_awaited()

    def test_send_work_return_sends_when_not_retained(self):
        """LLM 判定可回去时正常发送。"""
        from core.services.character_daily.activity_return.core import (
            send_activity_return_message,
        )

        mock_ac = self._build_mock_ac([
            {"role": "user", "content": "嗯嗯拜拜"},
        ])
        mock_ac.executor.trigger_message = AsyncMock(return_value=True)
        with patch(
            "core.services.active_care.core.service.get_active_care_service",
            return_value=mock_ac,
        ), patch(
            "core.services.character_daily.activity_return.core.resolve_persona_filename",
            return_value="qq/Aveline_QQ_Master.json",
        ), self._mock_llm('{"defer": false, "reason": "用户已道别"}'):
            result = asyncio.run(send_activity_return_message(
                conversation_id="test_cid_defer_6",
                role_id="aveline",
                activity="studying",
                return_type="work",
            ))

        self.assertTrue(result["delivered"])
        mock_ac.executor.trigger_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
