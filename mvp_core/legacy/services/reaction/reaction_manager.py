import logging
import time
import random
import asyncio
from typing import Dict, Any, Optional, List
from mvp_core.core import get_core_engine

logger = logging.getLogger(__name__)

class ReactionManager:
    """
    Reaction Manager Service
    Manages spontaneous reactions and reflexes based on system events and states
    """
    def __init__(self, config: Dict[str, Any] = None):
        self.core_engine = get_core_engine()
        self.event_bus = self.core_engine.event_bus
        self.config = config or {}
        
        self.enable_spontaneous_reaction = self.config.get("enable_spontaneous_reaction", False)
        self.last_reaction_time = 0
        self.reaction_cooldown = 300  # 5 minutes default cooldown
        
        # Load reflexes (simplified for MVP)
        self.reflexes = {
            "high_cpu": ["I'm feeling a bit hot...", "Processing a lot right now!"],
            "low_battery": ["I need some energy...", "Running low on power."],
            "idle": ["So quiet...", "Anyone there?"]
        }
        
        logger.info("ReactionManager initialized")

    async def check_spontaneous_reaction(self, status: Dict[str, Any], last_interaction_time: float) -> Optional[str]:
        """
        Check if a spontaneous reaction should be triggered based on status
        """
        if not self.enable_spontaneous_reaction:
            return None
            
        now = time.time()
        if now - self.last_reaction_time < self.reaction_cooldown:
            return None
            
        # Check conditions
        reaction = None
        
        # High CPU Temperature Reflex
        if status.get("cpu_temp", 0) > 80:
            reaction = random.choice(self.reflexes.get("high_cpu", ["It's hot!"]))
            
        # Low Battery Reflex
        elif status.get("battery", 100) < 20:
            reaction = random.choice(self.reflexes.get("low_battery", ["Low battery!"]))
            
        # Idle Reflex
        elif now - last_interaction_time > 3600:  # 1 hour idle
            reaction = random.choice(self.reflexes.get("idle", ["Thinking..."]))
            
        if reaction:
            self.last_reaction_time = now
            # Publish reaction event
            await self.event_bus.publish("aveline.reaction", {
                "type": "spontaneous",
                "content": reaction,
                "timestamp": now
            })
            
        return reaction
