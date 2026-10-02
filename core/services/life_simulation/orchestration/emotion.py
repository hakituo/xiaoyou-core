"""生命模拟的情绪影响职责（从 orchestrator.py 拆出）。"""

from __future__ import annotations

from typing import Any

from config.debug_config import is_debug_enabled
from core.utils.logger import get_logger

logger = get_logger("LIFE_SIMULATION")


class LifeEmotionMixin:
    """把生命状态折算成情绪影响并施加到情绪系统。"""

    async def _apply_emotion_influence(self, state: dict[str, Any]) -> None:
        """应用情绪影响。"""
        try:
            from core.emotion import get_emotion_manager

            mgr = get_emotion_manager()
            life_stats = dict((state or {}).get("life", {}) or {})
            weights = mgr.compute_life_influence_weights(life_stats)
            if weights:
                mgr.apply_global_influence(
                    weights,
                    source="life_simulation_tick",
                    metadata={
                        "mood_score": life_stats.get("mood_score"),
                        "shyness_score": life_stats.get("shyness_score"),
                        "immune_damage": life_stats.get("immune_damage"),
                        "is_sick": life_stats.get("is_sick"),
                    },
                )
        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001 - 情绪系统异常不能影响主循环
            if is_debug_enabled("life_simulation"):
                logger.info(f"应用情绪影响失败: {e}")
