#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能话题生成系统

该模块基于记忆权重数据，在AI主动发起对话时优先选择权重较高的话题作为聊天切入点
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

# 导入记忆管理器
from .weighted_memory_manager import get_weighted_memory_manager

# 配置日志
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_TOPIC_CONFIG = {
    "max_topics_to_suggest": 5,         # 最大建议话题数量
    "min_weight_threshold": 1.0,        # 最小权重阈值
    "min_memory_count": 2,              # 话题相关的最小记忆数量
    "freshness_weight": 0.3,            # 新鲜度权重 (最近的记忆优先级更高)
    "topic_diversity": True,            # 是否启用话题多样性
    "max_topics_per_category": 3,       # 每个分类最多选择的话题数量
    "time_decay_factor": 0.05,          # 时间衰减因子
    "use_topic_categories": True,       # 是否使用话题分类
    "exclude_recent_topics": True,      # 是否排除最近讨论过的话题
    "recent_window_days": 3             # 最近话题的时间窗口（天）
}

# 话题分类映射
TOPIC_CATEGORIES = {
    "技术": ["编程", "代码", "软件", "算法", "开发", "项目", "架构", "框架", "Python", "Java", "C++"],
    "生活": ["吃饭", "睡觉", "旅游", "购物", "电影", "音乐", "运动", "健康", "美食", "旅行", "阅读"],
    "工作": ["会议", "报告", "任务", "截止日期", "同事", "客户", "公司", "老板", "项目", "团队", "目标"],
    "学习": ["考试", "作业", "书籍", "课程", "学校", "成绩", "老师", "学生", "学习方法", "知识点"],
    "娱乐": ["游戏", "视频", "直播", "社交媒体", "明星", "综艺", "动漫", "小说", "电影", "音乐"],
    "情感": ["开心", "伤心", "生气", "难过", "高兴", "喜欢", "讨厌", "爱", "友情", "亲情", "爱情"],
    "天气": ["下雨", "晴天", "温度", "气候", "季节", "台风", "雪", "炎热", "寒冷", "凉爽"],
    "健康": ["身体", "生病", "医院", "医生", "药物", "锻炼", "饮食", "休息", "睡眠", "压力"],
    "科技": ["手机", "电脑", "AI", "人工智能", "机器人", "互联网", "5G", "区块链", "元宇宙"],
    "兴趣爱好": ["摄影", "绘画", "烹饪", "手工", "钓鱼", "瑜伽", "健身", "舞蹈", "乐器", "写作"],
    "新闻时事": ["新闻", "政治", "经济", "社会", "国际", "政策", "事件", "热点"],
    "其他": []  # 未分类话题
}

# 话题建议模板
TOPIC_SUGGESTION_TEMPLATES = [
    "你之前提到过{topic}，我很感兴趣，能多聊聊这个吗？",
    "最近有没有继续关注{topic}？",
    "我记得你对{topic}很感兴趣，有什么新的发现吗？",
    "关于{topic}，我有一些新的想法想和你分享。",
    "你之前分享的关于{topic}的内容很有意思，还能详细说说吗？",
    "不知道为什么，突然想到你之前提到过的{topic}。",
    "最近我看到了一些关于{topic}的信息，可能你会感兴趣。",
    "{topic}这个话题，你有什么特别的见解吗？",
    "我注意到你对{topic}似乎很有研究，能给我普及一下吗？",
    "我们很久没聊{topic}了，最近有什么新进展吗？"
]

class TopicGenerator:
    """
    智能话题生成器，负责基于记忆权重生成适合的聊天话题
    """
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化话题生成器
        
        Args:
            config: 话题生成配置参数
        """
        self.config = config or DEFAULT_TOPIC_CONFIG
        self._recent_topics_cache = defaultdict(list)  # 缓存最近讨论的话题
    
    def generate_topics(self, user_id: str, count: int = None, context: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        生成话题建议
        
        Args:
            user_id: 用户ID
            count: 需要生成的话题数量，默认为配置中的max_topics_to_suggest
            context: 当前上下文，用于优化话题建议
            
        Returns:
            List[Dict]: 话题建议列表，每项包含话题名称、相关记忆、权重和建议文本
        """
        logger.info(f"为用户 {user_id} 生成话题建议，请求数量: {count}")
        
        # 使用配置的数量或默认值
        if count is None:
            count = self.config["max_topics_to_suggest"]
        else:
            count = min(count, self.config["max_topics_to_suggest"])  # 限制最大数量
        
        # 获取记忆管理器实例
        manager = get_weighted_memory_manager(user_id)
        
        # 获取所有有权重的记忆
        all_memories = manager.get_weighted_memories(limit=200)  # 获取最近的200条记忆
        
        # 过滤低权重记忆
        min_weight = self.config["min_weight_threshold"]
        weighted_memories = [m for m in all_memories if m.get("weight", 0) >= min_weight]
        
        logger.info(f"用户 {user_id} 共有 {len(weighted_memories)} 条满足权重阈值的记忆")
        
        # 从记忆中提取话题并计算话题权重
        topic_scores = self._calculate_topic_scores(weighted_memories)
        
        # 获取最近讨论过的话题
        recent_topics = []
        if self.config["exclude_recent_topics"]:
            recent_topics = self._get_recent_topics(user_id)
        
        # 过滤最近讨论过的话题
        filtered_topics = [(topic, score) for topic, score in topic_scores.items() 
                          if topic not in recent_topics or len(topic_scores) <= count]
        
        # 按分数排序
        filtered_topics.sort(key=lambda x: x[1], reverse=True)
        
        # 如果启用了话题分类，按分类优化选择
        if self.config["use_topic_categories"]:
            selected_topics = self._select_topics_by_category(filtered_topics, count)
        else:
            selected_topics = [t for t, _ in filtered_topics[:count]]
        
        # 生成话题建议
        topic_suggestions = []
        for topic in selected_topics:
            # 获取与话题相关的记忆
            topic_memories = manager.get_weighted_memories(topics=[topic], limit=5)
            
            # 计算话题的综合分数
            total_weight = sum(m.get("weight", 0) for m in topic_memories)
            avg_weight = total_weight / len(topic_memories) if topic_memories else 0
            
            # 生成建议文本
            suggestion_text = self._generate_suggestion_text(topic, topic_memories)
            
            # 获取话题分类
            category = self._categorize_topic(topic)
            
            # 创建话题建议对象
            topic_suggestions.append({
                "topic": topic,
                "category": category,
                "score": topic_scores.get(topic, 0),
                "average_weight": avg_weight,
                "memory_count": len(topic_memories),
                "memories": topic_memories[:3],  # 保留前3个最相关的记忆
                "suggestion_text": suggestion_text,
                "timestamp": time.time()
            })
        
        logger.info(f"为用户 {user_id} 生成了 {len(topic_suggestions)} 个话题建议")
        
        return topic_suggestions
    
    def _calculate_topic_scores(self, memories: List[Dict[str, Any]]) -> Dict[str, float]:
        """
        计算每个话题的综合分数
        
        Args:
            memories: 记忆列表
            
        Returns:
            Dict[str, float]: 话题分数映射
        """
        topic_scores = defaultdict(float)
        topic_memory_count = defaultdict(int)
        topic_categories = defaultdict(set)
        
        # 计算当前时间戳
        now = time.time()
        
        # 遍历所有记忆，统计话题
        for memory in memories:
            topics = memory.get("topics", [])
            memory_weight = memory.get("weight", 0)
            memory_time = memory.get("timestamp", now)
            
            # 计算时间权重（越新的记忆权重越高）
            time_diff_days = (now - memory_time) / (60 * 60 * 24)  # 转换为天
            time_weight = 1 / (1 + self.config["time_decay_factor"] * time_diff_days)
            
            # 应用新鲜度权重
            freshness_factor = 1 + (self.config["freshness_weight"] * (1 - time_weight))
            
            # 更新话题分数
            for topic in topics:
                topic_scores[topic] += memory_weight * freshness_factor
                topic_memory_count[topic] += 1
                
                # 记录话题分类
                category = self._categorize_topic(topic)
                topic_categories[topic].add(category)
        
        # 过滤记忆数量不足的话题
        filtered_scores = {}
        for topic, score in topic_scores.items():
            if topic_memory_count[topic] >= self.config["min_memory_count"]:
                # 考虑记忆数量的加权
                count_factor = min(1.0 + (topic_memory_count[topic] * 0.1), 2.0)  # 最多翻倍
                filtered_scores[topic] = score * count_factor
        
        return dict(filtered_scores)
    
    def _categorize_topic(self, topic: str) -> str:
        """
        将话题归类到预定义的类别
        
        Args:
            topic: 话题名称
            
        Returns:
            str: 话题类别
        """
        topic_lower = topic.lower()
        
        for category, keywords in TOPIC_CATEGORIES.items():
            for keyword in keywords:
                if keyword.lower() in topic_lower:
                    return category
        
        return "其他"
    
    def _select_topics_by_category(self, topic_list: List[Tuple[str, float]], count: int) -> List[str]:
        """
        按分类选择话题，确保多样性
        
        Args:
            topic_list: 排序后的话题列表 [(topic, score), ...]
            count: 需要选择的话题数量
            
        Returns:
            List[str]: 选择的话题列表
        """
        selected_topics = []
        category_count = defaultdict(int)
        max_per_category = self.config["max_topics_per_category"]
        
        # 优先选择高分话题，但限制每个类别的数量
        for topic, _ in topic_list:
            if len(selected_topics) >= count:
                break
                
            category = self._categorize_topic(topic)
            
            # 如果该类别还未达到最大数量，则选择该话题
            if category_count.get(category, 0) < max_per_category:
                selected_topics.append(topic)
                category_count[category] += 1
        
        # 如果还没选够数量，放宽限制继续选择
        if len(selected_topics) < count:
            for topic, _ in topic_list:
                if len(selected_topics) >= count:
                    break
                    
                if topic not in selected_topics:
                    selected_topics.append(topic)
        
        return selected_topics
    
    def _generate_suggestion_text(self, topic: str, memories: List[Dict[str, Any]]) -> str:
        """
        为话题生成建议文本
        
        Args:
            topic: 话题名称
            memories: 与话题相关的记忆列表
            
        Returns:
            str: 建议文本
        """
        # 选择一个随机模板
        template = random.choice(TOPIC_SUGGESTION_TEMPLATES)
        
        # 如果有相关记忆，可以基于记忆内容优化建议文本
        if memories:
            # 找到权重最高的记忆
            top_memory = max(memories, key=lambda x: x.get("weight", 0))
            
            # 从记忆中提取关键信息（简单实现）
            content = top_memory.get("content", "")
            
            # 如果内容较长，截取前一部分作为提示
            if len(content) > 20:
                hint = f"（我记得你提到过：{content[:20]}...）"
                return template.format(topic=topic) + hint
        
        return template.format(topic=topic)
    
    def _get_recent_topics(self, user_id: str) -> Set[str]:
        """
        获取用户最近讨论过的话题
        
        Args:
            user_id: 用户ID
            
        Returns:
            Set[str]: 最近讨论的话题集合
        """
        recent_topics = set()
        window_days = self.config["recent_window_days"]
        window_seconds = window_days * 24 * 60 * 60
        now = time.time()
        
        # 获取记忆管理器实例
        manager = get_weighted_memory_manager(user_id)
        
        # 从最近的记忆中提取话题
        recent_memories = manager.get_weighted_memories(limit=100)
        
        for memory in recent_memories:
            memory_time = memory.get("timestamp", 0)
            
            # 如果记忆在时间窗口内
            if now - memory_time <= window_seconds:
                topics = memory.get("topics", [])
                recent_topics.update(topics)
        
        # 从缓存中获取（如果有）
        cached_topics = self._recent_topics_cache.get(user_id, [])
        valid_cached = [(t, ts) for t, ts in cached_topics if now - ts <= window_seconds]
        recent_topics.update(t[0] for t in valid_cached)
        
        # 更新缓存
        self._recent_topics_cache[user_id] = valid_cached
        
        return recent_topics
    
    def mark_topic_as_used(self, user_id: str, topic: str):
        """
        标记话题为已使用，避免短期内重复推荐
        
        Args:
            user_id: 用户ID
            topic: 已使用的话题
        """
        now = time.time()
        
        # 将话题添加到缓存
        self._recent_topics_cache[user_id].append((topic, now))
        
        # 清理过期缓存
        window_days = self.config["recent_window_days"]
        window_seconds = window_days * 24 * 60 * 60
        self._recent_topics_cache[user_id] = [(t, ts) for t, ts in self._recent_topics_cache[user_id] 
                                            if now - ts <= window_seconds]
    
    def get_contextual_topics(self, user_id: str, context_text: str, count: int = 3) -> List[Dict[str, Any]]:
        """
        基于上下文文本生成相关话题建议
        
        Args:
            user_id: 用户ID
            context_text: 上下文文本
            count: 需要生成的话题数量
            
        Returns:
            List[Dict]: 话题建议列表
        """
        logger.info(f"为用户 {user_id} 基于上下文生成话题建议")
        
        # 从上下文提取关键词
        context_keywords = self._extract_keywords(context_text)
        
        # 获取记忆管理器实例
        manager = get_weighted_memory_manager(user_id)
        
        # 查找与关键词相关的记忆
        related_memories = []
        
        for keyword in context_keywords[:5]:  # 使用前5个关键词
            memories = manager.get_weighted_memories(keywords=[keyword], limit=10)
            related_memories.extend(memories)
        
        # 去重（基于记忆ID）
        unique_memories = {}
        for mem in related_memories:
            mem_id = mem.get("id", None)
            if mem_id and mem_id not in unique_memories:
                unique_memories[mem_id] = mem
        
        related_memories = list(unique_memories.values())
        
        logger.info(f"找到 {len(related_memories)} 条与上下文相关的记忆")
        
        # 如果没有相关记忆，返回常规话题建议
        if not related_memories:
            return self.generate_topics(user_id, count=count)
        
        # 基于相关记忆生成话题
        topic_scores = self._calculate_topic_scores(related_memories)
        
        # 排序并选择话题
        sorted_topics = sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)
        selected_topics = [t for t, _ in sorted_topics[:count]]
        
        # 生成话题建议
        topic_suggestions = []
        for topic in selected_topics:
            topic_memories = manager.get_weighted_memories(topics=[topic], limit=3)
            
            # 计算平均权重
            total_weight = sum(m.get("weight", 0) for m in topic_memories)
            avg_weight = total_weight / len(topic_memories) if topic_memories else 0
            
            # 生成建议文本
            suggestion_text = self._generate_suggestion_text(topic, topic_memories)
            
            # 获取话题分类
            category = self._categorize_topic(topic)
            
            topic_suggestions.append({
                "topic": topic,
                "category": category,
                "score": topic_scores.get(topic, 0),
                "average_weight": avg_weight,
                "memory_count": len(topic_memories),
                "memories": topic_memories[:2],
                "suggestion_text": suggestion_text,
                "timestamp": time.time(),
                "context_related": True
            })
        
        return topic_suggestions
    
    def _extract_keywords(self, text: str) -> List[str]:
        """
        从文本中提取关键词
        
        Args:
            text: 输入文本
            
        Returns:
            List[str]: 关键词列表
        """
        # 简单的关键词提取实现
        # 1. 移除标点符号
        text = re.sub(r'[\s\n\t\r\,\.\!\?\;\:\"\'\(\)\[\]\{\}]', ' ', text)
        
        # 2. 分词
        words = text.split()
        
        # 3. 过滤停用词（简单实现）
        stop_words = {
            "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也", "很", "到", "说", "要", 
            "去", "你", "会", "着", "没有", "看", "好", "自己", "这", "我", "你", "他", "她", "它", "们", "这", "那", 
            "and", "or", "but", "the", "a", "an", "in", "on", "at", "to", "of", "for", "with", "by", "from", "is", "are", 
            "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should"
        }
        
        keywords = [word for word in words if word.lower() not in stop_words and len(word) > 1]
        
        # 4. 去重并返回前10个关键词
        return list(dict.fromkeys(keywords))[:10]
    
    def update_config(self, new_config: Dict[str, Any]):
        """
        更新配置
        
        Args:
            new_config: 新的配置参数
        """
        self.config.update(new_config)
        logger.info(f"话题生成器配置已更新: {new_config}")
    
    def get_topic_statistics(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户的话题统计信息
        
        Args:
            user_id: 用户ID
            
        Returns:
            Dict: 话题统计信息
        """
        # 获取记忆管理器实例
        manager = get_weighted_memory_manager(user_id)
        
        # 获取所有有话题的记忆
        all_memories = manager.get_weighted_memories(limit=200)
        
        # 统计话题
        topic_counter = Counter()
        category_counter = Counter()
        topic_weights = defaultdict(float)
        topic_memory_count = defaultdict(int)
        
        for memory in all_memories:
            topics = memory.get("topics", [])
            memory_weight = memory.get("weight", 0)
            
            for topic in topics:
                topic_counter[topic] += 1
                topic_weights[topic] += memory_weight
                topic_memory_count[topic] += 1
                
                # 统计分类
                category = self._categorize_topic(topic)
                category_counter[category] += 1
        
        # 计算平均权重
        avg_topic_weights = {topic: topic_weights[topic] / topic_memory_count[topic] 
                           for topic in topic_memory_count}
        
        # 获取前10个热门话题
        top_topics = topic_counter.most_common(10)
        
        return {
            "total_topics": len(topic_counter),
            "total_categories": len(category_counter),
            "top_topics": top_topics,
            "category_distribution": dict(category_counter),
            "topic_weights": dict(avg_topic_weights),
            "timestamp": time.time()
        }

# 创建全局话题生成器实例
global_topic_generator = None

def get_topic_generator() -> TopicGenerator:
    """
    获取全局话题生成器实例
    
    Returns:
        TopicGenerator: 话题生成器实例
    """
    global global_topic_generator
    
    if global_topic_generator is None:
        global_topic_generator = TopicGenerator()
    
    return global_topic_generator

# 便捷函数
def generate_conversation_topics(user_id: str, count: int = None) -> List[Dict[str, Any]]:
    """
    便捷函数：为用户生成聊天话题建议
    """
    generator = get_topic_generator()
    return generator.generate_topics(user_id, count)

def generate_contextual_topics(user_id: str, context: str, count: int = 3) -> List[Dict[str, Any]]:
    """
    便捷函数：基于上下文生成话题建议
    """
    generator = get_topic_generator()
    return generator.get_contextual_topics(user_id, context, count)

def mark_topic_as_discussed(user_id: str, topic: str):
    """
    便捷函数：标记话题为已讨论
    """
    generator = get_topic_generator()
    generator.mark_topic_as_used(user_id, topic)

def get_user_topic_statistics(user_id: str) -> Dict[str, Any]:
    """
    便捷函数：获取用户话题统计
    """
    generator = get_topic_generator()
    return generator.get_topic_statistics(user_id)