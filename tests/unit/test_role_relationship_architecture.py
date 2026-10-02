import os
import sys
import unittest
from datetime import date
from unittest.mock import MagicMock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core.agents.chat_agent_components.persona_system.prompt.special_days import (  # noqa: E402
    get_special_days,
)
from core.character.people.manager import PeopleProfileManager  # noqa: E402
from core.services.dual_role.personas import (  # noqa: E402
    knows_role,
    resolve_role_id,
)


def _make_profile(profile_id: str, name: str, aliases=()):
    return MagicMock(profile_id=profile_id, name=name, aliases=list(aliases))


class TestRoleResolution(unittest.TestCase):
    """角色解析：认得出就返回，认不出返回空，绝不猜默认值。"""

    def test_resolve_by_name_and_filename(self):
        self.assertEqual(resolve_role_id("Ye"), "ye")
        self.assertEqual(resolve_role_id("core_ye.json"), "ye")
        self.assertEqual(resolve_role_id("七濑 Aveline"), "aveline")
        self.assertEqual(resolve_role_id("aveline"), "aveline")
        self.assertEqual(resolve_role_id("ye"), "ye")

    def test_unknown_returns_empty_instead_of_guessing(self):
        self.assertEqual(resolve_role_id("某个未注册角色"), "")
        self.assertEqual(resolve_role_id(""), "")


class TestKnowsRole(unittest.TestCase):
    """互识关系是数据的产物：登记了才认识，没登记就不认识。"""

    def test_registered_pair_know_each_other(self):
        self.assertTrue(knows_role("aveline", "ling"))
        self.assertTrue(knows_role("ling", "aveline"))

    def test_everyone_knows_themselves(self):
        self.assertTrue(knows_role("ye", "ye"))
        self.assertTrue(knows_role("aveline", "aveline"))

    def test_single_roles_know_nobody_else(self):
        for viewer in ("ye", "lin", "yeye", "rushuang"):
            self.assertFalse(knows_role(viewer, "aveline"))
            self.assertFalse(knows_role(viewer, "ling"))

    def test_empty_input_is_false(self):
        self.assertFalse(knows_role("", "aveline"))
        self.assertFalse(knows_role("ye", ""))


class TestPeopleProfileVisibility(unittest.TestCase):
    """人物档案：AI 角色档案只对本人与互识 peer 可见。"""

    _aveline = _make_profile("aveline", "七濑 Aveline", ["Aveline", "Aveline", "Aveline"])
    _ling = _make_profile("ling", "Ling", ["玲", "Ling"])
    _stranger = _make_profile("zhangsan", "张三", [])

    def test_ai_role_profile_hidden_from_unrelated_roles(self):
        self.assertFalse(PeopleProfileManager._is_visible_to(self._aveline, "ye"))
        self.assertFalse(PeopleProfileManager._is_visible_to(self._aveline, "lin"))
        self.assertFalse(PeopleProfileManager._is_visible_to(self._ling, "ye"))

    def test_ai_role_profile_visible_to_self_and_peer(self):
        self.assertTrue(PeopleProfileManager._is_visible_to(self._aveline, "aveline"))
        self.assertTrue(PeopleProfileManager._is_visible_to(self._aveline, "ling"))
        self.assertTrue(PeopleProfileManager._is_visible_to(self._ling, "ling"))

    def test_ordinary_person_visible_to_everyone(self):
        for viewer in ("ye", "aveline", "lin"):
            self.assertTrue(PeopleProfileManager._is_visible_to(self._stranger, viewer))

    def test_unknown_viewer_keeps_legacy_behavior(self):
        """调用方没给角色信息时不过滤（不臆造限制）。"""
        self.assertTrue(PeopleProfileManager._is_visible_to(self._aveline, ""))


class TestBirthdayOwnership(unittest.TestCase):
    """生日只属于本人：别人的生日不能出现在自己的 prompt 里。"""

    def test_role_birthday_only_visible_to_owner(self):
        the_day = date(2026, 11, 4)
        aveline_days = get_special_days(the_day, role_id="aveline")
        self.assertTrue(
            any(d["type"] == "birthday" for d in aveline_days),
            "11-04 是 Aveline 的生日，本人应该看到",
        )
        for other in ("ling", "ye", "lin", "yeye"):
            days = get_special_days(the_day, role_id=other)
            self.assertFalse(
                any(d["type"] == "birthday" for d in days),
                f"{other} 不该过 Aveline 的生日",
            )

    def test_user_birthday_visible_to_everyone(self):
        the_day = date(2026, 5, 12)
        for role in ("aveline", "ling", "ye"):
            days = get_special_days(the_day, role_id=role)
            self.assertTrue(
                any(d["type"] == "birthday" for d in days),
                f"{role} 应该知道用户生日",
            )


if __name__ == "__main__":
    unittest.main()
