# Memory Utils Module

import re
from typing import List, Dict, Any

def extract_key_information(content: str) -> List[str]:
    """从消息内容中提取关键信息"""
    key_info = []
    patterns = [
        r'\b(?:\d{4}年\d{1,2}月\d{1,2}日|\d{4}/\d{1,2}/\d{1,2}|\d{1,2}/\d{1,2}/\d{4})\b',
        r'\b\d+(?:\.\d+)?\s*(?:个|件|元|美元|人民币|斤|公斤|米|厘米|升|毫升|小时|分钟|秒)\b',
        r'\b[A-Z][a-zA-Z0-9_]{2,}\b',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, content)
        key_info.extend(matches)
    return list(set(key_info))[:5]

def detect_topics(content: str) -> List[str]:
    """自动检测消息主题"""
    topic_keywords = {
        "技术": ["编程", "代码", "软件", "算法", "开发", "项目", "架构", "框架", "python", "java", "c++", "ai", "模型", "bug", "调试", "linux", "windows", "服务器", "数据库"],
        "生活": ["吃饭", "睡觉", "旅游", "购物", "电影", "音乐", "运动", "健康", "天气", "美食", "衣服", "房价", "装修", "家务", "宠物", "猫", "狗"],
        "工作": ["会议", "报告", "任务", "截止日期", "同事", "客户", "公司", "老板", "工资", "加班", "出差", "面试", "简历", "职业", "规划"],
        "学习": ["考试", "作业", "书籍", "课程", "学校", "成绩", "老师", "学生", "论文", "研究", "复习", "笔记", "大学", "专业", "知识"],
        "娱乐": ["游戏", "视频", "直播", "社交媒体", "明星", "综艺", "动漫", "小说", "漫画", "二次元", "番剧", "steam", "switch", "ps5", "玩"],
        "情感": ["喜欢", "爱", "讨厌", "难过", "开心", "焦虑", "烦恼", "心事", "男朋友", "女朋友", "恋爱", "分手", "表白", "情绪", "孤独", "想你", "恨"],
        "日常": ["你好", "早安", "晚安", "在吗", "干嘛", "哈哈", "呵呵", "嗯", "哦", "好的", "知道了", "闲聊", "无聊", "打招呼", "吃了吗"],
    }
    
    detected_topics = []
    content_lower = content.lower()
    
    for topic, keywords in topic_keywords.items():
        for keyword in keywords:
            if keyword in content_lower:
                detected_topics.append(topic)
                break
    
    if not detected_topics and len(content) > 10:
        detected_topics.append("其他")
        
    return detected_topics

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
                    preference_content = parts[1].strip().split('。')[0]
                    if preference_content:
                        user_preferences[pref_type][preference_content] = \
                            user_preferences[pref_type].get(preference_content, 0) + 1
