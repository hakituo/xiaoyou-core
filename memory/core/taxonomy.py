"""记忆主题分类词表（公开仓库占位版）。

说明：私有版本包含完整词表与额外分类；公开仓库出于隐私考虑仅保留
分类结构占位，接口签名与私有版一致，保证导入链完整。
"""

from typing import Dict, List


TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "daily": ["today", "sleep", "eat", "weather", "日常", "今天", "睡觉", "吃饭", "天气"],
    "learning": ["learn", "study", "code", "python", "学习", "研究", "代码", "读书"],
    "work": ["work", "meeting", "project", "工作", "开会", "项目", "加班"],
    "health": ["health", "sick", "医院", "生病", "运动", "健康"],
    "entertainment": ["game", "movie", "music", "游戏", "电影", "音乐", "动漫"],
    "tech": ["tech", "software", "科技", "数码", "编程"],
    "emotion": ["mood", "happy", "sad", "心情", "开心", "难过", "情绪"],
    "relationship": ["friend", "family", "朋友", "家人"],
}

CATEGORY_ORDER: List[str] = [
    "daily", "learning", "work", "health",
    "entertainment", "tech", "emotion", "relationship",
]


def detect_topics(content: str) -> List[str]:
    """检测文本命中的主题（占位实现：关键词子串匹配）。"""
    text = str(content or "").strip().lower()
    if not text:
        return []
    topics: List[str] = ["Chat"]
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(str(kw).lower() in text for kw in keywords):
            topics.append(topic)
    return topics


def classify_category(content: str) -> str:
    """将文本归类到主要分类（占位实现）。"""
    topics = detect_topics(content)
    for topic in CATEGORY_ORDER:
        if topic in topics:
            return topic
    return "general"
