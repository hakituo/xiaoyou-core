# Memory Utils Module

import re
from typing import List, Dict, Any, Optional, Set
from memory.core.taxonomy import (
    detect_topics as detect_topics_from_taxonomy,
    classify_category as classify_category_from_taxonomy,
)
from memory.core.text_segmenter import STOPWORDS as TEXT_SEGMENTER_STOPWORDS

_UNIFIED_STOPWORDS = TEXT_SEGMENTER_STOPWORDS | {
    "一个", "上", "也", "很", "到", "说", "要", "去", "会", "着", "没有", "看", "好", "自己", "这",
    "that", "the", "and", "is", "in", "i", "have", "with", "to", "not",
    "people", "all", "a", "an", "on", "also", "very", "said", "will", "your", "this",
}


def detect_topics(content: str) -> List[str]:
    return detect_topics_from_taxonomy(content)


def classify_category(content: str) -> str:
    return classify_category_from_taxonomy(content)


def extract_user_preferences(content: str, user_preferences: Dict[str, Any]):
    """从用户消息中提取偏好信息"""
    preference_patterns = {
        "preferred_topics": ["喜欢", "感兴趣", "想了解", "关注"],
        "disliked_topics": ["不喜欢", "讨厌", "反感", "不想"],
        "response_style": ["简洁", "详细", "专业", "口语化", "幽默", "严肃"],
    }

    for pref_type, indicators in preference_patterns.items():
        for indicator in indicators:
            if indicator in content:
                if pref_type not in user_preferences:
                    user_preferences[pref_type] = {}
                parts = content.split(indicator)
                if len(parts) > 1:
                    preference_content = parts[1].strip().split("。")[0]
                    if preference_content:
                        user_preferences[pref_type][preference_content] = (
                            user_preferences[pref_type].get(preference_content, 0) + 1
                        )


def _extract_keywords_by_jieba(text_lower: str) -> Optional[Set[str]]:
    """用 jieba 分词提取关键词；jieba 不可用时返回 None 由调用方回退"""
    try:
        import jieba

        jieba.setLogLevel(60)
        words = [str(w).strip() for w in jieba.cut(text_lower, cut_all=False)]
    except Exception:
        return None

    keywords: Set[str] = set()
    for w in words:
        if not w or len(w) <= 1 or w in _UNIFIED_STOPWORDS:
            continue
        keywords.add(w)
        # 长中文词补充 bigram，保证复合词的部分命中（如"那个初二的小鬼"→"初二"）
        if re.fullmatch(r"[\u4e00-\u9fa5]{4,}", w):
            for i in range(len(w) - 1):
                bigram = w[i : i + 2]
                if bigram not in _UNIFIED_STOPWORDS:
                    keywords.add(bigram)
    if not keywords:
        return set()
    return keywords


def extract_keywords(content: str) -> Set[str]:
    """从内容中提取关键词

    优先使用 jieba 分词（项目已有依赖），让索引侧与查询侧的词面一致：
    原正则方案把连续中文串当作单一 token，"初中女生"与"初二女生"
    这类近义表述完全无法相交。jieba 不可用时回退到原正则 + bigram 逻辑。
    """
    text = str(content or "").strip()
    if not text:
        return set()

    text_lower = text.lower()

    keywords = _extract_keywords_by_jieba(text_lower)
    if keywords is None:
        # 回退：匹配中文字符、英文字母、数字和下划线（原实现）
        tokens = re.findall(r"[\u4e00-\u9fa5]{2,}|[a-zA-Z0-9_]{2,}", text_lower)
        if not tokens:
            cleaned = re.sub(r"[^\w\s]", " ", text_lower)
            tokens = [w for w in cleaned.split() if w]

        keywords = set()
        for tok in tokens:
            t = str(tok).strip().lower()
            if not t or t in _UNIFIED_STOPWORDS:
                continue
            if len(t) <= 1:
                continue
            keywords.add(t)

            if re.fullmatch(r"[\u4e00-\u9fa5]{4,}", t):
                for i in range(len(t) - 1):
                    bigram = t[i : i + 2]
                    if bigram not in _UNIFIED_STOPWORDS:
                        keywords.add(bigram)

    if len(keywords) > 30:
        scored = []
        for kw in keywords:
            score = len(kw)
            if re.fullmatch(r"[\u4e00-\u9fa5]+", kw):
                score += 2
            scored.append((kw, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        keywords = {kw for kw, _ in scored[:30]}

    return keywords
