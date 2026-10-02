"""主动关怀动作选择模块（Contextual Bandit + JITAI 启发式）

从 decision.py 拆分而来，职责：
- 长时间沉默打破器（强制非 do_nothing）
- 基于奖励分值的 Contextual Bandit 探索/利用
- JITAI 启发式（紧急生理需求 / 极度过热）
- LLM 驱动的动作推理（可被调度器忙/超时降级）

对外暴露 ActionSelector 类，供 ActiveCareDecision 门面委托调用。
"""

import asyncio
import json
import random
import re
from typing import Any, Dict, List

from config.debug_config import is_debug_enabled
from config.integrated_config import get_settings
from core.llm import get_llm_module
from core.services.active_care.shared.tuning import DEFAULT_BANDIT_EPSILON
from core.services.active_care.storage.storage import ActiveCareStorage
from core.utils.config_accessor import get_active_care_config
from core.utils.logger import get_logger

logger = get_logger("ACTIVE_CARE_DECISION")

_UNINITIALIZED_SENTINEL = object()
_cached_scheduler_engine = _UNINITIALIZED_SENTINEL


def _get_scheduler_engine():
    global _cached_scheduler_engine
    if _cached_scheduler_engine is _UNINITIALIZED_SENTINEL:
        try:
            from core.services.scheduler.cpp_scheduler_engine import CPPSchedulerEngine

            _cached_scheduler_engine = CPPSchedulerEngine()
        except Exception:
            _cached_scheduler_engine = None
    return _cached_scheduler_engine if _cached_scheduler_engine is not None else None


class ActionSelector:
    """Contextual Bandit 动作选择器

    通过整体注入 storage 访问策略分值；settings 懒加载避免导入期副作用。
    """

    def __init__(self, storage: ActiveCareStorage):
        self.storage = storage
        self.settings = get_settings()

    async def select_action_bandit(
        self, ctx: Dict[str, Any], actions: List[str]
    ) -> str:
        """Contextual Bandit for Action Selection."""
        # 0. 强制动作检查（长时间沉默打破器）
        elapsed = ctx.get("elapsed_seconds", 0)
        silence_threshold = int(
            get_active_care_config("active_care_silence_breaker_seconds", default=2700, settings=self.settings)
            or 2700
        )
        quiet_mode_active = bool(ctx.get("quiet_mode_active", False))

        if (
            not quiet_mode_active
            and elapsed > silence_threshold
            and "do_nothing" in actions
        ):
            logger.info(
                f"Active Care: Long silence detected ({elapsed}s > {silence_threshold}s). Forcing proactive action (removing do_nothing)."
            )
            actions = [a for a in actions if a != "do_nothing"]
            if not actions:
                actions = ["share_thought"]

        epsilon = get_active_care_config(
            "active_care_epsilon",
            default=DEFAULT_BANDIT_EPSILON,
            settings=self.settings,
        )
        scores = await self.storage.load_policy_scores()

        # 1. 探索（随机选择）
        if random.random() < epsilon:
            chosen = random.choice(actions)
            if is_debug_enabled("active_care_decision"):
                logger.info(f"Active Care: Bandit Exploration (Random) -> {chosen}")
            return chosen

        # 2. 启发式/基于规则的覆盖（JITAI）
        bio = ctx.get("bio_state", {})
        urgent_needs = ctx.get("urgent_needs", [])
        if urgent_needs:
            if is_debug_enabled("active_care_decision"):
                logger.info("Active Care: JITAI Heuristic -> bio_complaint (urgent)")
            return "bio_complaint"

        # 硬件启发式
        cpu_temp = float(bio.get("cpu_temp", 0))
        if cpu_temp > 80:  # 极度过热
            if is_debug_enabled("active_care_decision"):
                logger.info(
                    f"Active Care: JITAI Heuristic -> bio_complaint (CPU {cpu_temp}°C)"
                )
            return "bio_complaint"

        # 3. LLM驱动的利用（推理）
        # 不是直接选择最高分，而是让LLM在表现最好的候选中选择
        top_actions = sorted(
            actions,
            key=lambda a: scores.get(a, {}).get("avg_reward", 0.0),
            reverse=True,
        )[:3]

        try:
            llm = get_llm_module()

            # 优化：资源检查
            scheduler_busy = False
            try:
                scheduler = _get_scheduler_engine()
                if scheduler and scheduler.enabled and scheduler.is_busy():
                    scheduler_busy = True
            except Exception:
                pass

            if scheduler_busy:
                if is_debug_enabled("active_care_decision"):
                    logger.info("Active Care: Scheduler busy, skipping LLM decision")
                # 立即回退到基于评分的选择
                best_action = max(
                    actions, key=lambda a: scores.get(a, {}).get("avg_reward", 0.0)
                )
                return best_action

            from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import DECISION_REASONING_PROMPT_TEMPLATE
            reasoning_prompt = DECISION_REASONING_PROMPT_TEMPLATE.format(
                now=ctx.get('now'),
                user_state=json.dumps(ctx.get('user_bio_state'), ensure_ascii=False),
                candidates=', '.join(top_actions),
            )

            # 动态模型路由
            from config.model_config import resolve_active_care_model_path
            model_path = resolve_active_care_model_path(
                model_type="decision",
                settings=self.settings,
                llm_module=llm,
            )

            recommended = await asyncio.wait_for(
                llm.chat(
                    [{"role": "system", "content": reasoning_prompt}],
                    max_new_tokens=10,
                    temperature=0.1,
                    model_path=model_path,
                ),
                timeout=8.0,
            )

            if isinstance(recommended, dict):
                if recommended.get("status") == "success":
                    recommended = str(recommended.get("response") or "")
                else:
                    recommended = ""
            else:
                recommended = str(recommended or "")

            recommended = recommended.strip().lower()
            recommended = re.sub(r"[^\w\s]", "", recommended)

            for a in actions:
                if a in recommended:
                    if is_debug_enabled("active_care_decision"):
                        logger.info(f"Active Care: LLM Recommended Action -> {a}")
                    return a
        except asyncio.TimeoutError:
            logger.warning(
                "Active Care: LLM decision timed out, falling back to scores"
            )
        except Exception as e:
            if is_debug_enabled("active_care_decision"):
                logger.info(
                    f"Active Care: LLM reasoning skipped/failed ({e}), falling back to scores"
                )

        # 4. 回退：基于评分的利用
        best_action = max(
            actions, key=lambda a: scores.get(a, {}).get("avg_reward", 0.0)
        )
        if is_debug_enabled("active_care_decision"):
            logger.info(f"Active Care: Score-based Exploitation -> {best_action}")

        return best_action
