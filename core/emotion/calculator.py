from typing import Dict, Any, Optional
import time
import math
from .models import EmotionType, EmotionState

class EmotionCalculator:
    """
    负责情绪状态的数值计算、叠加与衰减
    """
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        # 默认衰减系数 (每轮对话或随时间)
        self.decay_rate = self.config.get("decay_rate", 0.2) 
        # 相同情绪的叠加系数
        self.accumulation_rate = self.config.get("accumulation_rate", 0.3)
        # 最大强度
        self.max_intensity = 1.0
        # 最小保留阈值
        self.min_threshold = 0.1

    def update_state(self, current_state: EmotionState, new_input_state: EmotionState) -> EmotionState:
        """
        根据新的输入状态更新当前状态 (叠加逻辑)
        """
        if not current_state:
            return new_input_state

        # 1. 基础衰减：旧情绪随时间/轮次衰减
        # 这里简化为按次衰减，也可以引入 time.time() - current_state.timestamp 计算
        decayed_sub_emotions = {
            k: v * (1.0 - self.decay_rate) 
            for k, v in current_state.sub_emotions.items() 
            if v * (1.0 - self.decay_rate) > self.min_threshold
        }

        # 2. 叠加新情绪
        # new_input_state.sub_emotions 通常包含本次检测到的情绪及其置信度
        for emo_key, score in new_input_state.sub_emotions.items():
            if emo_key in decayed_sub_emotions:
                # 同种情绪叠加：非线性叠加，越接近1越难增加
                # 公式: new = old + (1 - old) * score * rate
                current_val = decayed_sub_emotions[emo_key]
                increment = (1.0 - current_val) * score * self.accumulation_rate
                decayed_sub_emotions[emo_key] = min(current_val + increment, self.max_intensity)
            else:
                # 新情绪直接加入
                decayed_sub_emotions[emo_key] = score

        # 3. 归一化 (可选，或者允许总和大于1表示情绪激动)
        # 为了方便比较，我们找出新的 primary emotion
        if not decayed_sub_emotions:
            return EmotionState(EmotionType.NEUTRAL, 0.0)

        primary_emo_key = max(decayed_sub_emotions.items(), key=lambda x: x[1])[0]
        primary_score = decayed_sub_emotions[primary_emo_key]
        
        try:
            primary_emo = EmotionType(primary_emo_key)
        except:
            primary_emo = EmotionType.NEUTRAL

        # 计算整体强度 (Intensity)
        # 可以是最大值，也可以是所有情绪的加权和
        intensity = min(primary_score, 1.0)

        return EmotionState(
            primary_emotion=primary_emo,
            confidence=primary_score,
            sub_emotions=decayed_sub_emotions,
            timestamp=time.time(),
            intensity=intensity,
            context=new_input_state.context
        )
