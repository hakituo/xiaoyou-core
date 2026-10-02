from core.utils.logger import get_logger
import psutil
import random

from typing import Dict, Any

logger = get_logger(__name__)


class HardwareMonitor:
    """
    Responsible for monitoring system hardware statistics (CPU, RAM, Battery).
    """

    def __init__(self):
        self.status = {
            "cpu_percent": 0.0,
            "memory_percent": 0.0,
            "cpu_temp": 45.0,  # Celsius
            "ram_usage": 32.0,  # Percentage
            "battery": 98.0,  # Percentage
            "network_latency": 20,  # ms
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get current hardware statistics."""
        self._update_stats()
        return self.status.copy()

    def _update_stats(self):
        try:
            # CPU Usage as base load metric
            cpu_percent = psutil.cpu_percent(interval=None)
            self.status["cpu_percent"] = cpu_percent

            # Simulated temperature (Base 35 + usage * 0.5 + noise)
            target_temp = 35.0 + (cpu_percent * 0.5) + (random.random() * 2 - 1)
            # Smooth transition
            self.status["cpu_temp"] += (target_temp - self.status["cpu_temp"]) * 0.2

            # Real RAM usage
            mem = psutil.virtual_memory()
            self.status["ram_usage"] = mem.percent
            self.status["memory_percent"] = mem.percent

            # Battery status
            battery = psutil.sensors_battery()
            if battery:
                self.status["battery"] = battery.percent
            else:
                # Desktop simulation: Keep around 99-100%
                self.status["battery"] = 99.0 + random.random()

        except Exception as e:
            logger.debug(f"Hardware monitoring error (falling back to simulation): {e}")
            # Fallback simulation
            target_temp = 45.0 + (random.random() * 10 - 5)
            self.status["cpu_temp"] += (target_temp - self.status["cpu_temp"]) * 0.1
            target_ram = 30.0 + (random.random() * 20)
            self.status["ram_usage"] += (target_ram - self.status["ram_usage"]) * 0.1
