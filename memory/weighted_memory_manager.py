#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版记忆管理器 - 带权重管理功能

该模块实现了记忆权重管理系统，能够对不同话题、事件和交互内容进行量化加权处理
"""

import json
import os
import time
import threading
import logging
import uuid
import re
from typing import List, Dict, Any, Optional, Union, Tuple, Set
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict, deque
import hashlib

# 导入向量嵌入生成模块
try:
    from .embedding_generator import embedding_generator
    VECTOR_SEARCH_ENABLED = True
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("未找到向量嵌入生成模块，向量搜索功能将被禁用")
    VECTOR_SEARCH_ENABLED = False

# 导入基础类
from .enhanced_memory_manager import EnhancedMemoryManager

from config.integrated_config import get_settings

# 配置日志
logger = logging.getLogger(__name__)

# 默认配置常量
DEFAULT_MAX_SHORT_TERM = 10  # 短期记忆最大长度
DEFAULT_MAX_LONG_TERM = 1000  # 长期记忆最大长度
DEFAULT_AUTO_SAVE_INTERVAL = 300  # 自动保存间隔（秒）
MAX_LENGTH_MIN = 1
MAX_LENGTH_MAX = 10000
DEFAULT_COMPACT_FORMAT = True
DEFAULT_ENCODING = 'utf-8'

# 默认权重配置
DEFAULT_WEIGHT_CONFIG = {
    "base_weight": 1.0,            # 基础权重
    "importance_multiplier": 3.0,  # 重要性权重倍数
    "recency_decay_factor": 0.9,   # 时间衰减因子
    "topic_frequency_bonus": 0.5,  # 话题频率奖励
    "emotion_relevance_bonus": 0.8  # 情绪相关奖励
}

# 使用配置目录路径
settings = get_settings()
HISTORY_DIR = Path(settings.memory.history_dir)
if not HISTORY_DIR.is_absolute():
    HISTORY_DIR = Path(os.getcwd()) / HISTORY_DIR

LONG_TERM_DIR = HISTORY_DIR / "long_term"
WEIGHTED_MEMORY_DIR = HISTORY_DIR / "weighted"

# 确保历史记录目录存在
def _ensure_history_dir_exists():
    """确保历史记录目录存在，如果不存在则创建"""
    try:
        if not HISTORY_DIR.exists():
            HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            logger.info(f"创建历史记录目录: {HISTORY_DIR}")
        
        if not LONG_TERM_DIR.exists():
            LONG_TERM_DIR.mkdir(parents=True, exist_ok=True)
            logger.info(f"创建长期记忆目录: {LONG_TERM_DIR}")
            
        if not WEIGHTED_MEMORY_DIR.exists():
            WEIGHTED_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            logger.info(f"创建权重记忆目录: {WEIGHTED_MEMORY_DIR}")
    except Exception as e:
        logger.error(f"创建历史记录目录时出错: {e}")

# 初始化历史记录目录
_ensure_history_dir_exists()

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
        self.config = config or DEFAULT_WEIGHT_CONFIG
    
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

class WeightedMemoryManager(EnhancedMemoryManager):
    """
    带权重管理的增强版记忆管理器
    """
    def __init__(self, user_id: str = "default",
                 max_short_term: int = DEFAULT_MAX_SHORT_TERM,
                 max_long_term: int = DEFAULT_MAX_LONG_TERM,
                 auto_save_interval: int = DEFAULT_AUTO_SAVE_INTERVAL,
                 weight_config: Dict[str, float] = None,
                 skip_auto_reclassify: bool = False):
        """
        初始化带权重管理的记忆管理器
        
        Args:
            user_id: 用户ID，用于保存/加载记忆
            max_short_term: 短期记忆最大条数
            max_long_term: 长期记忆最大条数
            auto_save_interval: 自动保存间隔（秒）
            weight_config: 权重配置参数
            skip_auto_reclassify: 是否跳过自动重分类（用于只读模式）
        """
        self.skip_auto_reclassify = skip_auto_reclassify
        
        # 初始化父类
        super().__init__(user_id, max_short_term, max_long_term, auto_save_interval)
        
        # 初始化权重计算器
        self.weight_calculator = MemoryWeightCalculator(weight_config)
        
        # 扩展数据结构
        self.weighted_memories: Dict[str, Dict[str, Any]] = {}  # 按ID索引的权重记忆
        self.topic_weights: Dict[str, float] = defaultdict(float)  # 话题权重映射
        self.emotion_memory_map: Dict[str, List[Dict[str, Any]]] = defaultdict(list)  # 情绪-记忆映射
        
        # 加载权重数据
        self._load_weighted_data()
    
    def add_memory(self, content: str, topics: List[str] = None, emotions: List[str] = None,
                   is_important: bool = False, source: str = "chat") -> str:
        """
        添加带权重的记忆
        
        Args:
            content: 记忆内容
            topics: 关联的话题列表
            emotions: 关联的情绪列表
            is_important: 是否重要记忆
            source: 记忆来源
            
        Returns:
            str: 记忆ID
        """
        with self.lock:
            # 生成唯一ID
            memory_id = str(uuid.uuid4())
            
            # 检测话题（如果未提供）
            if topics is None:
                topics = self._detect_topics(content)
                
            # 检测情感（如果未提供）
            if emotions is None:
                emotions = [self._detect_emotion(content)]
            
            # 计算初始权重
            weight = self.weight_calculator.calculate_initial_weight(
                content, is_important, topics, emotions
            )
            
            # 创建记忆对象
            memory = {
                "id": memory_id,
                "content": content,
                "timestamp": time.time(),
                "last_access_time": time.time(),
                "weight": weight,
                "topics": topics or [],
                "emotions": emotions or [],
                "is_important": is_important,
                "source": source,
                "metadata": {},
                "embedding": None  # 向量嵌入字段
            }
            
            # 生成向量嵌入
            if VECTOR_SEARCH_ENABLED and content:
                try:
                    embedding = embedding_generator.generate_embedding(content)
                    memory["embedding"] = embedding_generator.embedding_to_base64(embedding)
                except Exception as e:
                    logger.error(f"生成记忆向量嵌入失败: {e}")
            
            # 添加到短期记忆
            self.short_term_memory.append(memory)
            
            # 添加到长期记忆（如果重要）
            if is_important or len(content) > 50:
                self._add_to_long_term_memory(memory)
            
            # 添加到权重记忆索引
            self.weighted_memories[memory_id] = memory
            
            # 更新话题权重
            for topic in topics:
                self.topic_weights[topic] += 0.1
            
            # 更新情绪-记忆映射
            if emotions:
                for emotion in emotions:
                    self.emotion_memory_map[emotion].append({
                        "memory_id": memory_id,
                        "relevance_score": 0.8  # 默认相关度
                    })
            
            # 修剪记忆
            self._trim_short_term_memory()
            self._trim_long_term_memory()
            
            # 更新主题索引
            self._update_topic_index()
            
            # 更新修改时间
            self.last_modified_time = time.time()
            
            logger.info(f"已添加权重记忆，ID: {memory_id}, 权重: {weight}, 话题: {topics}")
            
            return memory_id
    
    def get_weighted_memories(self, min_weight: float = None, topics: List[str] = None,
                             limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取按权重排序的记忆列表
        
        Args:
            min_weight: 最小权重阈值
            topics: 筛选的话题列表
            limit: 返回的最大数量
            
        Returns:
            List[Dict]: 排序后的记忆列表
        """
        # 优化：只在获取数据快照时持有锁
        with self.lock:
            memories_snapshot = list(self.weighted_memories.values())
            
        # 筛选记忆 (在锁外进行)
        filtered_memories = []
        
        for memory in memories_snapshot:
            # 应用权重筛选
            if min_weight is not None and memory.get("weight", 0) < min_weight:
                continue
            
            # 应用话题筛选
            if topics:
                if not any(topic in memory.get("topics", []) for topic in topics):
                    continue
            
            # 应用时间衰减
            updated_memory = memory.copy()
            updated_memory["weight"] = self.weight_calculator.apply_time_decay(
                memory["weight"], memory["timestamp"]
            )
            
            filtered_memories.append(updated_memory)
        
        # 按权重降序排序
        filtered_memories.sort(key=lambda x: x.get("weight", 0), reverse=True)
        
        return filtered_memories[:limit]
            
    def _search_by_keyword(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """关键词搜索辅助方法"""
        results = []
        query_lower = query.lower()
        
        # 优化：只在获取数据快照时持有锁
        with self.lock:
            memories_snapshot = list(self.weighted_memories.values())
            
        for memory in memories_snapshot:
            if query_lower in memory.get("content", "").lower():
                results.append(memory)
        results.sort(key=lambda x: x.get("weight", 0), reverse=True)
        return results[:limit]

    def search_memories(self, query: str, limit: int = 10, min_similarity: float = 0.3) -> List[Dict[str, Any]]:
        """
        基于语义向量搜索记忆
        
        Args:
            query: 查询文本
            limit: 返回结果数量限制
            min_similarity: 最小相似度阈值
            
        Returns:
            List[Dict]: 匹配的记忆列表，按相似度降序排列
        """
        if not VECTOR_SEARCH_ENABLED or not query:
            if not VECTOR_SEARCH_ENABLED:
                logger.warning("向量搜索未启用，回退到关键词搜索")
            return self._search_by_keyword(query, limit)
        
        try:
            # 生成查询向量
            query_embedding = embedding_generator.generate_embedding(query)
            
            candidates = []
            
            # 优化：只在获取数据快照时持有锁
            with self.lock:
                memories_snapshot = list(self.weighted_memories.values())
            
            for memory in memories_snapshot:
                # 检查是否有嵌入向量
                if "embedding" in memory and memory["embedding"]:
                    try:
                        # 解码向量
                        mem_embedding = embedding_generator.base64_to_embedding(memory["embedding"])
                        
                        # 计算相似度
                        similarity = embedding_generator.cosine_similarity(query_embedding, mem_embedding)
                        
                        if similarity >= min_similarity:
                            # 创建副本并添加相似度
                            result = memory.copy()
                            result["similarity"] = similarity
                            
                            # 结合权重得分 (相似度 * 0.7 + 归一化权重 * 0.3)
                            # 假设最大权重约为10.0
                            weight_score = min(result.get("weight", 1.0) / 10.0, 1.0)
                            result["hybrid_score"] = similarity * 0.7 + weight_score * 0.3
                            
                            candidates.append(result)
                    except Exception as e:
                        logger.error(f"处理记忆向量时出错: {e}")
                        continue
            
            # 如果向量搜索没有结果，尝试关键词搜索
            if not candidates:
                logger.info(f"向量搜索未找到结果，尝试关键词搜索: {query}")
                return self._search_by_keyword(query, limit)

            # 按混合分数排序
            candidates.sort(key=lambda x: x.get("hybrid_score", 0), reverse=True)
            
            return candidates[:limit]
            
        except Exception as e:
            logger.error(f"向量搜索失败: {e}")
            return self._search_by_keyword(query, limit)
    
    def update_memory_weight(self, memory_id: str, weight_delta: float) -> bool:
        """
        更新记忆权重
        
        Args:
            memory_id: 记忆ID
            weight_delta: 权重变化量
            
        Returns:
            bool: 是否更新成功
        """
        with self.lock:
            if memory_id not in self.weighted_memories:
                logger.warning(f"记忆ID不存在: {memory_id}")
                return False
            
            # 更新权重
            memory = self.weighted_memories[memory_id]
            new_weight = max(0.1, memory["weight"] + weight_delta)
            memory["weight"] = round(new_weight, 2)
            memory["last_access_time"] = time.time()
            
            # 更新修改时间
            self.last_modified_time = time.time()
            
            logger.info(f"已更新记忆权重，ID: {memory_id}, 新权重: {new_weight}")
            
            return True
    
    def get_top_topics(self, limit: int = 5) -> List[Tuple[str, float]]:
        """
        获取权重最高的话题列表
        
        Args:
            limit: 返回的最大数量
            
        Returns:
            List[Tuple]: (话题名称, 权重) 的列表
        """
        with self.lock:
            # 计算话题权重（结合记忆权重）
            for topic in list(self.topic_weights.keys()):
                # 重新计算话题权重，基于相关记忆的权重和频率
                topic_memories = self.get_weighted_memories(topics=[topic])
                total_weight = sum(m.get("weight", 0) for m in topic_memories)
                self.topic_weights[topic] = round(total_weight, 2)
            
            # 按权重排序并返回
            sorted_topics = sorted(self.topic_weights.items(), 
                                  key=lambda x: x[1], reverse=True)
            
            return sorted_topics[:limit]
    
    def access_memory(self, memory_id: str, importance: int = 1) -> Optional[Dict[str, Any]]:
        """
        访问记忆并增加权重
        
        Args:
            memory_id: 记忆ID
            importance: 访问重要性（1-5）
            
        Returns:
            Dict or None: 记忆对象，如果不存在则返回None
        """
        with self.lock:
            if memory_id not in self.weighted_memories:
                logger.warning(f"记忆ID不存在: {memory_id}")
                return None
            
            # 获取记忆
            memory = self.weighted_memories[memory_id]
            
            # 更新权重
            memory["weight"] = self.weight_calculator.update_weight_by_access(
                memory["weight"], importance
            )
            
            # 更新最后访问时间
            memory["last_access_time"] = time.time()
            
            # 更新修改时间
            self.last_modified_time = time.time()
            
            logger.debug(f"已访问记忆，ID: {memory_id}, 新权重: {memory['weight']}")
            
            return memory.copy()
    
    def _load_weighted_data(self):
        """
        加载权重相关数据
        """
        try:
            weighted_file = WEIGHTED_MEMORY_DIR / f"{self.user_id}_weighted.json"
            if weighted_file.exists():
                with open(weighted_file, 'r', encoding=DEFAULT_ENCODING) as f:
                    data = json.load(f)
                    
                    # 恢复权重记忆索引
                    if "weighted_memories" in data:
                        self.weighted_memories = {}
                        for memory in data["weighted_memories"]:
                            # 应用时间衰减
                            memory["weight"] = self.weight_calculator.apply_time_decay(
                                memory["weight"], memory["timestamp"]
                            )
                            self.weighted_memories[memory["id"]] = memory
                    
                    # 恢复话题权重
                    if "topic_weights" in data:
                        self.topic_weights = defaultdict(float, data["topic_weights"])
                    
                    # 恢复情绪-记忆映射
                    if "emotion_memory_map" in data:
                        self.emotion_memory_map = defaultdict(list, data["emotion_memory_map"])
                    
                    logger.info(f"已加载用户 {self.user_id} 的权重数据")
        except Exception as e:
            logger.error(f"加载权重数据时出错: {e}")
    
    def _save_weighted_data(self):
        """
        保存权重相关数据
        """
        try:
            weighted_file = WEIGHTED_MEMORY_DIR / f"{self.user_id}_weighted.json"
            
            # 准备数据 (使用锁确保数据一致性)
            with self.lock:
                data = {
                    "weighted_memories": list(self.weighted_memories.values()),
                    "topic_weights": dict(self.topic_weights),
                    "emotion_memory_map": dict(self.emotion_memory_map),
                    "last_updated": time.time()
                }
            
            # 安全保存 (IO操作在锁外进行)
            temp_file_path = str(weighted_file) + '.tmp'
            with open(temp_file_path, 'w', encoding=DEFAULT_ENCODING) as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # 原子操作替换文件
            if os.path.exists(weighted_file):
                os.remove(weighted_file)
            os.rename(temp_file_path, weighted_file)
            
            logger.debug(f"已保存用户 {self.user_id} 的权重数据")
        except Exception as e:
            logger.error(f"保存权重数据时出错: {e}")
    
    def save_memory(self):
        """
        保存记忆数据（包括权重数据）
        """
        # 先调用父类的保存方法
        super().save_memory()
        
        # 再保存权重数据
        self._save_weighted_data()
        
        # 更新保存时间
        self.last_save_time = time.time()
        
    def reclassify_all_memories(self):
        """重新分类所有加权记忆 (Override)"""
        if getattr(self, 'skip_auto_reclassify', False):
            logger.debug("跳过自动重分类 (skip_auto_reclassify=True)")
            return

        logger.info("开始重新分类所有加权记忆...")
        count = 0
        
        # 1. 调用父类方法处理 long_term_memory
        # 父类方法内部有锁，所以这里不需要加锁调用
        super().reclassify_all_memories()
        
        with self.lock:
            # 2. 处理 weighted_memories
            for memory_id, memory in self.weighted_memories.items():
                content = memory.get("content", "")
                if not content:
                    continue
                    
                # 更新主题
                new_topics = self._detect_topics(content)
                current_topics = memory.get("topics", [])
                
                if not current_topics or \
                   (len(new_topics) > 0 and "其他" in current_topics) or \
                   (len(new_topics) > len(current_topics)):
                    memory["topics"] = new_topics
                    count += 1
                
                # 更新情感
                if "emotion" not in memory:
                    memory["emotion"] = self._detect_emotion(content)
                    
            # 更新话题权重统计
            self.topic_weights = defaultdict(float)
            for memory in self.weighted_memories.values():
                for topic in memory.get("topics", []):
                    # 基于记忆权重累加
                    self.topic_weights[topic] += memory.get("weight", 1.0) * 0.1
                    
        if count > 0:
            logger.info(f"加权记忆重新分类完成，更新了 {count} 条")
            self._save_weighted_data()
        else:
            logger.info("加权记忆重新分类完成，无需更新")
    
    def search_by_similarity(self, query: str, limit: int = 10, min_similarity: float = 0.5, 
                            min_weight: float = None, source: str = None, topics: List[str] = None) -> List[Dict[str, Any]]:
        """
        基于向量相似度搜索记忆，结合权重因素
        
        Args:
            query: 搜索查询文本
            limit: 返回结果数量限制
            min_similarity: 最小相似度阈值
            min_weight: 最小权重阈值
            source: 筛选记忆来源（如 "character_setting"）
            topics: 筛选话题列表
        Returns:
            匹配的记忆列表，包含额外的similarity_score和weighted_score字段
        """
        # 检查向量搜索是否启用
        if not VECTOR_SEARCH_ENABLED:
            logger.warning("向量搜索功能未启用")
            # 回退到基于权重的搜索
            return self.get_weighted_memories(min_weight=min_weight, limit=limit, topics=topics)
        
        with self.lock:
            # 生成查询的向量嵌入
            try:
                query_embedding = embedding_generator.generate_embedding(query)
            except Exception as e:
                logger.error(f"生成查询向量嵌入失败: {e}")
                return []
            
            # 收集所有有向量嵌入的记忆
            memories_with_embeddings = []
            embeddings = []
            
            for memory in self.weighted_memories.values():
                # 应用权重筛选
                if min_weight is not None and memory.get("weight", 0) < min_weight:
                    continue

                # 应用来源筛选
                if source and memory.get("source") != source:
                    continue

                # 应用话题筛选
                if topics:
                    memory_topics = memory.get("topics", [])
                    if not any(t in memory_topics for t in topics):
                        continue
                
                # 检查是否有嵌入
                if "embedding" in memory and memory["embedding"]:
                    try:
                        embedding = embedding_generator.base64_to_embedding(memory["embedding"])
                        memories_with_embeddings.append(memory)
                        embeddings.append(embedding)
                    except Exception as e:
                        logger.error(f"解码向量嵌入失败: {e}")
            
            # 计算相似度并排序
            results = []
            for i, memory in enumerate(memories_with_embeddings):
                # 计算余弦相似度
                similarity = embedding_generator.cosine_similarity(query_embedding, embeddings[i])
                
                if similarity >= min_similarity:
                    # 应用时间衰减更新权重
                    current_weight = self.weight_calculator.apply_time_decay(
                        memory["weight"], memory["timestamp"]
                    )
                    
                    # 计算加权分数（权重和相似度的加权平均）
                    # 权重归一化（假设最大权重为20）
                    normalized_weight = min(current_weight / 20.0, 1.0)
                    # 相似度已经是0-1范围
                    weighted_score = (normalized_weight * 0.4) + (similarity * 0.6)
                    
                    # 创建结果副本
                    result = memory.copy()
                    result["similarity_score"] = similarity
                    result["current_weight"] = current_weight
                    result["weighted_score"] = weighted_score
                    
                    results.append(result)
            
            # 按加权分数降序排序
            results.sort(key=lambda x: x.get("weighted_score", 0), reverse=True)
            
            return results[:limit]
    
    def hybrid_search(self, query: str, limit: int = 10, min_similarity: float = 0.5, 
                     min_weight: float = None, keyword_weight: float = 0.3) -> List[Dict[str, Any]]:
        """
        混合搜索：结合关键词、向量相似度和权重的搜索方法
        
        Args:
            query: 搜索查询文本
            limit: 返回结果数量限制
            min_similarity: 最小相似度阈值
            min_weight: 最小权重阈值
            keyword_weight: 关键词匹配的权重(0-1)
        Returns:
            匹配的记忆列表，包含综合评分
        """
        with self.lock:
            # 提取查询关键词
            keywords = re.findall(r'\b\w+\b', query.lower())
            
            # 获取向量相似度搜索结果
            vector_results = self.search_by_similarity(query, limit=limit*2, 
                                                      min_similarity=min_similarity, 
                                                      min_weight=min_weight)
            
            # 基于关键词匹配计算分数
            results_with_keyword_scores = []
            for result in vector_results:
                content_lower = result.get("content", "").lower()
                
                # 计算关键词匹配分数
                match_count = sum(1 for keyword in keywords if keyword in content_lower)
                keyword_score = min(match_count / len(keywords) if keywords else 0, 1.0)
                
                # 计算综合分数
                similarity_score = result.get("similarity_score", 0)
                weighted_score = result.get("weighted_score", 0)
                
                # 综合评分：关键词分数 + 加权相似度分数
                hybrid_score = (keyword_score * keyword_weight) + (weighted_score * (1 - keyword_weight))
                
                result["keyword_score"] = keyword_score
                result["hybrid_score"] = hybrid_score
                results_with_keyword_scores.append(result)
            
            # 按综合分数排序
            results_with_keyword_scores.sort(key=lambda x: x.get("hybrid_score", 0), reverse=True)
            
            return results_with_keyword_scores[:limit]
    
    def generate_missing_embeddings(self) -> int:
        """
        为所有缺少向量嵌入的记忆生成嵌入
        
        Returns:
            int: 生成的嵌入数量
        """
        if not VECTOR_SEARCH_ENABLED:
            logger.warning("向量搜索功能未启用，无法生成嵌入")
            return 0
        
        with self.lock:
            count = 0
            
            for memory_id, memory in self.weighted_memories.items():
                # 检查是否缺少嵌入
                if "embedding" not in memory or not memory["embedding"]:
                    try:
                        content = memory.get("content", "")
                        if content:
                            # 生成嵌入
                            embedding = embedding_generator.generate_embedding(content)
                            memory["embedding"] = embedding_generator.embedding_to_base64(embedding)
                            count += 1
                    except Exception as e:
                        logger.error(f"为记忆 {memory_id} 生成嵌入失败: {e}")
            
            # 如果有更新，保存数据
            if count > 0:
                self._save_weighted_data()
                logger.info(f"为用户 {self.user_id} 生成了 {count} 个缺失的向量嵌入")
            
            return count
    
    def update_weight_config(self, new_config: Dict[str, float]):
        """
        更新权重配置
        
        Args:
            new_config: 新的权重配置
        """
        with self.lock:
            # 更新计算器配置
            self.weight_calculator.update_config(new_config)
            
            # 重新计算所有记忆的权重（应用新配置）
            for memory_id, memory in self.weighted_memories.items():
                # 重新计算基础权重
                base_weight = self.weight_calculator.calculate_initial_weight(
                    memory["content"],
                    memory.get("is_important", False),
                    memory.get("topics", []),
                    memory.get("emotions", [])
                )
                
                # 应用时间衰减
                memory["weight"] = self.weight_calculator.apply_time_decay(
                    base_weight, memory["timestamp"]
                )
            
            # 更新修改时间
            self.last_modified_time = time.time()
            
            logger.info(f"已更新用户 {self.user_id} 的权重配置")

# 单例工厂函数
def get_weighted_memory_manager(user_id: str = "default") -> WeightedMemoryManager:
    """
    获取或创建用户的权重记忆管理器实例
    
    Args:
        user_id: 用户ID
        
    Returns:
        WeightedMemoryManager: 权重记忆管理器实例
    """
    # 使用字典缓存记忆管理器实例
    if not hasattr(get_weighted_memory_manager, '_instances'):
        get_weighted_memory_manager._instances = {}
    
    if user_id not in get_weighted_memory_manager._instances:
        get_weighted_memory_manager._instances[user_id] = WeightedMemoryManager(user_id=user_id)
    
    return get_weighted_memory_manager._instances[user_id]

# 导出便捷函数
def add_weighted_memory(user_id: str, content: str, topics: List[str] = None,
                       emotions: List[str] = None, is_important: bool = False) -> str:
    """
    便捷函数：添加带权重的记忆
    """
    manager = get_weighted_memory_manager(user_id)
    return manager.add_memory(content, topics, emotions, is_important)

def get_weighted_topics(user_id: str, limit: int = 5) -> List[Tuple[str, float]]:
    """
    便捷函数：获取用户的高权重话题
    """
    manager = get_weighted_memory_manager(user_id)
    return manager.get_top_topics(limit)

def update_memory_importance(user_id: str, memory_id: str, weight_delta: float) -> bool:
    """
    便捷函数：更新记忆权重
    """
    manager = get_weighted_memory_manager(user_id)
    return manager.update_memory_weight(memory_id, weight_delta)

def search_memory_by_similarity(user_id: str, query: str, limit: int = 10, 
                               min_similarity: float = 0.5, min_weight: float = None) -> List[Dict[str, Any]]:
    """
    便捷函数：基于向量相似度搜索记忆
    """
    manager = get_weighted_memory_manager(user_id)
    return manager.search_by_similarity(query, limit, min_similarity, min_weight)

def hybrid_search_memory(user_id: str, query: str, limit: int = 10, 
                         min_similarity: float = 0.5, min_weight: float = None, 
                         keyword_weight: float = 0.3) -> List[Dict[str, Any]]:
    """
    便捷函数：混合搜索记忆（关键词、向量相似度和权重）
    """
    manager = get_weighted_memory_manager(user_id)
    return manager.hybrid_search(query, limit, min_similarity, min_weight, keyword_weight)

def generate_embeddings_for_user(user_id: str) -> int:
    """
    便捷函数：为用户的所有记忆生成向量嵌入
    """
    manager = get_weighted_memory_manager(user_id)
    return manager.generate_missing_embeddings()