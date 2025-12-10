import random
from typing import Dict, Any, Optional, List
import logging

from .models import EmotionType, EmotionResponse, EmotionState
from .constants import EMOTION_COMFORT_TEMPLATES

logger = logging.getLogger(__name__)

class EmotionResponder:
    """
    负责生成基于情绪的响应策略（话术、硬件控制指令等）
    不直接处理记忆检索，只提供策略。
    """
    
    def generate_response_strategy(self, state: EmotionState, context: str = "") -> EmotionResponse:
        """
        根据情绪状态生成响应策略
        """
        emo = state.primary_emotion
        
        # 1. 决定是否需要安慰
        action_type = "none"
        response_text = ""
        
        if emo in [EmotionType.SAD, EmotionType.ANXIOUS, EmotionType.TIRED, EmotionType.WRONGED, EmotionType.LOST]:
            action_type = "comfort"
            # 随机选择模板
            templates = EMOTION_COMFORT_TEMPLATES.get(emo.value, [])
            if templates:
                response_text = random.choice(templates)
        
        elif emo == EmotionType.ANGRY:
            action_type = "empathy"
            templates = EMOTION_COMFORT_TEMPLATES.get("angry", [])
            if templates:
                response_text = random.choice(templates)

        elif emo == EmotionType.HAPPY or emo == EmotionType.EXCITED:
            action_type = "celebrate"
            templates = EMOTION_COMFORT_TEMPLATES.get("happy", [])
            if templates:
                response_text = random.choice(templates)

        # 2. 生成硬件控制元数据 (呼吸灯颜色)
        # 颜色格式: [R, G, B] 0-255
        color_map = {
            EmotionType.HAPPY: [255, 223, 0],   # Gold
            EmotionType.SAD: [0, 0, 255],       # Blue
            EmotionType.ANGRY: [255, 0, 0],     # Red
            EmotionType.ANXIOUS: [128, 0, 128], # Purple
            EmotionType.TIRED: [128, 128, 128], # Grey
            EmotionType.NEUTRAL: [255, 255, 255], # White
            EmotionType.SHY: [255, 192, 203],   # Pink
            EmotionType.EXCITED: [255, 165, 0], # Orange
            EmotionType.JEALOUS: [0, 255, 0],   # Green (Envy)
            EmotionType.COQUETRY: [255, 105, 180], # Hot Pink
            EmotionType.WRONGED: [75, 0, 130],  # Indigo
            EmotionType.LOST: [70, 130, 180],   # Steel Blue
        }
        
        target_color = color_map.get(emo, [255, 255, 255])
        
        # 呼吸频率 (breathing_rate): milliseconds per cycle
        rate_map = {
            EmotionType.ANGRY: 1000,   # Fast
            EmotionType.EXCITED: 1500,
            EmotionType.ANXIOUS: 2000,
            EmotionType.HAPPY: 3000,
            EmotionType.NEUTRAL: 4000,
            EmotionType.SAD: 5000,     # Slow
            EmotionType.TIRED: 6000,
        }
        breathing_rate = rate_map.get(emo, 4000)

        return EmotionResponse(
            text=response_text,
            emotion=emo,
            action_type=action_type,
            metadata={
                "light_color": target_color,
                "breathing_rate": breathing_rate,
                "intensity": state.intensity
            }
        )
