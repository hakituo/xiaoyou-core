import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core.agents.chat_agent_components.persona_system.prompt.components.bionic_state import (
    build_bionic_state,
    build_emotion_context,
    build_food_context,
)
from core.agents.chat_agent_components.persona_system.prompt.data import (
    clear_persona_cache,
    get_cached_bionic_state,
)
from core.services.character_daily.reply_hints import build_plan_transition_hint
from core.utils.time_utils import get_current_time


class TestPromptSleepContext(unittest.TestCase):
    def setUp(self) -> None:
        clear_persona_cache()

    def test_ling_night_awake_sleep_context_is_injected_as_facts(self):
        text = build_bionic_state(
            {},
            52,
            48,
            actor_relationships={"aveline|ling": 65},
            role_sleep_states={
                "ling": {
                    "phase": "night_awake",
                    "sleep_debt_hours": 1.2,
                    "sleep_inertia_score": 26,
                    "impact_level": "mild",
                    "nightmare_level": "none",
                }
            },
            current_persona_name="Ling",
        )

        self.assertIn("phase=半夜被叫醒后还醒着", text)
        self.assertIn("wake_recency=fresh", text)
        self.assertIn("sleep_debt_hours=1.2", text)
        self.assertNotIn("回复要", text)
        self.assertNotIn("困意和迷糊感", text)
        self.assertNotIn("你的硬件状态", text)

    def test_night_awake_recency_is_fact_not_style_instruction(self):
        now_ts = get_current_time().timestamp()
        base_state = {"ling": {"phase": "night_awake"}}

        fresh_state = dict(base_state)
        fresh_state["ling"] = {**base_state["ling"], "last_wake_ts": now_ts - 10}
        fresh_text = build_bionic_state(
            {}, 52, 48, role_sleep_states=fresh_state, current_persona_name="Ling"
        )
        self.assertIn("phase=半夜被叫醒后还醒着", fresh_text)
        self.assertIn("wake_recency=fresh", fresh_text)
        self.assertNotIn("回复要", fresh_text)

        stale_state = dict(base_state)
        stale_state["ling"] = {**base_state["ling"], "last_wake_ts": now_ts - 600}
        stale_text = build_bionic_state(
            {}, 52, 48, role_sleep_states=stale_state, current_persona_name="Ling"
        )
        self.assertIn("phase=半夜被叫醒后还醒着", stale_text)
        self.assertNotIn("wake_recency=fresh", stale_text)

    def test_food_context_is_state_not_reply_coaching(self):
        text = build_food_context(
            {
                "hunger": 25,
                "thirst": 70,
                "energy": 55,
                "food_inventory": [{"food_id": "bread", "quantity": 2}],
                "_last_meal": {
                    "food_name": "面包",
                    "source": "user_feed",
                    "reason": "早餐",
                },
            }
        )
        self.assertIn("fullness=25/100 (很饿)", text)
        self.assertIn("food_inventory_count=2", text)
        self.assertIn("last_meal=面包", text)
        self.assertIn("last_meal_source=user_feed", text)
        for phrase in ("可以自己去拿", "可以拒绝", "记得感谢"):
            self.assertNotIn(phrase, text)

    def test_emotion_context_is_state_not_voice_template(self):
        text = build_emotion_context("happy", 72, 88, "{}")
        self.assertIn("emotion=开心", text)
        self.assertIn("intensity=72/100", text)
        self.assertIn("confidence=88/100", text)
        self.assertNotIn("语气轻快", text)
        self.assertNotIn("适当调皮", text)

    def test_cached_state_refreshes_when_sleep_state_changes(self):
        sleeping_text = get_cached_bionic_state(
            {},
            50,
            40,
            role_sleep_states={"ling": {"phase": "sleeping"}},
            current_persona_name="Ling",
            cache_duration=300,
        )
        awake_text = get_cached_bionic_state(
            {},
            50,
            40,
            role_sleep_states={"ling": {"phase": "night_awake"}},
            current_persona_name="Ling",
            cache_duration=300,
        )

        self.assertNotEqual(sleeping_text, awake_text)
        self.assertIn("半夜被叫醒后还醒着", awake_text)

    def test_plan_transition_hint_mentions_sleep_when_next_activity_is_sleep(self):
        hint = build_plan_transition_hint("睡觉", "23:30", 3)

        # 提示只给事实（时间点 + 要去做什么），不再强制「必须体现你已经意识到」；
        # 是否提起由模型按聊天氛围决定（见 .trae/memory/2026-09-20.md）。
        self.assertIn("23:30", hint)
        self.assertIn("睡觉", hint)
        self.assertIn("不提也可以", hint)
        # 睡前的收尾倾向仍要保留，否则角色会直接无视睡觉时间继续聊。
        self.assertIn("准备去睡/去休息了", hint)


if __name__ == "__main__":
    unittest.main()
