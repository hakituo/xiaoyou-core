"""硬件监控协调器。

封装 HardwareMonitor 的状态采集、节流缓存和阈值检测逻辑。
"""

import time
from typing import Any, Dict

from core.services.monitoring.hardware_monitor import HardwareMonitor


class HardwareCoordinator:
    """硬件监控协调器，负责硬件状态采集与过热/低电检测。"""

    def __init__(self, hardware_monitor: HardwareMonitor):
        self._hardware_monitor = hardware_monitor
        self._cached_stats: Dict[str, Any] = {}
        self._last_update: float = 0.0
        self._update_interval: float = 0.5

    @property
    def hardware_monitor(self) -> HardwareMonitor:
        return self._hardware_monitor

    def get_stats(self) -> Dict[str, Any]:
        """获取硬件状态（带 0.5s 节流缓存）。"""
        now = time.time()
        if (now - self._last_update) < self._update_interval and self._cached_stats:
            return self._cached_stats
        self._cached_stats = self._hardware_monitor.get_stats()
        self._last_update = now
        return self._cached_stats

    def check_overheat(self, threshold: float = 75.0) -> bool:
        """检查 CPU 是否过热。"""
        return float(self.get_stats().get("cpu_temp", 0)) > threshold

    def check_low_battery(self, threshold: float = 20.0) -> bool:
        """检查电池是否低电量。"""
        return float(self.get_stats().get("battery", 100)) < threshold
