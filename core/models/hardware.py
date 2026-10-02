from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any, Union

class VibrationType(str, Enum):
    NONE = "none"
    HEAVY = "heavy"
    MEDIUM = "medium"
    LIGHT = "light"
    LONG = "long"
    SHORT = "short"
    DOUBLE_SHORT = "double_short"
    SOS = "sos"
    HEARTBEAT = "heartbeat"

@dataclass
class VibrationControl:
    pattern: VibrationType = VibrationType.NONE
    duration: Optional[int] = None  # ms, overrides pattern default if set
    intensity: float = 1.0          # 0.0 - 1.0 (Approximate mapping to Light/Medium/Heavy)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern": self.pattern.value,
            "duration": self.duration,
            "intensity": self.intensity
        }

class LightMode(str, Enum):
    STATIC = "static"
    BREATHING = "breathing"
    FLASHING = "flashing"
    OFF = "off"

@dataclass
class LightControl:
    color: str = "#FFFFFF"  # Hex code
    mode: LightMode = LightMode.STATIC
    interval: int = 1000  # ms
    brightness: float = 1.0  # 0.0 - 1.0

@dataclass
class HardwareIntent:
    """
    硬件控制意图
    由 ActiveCare 或 Emotion 模块生成
    """
    vibration: Union[VibrationType, VibrationControl] = VibrationType.NONE
    light: Optional[LightControl] = None
    priority: int = 0  # 0=Low, 1=Normal, 2=High (ActiveCare defaults to 1 or 2)

    def to_dict(self) -> Dict[str, Any]:
        vib_data = None
        if isinstance(self.vibration, VibrationType):
            vib_data = self.vibration.value
        elif isinstance(self.vibration, VibrationControl):
            vib_data = self.vibration.to_dict()
        elif hasattr(self.vibration, "value"): # Handle Enum if type check fails
            vib_data = self.vibration.value
        elif isinstance(self.vibration, str):
            vib_data = self.vibration
            
        return {
            "vibration": vib_data,
            "light": {
                "color": self.light.color,
                "mode": self.light.mode.value,
                "interval": self.light.interval,
                "brightness": self.light.brightness
            } if self.light else None
        }
