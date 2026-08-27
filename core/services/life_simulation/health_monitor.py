"""健康检查逻辑模块"""

from core.utils.logger import get_logger
import asyncio

import time
from typing import Any, Dict

logger = get_logger(__name__)


class HealthMonitor:
    """管理健康检查和免疫系统"""

    def __init__(
        self,
        life_stats: Dict[str, Any],
        life_config: Any,
        status: Dict[str, Any],
    ):
        self.life_stats = life_stats
        self.life_config = life_config
        self.status = status
        self._last_health_poll_ts = 0.0
        self._unhealthy_services: Dict[str, str] = {}
        self._poll_interval = float(
            getattr(life_config, "health_poll_interval_seconds", 10.0) or 10.0
        )
        self._immune_damage_increase = float(
            getattr(life_config, "immune_damage_increase_per_unhealthy", 12.0) or 12.0
        )
        self._immune_damage_decay = float(
            getattr(life_config, "immune_damage_decay_per_tick", 3.0) or 3.0
        )
        self._sickness_threshold = float(
            getattr(life_config, "sickness_threshold", 60.0) or 60.0
        )

    async def maybe_poll_health(self):
        """定期检查服务健康状态"""
        now = time.time()
        if (now - self._last_health_poll_ts) < max(1.0, self._poll_interval):
            return

        self._last_health_poll_ts = now

        services_health = await self._check_services_health()
        self._update_unhealthy_services(services_health)
        self._update_immune_damage()

    async def _check_services_health(self) -> Dict[str, Any]:
        """检查所有服务的健康状态"""
        try:
            from core.async_monitor import get_health_checker

            health_checker = get_health_checker()
            return await asyncio.wait_for(
                health_checker.check_all_services(), timeout=2.0
            )
        except asyncio.TimeoutError:
            logger.warning("健康检查超时")
            return {}
        except ImportError:
            logger.debug("health_checker 模块不可用")
            return {}
        except Exception as e:
            logger.warning(f"健康检查失败: {e}")
            return {}

    def _update_unhealthy_services(self, services_health: Dict[str, Any]):
        """更新不健康服务列表"""
        unhealthy: Dict[str, str] = {}
        for service_name, payload in (services_health or {}).items():
            status = str((payload or {}).get("status", "unknown"))
            if status in {"unhealthy", "error"}:
                unhealthy[str(service_name)] = status
        self._unhealthy_services = unhealthy

    def _update_immune_damage(self):
        """更新免疫损伤值"""
        immune_damage = float(self.life_stats.get("immune_damage", 0.0) or 0.0)
        if self._unhealthy_services:
            immune_damage = min(
                100.0,
                immune_damage + (len(self._unhealthy_services) * self._immune_damage_increase),
            )
        else:
            recovery_multiplier = self._calculate_recovery_multiplier()
            immune_damage = max(0.0, immune_damage - (self._immune_damage_decay * recovery_multiplier))

        self.life_stats["immune_damage"] = immune_damage
        self.life_stats["is_sick"] = immune_damage >= self._sickness_threshold

    def _calculate_recovery_multiplier(self) -> float:
        """计算恢复倍率"""
        multiplier = 1.0
        if self.status.get("activity") == "sleeping":
            multiplier *= 2.0

        energy = float(self.life_stats.get("energy", 0.0) or 0.0)
        if energy > 80:
            multiplier *= 1.5
        elif energy < 20:
            multiplier *= 0.5

        return multiplier

    def get_unhealthy_services(self) -> Dict[str, str]:
        """获取不健康服务列表"""
        return dict(self._unhealthy_services)

    def get_immune_status(self) -> Dict[str, Any]:
        """获取免疫系统状态"""
        immune_damage = float(self.life_stats.get("immune_damage", 0.0) or 0.0)
        return {
            "unhealthy_services": self._unhealthy_services,
            "unhealthy_count": len(self._unhealthy_services),
            "immune_damage": immune_damage,
            "immune_health": round(max(0.0, 100.0 - immune_damage), 1),
            "is_sick": bool(self.life_stats.get("is_sick")),
        }
