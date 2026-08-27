"""统一的学习模式检测与科目分类模块

将原先散落在 agents/chat_agent_components/study.py 和
services/study/subject_analyzer.py 中的分类逻辑合并为单一权威入口。
"""
from typing import Dict, List, Optional

# ============================================================
# 科目关键词表 —— 唯一权威定义
# ============================================================
# 用于 classify_subject()（返回 PascalCase）和
# StudySubjectAnalyzer.classify_topic()（返回 lowercase）
SUBJECT_KEYWORDS: Dict[str, List[str]] = {
    "biology": ["生物", "biology", "细胞", "遗传", "基因", "进化"],
    "chemistry": ["化学", "chemistry", "元素", "反应", "有机", "分子"],
    "physics": ["物理", "physics", "力学", "电磁", "光", "能量"],
    "math": ["数学", "math", "函数", "几何", "导数", "积分", "代数", "立体几何"],
    "english": [
        "英语", "english", "单词", "语法", "作文", "听力",
        "vocabulary", "word", "cet",
    ],
    "chinese": ["语文", "chinese", "古诗", "文言文", "阅读理解", "作文", "poetry", "文言"],
    "geography": ["地理", "geography", "地形", "气候", "洋流", "地貌"],
    "history": ["历史", "history", "朝代", "事件", "战争", "革命"],
    "political_science": ["政治", "politics", "马克思", "经济", "哲学"],
}

# 学习模式触发词
_MODE_TRIGGERS = ["进入学习模式", "开始学习", "study mode", "高考模式"]

# 学习模式内容关键词（不匹配科目但明显是学习场景）
_CONTENT_KEYWORDS = [
    "阅读理解", "七选五", "完形填空", "阅读", "英语阅读",
    "背诵", "复习", "考试", "高考",
    "数学题", "物理题", "化学题", "生物题",
    "听力", "翻译", "练习题", "试题",
    "解题", "答案", "选择题", "填空题", "解答题",
    "exam", "quiz", "test",
    "生词", "测验单词", "考单词", "背单词",
]

# model_hint 中的学习关键词
_HINT_KEYWORDS = ["study", "gaokao", "learning", "tutor"]


# ============================================================
# 公共 API
# ============================================================

def is_study_mode(message: str, model_hint: Optional[str] = None) -> bool:
    """判断消息是否处于学习模式。"""
    if model_hint and any(k in model_hint.lower() for k in _HINT_KEYWORDS):
        return True

    msg_lower = message.lower()
    if any(t in msg_lower for t in _MODE_TRIGGERS):
        return True

    if any(k in msg_lower for k in _CONTENT_KEYWORDS):
        return True

    if classify_subject(message) is not None:
        return True

    return False


def classify_subject(message: str) -> Optional[str]:
    """根据消息内容识别学科，返回 PascalCase 学科名或 None。"""
    msg_lower = message.lower()
    for subject, keywords in SUBJECT_KEYWORDS.items():
        if any(k in msg_lower for k in keywords):
            # 返回 PascalCase: biology -> Biology, political_science -> Political_Science
            if subject == "political_science":
                return "Political_Science"
            return subject.capitalize()
    return None
