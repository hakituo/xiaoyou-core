"""
生物系统管理模块
负责生物系统的状态管理和推理前的生物系统应用
"""

from core.utils.logger import get_logger
import asyncio

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..cpp_scheduler_engine import CPPSchedulerEngine

logger = get_logger(__name__)


class BioSystemManager:
    """生物系统管理器"""

    def __init__(self, engine: "CPPSchedulerEngine"):
        self.engine = engine

    def get_biological_system(self):
        """获取生物系统"""
        return self.engine.bio_system

    async def apply_bio_before_infer(self, prompt_text: str):
        """推理前应用生物系统"""
        bio = self.engine.bio_system
        if not bio:
            return

        try:
            from config.integrated_config import get_settings

            s = get_settings().scheduler
            enable_delay = bool(getattr(s, "bio_enable_cognitive_delay", False))
            max_delay = float(getattr(s, "bio_max_cognitive_delay", 1.8) or 1.8)
            min_apply = float(getattr(s, "bio_min_delay_to_apply", 0.2) or 0.2)
            energy_base = float(getattr(s, "bio_energy_cost_base", 0.005) or 0.005)
            energy_k = float(getattr(s, "bio_energy_cost_complexity", 0.02) or 0.02)
            dopamine_reward = float(getattr(s, "bio_dopamine_reward", 0.01) or 0.01)
            cortisol_base = float(getattr(s, "bio_cortisol_cost_base", 0.002) or 0.002)
            cortisol_k = float(getattr(s, "bio_cortisol_cost_complexity", 0.006) or 0.006)
        except Exception:
            enable_delay = False
            max_delay = 1.8
            min_apply = 0.2
            energy_base = 0.005
            energy_k = 0.02
            dopamine_reward = 0.01
            cortisol_base = 0.002
            cortisol_k = 0.006

        try:
            text = str(prompt_text or "")
        except Exception:
            text = ""

        complexity = min(1.0, float(len(text)) / 200.0) if text else 0.0
        sleep_delay_penalty = 0.0
        try:
            from core.services.life_simulation import get_life_simulation_service

            life_sim = get_life_simulation_service()
            sleep_summary = life_sim.get_sleep_summary("aveline") if life_sim else {}
            sleep_debt = float(sleep_summary.get("sleep_debt_hours", 0.0) or 0.0)
            inertia_score = float(sleep_summary.get("sleep_inertia_score", 0.0) or 0.0)
            nightmare_level = str(sleep_summary.get("nightmare_level") or "none")
            sleep_delay_penalty += min(0.45, sleep_debt * 0.08)
            sleep_delay_penalty += min(0.35, inertia_score / 220.0)
            if nightmare_level == "mild":
                sleep_delay_penalty += 0.05
            elif nightmare_level == "medium":
                sleep_delay_penalty += 0.1
            elif nightmare_level == "severe":
                sleep_delay_penalty += 0.18
        except Exception:
            sleep_delay_penalty = 0.0

        if enable_delay:
            try:
                delay = float(bio.calculateCognitiveDelay(float(complexity)) or 0.0)
                delay += sleep_delay_penalty
                if max_delay > 0:
                    delay = min(delay, max_delay)
                if delay > min_apply:
                    await asyncio.sleep(delay)
            except Exception:
                pass

        try:
            bio.consumeEnergy(float(energy_base + complexity * energy_k))
        except Exception:
            pass

        try:
            if dopamine_reward != 0:
                bio.adjustNeurotransmitter("dopamine", float(dopamine_reward))
        except Exception:
            pass

        try:
            inc = float(cortisol_base + complexity * cortisol_k)
            if inc != 0:
                bio.adjustNeurotransmitter("cortisol", inc)
        except Exception:
            pass
