"""
生命模拟服务协议类
定义 ILifeSimulation 接口，解耦服务消费者与具体实现
"""
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class ILifeSimulation(Protocol):
    """生命模拟服务协议接口"""

    def get_actor_life_state(self, actor_id: Optional[str]) -> Dict[str, Any]: ...

    def update_actor_interaction(self, actor_id: Optional[str], xp_gain: int = 2): ...

    def feed_actor(self, actor_id: Optional[str], hunger_amount: float = 8.0): ...

    def get_actor_relationship(
        self, actor_a: Optional[str], actor_b: Optional[str]
    ) -> float: ...

    def add_actor_relationship(
        self, actor_a: Optional[str], actor_b: Optional[str], delta: float = 0.0
    ) -> float: ...

    def share_food_between_actors(
        self,
        actor_a: Optional[str],
        actor_b: Optional[str],
        hunger_amount: float = 6.0,
    ) -> Dict[str, Any]: ...

    def add_food_to_inventory(
        self, food_id: str, quantity: int, expire_at_ts: float
    ): ...

    def take_food_from_inventory(self, food_id: str, quantity: int) -> int: ...

    def cleanup_expired_food(self) -> int: ...

    def add_digestion_effect(
        self, effects: Dict[str, float], duration_seconds: float, buff_desc: str = ""
    ): ...

    def tick_digestion(self): ...

    def add_food_craving(
        self,
        food_id: str,
        reason: str = "",
        ttl_seconds: Optional[float] = None,
    ) -> Dict[str, Any]: ...

    def get_food_cravings(
        self,
        only_active: bool = False,
        food_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]: ...

    def mark_craving_satisfied(
        self,
        food_id: str,
        satisfied_by: str = "cooking",
    ) -> bool: ...

    def cleanup_expired_cravings(self) -> int: ...

    def feed(self, amount: float = 30) -> Dict[str, Any]: ...

    def drink(self, amount: float = 30) -> Dict[str, Any]: ...

    def sleep(self, duration: int = 0) -> Dict[str, Any]: ...

    def update_interaction(self, xp_gain: int = 5): ...

    def add_xp(self, amount: int): ...

    def note_intimacy_context(self, bump: Optional[float] = None): ...

    def get_state(self) -> Dict[str, Any]: ...
