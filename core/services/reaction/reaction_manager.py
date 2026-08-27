from core.utils.logger import get_logger
import time
import random

import os
from typing import Optional, Dict, Any, Union

from core.character.aveline import AvelineCharacter
from core.llm import get_llm_module
from core.utils.time_utils import get_current_time

try:
    from config.integrated_config import LifeSimulationSettings
except ImportError:
    LifeSimulationSettings = None

logger = get_logger(__name__)


class ReactionManager:
    """
    Manages spontaneous reactions based on system state and environment.
    """

    def __init__(self, config: Union[Dict[str, Any], Any] = None):
        self.config = config or {}
        if hasattr(self.config, "model_dump"):
            self.config_dict = self.config.model_dump()
        elif hasattr(self.config, "dict"):
            self.config_dict = self.config.dict()
        else:
            self.config_dict = self.config if isinstance(self.config, dict) else {}

        self.enable_spontaneous_reaction = self.config_dict.get(
            "enable_spontaneous_reaction", False
        )
        self.last_reaction_time = 0
        self.reaction_cooldown = 300  # 5 minutes default

        # 检查环境是否为演示模式
        self.is_demo = os.environ.get("AVELINE_DEMO_MODE") or os.environ.get(
            "DEMO_MODE"
        )
        if self.is_demo:
            self.reaction_cooldown = 10  # 10s for demo

        self.aveline = AvelineCharacter()
        # 确保反射已加载
        if not self.aveline.reflexes:
            self.aveline.load_reflexes()

    async def check_spontaneous_reaction(
        self, status: Dict[str, Any], last_interaction_time: float
    ) -> Optional[str]:
        """检查条件，如果触发则返回反应字符串"""
        if not self.enable_spontaneous_reaction:
            return None

        now = time.time()
        if now - self.last_reaction_time < self.reaction_cooldown:
            return None

        # CPU使用率高
        if status.get("cpu_temp", 0) > 80:
            reflexes = self.aveline.get_reflexes("high_cpu")
            if reflexes:
                return random.choice(reflexes)

        # 低电量
        battery = status.get("battery", 100)
        if battery < 20 and battery > 0:
            reflexes = self.aveline.get_reflexes("low_battery")
            if reflexes:
                return random.choice(reflexes)

        # 长时间空闲
        idle_threshold = self.config_dict.get("idle_threshold", 1800)

        if self.is_demo:
            idle_threshold = 10  # 演示模式缩减

        if now - last_interaction_time > idle_threshold:
            reflexes = self.aveline.get_reflexes("idle_long")

            # 如果存在反射，演示模式下强制触发
            if self.is_demo and reflexes:
                return await self._generate_reaction_with_llm(
                    "User has been idle for a while", reflexes
                )

            if random.random() < 0.3 and reflexes:
                return await self._generate_reaction_with_llm(
                    "User has been idle for a long time", reflexes
                )

        # 深夜（凌晨2-4点）
        hour = get_current_time().hour
        if 2 <= hour < 4:
            reflexes = self.aveline.get_reflexes("late_night")
            if random.random() < 0.1 and reflexes:
                return await self._generate_reaction_with_llm(
                    "It is very late at night", reflexes
                )

        return None

    async def _generate_reaction_with_llm(
        self, context_type: str, fallback_reflexes: list
    ) -> str:
        """
        Use LLM to generate a dynamic reaction, falling back to reflexes if needed.
        """
        try:
            llm = get_llm_module()
            # 检查LLM是否可用/已加载
            # 注意：根据get_status的实现，这可能有所不同。
            # 假设与原始代码的API兼容。
            status = llm.get_status().get("llm_status", {})
            if status.get("instances_count", 0) == 0:
                return random.choice(fallback_reflexes) if fallback_reflexes else None

            from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
                REACTION_SYSTEM_PROMPT,
                REACTION_USER_PROMPT,
            )
            sys_prompt = REACTION_SYSTEM_PROMPT.format(context_type=context_type)

            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": REACTION_USER_PROMPT},
            ]

            response = await llm.chat(messages, temperature=0.8, max_new_tokens=50)
            if isinstance(response, dict):
                if response.get("status") == "success":
                    response = str(response.get("response") or "")
                else:
                    response = None
            return (
                response
                if response
                else (random.choice(fallback_reflexes) if fallback_reflexes else None)
            )

        except Exception as e:
            logger.warning(f"LLM generation failed for reaction: {e}")
            return random.choice(fallback_reflexes) if fallback_reflexes else None

    def record_reaction(self):
        """当反应成功触发/广播时调用此方法"""
        self.last_reaction_time = time.time()
