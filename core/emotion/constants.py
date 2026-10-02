import re
from typing import Dict, Set

from .models import EmotionType

EMOTION_PRIORITY: Dict[str, float] = {
    "sad": 1.0,
    "wronged": 1.0,
    "fear": 0.95,
    "anxious": 0.9,
    "lost": 0.9,
    "angry": 0.8,
    "lonely": 0.75,
    "tired": 0.7,
    "jealous": 0.7,
    "happy": 0.6,
    "excited": 0.6,
    "coquetry": 0.5,
    "shy": 0.5,
    "neutral": 0.0,
}

EMO_TAG_PATTERN = re.compile(r"\[EMO:\s*([a-zA-Z0-9_\u4e00-\u9fa5]+)\]", re.IGNORECASE)
EMO_SIMPLE_PATTERN = re.compile(r"\[([a-zA-Z0-9_\u4e00-\u9fa5]+)\]", re.IGNORECASE)

SYSTEM_TAGS: Set[str] = {
    "TOOL_USE", "GEN_IMG", "VOICE", "EMO", "ACTION", "THINK",
    "SYSTEM", "USER", "ASSISTANT", "MEMORY", "CONTEXT",
}

EMOTION_CN_MAP: Dict[str, str] = {
    "happy": "开心", "sad": "难过", "angry": "生气", "anxious": "焦虑",
    "tired": "疲惫", "neutral": "平静", "shy": "害羞", "excited": "兴奋",
    "jealous": "吃醋", "wronged": "委屈", "coquetry": "撒娇",
    "lost": "迷茫", "lonely": "孤独", "fear": "害怕",
}

EMOTION_BEHAVIOR_HINTS: Dict[str, str] = {
    "happy": "语气轻快，可以分享喜悦，适当调皮",
    "sad": "语气低落，话少，可能需要安慰",
    "angry": "语气急躁，可能带刺，需要理解和安抚",
    "anxious": "语气紧张不安，需要鼓励和安全感",
    "tired": "反应迟缓，话少，可能想休息",
    "shy": "说话拘谨，回避直视，小声",
    "excited": "语气激动，话多，充满期待",
    "jealous": "语气酸溜溜的，可能闹别扭",
    "wronged": "语气委屈，可能撒娇求安慰",
    "coquetry": "语气撒娇，粘人，想被关注",
    "lost": "语气迷茫，不知所措，需要指引",
    "lonely": "语气落寞，渴望陪伴",
    "fear": "语气害怕，需要保护和安慰",
    "neutral": "",
}

EMOTION_COLOR_MAP: Dict[EmotionType, str] = {
    EmotionType.HAPPY: "#FFDF00",
    EmotionType.SAD: "#0000FF",
    EmotionType.ANGRY: "#FF0000",
    EmotionType.ANXIOUS: "#800080",
    EmotionType.TIRED: "#808080",
    EmotionType.NEUTRAL: "#FFFFFF",
    EmotionType.SHY: "#FFC0CB",
    EmotionType.EXCITED: "#FFA500",
    EmotionType.JEALOUS: "#00FF00",
    EmotionType.COQUETRY: "#FF69B4",
    EmotionType.WRONGED: "#4B0082",
    EmotionType.LOST: "#4682B4",
    EmotionType.LONELY: "#191970",
    EmotionType.FEAR: "#2F4F4F",
}

EMOTION_BREATHING_RATE_MAP: Dict[EmotionType, int] = {
    EmotionType.ANGRY: 1000,
    EmotionType.EXCITED: 1500,
    EmotionType.JEALOUS: 2000,
    EmotionType.ANXIOUS: 2000,
    EmotionType.FEAR: 2000,
    EmotionType.HAPPY: 3000,
    EmotionType.COQUETRY: 3000,
    EmotionType.SHY: 3500,
    EmotionType.NEUTRAL: 4000,
    EmotionType.SAD: 5000,
    EmotionType.LONELY: 5000,
    EmotionType.WRONGED: 5500,
    EmotionType.LOST: 5500,
    EmotionType.TIRED: 6000,
}
