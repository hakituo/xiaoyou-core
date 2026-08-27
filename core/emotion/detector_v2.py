
from core.utils.logger import get_logger
import time
from typing import Optional, Tuple

from .models import EmotionType, EmotionState, EmotionDetectionResult
from .constants import (
    EMO_TAG_PATTERN,
    EMO_SIMPLE_PATTERN,
    SYSTEM_TAGS,
    EMOTION_CN_MAP,
)

_CN_TO_EN_MAP = {v: k for k, v in EMOTION_CN_MAP.items()}

logger = get_logger(__name__)


class EmotionDetectorV2:
    """
    情绪检测器 V2 - 仅 LLM 标签提取
    LLM 自己判断情绪并输出 [EMO: sad] 标签，本检测器只负责提取
    """

    def __init__(self, config=None):
        self.config = config or {}

    def detect(self, text: str) -> EmotionState:
        emotion, confidence = self._extract_llm_tag(text)

        if emotion is None:
            emotion = EmotionType.NEUTRAL
            confidence = 0.0

        return EmotionState(
            primary_emotion=emotion,
            confidence=confidence,
            source="llm_tag" if confidence > 0 else "no_tag",
            timestamp=time.time(),
            sub_emotions={emotion.value: confidence} if confidence > 0 else {},
            emotion_mix={emotion.value: confidence} if confidence > 0 else {},
            intensity=confidence,
        )

    def detect_with_details(self, text: str) -> EmotionDetectionResult:
        emotion, confidence = self._extract_llm_tag(text)

        if emotion is None:
            return EmotionDetectionResult(
                emotion=EmotionType.NEUTRAL,
                confidence=0.0,
                source="no_tag",
            )

        return EmotionDetectionResult(
            emotion=emotion,
            confidence=confidence,
            source="llm_tag",
            rule_score=confidence,
        )

    def _extract_llm_tag(self, text: str) -> Tuple[Optional[EmotionType], float]:
        if not text or not str(text).strip():
            return None, 0.0

        m = EMO_TAG_PATTERN.search(text)
        if m:
            tag = m.group(1).lower()
            if tag in _CN_TO_EN_MAP:
                tag = _CN_TO_EN_MAP[tag]
            try:
                return EmotionType(tag), 0.95
            except ValueError:
                pass

        for m in EMO_SIMPLE_PATTERN.finditer(text):
            tag = m.group(1).upper()
            if tag in SYSTEM_TAGS:
                continue
            tag_lower = tag.lower()
            if tag_lower in _CN_TO_EN_MAP:
                tag_lower = _CN_TO_EN_MAP[tag_lower]
            try:
                return EmotionType(tag_lower), 0.90
            except ValueError:
                continue

        return None, 0.0

    def get_emotion_for_meme(self, text: str) -> Tuple[str, float]:
        state = self.detect(text)
        return state.primary_emotion.value, state.confidence


_detector_instance: Optional[EmotionDetectorV2] = None


def get_emotion_detector_v2() -> EmotionDetectorV2:
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = EmotionDetectorV2()
    return _detector_instance
