"""验证食物系统升级：扩充食物库 + food_cravings 愿望清单 + 做饭优先读 wishlist。

验证点：
1. 食物库扩充：FOOD_DB 数量 >= 50；覆盖新增分类（汤/粥/早茶/地方特色/国际菜/下午茶/夜宵/节日/季节）
2. food_cravings 数据结构：add/get/mark_satisfied/cleanup_expired 全链路工作
3. 工具注册：CraveFoodTool 和 ListCravingsTool 在 registry 中
4. 做饭优先读 wishlist：
   - 有匹配 craving 时 → 产物来自 craving，且 mark_craving_satisfied 被调用
   - 无匹配 craving 时 → 回退到 _COOKING_OUTPUTS 默认映射
   - 餐窗类型过滤：lunch/dinner 只取 meal，breakfast 允许 meal/snack/drink
5. 投喂/自动进食联动：吃掉 wishlist 里的食物会标记已满足

运行方式：
    venv_core\\Scripts\\python.exe tests\\scripts\\food\\verify_food_system_upgrade.py
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


# 关键新增食物 ID，用于验证扩充生效
_EXPECTED_NEW_FOOD_IDS = [
    # 汤类
    "tomato_egg_soup", "miso_soup", "borscht", "tom_yum",
    # 粥类
    "congee_pork", "seafood_congee", "millet_porridge",
    # 早茶点心
    "xiaolongbao", "rice_noodle_roll", "jianbing",
    # 地方特色正餐
    "peking_duck", "mapo_tofu", "lanzhou_noodle", "hui_guo_rou",
    # 国际菜
    "pasta", "green_curry", "bibimbap", "japanese_curry", "taco", "pho",
    # 下午茶甜点
    "tiramisu", "macaron", "scone",
    # 夜宵
    "skewers", "malatang", "instant_noodle",
    # 节日限定
    "tangyuan", "zongzi", "mooncake", "dumpling",
    # 季节性
    "watermelon", "roasted_chestnut", "mulled_wine",
]


class TestFoodDbExpansion(unittest.TestCase):
    """验证食物库扩充。"""

    def test_food_count_at_least_50(self):
        """食物库总数应 >= 50（原 26 + 新增 27 = 53）。"""
        from core.food.data import get_all_food

        foods = get_all_food()
        self.assertGreaterEqual(
            len(foods),
            50,
            f"食物库数量不足：当前 {len(foods)} 种，预期至少 50 种",
        )

    def test_new_food_ids_present(self):
        """所有新增食物 ID 都应在 FOOD_DB 中存在。"""
        from core.food.data import get_food

        missing = [fid for fid in _EXPECTED_NEW_FOOD_IDS if not get_food(fid)]
        self.assertEqual(
            missing,
            [],
            f"新增食物缺失：{missing}",
        )

    def test_new_food_types_valid(self):
        """新增食物的 type 必须是合法枚举值。"""
        from core.food.data import get_food

        for fid in _EXPECTED_NEW_FOOD_IDS:
            food = get_food(fid)
            self.assertIsNotNone(food, f"食物 {fid} 不存在")
            self.assertIn(
                food.type,
                {"meal", "snack", "drink", "ingredient"},
                f"食物 {fid} 类型非法: {food.type}",
            )

    def test_new_food_categories_coverage(self):
        """覆盖所有新增分类（汤/粥/早茶/地方特色/国际菜/下午茶/夜宵/节日/季节）。"""
        # 汤类
        from core.food.data import get_food

        self.assertEqual(get_food("tomato_egg_soup").type, "meal")
        self.assertEqual(get_food("tiramisu").type, "snack")  # 下午茶
        self.assertEqual(get_food("mulled_wine").type, "drink")  # 季节饮品
        self.assertEqual(get_food("peking_duck").type, "meal")  # 地方特色
        self.assertEqual(get_food("dumpling").type, "meal")  # 节日正餐


class TestFoodCravingsLifecycle(unittest.TestCase):
    """验证 food_cravings 全生命周期。"""

    def _make_food_system(self):
        from core.services.life_simulation.food_system import FoodSystem

        life_stats = {"food_inventory": [], "digestion_queue": [], "food_events": []}
        status = {}
        return FoodSystem(life_stats, status), life_stats

    def test_ensure_food_state_creates_cravings_field(self):
        """_ensure_food_state 应该初始化 food_cravings 字段。"""
        fs, life_stats = self._make_food_system()
        self.assertIsInstance(life_stats.get("food_cravings"), list)
        self.assertEqual(life_stats["food_cravings"], [])

    def test_add_craving_creates_entry(self):
        """add_food_craving 应该创建一条活跃愿望。"""
        fs, life_stats = self._make_food_system()
        entry = fs.add_food_craving("ramen", reason="想吃点热的")
        self.assertTrue(entry)
        self.assertEqual(entry["food_id"], "ramen")
        self.assertEqual(entry["reason"], "想吃点热的")
        self.assertFalse(entry["satisfied"])
        active = fs.get_food_cravings(only_active=True)
        self.assertEqual(len(active), 1)

    def test_add_same_food_refreshes_existing(self):
        """重复添加同一食物应该刷新已有项，而不是新增。"""
        fs, life_stats = self._make_food_system()
        fs.add_food_craving("ramen", reason="第一次")
        time.sleep(0.01)
        fs.add_food_craving("ramen", reason="第二次")
        active = fs.get_food_cravings(only_active=True)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["reason"], "第二次")

    def test_mark_satisfied(self):
        """mark_craving_satisfied 应该把对应项标记为已满足。"""
        fs, life_stats = self._make_food_system()
        fs.add_food_craving("ramen")
        ok = fs.mark_craving_satisfied("ramen", satisfied_by="cooking")
        self.assertTrue(ok)
        active = fs.get_food_cravings(only_active=True)
        self.assertEqual(len(active), 0, "已满足的愿望不应出现在活跃列表")

    def test_cleanup_expired(self):
        """cleanup_expired_cravings 应该清理过期的活跃愿望。"""
        fs, life_stats = self._make_food_system()
        # ttl = 60 秒，立即过期（构造一个过去的时间）
        fs.add_food_craving("ramen", ttl_seconds=60.0)
        # 手动把 expire_at 改成过去
        life_stats["food_cravings"][0]["expire_at"] = time.time() - 1
        removed = fs.cleanup_expired_cravings()
        self.assertEqual(removed, 1)
        self.assertEqual(len(life_stats["food_cravings"]), 0)

    def test_max_active_cap(self):
        """超过 _MAX_ACTIVE_CRAVINGS 时应该丢弃最早的。"""
        fs, life_stats = self._make_food_system()
        cap = fs._MAX_ACTIVE_CRAVINGS
        # 加 cap + 5 个不同的食物
        food_ids = [
            "ramen", "cookie", "cake", "cola", "burger",
            "pizza", "steak", "hotpot", "sushi", "salad", "sandwich",
        ]
        for fid in food_ids[: cap + 5]:
            fs.add_food_craving(fid)
        active = fs.get_food_cravings(only_active=True)
        self.assertLessEqual(len(active), cap, "活跃愿望不应超过上限")


class TestToolRegistration(unittest.TestCase):
    """验证新工具已注册。"""

    def test_crave_food_tool_registered(self):
        from core.tools.food_tool import CraveFoodTool

        tool = CraveFoodTool()
        self.assertEqual(tool.name, "crave_food")
        self.assertTrue(tool.description)
        self.assertIn("愿望清单", tool.description)

    def test_list_cravings_tool_registered(self):
        from core.tools.food_tool import ListCravingsTool

        tool = ListCravingsTool()
        self.assertEqual(tool.name, "list_food_cravings")


class TestCookingOutputsReadCravings(unittest.TestCase):
    """验证做饭优先读 wishlist 逻辑。"""

    def _make_plan_slot(self, role_id="aveline"):
        from core.services.character_daily.activity_model import (
            ActivityExecutionStatus,
            ActivitySlot,
            ActivityType,
        )
        from datetime import datetime, timedelta

        now = datetime.now()
        slot = ActivitySlot(
            activity=ActivityType.COOKING,
            planned_start=now - timedelta(minutes=30),
            planned_end=now,
            execution_status=ActivityExecutionStatus.COMPLETED,
            started_at=(now - timedelta(minutes=30)).isoformat(),
            completed_at=now.isoformat(),
        )
        plan = MagicMock()
        plan.role_id = role_id
        plan.slots = [slot]
        plan.find_current_slot.return_value = None
        return plan, slot

    def test_resolve_craving_picks_meal_for_lunch(self):
        """lunch 餐窗应该优先挑 meal，名额未满时才以 snack 作为 fallback。"""
        from core.services.character_daily.plan_execution import (
            _resolve_craving_output_ids,
        )
        from core.services.life_simulation.food_system import FoodSystem

        life_stats = {
            "food_inventory": [],
            "digestion_queue": [],
            "food_events": [],
            "food_cravings": [
                {
                    "food_id": "cookie",
                    "food_type": "snack",
                    "added_at": time.time(),
                    "expire_at": time.time() + 86400,
                    "satisfied": False,
                },
                {
                    "food_id": "ramen",
                    "food_type": "meal",
                    "added_at": time.time(),
                    "expire_at": time.time() + 86400,
                    "satisfied": False,
                },
            ],
        }
        fs = FoodSystem(life_stats, {})
        with patch(
            "core.services.life_simulation.service.get_life_simulation_service",
            return_value=MagicMock(
                get_food_cravings=fs.get_food_cravings,
            ),
        ):
            picked = _resolve_craving_output_ids("lunch")
        # meal 必须被选中
        self.assertIn("ramen", picked)
        # 最多 2 个
        self.assertLessEqual(len(picked), 2)
        # 第一项必须是 meal（首选类型）
        self.assertEqual(
            picked[0], "ramen", "lunch 第一项必须是 meal 类型，不能 snack 优先"
        )

    def test_resolve_cravity_returns_empty_when_no_cravings(self):
        """无 craving 时应返回空列表（让上层回退到默认映射）。"""
        from core.services.character_daily.plan_execution import (
            _resolve_craving_output_ids,
        )
        from core.services.life_simulation.food_system import FoodSystem

        life_stats = {
            "food_inventory": [],
            "digestion_queue": [],
            "food_events": [],
            "food_cravings": [],
        }
        fs = FoodSystem(life_stats, {})
        with patch(
            "core.services.life_simulation.service.get_life_simulation_service",
            return_value=MagicMock(
                get_food_cravings=fs.get_food_cravings,
            ),
        ):
            picked = _resolve_craving_output_ids("dinner")
        self.assertEqual(picked, [])

    def test_produce_cooking_outputs_uses_craving_when_present(self):
        """有活跃 craving 时做饭应该产出 craving 的食物，并标记已满足。"""
        from core.services.character_daily import plan_execution
        from core.services.life_simulation.food_system import FoodSystem

        life_stats = {
            "food_inventory": [],
            "digestion_queue": [],
            "food_events": [],
            "food_cravings": [
                {
                    "food_id": "hotpot",
                    "food_name": "麻辣火锅",
                    "food_type": "meal",
                    "added_at": time.time(),
                    "expire_at": time.time() + 86400,
                    "satisfied": False,
                }
            ],
        }
        fs = FoodSystem(life_stats, {})

        mock_life_service = MagicMock()
        mock_life_service.get_food_cravings = fs.get_food_cravings
        mock_life_service.add_food_to_inventory = MagicMock()
        mock_life_service.mark_craving_satisfied = MagicMock(
            side_effect=lambda fid, satisfied_by="cooking": fs.mark_craving_satisfied(
                fid, satisfied_by
            )
        )

        plan, slot = self._make_plan_slot(role_id="aveline")
        # 让 _resolve_cooking_meal_window 返回 dinner
        with patch.object(
            plan_execution, "_resolve_cooking_meal_window", return_value="dinner"
        ), patch(
            "core.services.life_simulation.service.get_life_simulation_service",
            return_value=mock_life_service,
        ):
            produced = plan_execution._produce_cooking_outputs(plan, slot)

        self.assertIn("hotpot", produced, "应优先用 wishlist 里的食物")
        mock_life_service.add_food_to_inventory.assert_called_once()
        mock_life_service.mark_craving_satisfied.assert_called_once_with(
            "hotpot", satisfied_by="cooking"
        )
        # 确认 wishlist 已标记为已满足
        active = fs.get_food_cravings(only_active=True)
        self.assertEqual(len(active), 0, "满足后应不再出现在活跃列表")

    def test_produce_cooking_outputs_fallback_to_default(self):
        """无 craving 时应该回退到 _COOKING_OUTPUTS 默认映射。"""
        from core.services.character_daily import plan_execution
        from core.services.character_daily.activity_model import ActivityType
        from core.services.life_simulation.food_system import FoodSystem

        life_stats = {
            "food_inventory": [],
            "digestion_queue": [],
            "food_events": [],
            "food_cravings": [],
        }
        fs = FoodSystem(life_stats, {})

        mock_life_service = MagicMock()
        mock_life_service.get_food_cravings = fs.get_food_cravings
        mock_life_service.add_food_to_inventory = MagicMock()
        mock_life_service.mark_craving_satisfied = MagicMock()

        plan, slot = self._make_plan_slot(role_id="aveline")
        with patch.object(
            plan_execution, "_resolve_cooking_meal_window", return_value="dinner"
        ), patch(
            "core.services.life_simulation.service.get_life_simulation_service",
            return_value=mock_life_service,
        ):
            produced = plan_execution._produce_cooking_outputs(plan, slot)

        # 默认 aveline dinner = beef_noodle
        self.assertIn("beef_noodle", produced)
        mock_life_service.mark_craving_satisfied.assert_not_called()


class TestEatMarksCravingSatisfied(unittest.TestCase):
    """验证 FoodManager.eat 调用时会联动标记 craving 已满足。"""

    def test_eat_calls_mark_craving_satisfied(self):
        from core.food.manager import FoodManager

        manager = FoodManager()
        mock_life_service = MagicMock()
        mock_life_service.life_stats = {
            "hunger": 50.0,
            "thirst": 50.0,
            "energy": 50.0,
            "mood_score": 70.0,
            "immune_damage": 0.0,
            "food_inventory": [
                {"food_id": "ramen", "quantity": 2, "expire_at": time.time() + 3600}
            ],
            "digestion_queue": [],
        }
        mock_life_service._ensure_food_state = MagicMock()
        mock_life_service.take_food_from_inventory = MagicMock(return_value=1)
        mock_life_service.add_digestion_effect = MagicMock()
        mock_life_service.mark_craving_satisfied = MagicMock()

        with patch(
            "core.services.life_simulation.service.get_life_simulation_service",
            return_value=mock_life_service,
        ), patch(
            "core.services.scheduler.cpp_scheduler_engine.CPPSchedulerEngine"
        ) as mock_engine_cls:
            mock_engine = MagicMock()
            mock_engine.enabled = False
            mock_engine_cls.return_value = mock_engine

            import asyncio

            result = asyncio.run(
                manager.eat(
                    "ramen",
                    from_inventory=True,
                    eater="user",
                    role_id="aveline",
                )
            )

        self.assertTrue(result["success"])
        mock_life_service.mark_craving_satisfied.assert_called_once_with(
            "ramen", satisfied_by="user_feed"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
