"""食物系统协调器。

封装 FoodSystem 和 AutoEatManager 的食物库存、消化和自动进食逻辑。
"""

from typing import Any, Dict

from core.services.life_simulation.auto_eat import AutoEatManager
from core.services.life_simulation.food_system import FoodSystem


class FoodCoordinator:
    """食物系统协调器，负责库存管理、消化和自动进食。"""

    def __init__(
        self,
        food_system: FoodSystem,
        auto_eat_manager: AutoEatManager,
    ):
        self._food_system = food_system
        self._auto_eat_manager = auto_eat_manager

    @property
    def food_system(self) -> FoodSystem:
        return self._food_system

    @property
    def auto_eat_manager(self) -> AutoEatManager:
        return self._auto_eat_manager

    def add_food_to_inventory(self, food_id: str, quantity: int, expire_at_ts: float):
        """添加食物到库存。"""
        self._food_system.add_food_to_inventory(food_id, quantity, expire_at_ts)

    def take_food_from_inventory(self, food_id: str, quantity: int) -> int:
        """从库存取出食物。"""
        return self._food_system.take_food_from_inventory(food_id, quantity)

    def cleanup_expired_food(self) -> int:
        """清理过期食物。"""
        return self._food_system.cleanup_expired_food()

    def add_digestion_effect(
        self, effects: Dict[str, float], duration_seconds: float, buff_desc: str = ""
    ):
        """添加消化效果。"""
        self._food_system.add_digestion_effect(effects, duration_seconds, buff_desc)

    def tick_digestion(self):
        """处理消化（每秒调用）。"""
        self._food_system.tick_digestion()

    # ==================== 食物愿望清单（cravings） ====================

    def add_food_craving(
        self,
        food_id: str,
        reason: str = "",
        ttl_seconds: float | None = None,
    ) -> Dict[str, Any]:
        """添加"想吃X"愿望。"""
        return self._food_system.add_food_craving(food_id, reason, ttl_seconds)

    def get_food_cravings(
        self,
        only_active: bool = False,
        food_type: str | None = None,
    ) -> list[Dict[str, Any]]:
        """读取愿望清单。"""
        return self._food_system.get_food_cravings(only_active, food_type)

    def mark_craving_satisfied(
        self,
        food_id: str,
        satisfied_by: str = "cooking",
    ) -> bool:
        """标记愿望已满足。"""
        return self._food_system.mark_craving_satisfied(food_id, satisfied_by)

    def cleanup_expired_cravings(self) -> int:
        """清理过期愿望。"""
        return self._food_system.cleanup_expired_cravings()

    async def maybe_auto_eat(self, now: float):
        """检查并执行自动进食（每分钟调用）。"""
        await self._auto_eat_manager.maybe_auto_eat(now)
