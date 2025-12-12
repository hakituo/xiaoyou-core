import re
import time
from typing import Dict, Any, List
from collections import defaultdict

from .models import EmotionType, EmotionState
from .constants import EMOTION_KEYWORDS, EMOTION_PRIORITY, CN_TO_EN_MAP

class EmotionDetector:
    """
    负责从文本中检测情绪
    """
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.threshold = self.config.get("detection_threshold", 0.6)

    def detect(self, text: str) -> EmotionState:
        """
        检测文本情绪，返回 EmotionState
        """
        if not text:
            return self._create_neutral_state()

        # 1. 尝试从 LLM 标记中提取 [EMO: xxx] 或 [xxx]
        llm_emotion = self._extract_llm_tag(text)
        if llm_emotion:
            return EmotionState(
                primary_emotion=llm_emotion,
                confidence=1.0,
                sub_emotions={llm_emotion.value: 1.0},
                intensity=0.8
            )

        # 2. 关键词/规则匹配 (User requested to disable keyword recognition fallback)
        # return self._detect_by_keywords(text)
        return self._create_neutral_state()

    def _create_neutral_state(self) -> EmotionState:
        return EmotionState(
            primary_emotion=EmotionType.NEUTRAL,
            confidence=1.0,
            sub_emotions={}
        )

    def _extract_llm_tag(self, text: str) -> EmotionType:
        """
        提取 [EMO: happy] 或 [happy] 格式的标签
        """
        # Pattern 1: [EMO: happy]
        match = re.search(r'\[EMO:\s*([a-zA-Z0-9_\u4e00-\u9fa5]+)\]', text, re.IGNORECASE)
        if not match:
            # Pattern 2: [happy] - exclude [TOOL_USE: ...] or [GEN_IMG: ...]
            # We look for simple tags that match emotion names
            match = re.search(r'\[([a-zA-Z0-9_\u4e00-\u9fa5]+)\]', text, re.IGNORECASE)
            
        if match:
            label = match.group(1).lower()
            
            # Skip known system tags
            if label in ["tool_use", "gen_img", "voice", "system", "user"]:
                return None
                
            # 尝试映射
            if label in CN_TO_EN_MAP:
                label = CN_TO_EN_MAP[label]
            
            # 检查是否在枚举中
            try:
                return EmotionType(label)
            except ValueError:
                # 模糊匹配
                for et in EmotionType:
                    if et.value in label or label in et.value:
                        return et
        return None

    def _detect_by_keywords(self, text: str) -> EmotionState:
        """
        使用关键词频率和位置权重检测
        """
        text_lower = text.lower()
        scores = defaultdict(float)
        
        # 分词 (简单正则)
        words = re.findall(r'[\u4e00-\u9fa5]+|[a-zA-Z0-9]+', text_lower)
        total_words = len(words)
        
        for i, word in enumerate(words):
            # 位置权重：越靠前权重越高 (0.5 ~ 1.0)
            # 或者是越靠后？通常用户表达情绪的词可能在句尾 "我好难过"
            # 原实现是前面的词权重高，这里我们改一下，认为任何位置都重要，但句首句尾可能更重要
            # 暂时保持简单的线性衰减或不衰减
            position_weight = 1.0 
            
            for emo_key, keywords in EMOTION_KEYWORDS.items():
                if emo_key == "neutral":
                    continue
                
                # 检查是否匹配关键词
                if word in keywords:
                    # 基础分 + 优先级加成
                    base_score = 1.0
                    priority = EMOTION_PRIORITY.get(emo_key, 0.5)
                    scores[emo_key] += base_score * (1 + priority)

        if not scores:
            return self._create_neutral_state()

        # 归一化
        total_score = sum(scores.values())
        normalized_scores = {k: v / total_score for k, v in scores.items()}
        
        # 找出最大值
        primary_emo_str = max(normalized_scores.items(), key=lambda x: x[1])[0]
        confidence = normalized_scores[primary_emo_str]
        
        try:
            primary_emo = EmotionType(primary_emo_str)
        except:
            primary_emo = EmotionType.NEUTRAL

        return EmotionState(
            primary_emotion=primary_emo,
            confidence=confidence,
            sub_emotions=normalized_scores,
            intensity=min(confidence * 1.5, 1.0) # 简单估算强度
        )
