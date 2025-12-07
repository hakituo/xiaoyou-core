import psutil
import random
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class HardwareMonitor:
    """
    Responsible for monitoring system hardware statistics (CPU, RAM, Battery).
    """
    def __init__(self):
        self.status = {
            "cpu_temp": 45.0,  # Celsius
            "ram_usage": 32.0,  # Percentage
            "battery": 98.0,   # Percentage
            "network_latency": 20 # ms
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get current hardware statistics."""
        self._update_stats()
        return self.status.copy()

    def _update_stats(self):
        try:
            # CPU Usage as base load metric
            cpu_percent = psutil.cpu_percent(interval=None)
            
            # Simulated temperature (Base 35 + usage * 0.5 + noise)
            target_temp = 35.0 + (cpu_percent * 0.5) + (random.random() * 2 - 1)
            # Smooth transition
            self.status["cpu_temp"] += (target_temp - self.status["cpu_temp"]) * 0.2
            
            # Real RAM usage
            mem = psutil.virtual_memory()
            self.status["ram_usage"] = mem.percent
            
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
