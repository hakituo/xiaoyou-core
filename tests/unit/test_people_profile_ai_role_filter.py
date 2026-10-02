import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core.character.people.external_profile_service import (  # noqa: E402
    ExternalPeopleProfileService,
)
from core.services.dual_role.personas import resolve_ai_role_id  # noqa: E402


class TestResolveAiRoleId(unittest.TestCase):
    """严格判定：只认权威名/英文名/长度≥2 的非通用别名。"""

    def test_recognizes_registered_roles(self):
        for name, expect in (
            ("七濑 Aveline", "aveline"),
            ("Aveline", "aveline"),
            ("aveline", "aveline"),
            ("Aveline", "aveline"),
            ("Ling", "ling"),
            ("Ye", "ye"),
            ("Coco", "yeye"),
            ("Frost", "rushuang"),
            ("Lin", "lin"),
        ):
            self.assertEqual(resolve_ai_role_id(name), expect, f"{name} 应判定为 {expect}")

    def test_does_not_swallow_real_people(self):
        """单字与通用称呼不算证据——真实人物也可能叫这些。"""
        for name in ("张三", "李小明", "妹妹", "玲", "Aveline", "叶", ""):
            self.assertEqual(resolve_ai_role_id(name), "", f"{name!r} 不应判定为 AI 角色")


class TestExtractorAiRoleFilter(unittest.TestCase):
    """提取落库前必须把 AI 角色挡在外面。"""

    def _service(self):
        return ExternalPeopleProfileService(
            llm_caller=MagicMock(),
            batch_formatter=MagicMock(),
        )

    def test_matched_ai_role_id_checks_name_and_aliases(self):
        service = self._service()
        self.assertEqual(service._matched_ai_role_id("Aveline"), "aveline")
        self.assertEqual(service._matched_ai_role_id("Aveline"), "aveline")
        self.assertEqual(
            service._matched_ai_role_id("阿七", ["Aveline", "Aveline"]), "aveline"
        )
        self.assertEqual(service._matched_ai_role_id("张三"), "")
        self.assertEqual(service._matched_ai_role_id("张三", ["小明", "老王"]), "")

    def test_persist_skips_ai_roles_and_keeps_real_people(self):
        service = self._service()
        manager = MagicMock()
        manager.list_all_people_profiles.return_value = []
        manager.query_profile_details.return_value = None  # 没有已存在的同名档案

        with patch.object(
            ExternalPeopleProfileService, "create_new_profile"
        ) as create_mock, patch.object(
            ExternalPeopleProfileService, "update_existing_profile"
        ) as update_mock:
            stats = service._persist_people(
                [
                    {"name": "Aveline", "aliases": ["Aveline"], "confidence": 0.9},
                    {"name": "Aveline", "confidence": 0.9},
                    {"name": "Ling", "confidence": 0.8},
                    {"name": "Ye", "confidence": 0.8},
                    {"name": "张三", "aliases": ["小张"], "confidence": 0.8},
                ],
                manager,
            )

        # AI 角色既不该新建档案，也不该被拿去更新历史遗留的角色档案
        self.assertEqual(stats["extracted_count"], 1, "只有张三被算作提取到的人物")
        self.assertEqual(stats["created_count"], 1)
        self.assertEqual(stats["updated_count"], 0)
        update_mock.assert_not_called()
        self.assertEqual(create_mock.call_count, 1)
        self.assertEqual(create_mock.call_args[0][0], "张三")

    def test_existing_profile_list_excludes_ai_roles(self):
        """候选列表里不能出现 AI 角色条目，否则会被 match_existing 指过去。"""
        service = self._service()
        aveline = MagicMock(
            profile_id="aveline", name="七濑 Aveline", aliases=["Aveline", "Aveline"]
        )
        stranger = MagicMock(profile_id="abc123", name="张三", aliases=["小张"])
        self.assertTrue(service._is_ai_role_profile(aveline))
        self.assertFalse(service._is_ai_role_profile(stranger))


if __name__ == "__main__":
    unittest.main()
