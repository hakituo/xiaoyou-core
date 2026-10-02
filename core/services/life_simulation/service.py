"""生命模拟服务（门面）。

重构后作为轻量级门面，委托 LifeOrchestrator 处理所有协调逻辑。
外部 API 完全兼容：所有原方法和属性保持不变。

架构层次：
  LifeSimulationService（门面）
    └── LifeOrchestrator（总协调器）
          ├── HardwareCoordinator → HardwareMonitor
          ├── ActorCoordinator    → ActorManager
          ├── FoodCoordinator     → FoodSystem + AutoEatManager
          ├── SleepCoordinator    → SleepManager
          ├── ReactionCoordinator → RitualManager + ReactionManager
          └── WebSocketCoordinator → WebSocketManager
"""

import threading
import time
from typing import Any, Dict, List, Optional

from core.utils.logger import get_logger

from .orchestrator import LifeOrchestrator

logger = get_logger("LIFE_SIMULATION")


class LifeSimulationService:
    """生命模拟服务（门面）。

    通过委托 LifeOrchestrator 实现全部功能，外部 API 完全兼容。
    原始 532 行 → 重构后约 200 行，协调逻辑移入 Orchestrator。
    """

    def __init__(self, orchestrator: Optional[LifeOrchestrator] = None):
        self._orchestrator = orchestrator or LifeOrchestrator()

    # ==================== 属性代理（外部直接访问） ====================

    @property
    def orchestrator(self) -> LifeOrchestrator:
        return self._orchestrator

    @property
    def settings(self):
        return self._orchestrator.settings

    @property
    def life_config(self):
        return self._orchestrator.life_config

    @property
    def hardware_monitor(self):
        return self._orchestrator.hardware_monitor

    @property
    def reaction_manager(self):
        return self._orchestrator.reaction_manager

    @property
    def life_stats_manager(self):
        return self._orchestrator.life_stats_manager

    @property
    def life_stats(self) -> Dict[str, Any]:
        return self._orchestrator.life_stats

    @property
    def status(self) -> Dict[str, Any]:
        return self._orchestrator.status

    @property
    def actor_manager(self):
        return self._orchestrator.actor_manager

    @property
    def food_system(self):
        return self._orchestrator.food_system

    @property
    def health_monitor(self):
        return self._orchestrator.health_monitor

    @property
    def auto_eat_manager(self):
        return self._orchestrator.auto_eat_manager

    @property
    def sleep_manager(self):
        return self._orchestrator.sleep_manager

    @property
    def ritual_manager(self):
        return self._orchestrator.ritual_manager

    @property
    def last_interaction_time(self) -> float:
        return self._orchestrator.last_interaction_time

    @last_interaction_time.setter
    def last_interaction_time(self, value: float):
        self._orchestrator.last_interaction_time = value

    @property
    def active_minutes_today(self) -> int:
        return self._orchestrator.active_minutes_today

    # ==================== 角色管理（委托 ActorCoordinator） ====================

    def get_actor_life_state(self, actor_id: Optional[str]) -> Dict[str, Any]:
        """获取角色生命状态"""
        return self._orchestrator.actor_coordinator.get_actor_life_state(actor_id)

    def update_actor_interaction(self, actor_id: Optional[str], xp_gain: int = 2):
        """更新角色交互"""
        self._orchestrator.actor_coordinator.update_actor_interaction(actor_id, xp_gain)

    def feed_actor(self, actor_id: Optional[str], hunger_amount: float = 8.0):
        """喂食角色"""
        return self._orchestrator.actor_coordinator.feed_actor(actor_id, hunger_amount)

    def get_actor_relationship(
        self, actor_a: Optional[str], actor_b: Optional[str]
    ) -> float:
        """获取角色关系值"""
        return self._orchestrator.actor_coordinator.get_actor_relationship(actor_a, actor_b)

    def add_actor_relationship(
        self, actor_a: Optional[str], actor_b: Optional[str], delta: float = 0.0
    ) -> float:
        """增加角色关系值"""
        return self._orchestrator.actor_coordinator.add_actor_relationship(actor_a, actor_b, delta)

    def share_food_between_actors(
        self,
        actor_a: Optional[str],
        actor_b: Optional[str],
        hunger_amount: float = 6.0,
    ) -> Dict[str, Any]:
        """角色间分享食物"""
        return self._orchestrator.actor_coordinator.share_food_between_actors(
            actor_a, actor_b, hunger_amount
        )

    # ==================== 食物系统（委托 FoodCoordinator） ====================

    def add_food_to_inventory(self, food_id: str, quantity: int, expire_at_ts: float):
        """添加食物到库存"""
        self._orchestrator.food_coordinator.add_food_to_inventory(
            food_id, quantity, expire_at_ts
        )

    def take_food_from_inventory(self, food_id: str, quantity: int) -> int:
        """从库存取出食物"""
        return self._orchestrator.food_coordinator.take_food_from_inventory(
            food_id, quantity
        )

    def cleanup_expired_food(self) -> int:
        """清理过期食物"""
        return self._orchestrator.food_coordinator.cleanup_expired_food()

    def add_digestion_effect(
        self, effects: Dict[str, float], duration_seconds: float, buff_desc: str = ""
    ):
        """添加消化效果"""
        self._orchestrator.food_coordinator.add_digestion_effect(
            effects, duration_seconds, buff_desc
        )

    def tick_digestion(self):
        """处理消化"""
        self._orchestrator.food_coordinator.tick_digestion()

    # ==================== 食物愿望清单（cravings） ====================

    def add_food_craving(
        self,
        food_id: str,
        reason: str = "",
        ttl_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """添加"想吃X"愿望"""
        return self._orchestrator.food_coordinator.add_food_craving(
            food_id, reason, ttl_seconds
        )

    def get_food_cravings(
        self,
        only_active: bool = False,
        food_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """读取愿望清单"""
        return self._orchestrator.food_coordinator.get_food_cravings(
            only_active, food_type
        )

    def mark_craving_satisfied(
        self,
        food_id: str,
        satisfied_by: str = "cooking",
    ) -> bool:
        """标记愿望已满足"""
        return self._orchestrator.food_coordinator.mark_craving_satisfied(
            food_id, satisfied_by
        )

    def cleanup_expired_cravings(self) -> int:
        """清理过期愿望"""
        return self._orchestrator.food_coordinator.cleanup_expired_cravings()

    # ==================== 生命状态（委托 LifeStatsManager） ====================

    def feed(self, amount: float = 30) -> Dict[str, Any]:
        """喂食"""
        self.update_interaction(xp_gain=0)
        return self._orchestrator.life_stats_manager.feed(amount)

    def drink(self, amount: float = 30) -> Dict[str, Any]:
        """喝水"""
        self.update_interaction(xp_gain=0)
        return self._orchestrator.life_stats_manager.drink(amount)

    def sleep(self, duration: int = 0) -> Dict[str, Any]:
        """睡觉"""
        self.update_interaction(xp_gain=0)
        return self._orchestrator.life_stats_manager.sleep(duration)

    def update_interaction(self, xp_gain: int = 5):
        """更新交互"""
        self._orchestrator.last_interaction_time = time.time()
        self.add_xp(xp_gain)

    def add_xp(self, amount: int):
        """添加经验值"""
        self._orchestrator.life_stats_manager.add_xp(amount)

    def note_intimacy_context(self, bump: Optional[float] = None):
        """记录亲密上下文"""
        self._orchestrator.life_stats_manager.note_intimacy_context(bump)

    # ==================== 睡眠管理（委托 SleepCoordinator） ====================

    def get_sleep_state(self, role_id: str) -> Dict[str, Any]:
        """获取角色睡眠摘要。"""
        return self._orchestrator.sleep_coordinator.get_sleep_state(role_id)

    def get_sleep_summary(self, role_id: str) -> Dict[str, Any]:
        """获取角色睡眠摘要。"""
        return self._orchestrator.sleep_coordinator.get_sleep_summary(role_id)

    def get_bio_state(self, role_id: str) -> Dict[str, Any]:
        """获取角色生物状态摘要，供角色日常等链路复用。"""
        return {
            "life": dict(self._orchestrator.life_stats),
            "sleep": self.get_sleep_summary(role_id),
            "mood": self._orchestrator.status.get("mood", "unknown"),
            "activity": self._orchestrator.status.get("activity", "unknown"),
        }

    def notify_sleep_interruption(
        self,
        role_id: str,
        message: str = "",
        conversation_id: str = "",
    ) -> Dict[str, Any]:
        """记录角色被吵醒。"""
        return self._orchestrator.sleep_coordinator.notify_sleep_interruption(
            role_id=role_id,
            message=message,
            conversation_id=conversation_id,
        )

    def notify_sleep_chat_activity(
        self,
        role_id: str,
        message: str = "",
    ) -> Dict[str, Any]:
        """记录被吵醒后的继续聊天。"""
        return self._orchestrator.sleep_coordinator.notify_sleep_chat_activity(
            role_id=role_id,
            message=message,
        )

    async def finalize_sleep_recovery_check(self, role_id: str) -> Dict[str, Any]:
        """执行静默窗口后的恢复判定。"""
        return await self._orchestrator.sleep_coordinator.finalize_sleep_recovery_check(
            role_id
        )

    # ==================== 状态与生命周期（委托 Orchestrator） ====================

    def update(self):
        """更新内部状态"""
        self._orchestrator.update()

    def get_state(self) -> Dict[str, Any]:
        """获取当前状态快照"""
        return self._orchestrator.build_state()

    def get_state_for_scope(self, scope: str) -> Dict[str, Any]:
        """获取指定角色 scope 的状态快照。

        生命状态(life)从 ActorManager 取该角色的独立数据（energy/hunger/thirst/mood_score 等），
        而不是全局共享的 life_stats。其他字段（bio/immune/hardware）仍共享全局。
        """
        state = self._orchestrator.build_state()
        normalized_scope = str(scope or "").strip().lower() or "aveline"
        actor_state = self._orchestrator.actor_coordinator.get_actor_life_state(normalized_scope)
        if actor_state:
            # 用该角色的独立生命状态覆盖全局 life 字段
            state["life"] = actor_state
            state["life_scope"] = normalized_scope
        return state

    def get_emotion_for_scope(self, scope: str) -> Dict[str, Any]:
        """获取指定角色 scope 的情绪状态。

        TODO: 后端情绪目前按 WebSocket user_id 隔离，未与 persona scope 打通。
        此处先返回 mock 占位数据，待情绪系统 per-scope 改造后接入真实数据。
        """
        normalized_scope = str(scope or "").strip().lower() or "aveline"
        return {
            "primary_emotion": "calm",
            "intensity": 0.5,
            "emotion_mix": {},
            "scope": normalized_scope,
            "mock": True,  # 标识当前为 mock 数据，前端可据此显示"情绪开发中"
        }

    async def start(self):
        """启动服务"""
        await self._orchestrator.start()

    async def stop(self):
        """停止服务"""
        await self._orchestrator.stop()

    async def start_monitor(self):
        """启动监控任务"""
        await self._orchestrator.start_monitor()

    @property
    def _monitor_task(self):
        return self._orchestrator._monitor_task


# ==================== 单例 ====================

_service_instance = None
_service_lock = threading.Lock()


def get_life_simulation_service() -> LifeSimulationService:
    """获取生命模拟服务单例（线程安全）"""
    global _service_instance
    if _service_instance is None:
        with _service_lock:
            if _service_instance is None:
                _service_instance = LifeSimulationService()
    return _service_instance
