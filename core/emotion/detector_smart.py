"""
智能情绪检测器 - 支持关键词 + BERT 零样本分类
论文级设计：
1. 快速路径（关键词+emoji+否定词+程度副词
2. 主路径（BERT 零样本语义分类
3. 多情绪分布输出
"""


from core.utils.logger import get_logger
import time
from typing import Dict, Optional

import numpy as np

from .models import EmotionType, EmotionState
from .constants import EMOTION_CN_MAP


logger = get_logger(__name__)


class EmotionDetectorSmart:
    """
    智能情绪检测器
    
    检测策略：
    1. Fast Path: 关键词 + emoji + 否定词 + 程度副词
    2. Main Path: BERT 零样本语义分类
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._bert_analyzer = None
        self._emotion_embeddings = None
        self._emotion_definitions = None

        self._negation_words = {
            "不", "没", "别", "非", "无", "没有", "未曾",
            "不要", "不能", "不会", "不可",
            "毫无", "并没有", "并不会", "并不要"
        }

        self._intensifier_words = {
            "超级": 1.5, "超": 1.5, "太": 1.4, "非常": 1.4,
            "特别": 1.4, "很": 1.3, "好": 1.3, "真": 1.3,
            "有点": 0.8, "有一点": 0.8, "稍微": 0.7, "一点": 0.7
        }

        self._emotion_order = list(EMOTION_CN_MAP.keys())

        self._keyword_only = self.config.get("keyword_only", False)
        self._keyword_weight = self.config.get("keyword_weight", 0.6)
        self._bert_weight = self.config.get("bert_weight", 0.4)

    def _get_bert_analyzer(self):
        """懒加载 BERT 分析器"""
        if self._bert_analyzer is not None:
            return self._bert_analyzer

        try:
            from core.services.data_ops.bert_analyzer import get_bert_analyzer
            self._bert_analyzer = get_bert_analyzer()
            logger.info("Loaded BERT Analyzer for emotion detection")
            return self._bert_analyzer
        except Exception as e:
            logger.warning(f"Failed to load BERT Analyzer: {e}, falling back to keyword-only mode")
            self._keyword_only = True
            return None

    def _get_emotion_definitions(self):
        """获取情绪定义"""
        if self._emotion_definitions is not None:
            return self._emotion_definitions

        try:
            from core.services.data_ops.bert_definitions import EMOTION_DEFINITIONS
            self._emotion_definitions = EMOTION_DEFINITIONS
            return self._emotion_definitions
        except Exception as e:
            logger.warning(f"Failed to load EMOTION_DEFINITIONS: {e}")
            return None

    def detect_fast_path(self, text: str) -> Optional[Dict[str, float]]:
        """
        快速路径：关键词 + emoji + 否定词 + 程度副词

        返回: {emotion: score}
        """
        if not text or not text.strip():
            return None

        text = text.strip().lower()
        emotion_defs = self._get_emotion_definitions()
        if not emotion_defs:
            return None

        scores = {emo: 0.0 for emo in emotion_defs.keys()}

        negation_found = False
        intensifier_multiplier = 1.0

        for neg_word in self._negation_words:
            if neg_word in text:
                negation_found = not negation_found
                break

        for intensifier, multiplier in self._intensifier_words.items():
            if intensifier in text:
                intensifier_multiplier = max(intensifier_multiplier, multiplier)

        for emo, keywords in emotion_defs.items():
            for keyword in keywords:
                if keyword in text:
                    base_score = 0.5 if len(keyword) >= 3 else 0.4
                    if negation_found:
                        scores["neutral"] += 0.2
                    else:
                        scores[emo] += base_score * intensifier_multiplier

        total = sum(scores.values())
        if total > 0:
            scores = {k: v / total for k, v in scores.items()}
            return scores
        return None

    def detect_bert_path(self, text: str) -> Optional[Dict[str, float]]:
        """
        BERT 零样本路径：语义分类

        返回: {emotion: score}
        """
        if self._keyword_only:
            return None

        bert = self._get_bert_analyzer()
        if not bert or not hasattr(bert, "_session"):
            return None

        try:
            content_emb = bert._get_text_embedding(text)
            if content_emb is None:
                return None

            norm = np.linalg.norm(content_emb)
            if norm > 0:
                content_emb = content_emb / norm

            emotion_defs = self._get_emotion_definitions()
            if not emotion_defs:
                return None

            emotion_emb = bert._compute_embeddings_for_dict(emotion_defs)
            if not emotion_emb:
                return None

            scores = {}
            for emo, proto_emb in emotion_emb.items():
                score = float(np.dot(content_emb, proto_emb))
                scores[emo] = max(0.0, score)

            total = sum(scores.values())
            if total > 0:
                scores = {k: v / total for k, v in scores.items()}
                return scores

            return None
        except Exception as e:
            logger.warning(f"BERT emotion detection failed: {e}")
            return None

    def detect(self, text: str) -> EmotionState:
        """
        综合检测：融合 Fast Path + BERT Path

        返回: EmotionState
        """
        t0 = time.time()

        fast_scores = self.detect_fast_path(text)
        bert_scores = self.detect_bert_path(text)

        final_scores = {}
        source = "hybrid"

        emotion_defs = self._get_emotion_definitions() or {}
        emotion_list = list(emotion_defs.keys()) if emotion_defs else list(EMOTION_CN_MAP.keys())

        if fast_scores and bert_scores:
            for emo in emotion_list:
                final_scores[emo] = (fast_scores.get(emo, 0) * self._keyword_weight + bert_scores.get(emo, 0) * self._bert_weight)
        elif fast_scores:
            final_scores = fast_scores
            source = "keyword"
        elif bert_scores:
            final_scores = bert_scores
            source = "bert"
        else:
            final_scores = {"neutral": 1.0}
            source = "default"

        sorted_emotions = sorted(final_scores.items(), key=lambda x: -x[1])
        primary_emo_key, primary_score = sorted_emotions[0]

        try:
            primary_emo = EmotionType(primary_emo_key)
        except Exception:
            primary_emo = EmotionType.NEUTRAL

        sub_emotions = {k: v for k, v in sorted_emotions if v > 0.1}
        emotion_mix = dict(sub_emotions)
        intensity = min(primary_score, 1.0)

        latency = (time.time() - t0) * 1000
        logger.debug(f"Emotion detection: {primary_emo.value} ({primary_score:.2f}) in {latency:.1f}ms, source={source}")

        return EmotionState(
            primary_emotion=primary_emo,
            confidence=primary_score,
            sub_emotions=sub_emotions,
            emotion_mix=emotion_mix,
            timestamp=time.time(),
            intensity=intensity,
            source=source
        )

    def detect_with_details(self, text: str) -> EmotionState:
        """带详情的检测（直接返回 EmotionState）"""
        return self.detect(text)


_detector_instance: Optional[EmotionDetectorSmart] = None


def get_emotion_detector_smart() -> EmotionDetectorSmart:
    """获取单例"""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = EmotionDetectorSmart()
    return _detector_instance
