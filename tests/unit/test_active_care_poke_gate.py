"""主动关怀四层改造回归测试（2026-09-04）

覆盖用户定义的 7 个行为用例（决策层 / 频控层 / 发送层 / GOODNIGHT 冲突）：

    Case 1  上一条 proactive 用户未回复 → 本轮应 defer
    Case 2  15 分钟前刚问过吃饭 → 不得再次问外卖/吃饭
    Case 3  模型认为不值得发 → 必须 defer，不得产生"先不发了"
    Case 4  生成"浇花呢…你英语复习开始了没？" → validator 不通过
    Case 5  生成"外卖点好没？" → 通过
    Case 6  sleep_session active + morning trigger → 不出现 prompt 冲突
    Case 7  输出含 [GOODNIGHT_GUARD] → 绝对不得进入发送链路

测试只测行为（defer/block/allow），不跑 LLM。
"""

import time
import unittest

from core.services.active_care.cadence.cadence_guard import CadenceGuard
from core.services.active_care.postprocess.send_validator import (
    ActiveCareSendValidator,
)


def _now() -> float:
    return time.time()


class CadenceGuardUnansweredCase(unittest.TestCase):
    """Case 1：上一条 proactive 用户未回复 → 本轮应 defer（提问类）"""

    def test_unanswered_suppresses_curious_question(self):
        guard = CadenceGuard()
        state = {
            "last_proactive_at": _now() - 300,   # 5 分钟前发过
            "last_proactive_type": "curious_question",
            "last_proactive_replied": False,      # 用户没回
        }
        verdict = guard.evaluate(
            now=_now(),
            chosen_action="curious_question",
            proactive_state=state,
        )
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.reason, "last_proactive_unanswered")

    def test_unanswered_does_not_suppress_after_reply(self):
        guard = CadenceGuard()
        state = {
            "last_proactive_at": _now() - 300,
            "last_proactive_type": "curious_question",
            "last_proactive_replied": True,       # 用户回了
        }
        # 回复后不再因"未回复"抑制，但仍受全局冷却限制
        verdict = guard.evaluate(
            now=_now(),
            chosen_action="curious_question",
            proactive_state=state,
        )
        self.assertFalse(verdict.allowed)
        self.assertNotEqual(verdict.reason, "last_proactive_unanswered")


class CadenceGuardSameTopicCase(unittest.TestCase):
    """Case 2：刚问过吃饭/外卖 → 不得再问吃饭/外卖（换措辞也不行）"""

    def _state_after_meal_45min_ago(self) -> dict:
        return {
            "last_proactive_at": _now() - 45 * 60,   # 45 分钟前（全局冷却已过）
            "last_proactive_type": "share_thought",
            "last_proactive_replied": True,
            "last_sent_topic": "curious_question:food",  # 上一条是吃饭话题
        }

    def test_same_topic_group_blocked(self):
        guard = CadenceGuard()
        verdict = guard.evaluate(
            now=_now(),
            chosen_action="curious_question",
            proactive_state=self._state_after_meal_45min_ago(),
            candidate_topic_label="curious_question:food",  # 又想问吃饭
        )
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.reason, "cadence_same_topic_group")

    def test_different_topic_allowed(self):
        guard = CadenceGuard()
        verdict = guard.evaluate(
            now=_now(),
            chosen_action="curious_question",
            proactive_state=self._state_after_meal_45min_ago(),
            candidate_topic_label="curious_question:study",  # 换成学习话题
        )
        self.assertTrue(verdict.allowed)

    def test_global_cooldown_blocks_15min_ago(self):
        """15 分钟内刚发过主动消息：全局冷却挡在第 2 层。"""
        guard = CadenceGuard()
        state = {
            "last_proactive_at": _now() - 15 * 60,   # 15 分钟前
            "last_proactive_type": "curious_question",
            "last_proactive_replied": True,
        }
        verdict = guard.evaluate(
            now=_now(),
            chosen_action="share_thought",
            proactive_state=state,
        )
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.reason, "cadence_global_cooldown")

    def test_daily_curious_cap(self):
        """每日好奇提问软上限：当天 3 条后第 4 条 defer。"""
        guard = CadenceGuard()
        state = {
            "last_proactive_replied": True,
            "last_proactive_at": _now() - 6 * 3600,  # 6 小时前，各冷却已过
            "last_proactive_type": "share_thought",
            "today_sent_events": [
                {"sys_prompt_type": "curious_question"},
                {"sys_prompt_type": "curious_question"},
                {"sys_prompt_type": "curious_question"},
            ],
        }
        verdict = guard.evaluate(
            now=_now(),
            chosen_action="curious_question",
            proactive_state=state,
        )
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.reason, "cadence_curious_question_daily_cap")


class SendValidatorBehaviorCase(unittest.TestCase):
    """Case 4 / 5 / 7：发送层硬 Gate 行为"""

    def setUp(self):
        self.validator = ActiveCareSendValidator()

    def test_short_poke_passes(self):
        """Case 5：'外卖点好没？' → 通过"""
        result = self.validator.validate("外卖点好没？", "curious_question")
        self.assertTrue(result.allowed)

    def test_short_study_poke_passes(self):
        result = self.validator.validate("英语开始背没？", "curious_question")
        self.assertTrue(result.allowed)

    def test_padded_poke_rejected(self):
        """Case 4：'浇花呢…你英语复习开始了没？' → 不通过"""
        padded = "浇花呢，刚看到阳台上的绿萝又抽新芽了。你英语复习开始了没？"
        result = self.validator.validate(padded, "curious_question")
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "padded_poke_style")

    def test_transition_padded_poke_rejected(self):
        padded = "话说，刚才不是说要看外卖吗，看好没？别告诉我滑了十分钟还没决定。"
        result = self.validator.validate(padded, "curious_question")
        self.assertFalse(result.allowed)

    def test_overlong_poke_rejected(self):
        long_text = "我跟你说今天天气真的很好很适合出门去公园走走顺便买一杯奶茶再绕去书店看看新出的那本小说你有没有兴趣"
        result = self.validator.validate(long_text, "curious_question")
        self.assertFalse(result.allowed)
        self.assertTrue(str(result.reason).startswith("excessive_length"))

    def test_meta_marker_never_reaches_send_chain(self):
        """Case 7：[GOODNIGHT_GUARD] 泄漏 → 拦截，绝不进入发送链路"""
        leaky = "[GOODNIGHT_GUARD] 早啊，我醒了"
        result = self.validator.validate(leaky, "good_morning_proactive")
        self.assertFalse(result.allowed)
        self.assertTrue(str(result.reason).startswith("internal_meta_marker"))

    def test_no_defer_leak_as_text(self):
        """决策过程表述（先不发了/等他回）不得作为消息内容发出。"""
        result = self.validator.validate("先不发了，等你忙完再聊", "curious_question")
        self.assertFalse(result.allowed)
        result2 = self.validator.validate("这轮不适合发，稍后再看", "share_thought")
        self.assertFalse(result2.allowed)

    def test_m3_english_cot_is_rejected_for_length_exempt_intent(self):
        """M3 把英文推理塞进正文时，即使健康提醒豁免长度也必须拦截。"""
        leaky = (
            'The user said "早安" a few minutes ago. Now I need to send an active '
            "care message. Let me analyze the situation: I already asked about food."
        )
        result = self.validator.validate(leaky, "user_health_reminder")
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "prompt_or_reasoning_leak")

    def test_absolute_length_cap_applies_to_exempt_intent(self):
        """固定任务只豁免 40 字短门，不得绕过全类型绝对上限。"""
        result = self.validator.validate("普通内容" * 301, "user_health_reminder")
        self.assertFalse(result.allowed)
        self.assertTrue(str(result.reason).startswith("excessive_length_absolute"))


class DeferLeakParserCase(unittest.TestCase):
    """Case 3：模型把"先不发了"写进 text → 归一化强制降级为 defer"""

    def test_defer_phrase_in_text_downgraded_to_defer(self):
        from core.services.active_care.decision.decision_output_parser import (
            _normalize_decision_dict,
        )

        decision = _normalize_decision_dict(
            {
                "thought": "模型觉得不该发",
                "action": "send_active_care",
                "text": "先不发了，等他回复再聊",
                "should_send": True,
                "intent": "curious_question",
            },
            chosen_action="curious_question",
        )
        self.assertEqual(decision["action"], "defer_active_care")
        self.assertFalse(decision["should_send"])
        self.assertEqual(decision["text"], "")

    def test_explicit_defer_action(self):
        from core.services.active_care.decision.decision_output_parser import (
            _normalize_decision_dict,
        )

        decision = _normalize_decision_dict(
            {
                "thought": "没有明确价值",
                "action": "defer_active_care",
                "defer_reason": "没有值得说的内容",
                "retry_after_minutes": 45,
                "should_send": False,
                "intent": "curious_question",
            },
            chosen_action="curious_question",
        )
        self.assertEqual(decision["action"], "defer_active_care")
        self.assertFalse(decision["should_send"])
        self.assertEqual(decision["defer_reason"], "没有值得说的内容")
        # Prompt v2：retry 统一为秒级 retry_after_seconds（兼容分钟级旧字段折算）
        self.assertEqual(decision["retry_after_seconds"], 2700)

    def test_send_action_text_is_dropped(self):
        """Prompt v2：Decision 不产最终文本，send 时不携带 text。"""
        from core.services.active_care.decision.decision_output_parser import (
            _normalize_decision_dict,
        )

        decision = _normalize_decision_dict(
            {
                "thought": "正好问下",
                "action": "send_active_care",
                "text": "英语开始背没？",
                "should_send": True,
                "intent": "curious_question",
            },
            chosen_action="curious_question",
        )
        self.assertEqual(decision["action"], "send_active_care")
        self.assertTrue(decision["should_send"])
        # 最终文本由生成层在 send 后产出，决策输出必须丢弃 text
        self.assertEqual(decision["text"], "")


class SleepSafeMorningCase(unittest.TestCase):
    """Case 6：sleep_session active + morning trigger → 不出现 prompt 冲突"""

    @classmethod
    def setUpClass(cls):
        from core.services.active_care.prompt import prompt_builder
        cls.builder = prompt_builder

    def test_sleep_session_active_uses_sleep_safe_template(self):
        block = self.builder._build_task_block_dynamic(
            "good_morning_proactive",
            "07:00",
            "[GOOD_MORNING_TRIGGER]",
            reminder_msg=None,
            thought=None,
            sleep_session_active=True,
        )
        # sleep-safe 模板只表达"角色自己醒了"，不得询问/暗示用户该醒
        self.assertIn("你（角色本人）刚醒", block)
        self.assertIn("不得询问或暗示用户应该醒、应该起床", block)
        # 不得出现普通早安模板里针对用户的起床问候冲突指令
        self.assertNotIn("给用户发一句简短的起床问候", block)

    def test_sleep_session_inactive_uses_normal_template(self):
        block = self.builder._build_task_block_dynamic(
            "good_morning_proactive",
            "07:00",
            "[GOOD_MORNING_TRIGGER]",
            reminder_msg=None,
            thought=None,
            sleep_session_active=False,
        )
        # 用户清醒场景保持原有起床问候行为
        self.assertIn("你（角色本人）刚睡醒", block)


class TopicGroupCase(unittest.TestCase):
    """题材分组：吃饭 / 外卖 归入同一个 meal 组，防换措辞绕过冷却"""

    def test_food_and_delivery_same_group(self):
        from core.services.active_care.cadence.topic_groups import (
            group_for_subtopic,
        )

        # classify_topic 对"吃饭/外卖"都判 FOOD → subtopic food → group meal
        self.assertEqual(group_for_subtopic("food"), "meal")

    def test_meal_group_is_cooldown_eligible(self):
        from core.services.active_care.cadence.topic_groups import (
            is_eligible_for_group_cooldown,
        )

        self.assertTrue(is_eligible_for_group_cooldown("meal"))
        self.assertFalse(is_eligible_for_group_cooldown("general"))


if __name__ == "__main__":
    unittest.main()
