"""反应协调器。

封装 RitualManager 的仪式检查和 ReactionManager 的自发反应逻辑。
"""

from typing import Any, Dict, Optional

from core.services.reaction.reaction_manager import ReactionManager
from core.services.life_simulation.ritual_manager import RitualManager


class ReactionCoordinator:
    """反应协调器，负责仪式触发与自发反应检查。"""

    def __init__(
        self,
        ritual_manager: RitualManager,
        reaction_manager: ReactionManager,
    ):
        self._ritual_manager = ritual_manager
        self._reaction_manager = reaction_manager

    @property
    def ritual_manager(self) -> RitualManager:
        return self._ritual_manager

    @property
    def reaction_manager(self) -> ReactionManager:
        return self._reaction_manager

    def check_rituals(self, active_minutes: int) -> Optional[str]:
        """检查是否应该触发日常仪式。"""
        return self._ritual_manager.check_rituals(active_minutes)

    async def check_spontaneous_reaction(
        self, state: Dict[str, Any], last_interaction_time: float
    ) -> Optional[str]:
        """检查并返回自发反应文本。"""
        return await self._reaction_manager.check_spontaneous_reaction(
            state, last_interaction_time
        )

    def record_reaction(self):
        """记录一次自发反应已触发。"""
        self._reaction_manager.record_reaction()
