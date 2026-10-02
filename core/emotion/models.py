from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
import time


class EmotionType(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    ANXIOUS = "anxious"
    TIRED = "tired"
    SHY = "shy"
    EXCITED = "excited"
    JEALOUS = "jealous"
    WRONGED = "wronged"
    COQUETRY = "coquetry"
    LOST = "lost"
    LONELY = "lonely"
    FEAR = "fear"


@dataclass
class EmotionState:
    primary_emotion: EmotionType
    confidence: float
    sub_emotions: Dict[str, float] = field(default_factory=dict)
    emotion_mix: Dict[str, float] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    intensity: float = 0.5
    context: Optional[str] = None
    source: str = "unknown"


@dataclass
class EmotionInfluence:
    source: str
    weights: Dict[str, float]
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EmotionDebugSnapshot:
    primary_emotion: EmotionType
    confidence: float
    sub_emotions: Dict[str, float]
    influences: List[EmotionInfluence] = field(default_factory=list)


@dataclass
class EmotionDetectionResult:
    emotion: EmotionType
    confidence: float
    source: str
    rule_score: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DialogueAffectContext:
    life_level: int = 5
    mood_score: float = 80.0
    shyness_score: float = 0.0
    immune_damage: float = 0.0
    is_sick: bool = False
    intimacy_level: float = 0.5
    soft_reply_char_limit: Optional[int] = None
    max_tokens: Optional[int] = None


@dataclass
class ResponseStrategy:
    emotion: EmotionType
    intensity: float
    metadata: Dict[str, Any] = field(default_factory=dict)
