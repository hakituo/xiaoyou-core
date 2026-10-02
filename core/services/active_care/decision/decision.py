"""主动关怀决策门面

从 700+ 行单体拆分而来，职责收敛为：把三个决策子能力委托给独立模块。
保持原有方法签名不变，调用方（service / checker / peer_chat_scheduler）无需改动。

- select_action_bandit   → decision.action_selector.ActionSelector
- decide_proactive_content → decision.content_planner.ContentPlanner
- decide_peer_chat       → peer_chat.peer_chat_decision.PeerChatDecider
"""

from typing import Any, Dict, List

from core.services.active_care.decision.action_selector import ActionSelector
from core.services.active_care.decision.content_planner import ContentPlanner
from core.services.active_care.peer_chat.peer_chat_decision import PeerChatDecider
from core.services.active_care.storage.storage import ActiveCareStorage


class ActiveCareDecision:
    def __init__(self, storage: ActiveCareStorage):
        self.storage = storage
        self._action_selector = ActionSelector(storage)
        self._content_planner = ContentPlanner(storage)
        self._peer_chat_decider = PeerChatDecider()

    async def select_action_bandit(
        self, ctx: Dict[str, Any], actions: List[str]
    ) -> str:
        """Contextual Bandit for Action Selection."""
        return await self._action_selector.select_action_bandit(ctx, actions)

    async def decide_proactive_content(
        self,
        context: Dict[str, Any],
        chosen_action: str,
        device_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generate proactive content based on selected action."""
        return await self._content_planner.decide(
            context, chosen_action, device_context,
        )

    async def decide_peer_chat(
        self,
        context: Dict[str, Any],
        role_id: str,
        peer_name: str,
    ) -> Dict[str, Any]:
        """决策是否主动找对方角色聊天"""
        return await self._peer_chat_decider.decide(context, role_id, peer_name)
