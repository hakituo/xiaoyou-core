"""生命模拟协调器层。

将原 LifeSimulationService 中的多领域协调逻辑拆分为 6 个专职协调器：
- HardwareCoordinator: 硬件状态采集与过热检测
- ActorCoordinator: 角色状态与关系管理
- FoodCoordinator: 食物库存、消化与自动进食
- SleepCoordinator: 睡眠状态与恢复判定
- ReactionCoordinator: 仪式与自发反应检查
- WebSocketCoordinator: 状态广播

各协调器仅持有自己领域的子模块，互不依赖，可独立测试。
"""

from .hardware_coordinator import HardwareCoordinator
from .actor_coordinator import ActorCoordinator
from .food_coordinator import FoodCoordinator
from .sleep_coordinator import SleepCoordinator
from .reaction_coordinator import ReactionCoordinator
from .websocket_coordinator import WebSocketCoordinator

__all__ = [
    "HardwareCoordinator",
    "ActorCoordinator",
    "FoodCoordinator",
    "SleepCoordinator",
    "ReactionCoordinator",
    "WebSocketCoordinator",
]
