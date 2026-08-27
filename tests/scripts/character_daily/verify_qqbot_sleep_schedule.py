"""验证 QQ 官方机器人（yeye/xiaolu）的作息系统接入。

验证点：
1. character_daily.yaml 加载 yeye/xiaolu 模板，wake_time/sleep_time 正确
2. engine.KNOWN_ROLES / ROLE_NAMES 包含 yeye/xiaolu
3. sleep_manager._ROLE_NAMES 包含 yeye/xiaolu
4. storage.resolve_scope_from_persona_filename 对 qq/Yeye.json / qq/Xiaolu.json
   返回 "yeye" / "xiaolu"（不再误 fallback 到 aveline）
5. storage.resolve_scope_from_conversation_id 对 yeye/xiaolu 会话返回正确 scope
6. reply_policy_support.resolve_reply_scope 对 yeye/xiaolu persona 返回正确 scope
7. life._resolve_role_scope 对 yeye/xiaolu payload 返回正确 scope
8. sleep_manager 对 yeye/xiaolu 容错（_ensure_role_state 自动创建 state）
9. DailyPlanGenerator 能为 yeye 生成跨午夜 sleeping slot（02:00-09:00）

背景：QQ 官方机器人 persona 此前被 resolve_scope_from_persona_filename
误 fallback 到 "aveline"，导致：
- yeye 半夜发消息被 aveline 的 sleeping 状态静默累积
- /wake 误唤醒 aveline 而非 yeye
本次接入让 yeye/xiaolu 拥有独立作息（不接 active_care）。
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


class TestYamlTemplateLoaded(unittest.TestCase):
    """验证 character_daily.yaml 正确加载 yeye/xiaolu 模板。"""

    def test_yeye_template_exists_with_correct_sleep_wake(self):
        """yeye 模板存在，wake=09:00 sleep=02:00（跨午夜）。"""
        from core.services.character_daily.config import load_schedule_templates

        templates = load_schedule_templates()
        self.assertIn("yeye", templates, "yeye 模板应存在于 character_daily.yaml")
        yeye = templates["yeye"]
        self.assertEqual(yeye.wake_time, "09:00")
        self.assertEqual(yeye.sleep_time, "02:00")

    def test_xiaolu_template_exists_with_correct_sleep_wake(self):
        """xiaolu 模板存在，wake=08:00 sleep=23:30。"""
        from core.services.character_daily.config import load_schedule_templates

        templates = load_schedule_templates()
        self.assertIn("xiaolu", templates, "xiaolu 模板应存在于 character_daily.yaml")
        xiaolu = templates["xiaolu"]
        self.assertEqual(xiaolu.wake_time, "08:00")
        self.assertEqual(xiaolu.sleep_time, "23:30")

    def test_yeye_has_sleep_profile(self):
        """yeye 有 sleep_profile，且 chronotype=night_owl。"""
        from core.services.character_daily.config import load_schedule_templates

        templates = load_schedule_templates()
        yeye = templates["yeye"]
        self.assertIsNotNone(yeye.sleep_profile)
        self.assertEqual(yeye.sleep_profile.chronotype, "night_owl")
        self.assertEqual(yeye.sleep_profile.weekend_wake_time, "11:00")
        self.assertEqual(yeye.sleep_profile.weekend_sleep_time, "03:00")

    def test_yeye_has_late_night_block_crossing_midnight(self):
        """yeye 有跨午夜 late_night 时段（23:30-02:00）。"""
        from core.services.character_daily.config import load_schedule_templates

        templates = load_schedule_templates()
        yeye = templates["yeye"]
        periods = [b.period for b in yeye.time_blocks]
        self.assertIn("late_night", periods, "yeye 应有 late_night 时段")
        late_night = next(b for b in yeye.time_blocks if b.period == "late_night")
        self.assertEqual(late_night.start, "23:30")
        self.assertEqual(late_night.end, "02:00")


class TestEngineKnownRoles(unittest.TestCase):
    """验证 engine.KNOWN_ROLES / ROLE_NAMES 包含 yeye/xiaolu。"""

    def test_known_roles_includes_yeye_xiaolu(self):
        from core.services.character_daily.engine import KNOWN_ROLES

        self.assertIn("yeye", KNOWN_ROLES)
        self.assertIn("xiaolu", KNOWN_ROLES)

    def test_role_names_includes_yeye_xiaolu(self):
        from core.services.character_daily.engine import ROLE_NAMES

        self.assertEqual(ROLE_NAMES.get("yeye"), "Coco")
        self.assertEqual(ROLE_NAMES.get("xiaolu"), "小鹿")

    def test_sleep_manager_role_names_includes_yeye_xiaolu(self):
        from core.services.life_simulation.sleep_manager import _ROLE_NAMES

        self.assertEqual(_ROLE_NAMES.get("yeye"), "Coco")
        self.assertEqual(_ROLE_NAMES.get("xiaolu"), "小鹿")


class TestResolveScopeFromPersonaFilename(unittest.TestCase):
    """验证 storage.resolve_scope_from_persona_filename 对 yeye/xiaolu 返回独立 scope。"""

    def setUp(self):
        from core.services.active_care.storage.storage import ActiveCareStorage

        self.storage = ActiveCareStorage()

    def test_yeye_persona_returns_yeye_scope(self):
        """qq/Yeye.json 应返回 yeye，不再误 fallback 到 aveline。"""
        self.assertEqual(self.storage.resolve_scope_from_persona_filename("qq/Yeye.json"), "yeye")

    def test_xiaolu_persona_returns_xiaolu_scope(self):
        """qq/Xiaolu.json 应返回 xiaolu。"""
        self.assertEqual(
            self.storage.resolve_scope_from_persona_filename("qq/Xiaolu.json"), "xiaolu"
        )

    def test_aveline_persona_still_returns_aveline(self):
        """aveline persona 不受影响。"""
        self.assertEqual(
            self.storage.resolve_scope_from_persona_filename("qq/Aveline_QQ_Master.json"),
            "aveline",
        )

    def test_ling_persona_still_returns_ling(self):
        """ling persona 不受影响。"""
        self.assertEqual(
            self.storage.resolve_scope_from_persona_filename("core/character/configs/core_ling.json"),
            "ling",
        )

    def test_yeye_chinese_name_returns_yeye_scope(self):
        """包含 'Coco' 的 persona 返回 yeye。"""
        self.assertEqual(self.storage.resolve_scope_from_persona_filename("qq/Coco.json"), "yeye")

    def test_xiaolu_chinese_name_returns_xiaolu_scope(self):
        """包含 '小鹿' 的 persona 返回 xiaolu。"""
        self.assertEqual(self.storage.resolve_scope_from_persona_filename("qq/小鹿.json"), "xiaolu")

    def test_unknown_persona_falls_back_to_aveline(self):
        """未知 persona 仍 fallback 到 aveline（保持原行为）。"""
        self.assertEqual(
            self.storage.resolve_scope_from_persona_filename("unknown/persona.json"), "aveline"
        )


class TestResolveScopeFromConversationId(unittest.TestCase):
    """验证 storage.resolve_scope_from_conversation_id 对 yeye/xiaolu 会话返回正确 scope。"""

    def setUp(self):
        from core.services.active_care.storage.storage import ActiveCareStorage

        self.storage = ActiveCareStorage()

    def test_yeye_conversation_returns_yeye(self):
        """__persona__yeye 后缀应返回 yeye。"""
        cid = "private_123__persona__yeye"
        self.assertEqual(self.storage.resolve_scope_from_conversation_id(cid), "yeye")

    def test_xiaolu_conversation_returns_xiaolu(self):
        """__persona__xiaolu 后缀应返回 xiaolu。"""
        cid = "private_123__persona__xiaolu"
        self.assertEqual(self.storage.resolve_scope_from_conversation_id(cid), "xiaolu")

    def test_yeye_scope_marker_returns_yeye(self):
        """__scope__yeye 应返回 yeye。"""
        cid = "user_123__scope__yeye"
        self.assertEqual(self.storage.resolve_scope_from_conversation_id(cid), "yeye")

    def test_xiaolu_scope_marker_returns_xiaolu(self):
        """__scope__xiaolu 应返回 xiaolu。"""
        cid = "user_123__scope__xiaolu"
        self.assertEqual(self.storage.resolve_scope_from_conversation_id(cid), "xiaolu")


class TestResolveReplyScope(unittest.TestCase):
    """验证 reply_policy_support.resolve_reply_scope 对 yeye/xiaolu 返回正确 scope。"""

    def test_yeye_persona_returns_yeye_without_active_care(self):
        """active_care 未就绪时，yeye persona 仍能正确返回 yeye scope。"""
        from core.services.character_daily.reply_policy_support import resolve_reply_scope

        # active_care service 不存在时，走 fallback 逻辑
        with patch("core.services.active_care.core.service.get_active_care_service", return_value=None):
            scope = resolve_reply_scope("aveline", "qq/Yeye.json")
            self.assertEqual(scope, "yeye")

    def test_xiaolu_persona_returns_xiaolu_without_active_care(self):
        """active_care 未就绪时，xiaolu persona 仍能正确返回 xiaolu scope。"""
        from core.services.character_daily.reply_policy_support import resolve_reply_scope

        with patch("core.services.active_care.core.service.get_active_care_service", return_value=None):
            scope = resolve_reply_scope("aveline", "qq/Xiaolu.json")
            self.assertEqual(scope, "xiaolu")

    def test_explicit_yeye_role_id_returns_yeye(self):
        """显式传 role_id=yeye 时直接返回 yeye（不依赖 persona_filename）。"""
        from core.services.character_daily.reply_policy_support import resolve_reply_scope

        with patch("core.services.active_care.core.service.get_active_care_service", return_value=None):
            scope = resolve_reply_scope("yeye", "")
            self.assertEqual(scope, "yeye")


class TestResolveRoleScopeForWake(unittest.TestCase):
    """验证 life._resolve_role_scope 对 yeye/xiaolu payload 返回正确 scope。"""

    def _make_payload(self, **kwargs):
        from routers.v1.life import SleepWakeRequest

        return SleepWakeRequest(**kwargs)

    def test_yeye_persona_returns_yeye(self):
        """yeye persona 的 /wake 请求应解析到 yeye scope。"""
        from routers.v1.life import _resolve_role_scope

        with patch("core.services.active_care.core.service.get_active_care_service", return_value=None):
            payload = self._make_payload(persona_filename="qq/Yeye.json")
            self.assertEqual(_resolve_role_scope(payload), "yeye")

    def test_xiaolu_persona_returns_xiaolu(self):
        """xiaolu persona 的 /wake 请求应解析到 xiaolu scope。"""
        from routers.v1.life import _resolve_role_scope

        with patch("core.services.active_care.core.service.get_active_care_service", return_value=None):
            payload = self._make_payload(persona_filename="qq/Xiaolu.json")
            self.assertEqual(_resolve_role_scope(payload), "xiaolu")

    def test_yeye_conversation_id_returns_yeye(self):
        """__persona__yeye 会话的 /wake 请求应解析到 yeye scope。"""
        from routers.v1.life import _resolve_role_scope

        with patch("core.services.active_care.core.service.get_active_care_service", return_value=None):
            payload = self._make_payload(conversation_id="private_123__persona__yeye")
            self.assertEqual(_resolve_role_scope(payload), "yeye")

    def test_explicit_role_id_yeye_returns_yeye(self):
        """显式传 role_id=yeye 直接返回 yeye。"""
        from routers.v1.life import _resolve_role_scope

        payload = self._make_payload(role_id="yeye")
        self.assertEqual(_resolve_role_scope(payload), "yeye")

    def test_aveline_persona_still_returns_aveline(self):
        """aveline persona 不受影响。"""
        from routers.v1.life import _resolve_role_scope

        with patch("core.services.active_care.core.service.get_active_care_service", return_value=None):
            payload = self._make_payload(persona_filename="qq/Aveline_QQ_Master.json")
            self.assertEqual(_resolve_role_scope(payload), "aveline")


class TestSleepManagerToleratesNewScopes(unittest.TestCase):
    """验证 sleep_manager 对 yeye/xiaolu scope 的容错性。"""

    def test_ensure_role_state_creates_yeye_state(self):
        """_ensure_role_state 对 yeye 自动创建 state，不报错。"""
        from core.services.life_simulation.sleep_manager import SleepManager

        mgr = SleepManager()
        state = mgr._ensure_role_state("yeye", now=datetime(2026, 7, 31, 12, 0))
        self.assertEqual(state.role_id, "yeye")

    def test_ensure_role_state_creates_xiaolu_state(self):
        """_ensure_role_state 对 xiaolu 自动创建 state，不报错。"""
        from core.services.life_simulation.sleep_manager import SleepManager

        mgr = SleepManager()
        state = mgr._ensure_role_state("xiaolu", now=datetime(2026, 7, 31, 12, 0))
        self.assertEqual(state.role_id, "xiaolu")

    def test_yeye_sleep_window_is_02_to_09(self):
        """yeye 的睡眠窗口应为 02:00-09:00（跨午夜）。

        注意：_weekday_offset_minutes 会给工作日加 sleep_inertia_tendency*8 分钟的
        睡眠惯性偏移（yeye 0.6 → +4 分钟），所以工作日实际 wake 可能是 09:04。
        断言用范围而非精确值。
        """
        from core.services.life_simulation.sleep_manager import SleepManager

        mgr = SleepManager()
        # 凌晨 03:00 应在睡眠窗口内
        sleep_dt, wake_dt = mgr._resolve_sleep_window(
            "yeye", now=datetime(2026, 7, 31, 3, 0)
        )
        self.assertEqual(sleep_dt.strftime("%H:%M"), "02:00")
        # 周五（weekday=4）会有 +4 分钟睡眠惯性偏移
        wake_time_str = wake_dt.strftime("%H:%M")
        wake_hour, wake_minute = wake_dt.hour, wake_dt.minute
        self.assertEqual(wake_hour, 9, f"yeye 起床应在 09 点，实际 {wake_time_str}")
        self.assertLessEqual(wake_minute, 10, f"yeye 起床应在 09:10 内，实际 {wake_time_str}")

    def test_yeye_not_sleeping_at_noon(self):
        """yeye 中午 12:00 不在睡眠窗口。"""
        from core.services.life_simulation.sleep_manager import SleepManager

        mgr = SleepManager()
        state = mgr.get_state("yeye", now=datetime(2026, 7, 31, 12, 0))
        self.assertFalse(state.is_sleeping, "yeye 中午不应在睡")

    def test_yeye_sleeping_at_3am(self):
        """yeye 凌晨 03:00 应在睡。"""
        from core.services.life_simulation.sleep_manager import SleepManager

        mgr = SleepManager()
        state = mgr.get_state("yeye", now=datetime(2026, 7, 31, 3, 0))
        self.assertTrue(state.is_sleeping, "yeye 凌晨 3 点应在睡")

    def test_xiaolu_not_sleeping_at_noon(self):
        """xiaolu 中午 12:00 不在睡眠窗口。"""
        from core.services.life_simulation.sleep_manager import SleepManager

        mgr = SleepManager()
        state = mgr.get_state("xiaolu", now=datetime(2026, 7, 31, 12, 0))
        self.assertFalse(state.is_sleeping, "xiaolu 中午不应在睡")


class TestDailyPlanGeneratorForYeye(unittest.TestCase):
    """验证 DailyPlanGenerator 能为 yeye 生成跨午夜计划。"""

    def test_yeye_plan_has_sleeping_slot_crossing_midnight(self):
        """yeye 的 sleeping slot 应跨越午夜（02:00-次日 09:00）。"""
        from core.services.character_daily.config import load_schedule_templates
        from core.services.character_daily.daily_plan import DailyPlanGenerator
        from core.services.character_daily.activity_model import ActivityType

        templates = load_schedule_templates()
        gen = DailyPlanGenerator(templates)
        plan = gen.generate("yeye", "2026-07-31")
        self.assertIsNotNone(plan, "yeye 应能生成计划")

        sleeping_slots = [s for s in plan.slots if s.activity == ActivityType.SLEEPING]
        self.assertEqual(len(sleeping_slots), 1, "yeye 应有 1 个 sleeping slot")

        slot = sleeping_slots[0]
        self.assertEqual(slot.planned_start.strftime("%H:%M"), "02:00")
        self.assertEqual(slot.planned_end.strftime("%H:%M"), "09:00")
        # 跨午夜：end 在第二天
        self.assertGreater(slot.planned_end.date(), slot.planned_start.date())

    def test_xiaolu_plan_has_sleeping_slot(self):
        """xiaolu 的 sleeping slot 应为 23:30-次日 08:00。"""
        from core.services.character_daily.config import load_schedule_templates
        from core.services.character_daily.daily_plan import DailyPlanGenerator
        from core.services.character_daily.activity_model import ActivityType

        templates = load_schedule_templates()
        gen = DailyPlanGenerator(templates)
        plan = gen.generate("xiaolu", "2026-07-31")
        self.assertIsNotNone(plan, "xiaolu 应能生成计划")

        sleeping_slots = [s for s in plan.slots if s.activity == ActivityType.SLEEPING]
        self.assertEqual(len(sleeping_slots), 1, "xiaolu 应有 1 个 sleeping slot")

        slot = sleeping_slots[0]
        self.assertEqual(slot.planned_start.strftime("%H:%M"), "23:30")
        self.assertEqual(slot.planned_end.strftime("%H:%M"), "08:00")


if __name__ == "__main__":
    unittest.main(verbosity=2)
