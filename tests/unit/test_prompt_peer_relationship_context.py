import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core.agents.chat_agent_components.persona_system.prompt.components.bionic_state import (  # noqa: E402
    build_bionic_state,
)
from core.services.dual_role.personas import (  # noqa: E402
    get_peer_address_term,
    lookup_relationship_value,
    relationship_key,
)


class TestPeerRelationshipContext(unittest.TestCase):
    """关系块必须按注册表走：有互识关系才注入，没有就走单角色默认（不注入）。"""

    def test_aveline_gets_ling_relation(self):
        text = build_bionic_state(
            {}, 52, 48,
            actor_relationships={"aveline|ling": 85},
            current_persona_name="七濑 Aveline",
        )
        self.assertIn("和Ling的关系：亲密无间", text)

    def test_ling_gets_aveline_relation(self):
        text = build_bionic_state(
            {}, 52, 48,
            actor_relationships={"aveline|ling": 65},
            current_persona_name="Ling",
        )
        self.assertIn("和Aveline的关系：非常要好", text)

    def test_single_role_ye_gets_no_peer_relation(self):
        """Ye在注册表里没有互识关系，不能凭空冒出"Aveline/Ling"。"""
        text = build_bionic_state(
            {}, 52, 48,
            actor_relationships={"aveline|ling": 90},
            current_persona_name="Ye",
        )
        self.assertNotIn("Aveline", text)
        self.assertNotIn("Ling", text)
        self.assertNotIn("的关系", text)

    def test_single_role_by_persona_filename_gets_no_peer_relation(self):
        text = build_bionic_state(
            {}, 52, 48,
            actor_relationships={"aveline|ling": 90},
            current_persona_name="core_ye.json",
        )
        self.assertNotIn("Aveline", text)
        self.assertNotIn("的关系", text)

    def test_unknown_persona_gets_no_peer_relation(self):
        text = build_bionic_state(
            {}, 52, 48,
            actor_relationships={"aveline|ling": 90},
            current_persona_name="某个未注册角色",
        )
        self.assertNotIn("的关系", text)

    def test_no_relationship_data_gets_no_relation_line(self):
        text = build_bionic_state({}, 52, 48, current_persona_name="Ling")
        self.assertNotIn("的关系", text)

    def test_hardware_state_only_for_bionic_body(self):
        """硬件指标只给仿生体（aveline），Ling/Ye这类真人向角色不该看到。"""
        aveline_text = build_bionic_state({}, 52, 48, current_persona_name="七濑 Aveline")
        self.assertIn("你的硬件状态", aveline_text)
        for name in ("Ling", "Ye"):
            self.assertNotIn(
                "你的硬件状态", build_bionic_state({}, 52, 48, current_persona_name=name)
            )


class TestSleepContextIsolation(unittest.TestCase):
    """睡眠状态按角色自己的 role_id 取，不能回落到别的角色。"""

    def test_ye_reads_own_sleep_state_not_aveline(self):
        text = build_bionic_state(
            {}, 52, 48,
            role_sleep_states={
                "aveline": {"phase": "sleeping"},
                "ye": {"phase": "night_awake"},
            },
            current_persona_name="Ye",
        )
        self.assertIn("phase=半夜被叫醒后还醒着", text)

    def test_ye_without_own_sleep_state_gets_nothing(self):
        text = build_bionic_state(
            {}, 52, 48,
            role_sleep_states={"aveline": {"phase": "sleeping"}},
            current_persona_name="Ye",
        )
        self.assertNotIn("正在睡觉", text)

    def test_aveline_still_reads_own_sleep_state(self):
        text = build_bionic_state(
            {}, 52, 48,
            role_sleep_states={"aveline": {"phase": "sleeping"}},
            current_persona_name="七濑 Aveline",
        )
        self.assertIn("phase=正在睡觉", text)


class TestPersonasRelationshipHelpers(unittest.TestCase):
    def test_relationship_key_is_order_independent(self):
        self.assertEqual(relationship_key("ling", "aveline"), "aveline|ling")
        self.assertEqual(relationship_key("aveline", "ling"), "aveline|ling")

    def test_lookup_relationship_value_tolerates_reversed_key(self):
        self.assertEqual(
            lookup_relationship_value({"ling|aveline": 42}, "aveline", "ling"), 42.0
        )
        self.assertIsNone(lookup_relationship_value({}, "aveline", "ling"))
        self.assertIsNone(
            lookup_relationship_value({"aveline|ling": 42}, "ye", "ling")
        )

    def test_address_term_falls_back_to_cn_name_and_empty_for_single_role(self):
        self.assertEqual(get_peer_address_term("aveline"), "Ling")
        self.assertEqual(get_peer_address_term("ling"), "Aveline")
        # 无互识关系 → 空串，调用方据此跳过注入
        self.assertEqual(get_peer_address_term("ye"), "")
        self.assertEqual(get_peer_address_term(""), "")


if __name__ == "__main__":
    unittest.main()
