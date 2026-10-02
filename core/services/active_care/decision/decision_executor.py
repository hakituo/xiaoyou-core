"""
决策执行模块
负责执行主动关怀的最终决策逻辑，委托 action_builder 和 context_gatherer 完成具体工作。
"""
import asyncio
import random
from typing import Any, Dict, List, Tuple

from core.utils.logger import get_module_logger
from core.services.active_care.decision.decision_context import DecisionFlowContext
from core.services.active_care.decision.action_builder import (
    build_available_actions,
    apply_action_overrides,
    should_force_send,
)
from core.services.active_care.decision.context_gatherer import (
    get_workspace_snapshot,
    get_recent_history,
    get_user_signal_and_intent,
    get_life_and_emotion_state,
    build_urgent_needs,
    sanitize_device_context,
)

logger = get_module_logger("ACTIVE_CARE_DECISION", "active_care_schedule.log")


class DecisionExecutor:
    """决策执行器，负责执行主动关怀的最终决策"""

    def __init__(self, storage, context, decision, executor, priority_analyzer, intent_detector, sleep_policy):
        self.storage = storage
        self.context = context
        self.decision = decision
        self.executor = executor
        self.priority_analyzer = priority_analyzer
        self.intent_detector = intent_detector
        self.sleep_policy = sleep_policy

    # ---- 委托 action_builder ----

    def build_available_actions(self, *args, **kwargs) -> List[str]:
        """构建可用动作列表（委托 action_builder）"""
        return build_available_actions(*args, **kwargs)

    def apply_action_overrides(self, chosen_action: str, ctx: "DecisionFlowContext") -> Tuple[str, int]:
        """应用动作覆盖规则（委托 action_builder）"""
        return apply_action_overrides(chosen_action, ctx)

    def should_force_send(self, ctx: "DecisionFlowContext", non_response_count: int = 0) -> Tuple[bool, str]:
        """判断是否应该强制发送（委托 action_builder）"""
        return should_force_send(ctx, non_response_count)

    # ---- 委托 context_gatherer ----

    async def get_workspace_snapshot(self, now_dt) -> Dict[str, Any]:
        """获取工作区快照（委托 context_gatherer）"""
        return await get_workspace_snapshot(now_dt)

    async def get_recent_history(self, workspace_snapshot: Dict[str, Any], cached_history: list = None) -> List[Dict[str, Any]]:
        """获取最近的历史记录（委托 context_gatherer）"""
        return await get_recent_history(workspace_snapshot, cached_history, context=self.context)

    async def get_user_signal_and_intent(
        self, cached_history: list = None, primary_cid: str = None, persona_filename: str = ""
    ) -> Tuple[str, float, bool, bool, bool, str]:
        """获取用户信号与意图（委托 context_gatherer）"""
        return await get_user_signal_and_intent(
            cached_history, primary_cid, persona_filename,
            context=self.context, intent_detector=self.intent_detector,
        )

    def get_life_and_emotion_state(self) -> Tuple[Dict, Dict, Dict, Dict]:
        """获取生命状态和情绪状态（委托 context_gatherer）"""
        return get_life_and_emotion_state()

    def build_urgent_needs(self, life_stats: Dict, immune_stats: Dict, device_context: Dict, now: float) -> List[str]:
        """构建紧急需求列表（委托 context_gatherer）"""
        return build_urgent_needs(life_stats, immune_stats, device_context, now)

    def sanitize_device_context(self, device_context: Dict, now: float) -> Dict:
        """清理设备上下文，移除过期数据（委托 context_gatherer）"""
        return sanitize_device_context(device_context, now)

    # ---- 核心决策入口 ----

    async def select_action(
        self,
        decision_ctx: Dict,
        available_actions: List[str],
        priority_analysis: Dict,
        priority_focus: Dict,
        urgent_needs: List[str],
    ) -> str:
        """选择动作

        决策优先级（题材感知 MDP 优先，bandit 兜底）：
        1. 每日推送优先级 / must_probe / 紧急需求等规则覆盖（原有，最高优先级）
        2. MDP 选择（若 Q 表有数据）——题材感知，按 (state, action) 学习
        3. 回退 Contextual Bandit（MDP 冷启动/异常时兜底，原有逻辑）
        """
        try:
            ranked_priority = []
            if isinstance(priority_analysis, dict):
                ranked_priority = priority_analysis.get("ranked") or []
            top_priority = ranked_priority[0] if isinstance(ranked_priority, list) and ranked_priority else {}
            top_intent = str((top_priority or {}).get("suggested_intent") or "").strip()

            if top_intent and top_intent in available_actions:
                chosen_action = top_intent
                logger.info(
                    "Active Care: chosen_action overridden by daily priority -> %s (%s)",
                    top_intent,
                    str((top_priority or {}).get("title") or "")[:80],
                )
            elif priority_focus.get("must_probe") and not urgent_needs:
                # must_probe：必须主动探测，但不硬编码 curious_question，
                # 否则会架空 MDP（Q 表白学）。改为让 MDP 从"非 do_nothing"
                # 动作中按 Q 表选一个，冷启动/异常时回退 bandit。
                probe_actions = [a for a in available_actions if a != "do_nothing"]
                if not probe_actions:
                    probe_actions = ["curious_question"]
                chosen_action = await self._select_mdp_or_bandit(
                    decision_ctx, probe_actions
                )
                logger.info(
                    "Active Care: Priority probe mode enabled by portrait/tasks snapshot, "
                    "action chosen by MDP/bandit -> %s",
                    chosen_action,
                )
            elif urgent_needs:
                if random.random() < 0.8:
                    chosen_action = "bio_complaint"
                else:
                    chosen_action = await self._select_mdp_or_bandit(
                        decision_ctx, available_actions
                    )
            else:
                chosen_action = await self._select_mdp_or_bandit(
                    decision_ctx, available_actions
                )
        except asyncio.TimeoutError:
            raise asyncio.TimeoutError("select_action timed out")

        return chosen_action

    async def _select_mdp_or_bandit(
        self, decision_ctx: Dict, available_actions: List[str]
    ) -> str:
        """题材感知 MDP 优先选择，bandit 兜底。

        逻辑：
        1. 用 proactive_state 派生当前 MDP 状态 S = (tod, last_topic, last_reply)
        2. 若 MDP Q 表非空（已积累学习数据），用 MDP 选择动作
        3. 否则（冷启动/无数据/异常）回退 bandit
        """
        try:
            from core.services.active_care.decision.mdp import (
                ActiveCareMDP,
                derive_mdp_state_from_proactive_state,
            )
            from core.utils.time_utils import get_current_time

            state = await self.storage.get_proactive_state()
            if isinstance(state, dict) and state:
                state_key = derive_mdp_state_from_proactive_state(
                    state, get_current_time()
                )
                mdp = ActiveCareMDP(self.storage)
                q = await mdp._load_q()
                if q:
                    return await asyncio.wait_for(
                        mdp.select_action(state_key, available_actions),
                        timeout=5.0,
                    )
                logger.info(
                    "Active Care: MDP Q 表为空（冷启动），回退 bandit"
                )
        except asyncio.TimeoutError:
            logger.warning("Active Care: MDP 选择超时，回退 bandit")
        except Exception as e:
            logger.debug(f"Active Care: MDP 选择失败回退 bandit: {e}")

        return await asyncio.wait_for(
            self.decision.select_action_bandit(decision_ctx, available_actions),
            timeout=12.0,
        )
