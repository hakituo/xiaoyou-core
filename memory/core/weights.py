# Memory Weights Module

from typing import Dict, List
import time
import logging

logger = logging.getLogger(__name__)

# 默认权重配置
DEFAULT_WEIGHT_CONFIG = {
    "base_weight": 1.0,            # 基础权重
    "importance_multiplier": 3.0,  # 重要性权重倍数
    "recency_decay_factor": 0.9,   # 时间衰减因子
    "topic_frequency_bonus": 0.5,  # 话题频率奖励
    "emotion_relevance_bonus": 0.8  # 情绪相关奖励
}

class MemoryWeightCalculator:
    """
    记忆权重计算器，负责计算和调整记忆权重
    """
    def __init__(self, config: Dict[str, float] = None):
        """
        初始化权重计算器
        
        Args:
            config: 权重计算配置参数
        """
        self.config = config or DEFAULT_WEIGHT_CONFIG.copy()
    
    def calculate_initial_weight(self, content: str, is_important: bool = False, 
                                topics: List[str] = None, emotions: List[str] = None) -> float:
        """
        计算记忆的初始权重
        
        Args:
            content: 记忆内容
            is_important: 是否重要记忆
            topics: 关联的话题列表
            emotions: 关联的情绪列表
            
        Returns:
            float: 计算后的权重值
        """
        # 基础权重
        weight = self.config["base_weight"]
        
        # 重要性权重
        if is_important:
            weight *= self.config["importance_multiplier"]
        
        # 话题多样性奖励（话题越多，权重越高）
        if topics and len(topics) > 0:
            topic_bonus = min(len(topics) * self.config["topic_frequency_bonus"], 5.0)
            weight += topic_bonus
        
        # 情绪相关奖励
        if emotions and len(emotions) > 0:
            emotion_bonus = min(len(emotions) * self.config["emotion_relevance_bonus"], 3.0)
            weight += emotion_bonus
        
        return round(weight, 2)
    
    def apply_time_decay(self, weight: float, timestamp: float) -> float:
        """
        应用时间衰减因子
        
        Args:
            weight: 当前权重
            timestamp: 记忆创建时间戳
            
        Returns:
            float: 衰减后的权重
        """
        now = time.time()
        hours_passed = (now - timestamp) / 3600  # 转换为小时
        
        # 计算衰减天数
        days_passed = hours_passed / 24
        
        # 应用衰减因子（每天衰减）
        decay_factor = self.config["recency_decay_factor"] ** days_passed
        
        # 权重不会低于基础权重的10%
        min_weight = self.config["base_weight"] * 0.1
        
        return max(round(weight * decay_factor, 2), min_weight)
    
    def update_weight_by_access(self, current_weight: float, importance: int = 1) -> float:
        """
        基于访问更新权重
        
        Args:
            current_weight: 当前权重
            importance: 访问的重要性级别（1-5）
            
        Returns:
            float: 更新后的权重
        """
        # 根据重要性增加权重
        importance_factor = importance * 0.2
        
        # 防止权重无限增长
        max_weight = 20.0
        new_weight = min(current_weight + importance_factor, max_weight)
        
        return round(new_weight, 2)
    
    def update_config(self, new_config: Dict[str, float]):
        """
        更新配置参数
        
        Args:
            new_config: 新的配置参数
        """
        self.config.update(new_config)
        logger.info(f"权重计算器配置已更新: {new_config}")
