"""角色管理协调器。

封装 ActorManager 的角色状态更新、关系管理和交互处理。
"""

from typing import Any, Dict, Optional

from core.services.life_simulation.actor_manager import ActorManager


class ActorCoordinator:
    """角色管理协调器，负责角色状态与关系的统一管理。"""

    def __init__(self, actor_manager: ActorManager):
        self._actor_manager = actor_manager

    @property
    def actor_manager(self) -> ActorManager:
        return self._actor_manager

    def get_actor_life_state(self, actor_id: Optional[str]) -> Dict[str, Any]:
        """获取角色生命状态。"""
        return self._actor_manager.get_actor_life_state(actor_id)

    def update_actor_interaction(self, actor_id: Optional[str], xp_gain: int = 2):
        """更新角色交互。"""
        self._actor_manager.update_actor_interaction(actor_id, xp_gain)

    def feed_actor(self, actor_id: Optional[str], hunger_amount: float = 8.0):
        """喂食角色。"""
        return self._actor_manager.feed_actor(actor_id, hunger_amount)

    def get_actor_relationship(
        self, actor_a: Optional[str], actor_b: Optional[str]
    ) -> float:
        """获取角色关系值。"""
        return self._actor_manager.get_actor_relationship(actor_a, actor_b)

    def add_actor_relationship(
        self, actor_a: Optional[str], actor_b: Optional[str], delta: float = 0.0
    ) -> float:
        """增加角色关系值。"""
        return self._actor_manager.add_actor_relationship(actor_a, actor_b, delta)

    def share_food_between_actors(
        self,
        actor_a: Optional[str],
        actor_b: Optional[str],
        hunger_amount: float = 6.0,
    ) -> Dict[str, Any]:
        """角色间分享食物。"""
        return self._actor_manager.share_food_between_actors(
            actor_a, actor_b, hunger_amount
        )

    def tick_all_actors(self, activity: str):
        """更新所有角色的生命状态（每分钟调用）。"""
        self._actor_manager.tick_actor_life_states(activity)

    def get_all_actor_states(self) -> Dict[str, Any]:
        """获取所有角色状态。"""
        return self._actor_manager.get_all_actor_states()

    def get_all_relationships(self) -> Dict[str, float]:
        """获取所有角色关系。"""
        return self._actor_manager.get_all_relationships()
