"""生命模拟总协调器（LifeOrchestrator）。

从 LifeSimulationService 中提取的主循环协调逻辑，负责：
- 每秒 tick：硬件采集、消化、健康检查、情绪影响、状态广播
- 每分钟 tick：角色状态衰减、过期食物清理、自动进食、日记补写窗口上报
- 事件检查：仪式触发、自发反应

本文件是薄壳门面，只负责装配子模块与持有运行时状态字段；具体职责按模块
拆在同入口的 ``orchestration/`` 子目录：
- ``runtime.py``：监控任务启停与每秒主循环
- ``minute_tick.py``：每分钟衰减任务与日记补写窗口上报
- ``emotion.py``：生命状态到情绪系统的影响
- ``state_building.py``：活动/情绪推导与对外状态快照

LifeSimulationService 作为门面保留全部外部 API，将协调职责委托给本类。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from core.utils.time_utils import now_str

from config.integrated_config import get_settings
from core.services.monitoring.hardware_monitor import HardwareMonitor
from core.services.reaction.reaction_manager import ReactionManager

from .actor_manager import ActorManager
from .auto_eat import AutoEatManager
from .coordinators import (
    ActorCoordinator,
    FoodCoordinator,
    HardwareCoordinator,
    ReactionCoordinator,
    SleepCoordinator,
    WebSocketCoordinator,
)
from .food_system import FoodSystem
from .health_monitor import HealthMonitor
from .life_stats import LifeStatsManager
from .orchestration import (
    LifeEmotionMixin,
    LifeMinuteTickMixin,
    LifeRuntimeMixin,
    LifeStateMixin,
)
from .ritual_manager import RitualManager
from .sleep_manager import get_sleep_manager


class LifeOrchestrator(
    LifeRuntimeMixin,
    LifeMinuteTickMixin,
    LifeEmotionMixin,
    LifeStateMixin,
):
    """生命模拟总协调器。

    负责：
    1. 初始化和管理所有子模块及协调器
    2. 运行主监控循环（orchestration/runtime.py）
    3. 每分钟定时任务（orchestration/minute_tick.py）
    4. 情绪影响应用（orchestration/emotion.py）
    5. 状态聚合（orchestration/state_building.py）

    外部通过 LifeSimulationService 门面间接访问，不直接实例化。
    """

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.life_config = self.settings.life_simulation

        # ── 核心子模块 ──
        self.hardware_monitor = HardwareMonitor()
        self.reaction_manager = ReactionManager(self.life_config)

        self.life_stats_manager = LifeStatsManager(self.life_config)
        self.life_stats = self.life_stats_manager.get_life_stats()

        self.status: dict[str, Any] = self.hardware_monitor.get_stats()
        self.status.update(
            {"mood": "calm", "activity": "idle", "life": self.life_stats}
        )

        self.actor_manager = ActorManager()
        self.food_system = FoodSystem(self.life_stats, self.status)
        self.health_monitor = HealthMonitor(
            self.life_stats, self.life_config, self.status
        )
        self.auto_eat_manager = AutoEatManager(self.life_stats, self.actor_manager)
        self.sleep_manager = get_sleep_manager()
        self.ritual_manager = RitualManager()

        # ── 专职协调器 ──
        self.hardware_coordinator = HardwareCoordinator(self.hardware_monitor)
        self.actor_coordinator = ActorCoordinator(self.actor_manager)
        self.food_coordinator = FoodCoordinator(self.food_system, self.auto_eat_manager)
        self.sleep_coordinator = SleepCoordinator(self.sleep_manager)
        self.reaction_coordinator = ReactionCoordinator(
            self.ritual_manager, self.reaction_manager
        )
        self.websocket_coordinator = WebSocketCoordinator()

        # ── 运行时状态 ──
        self.last_update = time.time()
        self._monitor_task: asyncio.Task | None = None
        self.last_interaction_time = time.time()
        self._consecutive_errors = 0

        self.active_minutes_today = 0
        self.last_minute_check = time.time()
        self._active_minutes_date = now_str("%Y-%m-%d")
