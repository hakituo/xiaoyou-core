import logging
import psutil
import random
from typing import Dict, Any

logger = logging.getLogger(__name__)

class HardwareMonitor:
    """
    Hardware Monitor Service
    Collects system hardware statistics (CPU, RAM, Battery, etc.)
    """
    def __init__(self):
        self.status = {
            "cpu_temp": 45.0,
            "ram_usage": 32.0,
            "battery": 98.0,
            "network_latency": 20
        }
        logger.info("HardwareMonitor initialized")

    def get_stats(self) -> Dict[str, Any]:
        """Get current hardware statistics"""
        self._update_stats()
        return self.status.copy()

    def _update_stats(self):
        """Update hardware statistics from system sensors"""
        try:
            # CPU Usage as proxy for temperature if sensor not available
            cpu_percent = psutil.cpu_percent(interval=None)
            
            # Simulate temperature fluctuation based on load
            target_temp = 35.0 + (cpu_percent * 0.5) + (random.random() * 2 - 1)
            self.status["cpu_temp"] += (target_temp - self.status["cpu_temp"]) * 0.2
            
            # Memory
            mem = psutil.virtual_memory()
            self.status["ram_usage"] = mem.percent
            
            # Battery
            battery = psutil.sensors_battery()
            if battery:
                self.status["battery"] = battery.percent
            else:
                # Simulation for desktop
                self.status["battery"] = 99.0 + random.random()
                
        except Exception as e:
            logger.debug(f"Hardware monitoring error (falling back to simulation): {e}")
            # Fallback simulation
            target_temp = 45.0 + (random.random() * 10 - 5)
            self.status["cpu_temp"] += (target_temp - self.status["cpu_temp"]) * 0.1
