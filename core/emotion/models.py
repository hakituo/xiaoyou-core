from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import time

class EmotionType(str, Enum):
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    ANXIOUS = "anxious"
    TIRED = "tired"
    NEUTRAL = "neutral"
    SHY = "shy"
    EXCITED = "excited"
    JEALOUS = "jealous"
    WRONGED = "wronged"
    COQUETRY = "coquetry"
    LOST = "lost"

@dataclass
class EmotionState:
    primary_emotion: EmotionType
    confidence: float
    sub_emotions: Dict[str, float] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    intensity: float = 0.5  # 0.0 to 1.0
    context: Optional[str] = None

@dataclass
class EmotionResponse:
    text: str
    emotion: EmotionType
    action_type: str = "none"  # comfort, encourage, empathy, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)
