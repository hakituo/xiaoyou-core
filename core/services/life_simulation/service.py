import uuid
import time
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from core.server.connection_manager import get_connection_manager
from config.integrated_config import get_settings
from core.services.monitoring.hardware_monitor import HardwareMonitor
from core.services.reaction.reaction_manager import ReactionManager

logger = logging.getLogger(__name__)

class RitualManager:
    """Manages daily rituals like morning check-in and bedtime summary"""
    def __init__(self):
        self.triggered_today = {
            "morning_checkin": False,
            "bedtime_summary": False
        }
        self.last_reset_day = datetime.now().day

    def check_rituals(self, active_minutes: int) -> Optional[str]:
        now = datetime.now()
        
        # Reset daily triggers
        if now.day != self.last_reset_day:
            self.triggered_today = {k: False for k in self.triggered_today}
            self.last_reset_day = now.day

        # Morning Check-in (6:00 - 9:00)
        if 6 <= now.hour < 9 and not self.triggered_today["morning_checkin"]:
            self.triggered_today["morning_checkin"] = True
            return "晨间打卡：‘今日适合穿你喜欢的浅蓝衬衫’"

        # Bedtime Summary (22:00 - 23:00)
        if 22 <= now.hour < 23 and not self.triggered_today["bedtime_summary"]:
            self.triggered_today["bedtime_summary"] = True
            return f"睡前小结：‘今日互动{active_minutes}分钟，算力99%存你说的话’"

        return None

class LifeSimulationService:
    """
    Service responsible for simulating character life, monitoring hardware,
    and triggering spontaneous reactions.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.life_config = self.settings.life_simulation
        
        self.hardware_monitor = HardwareMonitor()
        self.reaction_manager = ReactionManager(self.life_config)
        
        # Initialize status with hardware stats
        self.status = self.hardware_monitor.get_stats()
        self.status.update({
            "mood": "calm",
            "activity": "idle"
        })
        
        self.last_update = time.time()
        self._monitor_task = None
        self.last_interaction_time = time.time()
        
        # Ritual tracking
        self.ritual_manager = RitualManager()
        self.active_minutes_today = 0
        self.last_minute_check = time.time()

    def update_interaction(self):
        """Called when user interacts with the agent"""
        self.last_interaction_time = time.time()

    async def start(self):
        """Start the life simulation service"""
        await self.start_monitor()

    async def stop(self):
        """Stop the life simulation service"""
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        logger.info("Life Simulation service stopped")

    async def start_monitor(self):
        """Start monitoring task"""
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("Life Simulation monitor task started")

    async def _monitor_loop(self):
        """Monitor loop to broadcast state and check for reactions"""
        ws_manager = get_connection_manager()
        logger.info(f"Life Simulation monitor loop started. Connection Manager: {id(ws_manager)}")
        
        while True:
            try:
                state = self.get_state()
                
                # Update active minutes
                now = time.time()
                if now - self.last_minute_check >= 60:
                    # If status is not sleeping/idle, count as active
                    if state["activity"] not in ["sleeping", "idle"]:
                        self.active_minutes_today += 1
                    self.last_minute_check = now
                    
                    # Reset active minutes at midnight
                    if datetime.now().hour == 0 and datetime.now().minute == 0:
                        self.active_minutes_today = 0

                # Broadcast to all connected clients
                await ws_manager.broadcast({
                    "type": "life_status",
                    "data": state,
                    "timestamp": state["timestamp"]
                })
                
                # Check for rituals
                ritual = self.ritual_manager.check_rituals(self.active_minutes_today)
                if ritual:
                    logger.info(f"Triggering ritual: {ritual}")
                    await ws_manager.broadcast({
                        "type": "ritual_event",
                        "id": str(uuid.uuid4()),
                        "content": ritual,
                        "timestamp": datetime.now().isoformat()
                    })

                # Check for spontaneous reactions
                reaction = await self.reaction_manager.check_spontaneous_reaction(
                    state, self.last_interaction_time
                )
                
                if reaction:
                    logger.info(f"Triggering spontaneous reaction: {reaction}")
                    await ws_manager.broadcast({
                        "type": "spontaneous_reaction",
                        "id": str(uuid.uuid4()),
                        "content": reaction,
                        "timestamp": datetime.now().isoformat()
                    })
                    self.reaction_manager.record_reaction()
                    
            except Exception as e:
                logger.error(f"Error in life simulation monitor: {e}")
            
            await asyncio.sleep(1)

    def update(self):
        """Update internal state"""
        current_time = time.time()
        # Optimization: Don't update too frequently if called in tight loop
        if current_time - self.last_update < 0.5:
            return

        self.last_update = current_time
        
        # Update hardware stats
        hw_stats = self.hardware_monitor.get_stats()
        self.status.update(hw_stats)
        
        # Update activity and mood logic
        self._update_activity_and_mood()

    def _update_activity_and_mood(self):
        """Derive activity and mood from time and hardware stats"""
        hour = datetime.now().hour
        
        # Activity Logic
        if 0 <= hour < 6:
            self.status["activity"] = "sleeping"
        elif 6 <= hour < 9:
            self.status["activity"] = "waking_up"
        elif 9 <= hour < 18:
            if self.status.get("cpu_temp", 0) > 60:
                 self.status["activity"] = "working_hard"
            else:
                 self.status["activity"] = "working"
        elif 18 <= hour < 23:
            self.status["activity"] = "relaxing"
        else:
            self.status["activity"] = "preparing_sleep"

        # Mood Logic
        cpu_temp = self.status.get("cpu_temp", 0)
        battery = self.status.get("battery", 100)
        activity = self.status.get("activity", "idle")

        if cpu_temp > 75:
            self.status["mood"] = "overheated"
        elif battery < 20:
            self.status["mood"] = "exhausted"
        elif activity == "working_hard":
            self.status["mood"] = "focused"
        elif activity == "relaxing":
            self.status["mood"] = "calm"
        else:
            self.status["mood"] = "happy"

    def get_state(self) -> Dict[str, Any]:
        """Get current state snapshot"""
        self.update()
        return {
            "timestamp": datetime.now().isoformat(),
            "cpu_temp": round(self.status.get("cpu_temp", 0), 1),
            "ram_usage": round(self.status.get("ram_usage", 0), 1),
            "battery": round(self.status.get("battery", 0), 1),
            "network_latency": self.status.get("network_latency", 0),
            "mood": self.status.get("mood", "unknown"),
            "activity": self.status.get("activity", "unknown"),
            "vision_summary": self._get_vision_summary(),
            "is_running": self._monitor_task is not None and not self._monitor_task.done()
        }
        
    def _get_vision_summary(self) -> str:
        """Mock vision summary"""
        hour = datetime.now().hour
        if 6 <= hour < 18:
            return "光线充足，传感器正常"
        else:
            return "环境昏暗，启用夜视模式"

# Global instance management
_service_instance = None

def get_life_simulation_service() -> LifeSimulationService:
    global _service_instance
    if _service_instance is None:
        _service_instance = LifeSimulationService()
    return _service_instance
