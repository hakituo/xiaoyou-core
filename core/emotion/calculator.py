import math
import time
from typing import Dict, Any

from .models import EmotionType, EmotionState

_LN2 = math.log(2)


class EmotionCalculator:
    """
    负责情绪状态的数值计算、叠加与衰减
    支持基于时间的衰减：间隔越久衰减越多
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.decay_rate = self.config.get("decay_rate", 0.2)
        self.accumulation_rate = self.config.get("accumulation_rate", 0.3)
        self.max_intensity = 1.0
        self.min_threshold = 0.1
        self.time_decay_half_life = self.config.get("time_decay_half_life", 300.0)

    def update_state(
        self, current_state: EmotionState, new_input_state: EmotionState
    ) -> EmotionState:
        if not current_state:
            return new_input_state

        time_elapsed = time.time() - current_state.timestamp
        time_decay_factor = self._compute_time_decay(time_elapsed)
        effective_decay = 1.0 - self.decay_rate * time_decay_factor

        decayed_sub_emotions = {
            k: v * effective_decay
            for k, v in current_state.sub_emotions.items()
            if v * effective_decay > self.min_threshold
        }

        for emo_key, score in new_input_state.sub_emotions.items():
            if emo_key in decayed_sub_emotions:
                current_val = decayed_sub_emotions[emo_key]
                increment = (1.0 - current_val) * score * self.accumulation_rate
                decayed_sub_emotions[emo_key] = min(
                    current_val + increment, self.max_intensity
                )
            else:
                decayed_sub_emotions[emo_key] = score

        if not decayed_sub_emotions:
            return EmotionState(EmotionType.NEUTRAL, 0.0)

        primary_emo_key = max(decayed_sub_emotions.items(), key=lambda x: x[1])[0]
        primary_score = decayed_sub_emotions[primary_emo_key]

        try:
            primary_emo = EmotionType(primary_emo_key)
        except Exception:
            primary_emo = EmotionType.NEUTRAL

        intensity = min(primary_score, 1.0)

        return EmotionState(
            primary_emotion=primary_emo,
            confidence=primary_score,
            sub_emotions=decayed_sub_emotions,
            emotion_mix=dict(decayed_sub_emotions),
            timestamp=time.time(),
            intensity=intensity,
            context=new_input_state.context,
            source=new_input_state.source,
        )

    def _compute_time_decay(self, elapsed_seconds: float) -> float:
        """
        基于时间的衰减因子 (0.0 ~ 1.0)
        使用指数衰减模型: factor = 1 - exp(-ln(2) * t / half_life)
        - 0秒: factor=0 (无衰减)
        - half_life秒: factor≈0.5 (衰减一半)
        - 2*half_life秒: factor≈0.75
        """
        if elapsed_seconds <= 0:
            return 0.0
        decay = _LN2 * elapsed_seconds / self.time_decay_half_life
        return 1.0 - math.exp(-decay)
