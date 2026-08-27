import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core.agents.chat_agent_components.persona_system.prompt.components.bionic_state import (
    build_bionic_state,
)
from core.agents.chat_agent_components.persona_system.prompt.data import (
    clear_persona_cache,
    get_cached_bionic_state,
)
from core.services.character_daily.reply_hints import build_plan_transition_hint


class TestPromptSleepContext(unittest.TestCase):
    def setUp(self) -> None:
        clear_persona_cache()

    def test_ling_night_awake_sleep_context_is_injected(self):
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

        self.assertIn("半夜被叫醒后还醒着", text)
        self.assertIn("困意和迷糊感", text)
        self.assertNotIn("你的硬件状态", text)

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

        self.assertIn("不要完全不提", hint)
        self.assertIn("准备去睡/去休息了", hint)


if __name__ == "__main__":
    unittest.main()
