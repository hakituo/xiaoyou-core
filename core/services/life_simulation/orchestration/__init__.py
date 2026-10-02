"""生命模拟编排层。

把原 ``orchestrator.py`` 一个 567 行大类按职责拆成 4 个 mixin：
- ``LifeRuntimeMixin``：监控任务启停与每秒主循环
- ``LifeMinuteTickMixin``：每分钟衰减、自动进食、日记补写窗口上报
- ``LifeEmotionMixin``：生命状态到情绪系统的影响
- ``LifeStateMixin``：活动/情绪推导与对外状态快照

各 mixin 只操作 ``LifeOrchestrator`` 实例上的属性，互不依赖，可独立测试。
"""

from .emotion import LifeEmotionMixin
from .minute_tick import LifeMinuteTickMixin
from .runtime import LifeRuntimeMixin
from .state_building import LifeStateMixin

__all__ = [
    "LifeEmotionMixin",
    "LifeMinuteTickMixin",
    "LifeRuntimeMixin",
    "LifeStateMixin",
]
