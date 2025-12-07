import logging
import asyncio
import time
from typing import Dict, Any, Optional

from mvp_core.core import get_core_engine
from ..monitoring.hardware_monitor import HardwareMonitor
from ..reaction.reaction_manager import ReactionManager

logger = logging.getLogger(__name__)

class LifeSimulationService:
    """
    Life Simulation Service
    Orchestrates hardware monitoring and spontaneous reactions to simulate "life"
    """
    
    def __init__(self):
        self.core_engine = get_core_engine()
        self.event_bus = self.core_engine.event_bus
        self.config = self.core_engine.config_manager
        
        # Initialize components
        self.hardware_monitor = HardwareMonitor()
        self.reaction_manager = ReactionManager(self.config.get("life_simulation", {}))
        
        self._running = False
        self._monitor_task = None
        self.last_interaction_time = time.time()
        
        logger.info("LifeSimulationService initialized")
        
        # Subscribe to user interaction events to update last_interaction_time
        self._register_events()

    def _register_events(self):
        async def on_interaction(data: Dict[str, Any]):
            self.last_interaction_time = time.time()
            
        asyncio.create_task(self.event_bus.subscribe("user.message", on_interaction))
        asyncio.create_task(self.event_bus.subscribe("user.interaction", on_interaction))

    async def start(self):
        """Start the life simulation service"""
        if self._running:
            return
            
        self._running = True
        self._monitor_task = asyncio.create_task(self._simulation_loop())
        logger.info("LifeSimulationService started")

    async def stop(self):
        """Stop the life simulation service"""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("LifeSimulationService stopped")

    def get_state(self) -> Dict[str, Any]:
        """Get current life simulation state including hardware stats"""
        return {
            "hardware": self.hardware_monitor.get_stats(),
            "is_running": self._running,
            "last_interaction": self.last_interaction_time
        }

    async def _simulation_loop(self):
        """Main simulation loop"""
        logger.info("Starting simulation loop")
        while self._running:
            try:
                # 1. Get Hardware Stats
                stats = self.hardware_monitor.get_stats()
                
                # 2. Publish Heartbeat/Status Event
                await self.event_bus.publish("system.status", stats)
                
                # 3. Check for Spontaneous Reactions
                reaction = await self.reaction_manager.check_spontaneous_reaction(
                    stats, 
                    self.last_interaction_time
                )
                
                if reaction:
                    logger.info(f"Spontaneous reaction triggered: {reaction}")
                
                # Sleep for interval (e.g., 5 seconds)
                await asyncio.sleep(5)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in simulation loop: {e}")
                await asyncio.sleep(5)

# Singleton instance
_life_sim_service = None

def get_life_simulation_service():
    global _life_sim_service
    if _life_sim_service is None:
        _life_sim_service = LifeSimulationService()
    return _life_sim_service
