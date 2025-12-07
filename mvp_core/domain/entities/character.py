from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
import time

class SensoryTrigger(BaseModel):
    keywords: List[str]
    voice_config: Optional[Dict[str, Any]] = None
    visual_emotion_weights: Optional[Dict[str, float]] = None
    ui_interaction: Optional[Dict[str, Any]] = None

class BehaviorChain(BaseModel):
    name: str
    trigger_keywords: List[str]
    external_outputs: List[str]
    emo_weights: Optional[Dict[str, float]] = None

class CharacterProfile(BaseModel):
    name: str
    alias: Optional[str] = None
    system_prompt: str
    sensory_triggers: List[SensoryTrigger] = []
    behavior_chains: List[BehaviorChain] = []
    
    # Runtime state
    current_emotion: str = "neutral"
    intimacy_level: int = 0
    
    def check_sensory_triggers(self, message: str) -> Optional[SensoryTrigger]:
        for trigger in self.sensory_triggers:
            for kw in trigger.keywords:
                if kw in message:
                    return trigger
        return None

    def check_behavior_chains(self, message: str) -> Optional[BehaviorChain]:
        for chain in self.behavior_chains:
            for kw in chain.trigger_keywords:
                if kw in message:
                    return chain
        return None
