"""QQ 表情标签与情绪映射。"""

from __future__ import annotations

# 情绪英文键 -> QQ 表情中文标签
EMOTION_TO_FACE_LABEL = {
    "happy": "微笑",
    "joy": "微笑",
    "smile": "微笑",
    "neutral": "微笑",
    "sad": "难过",
    "grief": "难过",
    "lost": "难过",
    "angry": "生气",
    "anger": "生气",
    "annoyed": "生气",
    "fear": "疑问",
    "surprised": "惊讶",
    "shy": "害羞",
    "embarrassed": "害羞",
    "sleepy": "困",
    "tired": "困",
    "confused": "疑问",
    "anxious": "疑问",
    "concerned": "疑问",
    "wronged": "委屈",
}

# 中文近义情绪 -> 标准标签（用于把"疑惑/困惑/好奇"等归一到"疑问"等）
EMOTION_LABEL_NORMALIZATION = {
    "疑惑": "疑问",
    "困惑": "疑问",
    "好奇": "疑问",
    "问号": "疑问",
    "伤心": "难过",
    "失落": "难过",
    "低落": "难过",
    "沮丧": "难过",
    "愤怒": "生气",
    "火大": "生气",
    "暴躁": "生气",
    "开心": "微笑",
    "高兴": "微笑",
    "愉快": "微笑",
    "平静": "微笑",
    "冷静": "微笑",
    "紧张": "疑问",
    "焦虑": "疑问",
    "困倦": "困",
    "疲惫": "困",
}


def resolve_emotion_face_label(emotion_key: str) -> str:
    """把情绪键解析为 QQ 表情中文标签，找不到返回空串。"""
    key = str(emotion_key or "").strip().lower()
    normalized = EMOTION_LABEL_NORMALIZATION.get(key, key)
    return EMOTION_TO_FACE_LABEL.get(normalized, "")
