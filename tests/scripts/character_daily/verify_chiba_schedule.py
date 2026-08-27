# -*- coding: utf-8 -*-
"""验证Chiba（chiba）日程模板接入与每日计划生成。

背景：Chiba（千葉心藏）是 sensitive/ 下的 QQ 私密人设，此前没有日程模板，
也未接入 character_daily 的 scope 解析（消息会误路由到 aveline 的睡眠状态）。
本次在 character_daily_sensitive.yaml 追加 chiba 模板，并接线 scope 解析链路。

验证点：
1. load_schedule_templates 加载 chiba 模板，wake=14:00 sleep=05:00
2. sleep_profile 为 night_owl
3. 模板内所有 activity 均为合法 ActivityType（未知值会回落 idle）
4. DailyPlanGenerator 能为 chiba 生成跨午夜 sleeping slot（05:00-次日 14:00）
5. 计划包含晚间主活跃时段（21:00-00:00）的活动
6. sleep_manager 的 chiba 睡眠窗口为 05:00-14:00（凌晨睡、晚上醒）
7. storage.resolve_scope_from_persona_filename / resolve_scope_from_conversation_id
   对 sensitive/Chiba.json / shared__persona__Chiba 返回 chiba（不再 fallback 到 aveline）
8. reply_policy_support.resolve_reply_scope 对Chiba persona 返回 chiba
9. routers.v1.life._resolve_role_scope 对Chiba payload 返回 chiba
10. engine.KNOWN_ROLES / ROLE_NAMES 与 sleep_manager._ROLE_NAMES 包含 chiba

用法：
    venv_core\\Scripts\\python.exe tests\\scripts\\character_daily\\verify_chiba_schedule.py
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


class TestChibaTemplateLoaded(unittest.TestCase):
    """验证 character_daily_sensitive.yaml 正确加载 chiba 模板。"""

    def test_chiba_template_exists_with_correct_sleep_wake(self):
        from core.services.character_daily.config import load_schedule_templates

        templates = load_schedule_templates()
        self.assertIn("chiba", templates, "chiba 模板应存在于 sensitive yaml")
        chiba = templates["chiba"]
        self.assertEqual(chiba.wake_time, "14:00")
        self.assertEqual(chiba.sleep_time, "05:00")

    def test_chiba_has_sleep_profile(self):
        from core.services.character_daily.config import load_schedule_templates

        templates = load_schedule_templates()
        chiba = templates["chiba"]
        self.assertIsNotNone(chiba.sleep_profile)
        self.assertEqual(chiba.sleep_profile.chronotype, "night_owl")
        self.assertEqual(chiba.sleep_profile.weekend_wake_time, "15:00")
        self.assertEqual(chiba.sleep_profile.weekend_sleep_time, "05:30")

    def test_chiba_template_activities_all_valid(self):
        """模板内所有 activity 都应是合法 ActivityType 值。"""
        from core.services.character_daily.activity_model import ActivityType
        from core.services.character_daily.config import load_schedule_templates

        templates = load_schedule_templates()
        chiba = templates["chiba"]
        self.assertGreaterEqual(len(chiba.time_blocks), 5, "chiba 应有至少 5 个时段")
        for block in chiba.time_blocks:
            for item in list(block.fixed) + list(block.pool):
                converted = ActivityType.from_str(item.activity)
                self.assertEqual(
                    converted.value,
                    item.activity,
                    f"未知活动 {item.activity!r} 会回落 idle",
                )


class TestEngineKnownRoles(unittest.TestCase):
    """验证 engine / sleep_manager 角色列表包含 chiba。"""

    def test_known_roles_includes_chiba(self):
        from core.services.character_daily.engine import KNOWN_ROLES

        self.assertIn("chiba", KNOWN_ROLES)

    def test_role_names_includes_chiba(self):
        from core.services.character_daily.engine import ROLE_NAMES

        self.assertEqual(ROLE_NAMES.get("chiba"), "Chiba")

    def test_sleep_manager_role_names_includes_chiba(self):
        from core.services.life_simulation.sleep_manager import _ROLE_NAMES

        self.assertEqual(_ROLE_NAMES.get("chiba"), "Chiba")


class TestResolveScopeForChiba(unittest.TestCase):
    """验证 storage 对Chiba persona / 会话 id 返回 chiba scope。"""

    def setUp(self):
        from core.services.active_care.storage.storage import ActiveCareStorage

        self.storage = ActiveCareStorage()

    def test_chiba_chinese_filename_returns_chiba(self):
        self.assertEqual(
            self.storage.resolve_scope_from_persona_filename("sensitive/Chiba.json"),
            "chiba",
        )

    def test_chiba_pinyin_filename_returns_chiba(self):
        self.assertEqual(
            self.storage.resolve_scope_from_persona_filename("sensitive/chiba.json"),
            "chiba",
        )

    def test_chiba_scope_marker_returns_chiba(self):
        self.assertEqual(
            self.storage.resolve_scope_from_conversation_id("shared__scope__chiba"),
            "chiba",
        )

    def test_chiba_persona_suffix_returns_chiba(self):
        self.assertEqual(
            self.storage.resolve_scope_from_conversation_id("shared__persona__Chiba"),
            "chiba",
        )

    def test_aveline_persona_still_returns_aveline(self):
        self.assertEqual(
            self.storage.resolve_scope_from_persona_filename("qq/Aveline_QQ_Master.json"),
            "aveline",
        )

    def test_unknown_persona_falls_back_to_aveline(self):
        self.assertEqual(
            self.storage.resolve_scope_from_persona_filename("unknown/persona.json"),
            "aveline",
        )


class TestResolveReplyScopeForChiba(unittest.TestCase):
    """验证回复策略对Chiba persona 返回 chiba scope。"""

    def test_chiba_persona_returns_chiba(self):
        from core.services.character_daily.reply_policy_support import resolve_reply_scope

        with patch("core.services.active_care.core.service.get_active_care_service", return_value=None):
            scope = resolve_reply_scope("aveline", "sensitive/Chiba.json")
            self.assertEqual(scope, "chiba")

    def test_explicit_chiba_role_id_returns_chiba(self):
        from core.services.character_daily.reply_policy_support import resolve_reply_scope

        with patch("core.services.active_care.core.service.get_active_care_service", return_value=None):
            scope = resolve_reply_scope("chiba", "")
            self.assertEqual(scope, "chiba")


class TestResolveRoleScopeForChibaWake(unittest.TestCase):
    """验证 /wake 的 _resolve_role_scope 对Chiba payload 返回 chiba。"""

    def _make_payload(self, **kwargs):
        from routers.v1.life import SleepWakeRequest

        return SleepWakeRequest(**kwargs)

    def test_chiba_chinese_persona_returns_chiba(self):
        from routers.v1.life import _resolve_role_scope

        with patch("core.services.active_care.core.service.get_active_care_service", return_value=None):
            payload = self._make_payload(persona_filename="sensitive/Chiba.json")
            self.assertEqual(_resolve_role_scope(payload), "chiba")

    def test_chiba_conversation_id_returns_chiba(self):
        from routers.v1.life import _resolve_role_scope

        with patch("core.services.active_care.core.service.get_active_care_service", return_value=None):
            payload = self._make_payload(conversation_id="shared__persona__Chiba")
            self.assertEqual(_resolve_role_scope(payload), "chiba")

    def test_explicit_role_id_chiba_returns_chiba(self):
        from routers.v1.life import _resolve_role_scope

        payload = self._make_payload(role_id="chiba")
        self.assertEqual(_resolve_role_scope(payload), "chiba")


class TestChibaSleepWindow(unittest.TestCase):
    """验证 sleep_manager 对 chiba 的睡眠窗口为 05:00-14:00（跨午夜）。"""

    def test_chiba_sleep_window_is_05_to_14(self):
        from core.services.life_simulation.sleep_manager import SleepManager

        mgr = SleepManager()
        sleep_dt, wake_dt = mgr._resolve_sleep_window(
            "chiba", now=datetime(2026, 8, 27, 6, 0)
        )
        self.assertEqual(sleep_dt.strftime("%H:%M"), "05:00")
        # 睡眠惯性偏移：sleep_inertia_tendency=0.6 → 工作日 +4 分钟，wake 约 14:04
        self.assertEqual(wake_dt.hour, 14, f"chiba 起床应在 14 点，实际 {wake_dt}")

    def test_chiba_sleeping_at_6am(self):
        from core.services.life_simulation.sleep_manager import SleepManager

        mgr = SleepManager()
        state = mgr.get_state("chiba", now=datetime(2026, 8, 27, 6, 0))
        self.assertTrue(state.is_sleeping, "chiba 凌晨 6 点应在睡")

    def test_chiba_not_sleeping_at_9pm(self):
        from core.services.life_simulation.sleep_manager import SleepManager

        mgr = SleepManager()
        state = mgr.get_state("chiba", now=datetime(2026, 8, 27, 21, 0))
        self.assertFalse(state.is_sleeping, "chiba 晚上 21 点不应在睡")


class TestChibaDailyPlan(unittest.TestCase):
    """验证 DailyPlanGenerator 能为 chiba 生成跨午夜计划。"""

    @classmethod
    def setUpClass(cls):
        from core.services.character_daily.config import load_schedule_templates
        from core.services.character_daily.daily_plan import DailyPlanGenerator

        templates = load_schedule_templates()
        gen = DailyPlanGenerator(templates)
        cls.plan = gen.generate("chiba", "2026-08-27")
        cls.templates = templates

    def test_plan_generated(self):
        self.assertIsNotNone(self.plan, "chiba 应能生成每日计划")

    def test_plan_has_sleeping_slot_crossing_midnight(self):
        from core.services.character_daily.activity_model import ActivityType

        sleeping_slots = [s for s in self.plan.slots if s.activity == ActivityType.SLEEPING]
        self.assertEqual(len(sleeping_slots), 1, "chiba 应有 1 个 sleeping slot")
        slot = sleeping_slots[0]
        self.assertEqual(slot.planned_start.strftime("%H:%M"), "05:00")
        self.assertEqual(slot.planned_end.hour, 14, f"chiba wake hour 应为 14，实际 {slot.planned_end}")
        self.assertGreater(slot.planned_end.date(), slot.planned_start.date())

    def test_plan_has_night_active_slots(self):
        """计划应覆盖晚间主活跃时段（21:00-00:00，对应真实聊天峰值）。"""
        from core.services.character_daily.activity_model import ActivityType

        non_sleep_slots = [s for s in self.plan.slots if s.activity != ActivityType.SLEEPING]
        self.assertGreaterEqual(len(non_sleep_slots), 4, "chiba 应至少有 4 个非睡觉 slot")
        night_slots = [
            s for s in non_sleep_slots
            if 21 <= s.planned_start.hour < 24 or s.planned_start.hour < 1
        ]
        self.assertGreaterEqual(len(night_slots), 1, "chiba 晚间 21 点后应有活动 slot")


if __name__ == "__main__":
    unittest.main(verbosity=2)
