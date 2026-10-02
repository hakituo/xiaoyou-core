"""统一的学习模式检测与科目分类模块。

原有关键词继续作为无 Study Registry 部署时的兼容 fallback；正常运行时优先读取
``Study/Subjects/registry.yaml``，因此学科识别不再局限于高考九科。
"""
from typing import Dict, List, Optional

SUBJECT_KEYWORDS: Dict[str, List[str]] = {
    "biology": ["生物", "biology", "细胞", "遗传", "基因", "进化"],
    "chemistry": ["化学", "chemistry", "元素", "反应", "有机", "分子"],
    "physics": ["物理", "physics", "力学", "电磁", "能量"],
    "math": ["数学", "math", "函数", "几何", "导数", "积分", "代数", "立体几何"],
    "english": [
        "英语", "english", "单词", "语法", "作文", "听力",
        "vocabulary", "word", "cet",
    ],
    "chinese": ["语文", "chinese", "古诗", "文言文", "阅读理解", "作文", "poetry", "文言"],
    "geography": ["地理", "geography", "地形", "气候", "洋流", "地貌"],
    "history": ["历史", "history", "朝代", "事件", "战争", "革命"],
    "political_science": ["政治", "politics", "马克思", "经济"],
}

# 关键字命中要求的最短长度。
# 修复：「光」「力」这类**单字关键字**会让「这里有光」「这个力很大」被判成物理，
# 而单字在中文里几乎全是常用词的一部分，不构成学科证据。统一要求 >= 2 字符。
MIN_KEYWORD_LEN = 2

# 内容术语兜底。**分两档**，档位决定置信度，置信度决定消息层判定：
#
#   ``_DOMAIN_CONCEPT_HINTS``  —— **课程标准概念**（教科书章节/定律/定理名）。
#       命中即视为「明确学科」→ 0.9 → ``accept``。
#       矩阵 R-15「光合作用」/ R-16「胡克定律」走这一档。
#
#   ``_DOMAIN_TOPIC_HINTS``    —— **领域话题专名**（历史事件/制度/地域）。
#       命中说明「在聊这个领域」，但不等于「在学这个知识点」→ 0.75 →
#       ``candidate_only``。矩阵 R-08「柬埔寨国王」/ R-09「财产局」走这一档：
#       **真实历史问题、候选可用，但学科置信不足以让消息升格**。
#
# 两档的分界对齐 ``SubjectRegistry.match_text`` 的校准原则：
# 「长 alias（>= 3 字）→ 高置信」只适用于**概念名**；
# 话题专名再长也只是「提到了这个领域」，所以整档降一级。
#
# 收录原则（避免重演「光」那类过宽命中）：
#   1. **长度 >= 2 的具体术语/专名**，不收通用抽象词；
#   2. 只收**指向明确领域**的词，宁可漏也不能错——
#      「资本家」「资本主义」这类跨政治/历史/经济的词**不收**。
_DOMAIN_CONCEPT_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("history", (
        "辛亥革命", "五四运动", "改革开放", "封建制度", "君主专制",
        "丝绸之路", "新文化运动", "百日维新",
    )),
    ("geography", ("季风", "暖流", "寒流", "板块", "等高线", "经纬", "时区", "三角洲")),
    ("political_science", ("剩余价值", "生产力", "生产关系", "上层建筑", "国体", "政体")),
    ("biology", ("光合作用", "呼吸作用", "细胞膜", "有丝分裂", "减数分裂", "生态系统")),
    ("chemistry", ("氧化还原", "摩尔", "化学键", "电离", "中和反应", "催化剂")),
    ("physics", ("胡克定律", "简谐运动", "牛顿定律", "动量守恒", "机械能", "自由落体")),
    ("math", ("不等式", "数列", "向量", "概率", "三角函数", "解析几何")),
)

# 领域话题专名：说明「在聊这个领域」，但不构成「明确学科」。
_DOMAIN_TOPIC_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("history", (
        "文革", "文化大革命", "建国", "王朝", "朝廷", "国王", "皇帝",
        "条约", "殖民地", "冷战", "二战", "一战", "抗战", "民国", "清朝", "明朝",
        "唐朝", "宋朝", "元朝", "汉朝", "秦朝", "诸侯", "君主",
        "柬埔寨", "越南", "朝鲜", "苏联", "罗马", "希腊", "文艺复兴",
        "启蒙运动", "工业革命", "封建", "财产局", "国民政府", "北洋",
    )),
)

# 兼容旧名：以前只有一张表，外部若有引用仍可用。
_DOMAIN_CONTENT_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    _DOMAIN_CONCEPT_HINTS + _DOMAIN_TOPIC_HINTS
)

# Registry 无法穷举所有具体术语；这里只保留歧义较低的 fallback。
_DOMAIN_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("computer_networks", ("syn", "ack", "tcp", "三次握手", "tcp/ip")),
    ("computer_systems", ("gpu", "cuda", "nvidia mps", "wsl", "显存", "sm 数")),
    ("programming", ("gradle", "kotlin", "fastapi", "typescript", "git push", "git rebase")),
    ("chemistry", ("2d轨道", "2f轨道", "2d 轨道", "2f 轨道", "电子排布", "原子轨道")),
    ("linguistics", ("希腊文", "古希腊语", "拉丁文", "拉丁语")),
    ("religion", ("耶稣", "圣经", "基督教", "佛教", "伊斯兰教")),
)

_MODE_TRIGGERS = ["进入学习模式", "开始学习", "study mode", "高考模式"]
_CONTENT_KEYWORDS = [
    "阅读理解", "七选五", "完形填空", "阅读", "英语阅读",
    "背诵", "复习", "考试", "高考",
    "数学题", "物理题", "化学题", "生物题",
    "听力", "翻译", "练习题", "试题",
    "解题", "答案", "选择题", "填空题", "解答题",
    "exam", "quiz", "test",
    "生词", "测验单词", "考单词", "背单词",
]
_HINT_KEYWORDS = ["study", "gaokao", "learning", "tutor"]


def is_study_mode(message: str, model_hint: Optional[str] = None) -> bool:
    if model_hint and any(k in model_hint.lower() for k in _HINT_KEYWORDS):
        return True
    msg_lower = message.lower()
    if any(t in msg_lower for t in _MODE_TRIGGERS):
        return True
    if any(k in msg_lower for k in _CONTENT_KEYWORDS):
        return True
    if classify_subject(message) is not None:
        return True
    try:
        from core.services.study.signal_detector import detect_learning_signal
        if detect_learning_signal(message).is_learning:
            return True
    except Exception:
        pass
    return False


def classify_subject(message: str) -> Optional[str]:
    """返回历史兼容的 Pascal_Case subject token。"""
    try:
        from core.services.study.subject_registry import get_subject_registry
        match = get_subject_registry().match_text(message)
        if match is not None:
            return "_".join(part.capitalize() for part in match.subject_id.split("_"))
    except Exception:
        pass

    msg_lower = message.lower()
    for subject, hints in _DOMAIN_HINTS:
        if any(hint in msg_lower for hint in hints):
            return "_".join(part.capitalize() for part in subject.split("_"))
    # 内容术语兜底：学生真的会聊、但学科名本身不出现的场景。
    # **概念档先于话题档**：同一句同时命中两档时，概念档信息量更高
    # （「光合作用」比「国王」更明确地指向生物学）。
    for hints_table in (_DOMAIN_CONCEPT_HINTS, _DOMAIN_TOPIC_HINTS):
        for subject, hints in hints_table:
            if any(hint in msg_lower for hint in hints):
                return "_".join(part.capitalize() for part in subject.split("_"))
    # 关键字表：**要求命中长度 >= 2**，单字不算学科证据
    for subject, keywords in SUBJECT_KEYWORDS.items():
        if any(
            k in msg_lower and len(k) >= MIN_KEYWORD_LEN
            for k in keywords
        ):
            return "_".join(part.capitalize() for part in subject.split("_"))
    return None
