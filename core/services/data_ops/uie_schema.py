"""UIE信息抽取的Schema配置。

定义从用户对话中提取的结构化字段，取代正则+关键词的硬编码方式。
UIE通过自然语言schema描述抽取目标，零样本即可使用。
"""
from typing import Dict, List

# 主schema：用于一次调用提取所有字段（减少推理次数）
# 每个key是字段名，value是给UIE的抽取指令
EXTRACTION_SCHEMA: List[str] = [
    "起床时间",
    "睡觉时间",
    "吃的食物",
    "餐次",
    "喝的饮料",
    "学习内容",
    "活动内容",
    "健康症状",
    "情绪",
]

# 字段到ActivityExtractor记录类型的映射
SCHEMA_TO_RECORD_TYPE: Dict[str, str] = {
    "起床时间": "wakeup",
    "睡觉时间": "sleep",
    "吃的食物": "meal",
    "餐次": "meal_type",
    "喝的饮料": "drink",
    "学习内容": "study",
    "活动内容": "activity",
    "健康症状": "health",
    "情绪": "mood",
}

# 餐次标准化映射（用户可能说"早饭"/"早餐"/"早晨吃的"，统一为标准值）
MEAL_TYPE_NORMALIZE: Dict[str, str] = {
    "早饭": "breakfast",
    "早餐": "breakfast",
    "午饭": "lunch",
    "午餐": "lunch",
    "晚饭": "dinner",
    "晚餐": "dinner",
    "夜宵": "late_night",
    "宵夜": "late_night",
    "加餐": "snack",
    "下午茶": "snack",
}

# 情绪标准化映射
MOOD_NORMALIZE: Dict[str, str] = {
    "开心": "happy",
    "高兴": "happy",
    "快乐": "happy",
    "难过": "sad",
    "伤心": "sad",
    "郁闷": "sad",
    "焦虑": "anxious",
    "紧张": "anxious",
    "生气": "angry",
    "愤怒": "angry",
    "烦": "angry",
    "疲惫": "tired",
    "累": "tired",
    "困": "tired",
    "兴奋": "excited",
    "激动": "excited",
    "平静": "neutral",
    "孤独": "lonely",
    "害怕": "fear",
    "恐惧": "fear",
    "委屈": "wronged",
}
