"""Active Care 硬件意图策略。

把主动关怀消息类型到震动/灯效的映射从执行器中拆出，
后续接入新硬件或改策略时不用修改消息执行主流程。
"""

from typing import Any, Dict

from core.models.hardware import (
    HardwareIntent,
    LightControl,
    LightMode,
    VibrationControl,
    VibrationType,
)


class ActiveCareHardwareIntentResolver:
    """根据主动关怀类型和设备上下文生成硬件意图。"""

    def determine(self, sys_prompt_type: str, device_context: Dict[str, Any]) -> HardwareIntent:
        """确定硬件意图。"""
        vibration = VibrationType.NONE
        light = None
        priority = 0
        battery_level = device_context.get("battery_level")
        is_charging = device_context.get("is_charging")
        is_low_battery = (
            battery_level is not None and battery_level < 0.20 and not is_charging
        )
        if is_low_battery:
            vibration = VibrationControl(
                pattern=VibrationType.DOUBLE_SHORT, intensity=0.6
            )
            light = LightControl(
                color="#FF3300", mode=LightMode.BREATHING, interval=2000
            )
            priority = 1
        if sys_prompt_type == "reminder":
            vibration = VibrationControl(
                pattern=VibrationType.HEAVY, duration=1000, intensity=1.0
            )
            light = LightControl(color="#FF0000", mode=LightMode.FLASHING, interval=500)
            priority = 2
        elif sys_prompt_type == "wake_up_greeting":
            vibration = VibrationControl(pattern=VibrationType.LONG, intensity=0.6)
            light = LightControl(
                color="#FF9900", mode=LightMode.BREATHING, interval=3000
            )
            priority = 2
        elif sys_prompt_type == "notification_assistant":
            vibration = VibrationControl(pattern=VibrationType.SHORT, intensity=0.7)
            light = LightControl(
                color="#00CCFF", mode=LightMode.BREATHING, interval=1000
            )
            priority = 1
        elif sys_prompt_type == "bio_complaint":
            vibration = VibrationControl(pattern=VibrationType.HEARTBEAT, intensity=0.8)
            light = LightControl(
                color="#FF00FF", mode=LightMode.BREATHING, interval=800
            )
            priority = 1
        elif sys_prompt_type in ("checking", "planned_topic"):
            vibration = VibrationControl(
                pattern=VibrationType.LIGHT, duration=100, intensity=0.3
            )
            light = LightControl(color="#00FFCC", mode=LightMode.STATIC, brightness=0.8)
            priority = 0
        elif sys_prompt_type == "startup":
            vibration = VibrationType.NONE
            light = LightControl(
                color="#FFFFFF", mode=LightMode.BREATHING, interval=2000
            )
            priority = 0
        return HardwareIntent(vibration=vibration, light=light, priority=priority)
