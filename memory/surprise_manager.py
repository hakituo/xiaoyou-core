#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
惊喜准备功能模块

该模块基于记忆权重系统识别用户长期关注的兴趣点和偏好，
设计惊喜触发机制，并实现惊喜内容生成功能，能够基于高权重记忆创造用户可能感兴趣的新话题。
"""

import json
import os
import time
import random
import logging
from typing import List, Dict, Any, Optional, Union, Tuple, Set
from pathlib import Path
from collections import defaultdict, Counter
import re
from datetime import datetime, timedelta

# 导入记忆管理器和话题生成器
from .weighted_memory_manager import get_weighted_memory_manager
from .topic_generator import get_topic_generator

# 配置日志
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_SURPRISE_CONFIG = {
    "interest_min_weight": 2.0,           # 识别为兴趣点的最低记忆权重
    "min_interest_occurrences": 3,        # 兴趣点最少出现次数
    "interest_cooldown_days": 7,          # 同一兴趣点惊喜的冷却期（天）
    "max_interest_suggestions": 3,        # 每次最多生成的兴趣点建议
    "special_date_weight_multiplier": 2.0, # 特殊日期的权重倍数
    "emotion_threshold": 0.8,             # 情绪触发阈值
    "random_surprise_probability": 0.05,  # 随机惊喜触发概率（每次对话）
    "max_surprise_frequency": 3,          # 每周最大惊喜次数
    "interest_categories": [              # 兴趣分类
        "娱乐爱好", "工作学习", "生活方式", "人际关系", "健康运动", 
        "旅游出行", "科技数码", "美食烹饪", "艺术文化", "个人成长"
    ],
    "special_dates": {                    # 特殊日期配置（默认值，实际使用时应从配置文件加载）
        "birthday": None,                 # 用户生日
        "anniversary": None,              # 相识纪念日
        "custom_dates": []                # 自定义特殊日期
    },
    "surprise_categories": [              # 惊喜类型分类
        "话题推荐", "记忆回顾", "兴趣拓展", "成就祝贺", "鼓励支持"
    ],
    "surprise_content_templates": True,   # 是否使用内容模板
    "context_aware_surprise": True,       # 是否启用上下文感知
    "save_surprise_history": True,        # 是否保存惊喜历史
    "max_history_size": 100               # 最大历史记录数量
}

# 特殊日期关键词
SPECIAL_DATE_KEYWORDS = {
    "birthday": ["生日", "出生", "生日快乐", "诞辰", "年龄"],
    "anniversary": ["纪念日", "相识", "相遇", "认识", "初次见面"],
    "custom_dates": []
}

# 兴趣分类关键词
INTEREST_CATEGORY_KEYWORDS = {
    "娱乐爱好": ["电影", "音乐", "游戏", "动漫", "阅读", "绘画", "摄影", "舞蹈", "戏剧", 
                "演唱会", "展览", "收藏", "手工", "DIY", "瑜伽", "运动"],
    "工作学习": ["工作", "学习", "研究", "项目", "考试", "论文", "会议", "演讲", 
                "培训", "晋升", "求职", "面试", "报告", "方案", "目标"],
    "生活方式": ["生活", "日常", "习惯", "作息", "饮食", "购物", "装修", "旅行", 
                "聚会", "家务", "宠物", "园艺", "整理", "规划", "理财"],
    "人际关系": ["朋友", "家人", "同事", "同学", "恋爱", "感情", "交流", "沟通", 
                "相处", "关系", "社交", "聚会", "约会", "矛盾", "和解"],
    "健康运动": ["健康", "运动", "健身", "跑步", "游泳", "瑜伽", "减肥", "锻炼", 
                "饮食", "营养", "睡眠", "休息", "疾病", "治疗", "康复"],
    "旅游出行": ["旅行", "旅游", "出行", "度假", "景点", "风景", "拍照", "美食", 
                "住宿", "交通", "攻略", "打卡", "探索", "冒险", "文化"],
    "科技数码": ["科技", "数码", "手机", "电脑", "软件", "硬件", "游戏", "应用", 
                "AI", "人工智能", "编程", "开发", "互联网", "产品", "创新"],
    "美食烹饪": ["美食", "烹饪", "做饭", "烘焙", "餐厅", "菜品", "食材", "厨艺", 
                "品尝", "甜点", "饮品", "咖啡", "茶", "健康饮食", "食谱"],
    "艺术文化": ["艺术", "文化", "文学", "音乐", "绘画", "雕塑", "博物馆", "展览", 
                "历史", "传统", "戏剧", "电影", "表演", "创作", "欣赏"],
    "个人成长": ["成长", "学习", "进步", "目标", "挑战", "突破", "习惯", "自律", 
                "反思", "总结", "计划", "提升", "技能", "知识", "经验"]
}

# 惊喜模板
SURPRISE_TEMPLATES = {
    "话题推荐": [
        "对了，我记得你很喜欢{interest}，最近有什么新的进展或发现吗？",
        "突然想到，你之前提到过{interest}，不知道你最近怎么样了？",
        "我发现一个可能和你感兴趣的{interest}相关的话题，想和你分享一下！",
        "记得我们之前聊过{interest}，你对这个话题总是很有见解，想听听你现在的想法。",
        "看到一个关于{interest}的有趣内容，你应该会喜欢！",
        "你之前分享过关于{interest}的经历，让我印象深刻，想知道你最近还有没有新的体验？"
    ],
    "记忆回顾": [
        "突然想起我们之前聊到{memory}，那段对话真的很有趣！",
        "还记得我们第一次聊{memory}的时候吗？时间过得真快。",
        "回顾我们之前的对话，你提到的{memory}让我深受启发。",
        "我整理了一下我们之前关于{memory}的讨论，想和你分享一些有趣的发现。",
        "我一直在思考你之前说的关于{memory}的观点，真的很有见地。",
        "你之前分享的{memory}经历，我一直记在心里，很感谢你愿意告诉我这些。"
    ],
    "兴趣拓展": [
        "基于你对{interest}的兴趣，我觉得你可能也会对{related_interest}感兴趣！",
        "既然你喜欢{interest}，有没有尝试过{related_interest}？可能会给你不一样的体验。",
        "我发现{interest}和{related_interest}有很多相似之处，或许可以结合起来探索。",
        "作为{interest}爱好者，你可能想了解一下{related_interest}这个新兴领域。",
        "如果你喜欢{interest}，那么{related_interest}很可能也会引起你的兴趣。",
        "我一直在想，喜欢{interest}的人通常也会对{related_interest}感兴趣，你觉得呢？"
    ],
    "成就祝贺": [
        "恭喜你在{achievement}方面取得的进步！我一直相信你能做到。",
        "我注意到你在{achievement}上的努力和成果，真的很令人钦佩。",
        "还记得你之前设定的{achievement}目标吗？你现在已经走了这么远，太棒了！",
        "你在{achievement}方面的坚持真的很值得赞赏，继续加油！",
        "看到你在{achievement}上取得的成就，我感到非常高兴！",
        "你的{achievement}成果让我想起了你之前付出的努力，这一切都是值得的。"
    ],
    "鼓励支持": [
        "我知道你在{challenge}上遇到了一些困难，但我相信你一定能够克服。",
        "记得你之前成功处理过类似的{challenge}，这次也一样可以！",
        "面对{challenge}时，你的坚持和勇气真的很了不起。",
        "虽然{challenge}很困难，但我看到了你一直在进步，继续保持！",
        "你在{challenge}上的态度让我深受鼓舞，相信很快就能看到突破。",
        "每一个挑战都是成长的机会，我相信你一定能在{challenge}中收获满满。"
    ]
}

# 兴趣相关联映射（示例）
INTEREST_RELATED_MAPPING = {
    "电影": ["影评", "导演", "剧本", "电影史", "电影节"],
    "音乐": ["乐器", "乐理", "演唱会", "音乐制作", "音乐史"],
    "游戏": ["游戏设计", "电竞", "游戏开发", "游戏测评", "游戏音乐"],
    "阅读": ["写作", "文学创作", "书评", "作家", "出版业"],
    "工作": ["职业规划", "团队合作", "领导力", "时间管理", "工作效率"],
    "学习": ["学习方法", "知识管理", "记忆力训练", "专注力", "教育创新"],
    "旅行": ["摄影", "美食探索", "文化体验", "旅行规划", "背包客"],
    "运动": ["营养学", "健康生活", "运动科学", "比赛", "运动装备"],
    "美食": ["烹饪技巧", "食材知识", "饮食文化", "健康饮食", "美食摄影"],
    "编程": ["算法", "系统设计", "开源项目", "编程语言", "软件开发"],
    "健身": ["肌肉训练", "有氧运动", "营养补充", "健身计划", "身体塑形"],
    "摄影": ["后期处理", "摄影技巧", "器材知识", "摄影构图", "摄影史"]
}

# 惊喜历史存储目录
SURPRISE_HISTORY_DIR = Path(__file__).resolve().parents[2] / "data" / "surprise_history"

# 确保历史存储目录存在
def _ensure_history_dir_exists():
    """确保惊喜历史存储目录存在，如果不存在则创建"""
    try:
        if not SURPRISE_HISTORY_DIR.exists():
            SURPRISE_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            logger.info(f"创建惊喜历史存储目录: {SURPRISE_HISTORY_DIR}")
    except Exception as e:
        logger.error(f"创建惊喜历史存储目录时出错: {e}")

# 初始化目录
_ensure_history_dir_exists()

class SurpriseManager:
    """
    惊喜准备管理器，负责识别用户兴趣点、触发惊喜和生成惊喜内容
    """
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化惊喜管理器
        
        Args:
            config: 惊喜配置参数
        """
        self.config = config or DEFAULT_SURPRISE_CONFIG
        self._surprise_history = defaultdict(list)  # 用户惊喜历史
        self._user_interests = defaultdict(dict)  # 用户兴趣点
        self._user_special_dates = defaultdict(dict)  # 用户特殊日期
    
    def identify_user_interests(self, user_id: str) -> Dict[str, Any]:
        """
        识别用户的兴趣点和偏好
        
        Args:
            user_id: 用户ID
            
        Returns:
            Dict: 用户兴趣点信息
        """
        logger.info(f"识别用户 {user_id} 的兴趣点")
        
        # 获取记忆管理器
        memory_manager = get_weighted_memory_manager(user_id)
        
        # 获取高权重记忆
        high_weight_memories = memory_manager.get_weighted_memories(
            min_weight=self.config["interest_min_weight"],
            limit=100
        )
        
        # 分析记忆内容，识别兴趣点
        interest_counter = Counter()
        interest_categories = defaultdict(set)
        interest_memories = defaultdict(list)
        
        # 分析每个高权重记忆
        for memory in high_weight_memories:
            content = memory.get("content", "").lower()
            memory_weight = memory.get("weight", 1.0)
            
            # 检查是否包含兴趣分类关键词
            for category, keywords in INTEREST_CATEGORY_KEYWORDS.items():
                for keyword in keywords:
                    if keyword in content:
                        # 增加兴趣计数（加权）
                        interest_counter[keyword] += memory_weight
                        # 记录所属分类
                        interest_categories[keyword].add(category)
                        # 记录相关记忆
                        interest_memories[keyword].append(memory)
        
        # 过滤高频兴趣点
        filtered_interests = {}
        for interest, count in interest_counter.items():
            if count >= self.config["min_interest_occurrences"]:
                # 计算综合权重
                avg_weight = sum(m.get("weight", 1.0) for m in interest_memories[interest]) / len(interest_memories[interest])
                recency = max(m.get("timestamp", 0) for m in interest_memories[interest])
                recency_score = 1.0 - min((time.time() - recency) / (30 * 24 * 3600), 1.0)  # 30天内的记忆权重更高
                
                # 综合评分
                score = count * avg_weight * recency_score
                
                filtered_interests[interest] = {
                    "count": count,
                    "score": score,
                    "categories": list(interest_categories[interest]),
                    "memories": interest_memories[interest],
                    "last_occurrence": recency
                }
        
        # 更新用户兴趣点
        self._user_interests[user_id] = filtered_interests
        
        # 分析特殊日期
        self._analyze_special_dates(user_id, high_weight_memories)
        
        # 排序兴趣点
        sorted_interests = sorted(filtered_interests.items(), key=lambda x: x[1]["score"], reverse=True)
        
        return {
            "user_id": user_id,
            "interests": dict(sorted_interests[:20]),  # 返回前20个最高评分的兴趣点
            "total_interest_count": len(filtered_interests),
            "top_categories": self._get_top_categories(sorted_interests),
            "special_dates": self._user_special_dates.get(user_id, {}),
            "timestamp": time.time()
        }
    
    def _analyze_special_dates(self, user_id: str, memories: List[Dict[str, Any]]):
        """
        从记忆中分析用户的特殊日期
        
        Args:
            user_id: 用户ID
            memories: 记忆列表
        """
        special_dates = self._user_special_dates.get(user_id, {})
        
        # 分析每个记忆，查找特殊日期信息
        for memory in memories:
            content = memory.get("content", "").lower()
            
            # 检查生日关键词
            for keyword in SPECIAL_DATE_KEYWORDS["birthday"]:
                if keyword in content:
                    # 尝试提取日期（简单实现）
                    date_patterns = [
                        r'\d{1,2}月\d{1,2}日',  # 格式：X月X日
                        r'\d{4}-\d{1,2}-\d{1,2}',  # 格式：YYYY-MM-DD
                        r'\d{1,2}/\d{1,2}',  # 格式：MM/DD
                    ]
                    
                    for pattern in date_patterns:
                        matches = re.findall(pattern, content)
                        if matches:
                            special_dates["birthday"] = {
                                "date": matches[0],
                                "source_memory": memory.get("id"),
                                "discovered_at": time.time()
                            }
                            break
            
            # 检查纪念日关键词
            for keyword in SPECIAL_DATE_KEYWORDS["anniversary"]:
                if keyword in content:
                    # 尝试提取日期
                    date_patterns = [
                        r'\d{1,2}月\d{1,2}日',
                        r'\d{4}-\d{1,2}-\d{1,2}',
                        r'\d{1,2}/\d{1,2}',
                    ]
                    
                    for pattern in date_patterns:
                        matches = re.findall(pattern, content)
                        if matches:
                            special_dates["anniversary"] = {
                                "date": matches[0],
                                "source_memory": memory.get("id"),
                                "discovered_at": time.time()
                            }
                            break
        
        # 更新用户特殊日期
        self._user_special_dates[user_id] = special_dates
    
    def _get_top_categories(self, sorted_interests: List[Tuple[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        获取用户的顶级兴趣分类
        
        Args:
            sorted_interests: 排序后的兴趣点列表
            
        Returns:
            List[Dict]: 顶级分类列表
        """
        category_scores = defaultdict(float)
        
        # 统计每个分类的得分
        for interest, data in sorted_interests[:10]:  # 只考虑前10个兴趣点
            for category in data["categories"]:
                category_scores[category] += data["score"]
        
        # 排序并返回
        sorted_categories = sorted(category_scores.items(), key=lambda x: x[1], reverse=True)
        
        return [
            {
                "category": cat,
                "score": score,
                "rank": i + 1
            }
            for i, (cat, score) in enumerate(sorted_categories[:5])
        ]
    
    def should_trigger_surprise(self, user_id: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """
        判断是否应该触发惊喜
        
        Args:
            user_id: 用户ID
            context: 上下文信息（可选），包含情绪状态等
            
        Returns:
            bool: 是否触发惊喜
        """
        # 检查惊喜历史，避免过于频繁
        if not self._check_surprise_frequency(user_id):
            return False
        
        # 检查特殊日期
        if self._is_special_date(user_id):
            logger.info(f"特殊日期触发惊喜: {user_id}")
            return True
        
        # 检查情绪状态（如果提供）
        if context and "emotion" in context:
            emotion_data = context["emotion"]
            emotion = emotion_data.get("emotion")
            confidence = emotion_data.get("confidence", 0.0)
            
            # 对特定情绪触发惊喜
            if emotion in ["伤心", "焦虑", "疲惫"] and confidence >= self.config["emotion_threshold"]:
                logger.info(f"情绪状态触发惊喜: {user_id}, 情绪: {emotion}")
                return True
        
        # 随机触发
        if random.random() < self.config["random_surprise_probability"]:
            logger.info(f"随机触发惊喜: {user_id}")
            return True
        
        return False
    
    def _check_surprise_frequency(self, user_id: str) -> bool:
        """
        检查惊喜频率是否在限制范围内
        
        Args:
            user_id: 用户ID
            
        Returns:
            bool: 是否允许触发新的惊喜
        """
        # 获取用户的惊喜历史
        history = self._surprise_history.get(user_id, [])
        
        # 如果历史为空，允许触发
        if not history:
            return True
        
        # 检查本周的惊喜次数
        week_ago = time.time() - (7 * 24 * 3600)
        recent_surprises = [s for s in history if s["timestamp"] >= week_ago]
        
        if len(recent_surprises) >= self.config["max_surprise_frequency"]:
            logger.debug(f"用户 {user_id} 本周惊喜次数已达上限")
            return False
        
        return True
    
    def _is_special_date(self, user_id: str) -> bool:
        """
        检查今天是否是用户的特殊日期
        
        Args:
            user_id: 用户ID
            
        Returns:
            bool: 是否是特殊日期
        """
        special_dates = self._user_special_dates.get(user_id, {})
        today = datetime.now()
        
        # 检查生日
        if "birthday" in special_dates:
            birthday_info = special_dates["birthday"]
            birthday_str = birthday_info["date"]
            
            # 尝试解析生日（简化版）
            try:
                if "月" in birthday_str and "日" in birthday_str:
                    # 格式：X月X日
                    month_day_pattern = r'(\d{1,2})月(\d{1,2})日'
                    match = re.search(month_day_pattern, birthday_str)
                    if match:
                        month = int(match.group(1))
                        day = int(match.group(2))
                        if today.month == month and today.day == day:
                            return True
            except Exception as e:
                logger.debug(f"解析生日日期时出错: {e}")
        
        # 检查纪念日
        if "anniversary" in special_dates:
            anniversary_info = special_dates["anniversary"]
            anniversary_str = anniversary_info["date"]
            
            # 尝试解析纪念日（简化版）
            try:
                if "月" in anniversary_str and "日" in anniversary_str:
                    # 格式：X月X日
                    month_day_pattern = r'(\d{1,2})月(\d{1,2})日'
                    match = re.search(month_day_pattern, anniversary_str)
                    if match:
                        month = int(match.group(1))
                        day = int(match.group(2))
                        if today.month == month and today.day == day:
                            return True
            except Exception as e:
                logger.debug(f"解析纪念日日期时出错: {e}")
        
        return False
    
    def generate_surprise(self, user_id: str, context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        生成惊喜内容
        
        Args:
            user_id: 用户ID
            context: 上下文信息
            
        Returns:
            Optional[Dict]: 惊喜内容，如果不满足条件则返回None
        """
        # 首先确保我们有用户的兴趣点数据
        if user_id not in self._user_interests or not self._user_interests[user_id]:
            self.identify_user_interests(user_id)
        
        # 检查是否应该触发惊喜
        if not self.should_trigger_surprise(user_id, context):
            return None
        
        logger.info(f"为用户 {user_id} 生成惊喜内容")
        
        # 获取用户兴趣点
        interests = self._user_interests[user_id]
        
        # 如果没有足够的兴趣点，返回None
        if not interests:
            logger.warning(f"用户 {user_id} 没有足够的兴趣点数据")
            return None
        
        # 选择惊喜类型
        surprise_type = self._select_surprise_type(user_id, context)
        
        # 生成相应类型的惊喜
        if surprise_type == "话题推荐":
            surprise = self._generate_topic_recommendation(user_id, interests)
        elif surprise_type == "记忆回顾":
            surprise = self._generate_memory_review(user_id, interests)
        elif surprise_type == "兴趣拓展":
            surprise = self._generate_interest_expansion(user_id, interests)
        elif surprise_type == "成就祝贺":
            surprise = self._generate_achievement_congratulation(user_id, interests)
        elif surprise_type == "鼓励支持":
            surprise = self._generate_encouragement(user_id, context)
        else:
            # 默认使用话题推荐
            surprise = self._generate_topic_recommendation(user_id, interests)
        
        # 记录惊喜历史
        if surprise and self.config["save_surprise_history"]:
            self._record_surprise_history(user_id, surprise)
        
        return surprise
    
    def _select_surprise_type(self, user_id: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        选择合适的惊喜类型
        
        Args:
            user_id: 用户ID
            context: 上下文信息
            
        Returns:
            str: 惊喜类型
        """
        # 根据上下文选择
        if context and "emotion" in context:
            emotion = context["emotion"].get("emotion")
            
            # 对于负面情绪，优先选择鼓励支持
            if emotion in ["伤心", "焦虑", "疲惫"]:
                return "鼓励支持"
            # 对于正面情绪，可以选择成就祝贺或兴趣拓展
            elif emotion == "快乐":
                return random.choice(["成就祝贺", "兴趣拓展"])
        
        # 检查是否是特殊日期
        if self._is_special_date(user_id):
            return random.choice(["成就祝贺", "记忆回顾"])
        
        # 获取历史记录，避免重复同一类型
        history = self._surprise_history.get(user_id, [])
        recent_types = [s["type"] for s in history if time.time() - s["timestamp"] < 7 * 24 * 3600]
        
        # 计算各类型的权重
        type_weights = {}
        for surprise_type in self.config["surprise_categories"]:
            # 降低最近使用过的类型的权重
            if surprise_type in recent_types:
                weight = 0.5 / (recent_types.count(surprise_type) + 1)
            else:
                weight = 1.0
            
            # 为话题推荐增加基础权重
            if surprise_type == "话题推荐":
                weight *= 1.5
            
            type_weights[surprise_type] = weight
        
        # 根据权重选择
        types = list(type_weights.keys())
        weights = list(type_weights.values())
        
        # 归一化权重
        total_weight = sum(weights)
        normalized_weights = [w / total_weight for w in weights]
        
        return random.choices(types, weights=normalized_weights, k=1)[0]
    
    def _generate_topic_recommendation(self, user_id: str, interests: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        生成话题推荐惊喜
        
        Args:
            user_id: 用户ID
            interests: 用户兴趣点
            
        Returns:
            Dict: 惊喜内容
        """
        # 获取合适的兴趣点（排除最近使用过的）
        available_interests = self._get_available_interests(user_id, interests)
        
        if not available_interests:
            # 如果没有可用的兴趣点，使用最新的兴趣点
            sorted_interests = sorted(interests.items(), key=lambda x: x[1]["score"], reverse=True)
            if not sorted_interests:
                return None
            selected_interest, interest_data = sorted_interests[0]
        else:
            # 根据评分选择兴趣点
            selected_interest, interest_data = self._select_weighted_interest(available_interests)
        
        # 获取话题生成器
        topic_generator = get_topic_generator()
        
        # 生成相关话题
        topic_suggestions = topic_generator.generate_topics_around_interest(selected_interest, limit=3)
        
        # 选择一个模板
        templates = SURPRISE_TEMPLATES["话题推荐"]
        template = random.choice(templates)
        
        # 生成惊喜文本
        surprise_text = template.format(interest=selected_interest)
        
        # 如果有话题建议，添加到惊喜内容中
        if topic_suggestions:
            surprise_text += " " + random.choice(topic_suggestions)
        
        return {
            "type": "话题推荐",
            "text": surprise_text,
            "interest": selected_interest,
            "related_topics": topic_suggestions,
            "timestamp": time.time()
        }
    
    def _generate_memory_review(self, user_id: str, interests: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        生成记忆回顾惊喜
        
        Args:
            user_id: 用户ID
            interests: 用户兴趣点
            
        Returns:
            Dict: 惊喜内容
        """
        # 获取记忆管理器
        memory_manager = get_weighted_memory_manager(user_id)
        
        # 获取高权重但不是最新的记忆
        recent_time = time.time() - (7 * 24 * 3600)  # 一周前的记忆
        memories = memory_manager.get_weighted_memories(
            min_weight=self.config["interest_min_weight"] / 2,  # 较低的权重要求
            max_timestamp=recent_time,
            limit=50
        )
        
        if not memories:
            return None
        
        # 随机选择一个记忆
        selected_memory = random.choice(memories)
        memory_content = selected_memory.get("content", "")
        
        # 提取关键短语（简化版）
        key_phrases = []
        sentences = re.split(r'[。！？\.!?]', memory_content)
        for sentence in sentences:
            if len(sentence.strip()) > 5 and len(sentence.strip()) < 50:
                key_phrases.append(sentence.strip())
                break
        
        # 如果没有合适的短语，使用兴趣点
        if not key_phrases:
            for interest, data in interests.items():
                if interest in memory_content:
                    key_phrases = [interest]
                    break
        
        # 如果还是没有，使用记忆的前几个字
        if not key_phrases and len(memory_content) > 5:
            key_phrases = [memory_content[:20] + "..."]
        
        # 选择模板
        templates = SURPRISE_TEMPLATES["记忆回顾"]
        template = random.choice(templates)
        
        # 生成惊喜文本
        surprise_text = template.format(memory=key_phrases[0] if key_phrases else "之前的对话")
        
        return {
            "type": "记忆回顾",
            "text": surprise_text,
            "memory_id": selected_memory.get("id"),
            "timestamp": time.time()
        }
    
    def _generate_interest_expansion(self, user_id: str, interests: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        生成兴趣拓展惊喜
        
        Args:
            user_id: 用户ID
            interests: 用户兴趣点
            
        Returns:
            Dict: 惊喜内容
        """
        # 获取可用的兴趣点
        available_interests = self._get_available_interests(user_id, interests)
        
        if not available_interests:
            # 如果没有可用的兴趣点，使用最新的兴趣点
            sorted_interests = sorted(interests.items(), key=lambda x: x[1]["score"], reverse=True)
            if not sorted_interests:
                return None
            available_interests = dict(sorted_interests[:5])  # 使用前5个兴趣点
        
        # 选择一个兴趣点
        selected_interest, interest_data = self._select_weighted_interest(available_interests)
        
        # 查找相关兴趣
        related_interest = self._find_related_interest(selected_interest)
        
        if not related_interest:
            # 如果没有相关兴趣，返回话题推荐
            return self._generate_topic_recommendation(user_id, interests)
        
        # 选择模板
        templates = SURPRISE_TEMPLATES["兴趣拓展"]
        template = random.choice(templates)
        
        # 生成惊喜文本
        surprise_text = template.format(interest=selected_interest, related_interest=related_interest)
        
        return {
            "type": "兴趣拓展",
            "text": surprise_text,
            "base_interest": selected_interest,
            "related_interest": related_interest,
            "timestamp": time.time()
        }
    
    def _generate_achievement_congratulation(self, user_id: str, interests: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        生成成就祝贺惊喜
        
        Args:
            user_id: 用户ID
            interests: 用户兴趣点
            
        Returns:
            Dict: 惊喜内容
        """
        # 获取记忆管理器
        memory_manager = get_weighted_memory_manager(user_id)
        
        # 查找包含成就关键词的记忆
        achievement_keywords = ["成功", "完成", "实现", "达到", "突破", "获得", "通过", "拿到", "做到"]
        achievements = []
        
        for keyword in achievement_keywords:
            # 搜索包含关键词的记忆
            keyword_memories = memory_manager.search_memories(keyword, limit=10)
            achievements.extend(keyword_memories)
        
        # 按时间和权重排序
        achievements.sort(key=lambda x: (x.get("timestamp", 0), x.get("weight", 0)), reverse=True)
        
        if not achievements:
            # 如果没有找到成就相关的记忆，返回话题推荐
            return self._generate_topic_recommendation(user_id, interests)
        
        # 选择一个最近的成就记忆
        selected_memory = achievements[0]
        memory_content = selected_memory.get("content", "")
        
        # 提取成就相关的短语
        achievement_phrase = self._extract_achievement_phrase(memory_content)
        
        if not achievement_phrase:
            achievement_phrase = "你的成就"
        
        # 选择模板
        templates = SURPRISE_TEMPLATES["成就祝贺"]
        template = random.choice(templates)
        
        # 生成惊喜文本
        surprise_text = template.format(achievement=achievement_phrase)
        
        return {
            "type": "成就祝贺",
            "text": surprise_text,
            "achievement_memory_id": selected_memory.get("id"),
            "timestamp": time.time()
        }
    
    def _generate_encouragement(self, user_id: str, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        生成鼓励支持惊喜
        
        Args:
            user_id: 用户ID
            context: 上下文信息
            
        Returns:
            Dict: 惊喜内容
        """
        # 获取用户兴趣点
        interests = self._user_interests.get(user_id, {})
        
        # 从上下文或记忆中提取挑战相关信息
        challenge = "这个挑战"
        
        if context and "message" in context:
            message = context["message"]
            # 尝试从消息中提取挑战信息
            challenge_keywords = ["困难", "挑战", "压力", "累", "疲惫", "焦虑", "担心", "紧张", "害怕"]
            for keyword in challenge_keywords:
                if keyword in message:
                    # 提取包含关键词的短语
                    sentences = re.split(r'[。！？\.!?]', message)
                    for sentence in sentences:
                        if keyword in sentence and len(sentence.strip()) > 5:
                            challenge = sentence.strip()[:30] + "..." if len(sentence.strip()) > 30 else sentence.strip()
                            break
                    break
        
        # 如果没有从上下文中提取到挑战信息，使用用户的主要兴趣点
        if challenge == "这个挑战" and interests:
            sorted_interests = sorted(interests.items(), key=lambda x: x[1]["score"], reverse=True)
            if sorted_interests:
                challenge = sorted_interests[0][0]
        
        # 选择模板
        templates = SURPRISE_TEMPLATES["鼓励支持"]
        template = random.choice(templates)
        
        # 生成惊喜文本
        surprise_text = template.format(challenge=challenge)
        
        return {
            "type": "鼓励支持",
            "text": surprise_text,
            "context": context,
            "timestamp": time.time()
        }
    
    def _get_available_interests(self, user_id: str, interests: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        获取可用的兴趣点（排除最近使用过的）
        
        Args:
            user_id: 用户ID
            interests: 用户兴趣点
            
        Returns:
            Dict: 可用的兴趣点
        """
        # 获取最近使用过的兴趣点
        recent_time = time.time() - (self.config["interest_cooldown_days"] * 24 * 3600)
        used_interests = set()
        
        for surprise in self._surprise_history.get(user_id, []):
            if surprise["timestamp"] > recent_time:
                if "interest" in surprise:
                    used_interests.add(surprise["interest"])
                if "base_interest" in surprise:
                    used_interests.add(surprise["base_interest"])
        
        # 过滤出未使用的兴趣点
        available = {}
        for interest, data in interests.items():
            if interest not in used_interests:
                available[interest] = data
        
        return available
    
    def _select_weighted_interest(self, interests: Dict[str, Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
        """
        根据权重选择兴趣点
        
        Args:
            interests: 兴趣点字典
            
        Returns:
            Tuple[str, Dict]: 选择的兴趣点及其数据
        """
        if not interests:
            return None, None
        
        # 获取兴趣点和对应的权重
        interest_list = list(interests.keys())
        weights = [data["score"] for data in interests.values()]
        
        # 归一化权重
        total_weight = sum(weights)
        normalized_weights = [w / total_weight for w in weights]
        
        # 根据权重随机选择
        selected_interest = random.choices(interest_list, weights=normalized_weights, k=1)[0]
        
        return selected_interest, interests[selected_interest]
    
    def _find_related_interest(self, base_interest: str) -> Optional[str]:
        """
        查找相关的兴趣点
        
        Args:
            base_interest: 基础兴趣点
            
        Returns:
            Optional[str]: 相关兴趣点
        """
        # 直接查找映射
        if base_interest in INTEREST_RELATED_MAPPING:
            related_interests = INTEREST_RELATED_MAPPING[base_interest]
            return random.choice(related_interests)
        
        # 根据兴趣分类查找
        base_categories = []
        for interest, data in INTEREST_CATEGORY_KEYWORDS.items():
            if base_interest in data:
                base_categories.append(interest)
                break
        
        if base_categories:
            # 在相同分类中查找其他兴趣点
            category = base_categories[0]
            category_interests = INTEREST_CATEGORY_KEYWORDS[category]
            
            # 排除基础兴趣点
            available_interests = [i for i in category_interests if i != base_interest]
            
            if available_interests:
                return random.choice(available_interests)
        
        return None
    
    def _extract_achievement_phrase(self, text: str) -> Optional[str]:
        """
        从文本中提取成就相关的短语
        
        Args:
            text: 文本内容
            
        Returns:
            Optional[str]: 成就短语
        """
        # 成就关键词
        achievement_keywords = ["成功", "完成", "实现", "达到", "突破", "获得", "通过", "拿到", "做到"]
        
        for keyword in achievement_keywords:
            if keyword in text:
                # 提取包含关键词的句子
                sentences = re.split(r'[。！？\.!?]', text)
                for sentence in sentences:
                    if keyword in sentence and len(sentence.strip()) > 5:
                        # 提取关键词后的内容
                        keyword_pos = sentence.find(keyword)
                        phrase = sentence[keyword_pos:].strip()
                        
                        # 限制长度
                        if len(phrase) > 30:
                            phrase = phrase[:30] + "..."
                        
                        return phrase
        
        return None
    
    def _record_surprise_history(self, user_id: str, surprise: Dict[str, Any]):
        """
        记录惊喜历史
        
        Args:
            user_id: 用户ID
            surprise: 惊喜内容
        """
        # 添加到历史记录
        self._surprise_history[user_id].append(surprise)
        
        # 限制历史记录数量
        if len(self._surprise_history[user_id]) > self.config["max_history_size"]:
            self._surprise_history[user_id] = self._surprise_history[user_id][-self.config["max_history_size"]:]
        
        # 定期保存历史记录
        if random.random() < 0.2:  # 20%的概率保存
            self._save_surprise_history(user_id)
    
    def _save_surprise_history(self, user_id: str):
        """
        保存惊喜历史到文件
        
        Args:
            user_id: 用户ID
        """
        try:
            file_path = SURPRISE_HISTORY_DIR / f"{user_id}_surprises.json"
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self._surprise_history[user_id], f, ensure_ascii=False, indent=2)
            
            logger.debug(f"已保存用户 {user_id} 的惊喜历史到 {file_path}")
            
        except Exception as e:
            logger.error(f"保存惊喜历史时出错: {e}")
    
    def _load_surprise_history(self, user_id: str):
        """
        从文件加载惊喜历史
        
        Args:
            user_id: 用户ID
        """
        try:
            file_path = SURPRISE_HISTORY_DIR / f"{user_id}_surprises.json"
            
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    self._surprise_history[user_id] = json.load(f)
                
                logger.debug(f"已加载用户 {user_id} 的惊喜历史")
                
        except Exception as e:
            logger.error(f"加载惊喜历史时出错: {e}")
    
    def get_surprise_summary(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户的惊喜统计摘要
        
        Args:
            user_id: 用户ID
            
        Returns:
            Dict: 惊喜统计摘要
        """
        # 如果没有历史记录，尝试加载
        if user_id not in self._surprise_history:
            self._load_surprise_history(user_id)
        
        # 获取历史记录
        history = self._surprise_history.get(user_id, [])
        
        # 统计各类型的惊喜数量
        type_counter = Counter()
        interest_counter = Counter()
        
        for surprise in history:
            type_counter[surprise.get("type", "未知")] += 1
            
            # 统计兴趣点
            if "interest" in surprise:
                interest_counter[surprise["interest"]] += 1
            if "base_interest" in surprise:
                interest_counter[surprise["base_interest"]] += 1
        
        # 获取最近的惊喜
        recent_surprises = sorted(history, key=lambda x: x.get("timestamp", 0), reverse=True)[:5]
        
        # 计算每周平均惊喜次数
        if history:
            oldest_time = min(s["timestamp"] for s in history)
            days_passed = (time.time() - oldest_time) / (24 * 3600)
            weeks_passed = max(days_passed / 7, 1)
            avg_per_week = len(history) / weeks_passed
        else:
            avg_per_week = 0
        
        return {
            "user_id": user_id,
            "total_surprises": len(history),
            "type_distribution": dict(type_counter),
            "top_interests": dict(interest_counter.most_common(5)),
            "recent_surprises": recent_surprises,
            "average_per_week": round(avg_per_week, 2),
            "last_surprise_time": max(s["timestamp"] for s in history) if history else None,
            "timestamp": time.time()
        }
    
    def update_config(self, new_config: Dict[str, Any]):
        """
        更新配置
        
        Args:
            new_config: 新的配置参数
        """
        self.config.update(new_config)
        logger.info(f"惊喜管理器配置已更新: {new_config}")
    
    def process_user_context(self, user_id: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        处理用户上下文，判断是否生成惊喜
        
        Args:
            user_id: 用户ID
            context: 上下文信息，包含消息、情绪状态等
            
        Returns:
            Optional[Dict]: 惊喜内容，如果不满足条件则返回None
        """
        # 确保我们有用户的兴趣点数据
        if user_id not in self._user_interests or not self._user_interests[user_id]:
            self.identify_user_interests(user_id)
        
        # 生成惊喜
        surprise = self.generate_surprise(user_id, context)
        
        if surprise:
            logger.info(f"成功为用户 {user_id} 生成惊喜: {surprise['type']}")
        
        return surprise

# 创建全局惊喜管理器实例
global_surprise_manager = None

def get_surprise_manager() -> SurpriseManager:
    """
    获取全局惊喜管理器实例
    
    Returns:
        SurpriseManager: 惊喜管理器实例
    """
    global global_surprise_manager
    
    if global_surprise_manager is None:
        global_surprise_manager = SurpriseManager()
    
    return global_surprise_manager

# 便捷函数
def identify_interests(user_id: str) -> Dict[str, Any]:
    """
    便捷函数：识别用户兴趣点
    """
    manager = get_surprise_manager()
    return manager.identify_user_interests(user_id)

def generate_surprise_for_user(user_id: str, context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    便捷函数：为用户生成惊喜
    """
    manager = get_surprise_manager()
    return manager.generate_surprise(user_id, context)

def process_user_for_surprise(user_id: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    便捷函数：处理用户上下文并生成惊喜
    """
    manager = get_surprise_manager()
    return manager.process_user_context(user_id, context)

def get_surprise_statistics(user_id: str) -> Dict[str, Any]:
    """
    便捷函数：获取用户的惊喜统计信息
    """
    manager = get_surprise_manager()
    return manager.get_surprise_summary(user_id)