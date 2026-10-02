"""画像话题关键词映射与覆盖检测模块

集中管理所有画像话题的关键词映射，避免 priority_analyzer 和
decision_instruction_builder 中的重复定义。

包含：
- _PORTRAIT_KEYWORD_MAP：画像话题关键词映射（完整版，合并了两处定义）
- _USER_COVERED_KEYWORDS：用户已覆盖话题关键词映射（从 decision_instruction_builder 迁移）
- check_portrait_keyword_coverage：关键词兜底检测函数（从 PriorityAnalyzer 拆出）
- detect_user_already_covered：检测用户最近消息中已明确表示过的话题（从 decision_instruction_builder 迁移）
"""

from typing import Any, Dict, List, Optional, Set


# ============================================================
# 画像话题关键词映射（完整版）
# 合并自 priority_analyzer._PORTRAIT_KEYWORD_MAP 和
# decision_instruction_builder._USER_COVERED_KEYWORDS，
# 取两处定义的并集，确保关键词覆盖最全。
# ============================================================

_PORTRAIT_KEYWORD_MAP: Dict[str, List[str]] = {
    "wakeup": [
        "起床", "醒了", "起来", "早安", "早上好", "刚醒", "睡醒",
        "自然醒", "闹钟", "起来了", "刚起来", "早起了",
    ],
    "meal": [
        "吃了", "吃完", "吃饭", "吃了饭", "吃了面", "吃了早", "吃了午", "吃了晚",
        "吃饱", "吃好", "吃过了", "正在吃", "在吃", "点了外卖", "喝了粥",
        "吃了个", "刚吃完", "不用吃了", "早餐", "午饭", "晚饭", "夜宵",
    ],
    "sleep": [
        "晚安", "睡了", "要睡", "去睡", "困了", "好困", "想睡",
        "准备睡", "先睡", "躺下", "不睡了",
    ],
    "activity": [
        "出门", "回来", "到家", "在外面", "逛街", "运动", "锻炼",
        "健身", "跑步", "散步", "打球", "游泳", "骑车", "爬山",
        "在家", "没出门", "宅着",
    ],
    "study": [
        "学习", "看书", "写作业", "复习", "背单词", "上课",
        "刷题", "做卷子", "写代码", "查资料", "在学", "学完",
    ],
    "mood": [
        "心情好", "心情不好", "开心", "难过", "烦", "郁闷", "emo",
        "焦虑", "压力", "累", "放松", "平静", "兴奋", "满足",
    ],
    "health": [
        "不舒服", "生病", "头疼", "肚子疼", "感冒", "发烧",
        "咳嗽", "嗓子疼", "胃不舒服", "难受", "好多了", "恢复",
        "吃药", "去医院", "看医生", "体检",
    ],
}


# ============================================================
# 用户已覆盖话题关键词映射
# 从 decision_instruction_builder 迁移而来，用于决策指令构建时
# 检测用户是否已明确表示过某个话题，避免矛盾追问。
# 与 _PORTRAIT_KEYWORD_MAP 保持一致（同一份数据）。
# ============================================================

_USER_COVERED_KEYWORDS: Dict[str, List[str]] = _PORTRAIT_KEYWORD_MAP


def check_portrait_keyword_coverage(
    recent_history: List[Dict[str, Any]],
    candidate_topics: List[str],
    exclude: Optional[List[str]] = None,
) -> List[str]:
    """关键词兜底检测：检查用户最近消息中是否包含画像话题关键词

    当 BERT 语义检测可能漏检时，用关键词直接匹配作为第二道防线。
    只检查 role=user 的消息，避免助手消息中的关键词误判。

    Args:
        recent_history: 最近聊天记录
        candidate_topics: 候选画像话题列表
        exclude: 已由 BERT 检测到的话题，跳过

    Returns:
        已覆盖的话题列表
    """
    exclude_set = set(exclude or [])
    topics_to_check = [t for t in candidate_topics if t not in exclude_set]
    if not topics_to_check or not recent_history:
        return []

    # 只取用户消息，拼接为小写文本
    user_texts = []
    for msg in recent_history:
        if str(msg.get("role", "")).lower() == "user":
            content = str(msg.get("content", "")).strip().lower()
            if content:
                user_texts.append(content)

    if not user_texts:
        return []

    combined_text = " ".join(user_texts)
    covered = []
    for topic in topics_to_check:
        keywords = _PORTRAIT_KEYWORD_MAP.get(topic, [])
        if any(kw in combined_text for kw in keywords):
            covered.append(topic)

    return covered


def _detect_backend_meals_covered() -> Set[str]:
    """检测后端日常记录（daily_record）中已存储的今日餐饮

    用户可通过 /吃、/喝 等指令把"今天早餐/午餐/晚餐吃了什么"
    直接写入后端 daily_record 的 meals 列表。这种情况下用户
    并没有在聊天文字里提到吃饭，但仍应视作"餐饮话题已覆盖"，
    避免 active care 重复追问"早餐吃了没"。

    Returns:
        已覆盖的话题集合，若今日 meals 中存在正餐记录则包含 "meal"
    """
    covered = set()
    try:
        from core.services.daily.manager import get_daily_manager
        daily_mgr = get_daily_manager()
        record = daily_mgr.get_record()
        meals = (record or {}).get("meals") or []
        if not isinstance(meals, list):
            return covered
        # 正餐类型（后端记录时 meal_type 取值）
        main_meal_types = {"早餐", "午餐", "晚餐"}
        for item in meals:
            if not isinstance(item, dict):
                continue
            mtype = str(item.get("type", "")).strip()
            if mtype in main_meal_types:
                covered.add("meal")
                break
    except Exception:
        # 查询失败不应阻断决策流程
        pass
    return covered


def detect_user_already_covered(context: Dict[str, Any]) -> Set[str]:
    """检测用户最近消息中已经明确表示过的话题

    通过关键词匹配用户最近的消息，判断用户是否已经明确表示
    起床/吃饭/睡觉等，避免 LLM 生成矛盾的内容（如用户说了
    早安还问"还在睡吧"）。

    除聊天文字外，还会参考后端日常记录（daily_record）中已
    存储的今日餐饮：若后端已记录今天的早餐/午餐/晚餐，则视作
    餐饮话题已覆盖，不再追问"吃了没"。

    Args:
        context: 决策上下文，需包含 recent_history 字段

    Returns:
        已覆盖的话题集合，如 {"wakeup", "meal"}
    """
    recent_history = context.get("recent_history") or []
    if not recent_history:
        return set()

    # 只取用户消息
    user_texts = []
    for msg in recent_history:
        if str(msg.get("role", "")).lower() == "user":
            content = str(msg.get("content", "")).strip().lower()
            if content:
                user_texts.append(content)

    if not user_texts:
        return set()

    combined_text = " ".join(user_texts)
    covered = set()
    for topic, keywords in _USER_COVERED_KEYWORDS.items():
        if any(kw in combined_text for kw in keywords):
            covered.add(topic)

    # 合并后端日常记录中已存储的今日餐饮（如已记录早餐/午餐/晚餐）
    covered |= _detect_backend_meals_covered()

    return covered
