import time
import random
import logging
import os
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any, Union

from core.character.aveline import AvelineCharacter
from core.llm import get_llm_module
try:
    from config.integrated_config import LifeSimulationSettings
except ImportError:
    LifeSimulationSettings = None

logger = logging.getLogger(__name__)

class ReactionManager:
    """
    Manages spontaneous reactions based on system state and environment.
    """
    def __init__(self, config: Union[Dict[str, Any], Any] = None):
        self.config = config or {}
        if hasattr(self.config, "model_dump"):
             self.config_dict = self.config.model_dump()
        elif hasattr(self.config, "dict"):
             self.config_dict = self.config.dict()
        else:
             self.config_dict = self.config if isinstance(self.config, dict) else {}

        self.enable_spontaneous_reaction = self.config_dict.get("enable_spontaneous_reaction", False)
        self.last_reaction_time = 0
        self.reaction_cooldown = 300  # 5 minutes default
        
        # Check environment for demo mode
        self.is_demo = os.environ.get("AVELINE_DEMO_MODE") or os.environ.get("DEMO_MODE")
        if self.is_demo:
            self.reaction_cooldown = 10 # 10s for demo
            
        self.aveline = AvelineCharacter()
        # Ensure reflexes are loaded
        if not self.aveline.reflexes:
             self.aveline.load_reflexes()

    async def check_spontaneous_reaction(self, status: Dict[str, Any], last_interaction_time: float) -> Optional[str]:
        """Check conditions and return a reaction string if triggered"""
        if not self.enable_spontaneous_reaction:
            return None

        now = time.time()
        if now - self.last_reaction_time < self.reaction_cooldown:
            return None
            
        # High CPU
        if status.get("cpu_temp", 0) > 80:
            reflexes = self.aveline.get_reflexes("high_cpu")
            if reflexes:
                return random.choice(reflexes)
                
        # Low Battery
        battery = status.get("battery", 100)
        if battery < 20 and battery > 0:
             reflexes = self.aveline.get_reflexes("low_battery")
             if reflexes:
                return random.choice(reflexes)
        
        # Idle Long
        idle_threshold = self.config_dict.get("idle_threshold", 1800)
        
        if self.is_demo:
            idle_threshold = 10 # Reduced for demo
            
        if now - last_interaction_time > idle_threshold:
            reflexes = self.aveline.get_reflexes("idle_long")
            
            # Force trigger for demo mode if reflexes exist
            if self.is_demo and reflexes:
                return await self._generate_reaction_with_llm("User has been idle for a while", reflexes)

            if random.random() < 0.3 and reflexes:
                return await self._generate_reaction_with_llm("User has been idle for a long time", reflexes)
                
        # Late Night (2 AM - 4 AM)
        hour = datetime.now().hour
        if 2 <= hour < 4:
            reflexes = self.aveline.get_reflexes("late_night")
            if random.random() < 0.1 and reflexes:
                 return await self._generate_reaction_with_llm("It is very late at night", reflexes)
                 
        return None

    async def _generate_reaction_with_llm(self, context_type: str, fallback_reflexes: list) -> str:
        """
        Use LLM to generate a dynamic reaction, falling back to reflexes if needed.
        """
        try:
            llm = get_llm_module()
            # Check if LLM is available/loaded
            # Note: Depending on implementation of get_status, this might vary. 
            # Assuming API compatibility with original code.
            status = llm.get_status().get("llm_status", {})
            if status.get("instances_count", 0) == 0:
                return random.choice(fallback_reflexes) if fallback_reflexes else None

            sys_prompt = (
                "You are Aveline, a desktop AI assistant. "
                "You are currently 'idle' or 'bored' or reacting to a system state. "
                "Generate a VERY SHORT, casual, 1-sentence spontaneous thought/muttering. "
                "It should feel natural, like a friend sitting next to you. "
                "Strictly follow [EMO] protocol if applicable, but keep it short. "
                f"Context: {context_type}"
            )
            
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": "Say something spontaneous now."}
            ]
            
            response = await llm.chat(messages, temperature=0.8, max_new_tokens=50)
            return response if response else (random.choice(fallback_reflexes) if fallback_reflexes else None)
            
        except Exception as e:
            logger.warning(f"LLM generation failed for reaction: {e}")
            return random.choice(fallback_reflexes) if fallback_reflexes else None
            
    def record_reaction(self):
        """Call this when a reaction is successfully triggered/broadcasted"""
        self.last_reaction_time = time.time()
