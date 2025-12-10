#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版记忆管理器 - 带权重管理功能 (融合版)

该模块实现了记忆权重管理系统，能够对不同话题、事件和交互内容进行量化加权处理。
整合了原 EnhancedMemoryManager 的所有功能，作为统一的记忆管理入口。
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

from config.integrated_config import get_settings
# 导入拆分后的模块
from memory.core.weights import MemoryWeightCalculator, DEFAULT_WEIGHT_CONFIG
from memory.core.utils import detect_topics, extract_user_preferences, extract_key_information

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

class WeightedMemoryManager:
    """
    带权重管理的增强版记忆管理器
    融合了原 EnhancedMemoryManager 的功能
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
        # 参数验证
        self.user_id = str(user_id)
        self.max_short_term = max(MAX_LENGTH_MIN, min(max_short_term, MAX_LENGTH_MAX))
        self.max_long_term = max(MAX_LENGTH_MIN, min(max_long_term, MAX_LENGTH_MAX))
        self.auto_save_interval = max(0, int(auto_save_interval))
        self.skip_auto_reclassify = skip_auto_reclassify

        # 实例属性初始化 (原 EnhancedMemoryManager 属性)
        self.short_term_memory: List[Dict[str, Any]] = []  # 短期记忆，最近的对话
        self.long_term_memory: List[Dict[str, Any]] = []   # 长期记忆，重要的信息
        self.topics: Dict[str, List[Dict[str, Any]]] = defaultdict(list)  # 主题聚类
        self.user_preferences: Dict[str, Any] = {}  # 用户偏好信息
        self.memory_dir = HISTORY_DIR
        self.long_term_dir = LONG_TERM_DIR
        self.last_modified_time = time.time()
        self.last_save_time = 0
        self.last_access_time = time.time()
        self.lock = threading.RLock()  # 使用可重入锁
        self._stop_event = threading.Event()
        
        # 初始化权重计算器
        self.weight_calculator = MemoryWeightCalculator(weight_config)
        
        # 扩展数据结构 (WeightedMemoryManager 特有)
        self.weighted_memories: Dict[str, Dict[str, Any]] = {}  # 按ID索引的权重记忆
        self.topic_weights: Dict[str, float] = defaultdict(float)  # 话题权重映射
        self.emotion_memory_map: Dict[str, List[Dict[str, Any]]] = defaultdict(list)  # 情绪-记忆映射
        
        # 启动自动保存线程
        if self.auto_save_interval > 0:
            self._start_auto_save()
        
        # 加载保存的记忆 (基础记忆)
        self.load_memory()
        
        # 加载权重数据
        self._load_weighted_data()
        
        # 启动时自动重分类（优化历史数据）
        if not self.skip_auto_reclassify:
            threading.Thread(target=self.reclassify_all_memories, daemon=True).start()

    # --- 原 EnhancedMemoryManager 方法 ---

    def _start_auto_save(self):
        """启动自动保存线程"""
        # 检查是否已有运行的线程
        if hasattr(self, 'auto_save_thread') and self.auto_save_thread.is_alive():
            logger.warning(f"用户 {self.user_id} 已存在运行中的自动保存线程，停止旧线程")
            self._stop_event.set()
            try:
                if hasattr(self.auto_save_thread, '_started') and self.auto_save_thread._started.is_set():
                    self.auto_save_thread.join(timeout=3.0)
            except RuntimeError as e:
                logger.error(f"停止旧自动保存线程时出错: {e}")
        
        # 重置事件并创建新线程
        self._stop_event.clear()
        self.auto_save_thread = threading.Thread(
            target=self._auto_save_loop,
            daemon=True,
            name=f"auto-save-{self.user_id[:8]}"
        )
        try:
            self.auto_save_thread.start()
            logger.info(f"为用户 {self.user_id} 启动自动保存线程，间隔 {self.auto_save_interval} 秒")
        except RuntimeError as e:
            logger.error(f"启动自动保存线程失败: {e}")
            self.auto_save_interval = 0  # 禁用自动保存

    def _extract_key_information(self, content: str) -> List[str]:
        """从消息内容中提取关键信息"""
        return extract_key_information(content)

    def _detect_topics(self, content: str) -> List[str]:
        """自动检测消息主题"""
        return detect_topics(content)

    def _extract_user_preferences(self, content: str):
        """从用户消息中提取偏好信息"""
        extract_user_preferences(content, self.user_preferences)


    def _add_to_long_term_memory(self, message: Dict[str, Any]):
        """将消息添加到长期记忆"""
        if "topics" not in message or not message["topics"]:
            message["topics"] = self._detect_topics(message.get("content", ""))
        
        if "emotion" not in message:
            message["emotion"] = self._detect_emotion(message.get("content", ""))

        content_hash = hashlib.md5(message["content"].encode()).hexdigest()
        message["content_hash"] = content_hash
        
        for existing in self.long_term_memory:
            if existing.get("content_hash") == content_hash:
                if message.get("is_important", False):
                    existing["is_important"] = True
                
                existing_topics = set(existing.get("topics", []))
                new_topics = set(message.get("topics", []))
                existing["topics"] = list(existing_topics.union(new_topics))
                
                existing["last_reference_time"] = time.time()
                return
        
        message["last_reference_time"] = message["timestamp"]
        self.long_term_memory.append(message)

    def _trim_short_term_memory(self):
        """修剪短期记忆，保留最重要的内容"""
        if len(self.short_term_memory) <= self.max_short_term:
            return
        
        scored_messages = []
        now = time.time()
        
        for msg in self.short_term_memory:
            time_age = now - msg["timestamp"]
            recency_factor = 1.0 + min(2.0 * (1.0 - time_age / 3600), 2.0)
            importance_weight = 3.0 if msg.get("is_important", False) else 1.0
            role_weight = {'system': 3.0, 'user': 2.0, 'assistant': 1.0}.get(msg.get("role", "assistant"), 1.0)
            topic_weight = 1.0 + min(len(msg.get("topics", [])) * 0.5, 2.0)
            
            score = recency_factor * importance_weight * role_weight * topic_weight
            scored_messages.append((msg, score))
        
        scored_messages.sort(key=lambda x: x[1], reverse=True)
        self.short_term_memory = [msg[0] for msg in scored_messages[:self.max_short_term]]
        self.short_term_memory.sort(key=lambda x: x["timestamp"])
        
        logger.info(f"短期记忆已修剪，当前保留 {len(self.short_term_memory)}/{self.max_short_term} 条消息")

    def _trim_long_term_memory(self):
        """修剪长期记忆，保留最重要和最近引用的内容"""
        if len(self.long_term_memory) <= self.max_long_term:
            return
        
        scored_messages = []
        now = time.time()
        
        for msg in self.long_term_memory:
            last_ref = msg.get("last_reference_time", msg["timestamp"])
            recency_factor = 1.0 + min(2.0 * (1.0 - (now - last_ref) / (7 * 24 * 3600)), 2.0)
            importance_weight = 3.0 if msg.get("is_important", False) else 1.0
            topic_weight = 1.0 + min(len(msg.get("topics", [])) * 0.5, 2.0)
            
            score = recency_factor * importance_weight * topic_weight
            scored_messages.append((msg, score))
        
        scored_messages.sort(key=lambda x: x[1], reverse=True)
        self.long_term_memory = [msg[0] for msg in scored_messages[:self.max_long_term]]
        self._update_topic_index()
        
        logger.info(f"长期记忆已修剪，当前保留 {len(self.long_term_memory)}/{self.max_long_term} 条消息")

    def _update_topic_index(self):
        """更新主题索引"""
        new_topics = defaultdict(list)
        all_messages = self.short_term_memory + self.long_term_memory
        for message in all_messages:
            for topic in message.get("topics", []):
                new_topics[topic].append(message)
        self.topics = new_topics

    def _extract_core_fields(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从消息列表中提取核心字段"""
        core_fields = ['role', 'content', 'timestamp']
        result = []
        for msg in messages:
            filtered_msg = {k: v for k, v in msg.items() if k in core_fields}
            result.append(filtered_msg)
        return result

    def _safe_json_dump(self, data: Any, file_path: str):
        """安全地将数据保存为JSON文件，使用原子操作"""
        temp_file_path = file_path + '.tmp'
        try:
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if os.path.exists(file_path):
                os.remove(file_path)
            os.rename(temp_file_path, file_path)
        except Exception as e:
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception:
                    pass
            raise e

    def load_memory(self):
        """加载基础记忆数据"""
        try:
            with self.lock:
                short_file = str(self.memory_dir / f"{self.user_id}_short.json")
                long_file = str(self.long_term_dir / f"{self.user_id}_long.json")
                if os.path.exists(short_file):
                    try:
                        with open(short_file, 'r', encoding=DEFAULT_ENCODING) as f:
                            self.short_term_memory = json.load(f)
                    except Exception:
                        self.short_term_memory = []
                else:
                    self.short_term_memory = []
                
                if os.path.exists(long_file):
                    try:
                        with open(long_file, 'r', encoding=DEFAULT_ENCODING) as f:
                            self.long_term_memory = json.load(f)
                    except Exception:
                        self.long_term_memory = []
                else:
                    self.long_term_memory = []
                
                # 自动分类历史记录 (如果缺失主题)
                modified = False
                for msg in self.long_term_memory:
                    if "topics" not in msg or not msg["topics"]:
                        content = msg.get("content", "")
                        if content:
                            msg["topics"] = self._detect_topics(content)
                            if msg["topics"]:
                                modified = True
                
                if modified:
                    logger.info(f"已为 {self.user_id} 的历史记录自动补充主题分类")
                    self.save_memory()

                self._update_topic_index()
        except Exception:
            pass

    def shutdown(self):
        """关闭管理器"""
        try:
            self._stop_event.set()
            if hasattr(self, 'auto_save_thread') and getattr(self.auto_save_thread, 'is_alive', lambda: False)():
                try:
                    self.auto_save_thread.join(timeout=2.0)
                except Exception:
                    pass
            self.save_memory()
        except Exception:
            pass

    def _auto_save_loop(self):
        """自动保存循环线程"""
        logger.info(f"自动保存循环启动，间隔 {self.auto_save_interval} 秒")
        try:
            while not self._stop_event.is_set():
                try:
                    if self._stop_event.wait(timeout=self.auto_save_interval):
                        break
                    
                    current_time = time.time()
                    with self.lock:
                        should_save = (current_time - self.last_modified_time > 60 and 
                                      current_time - self.last_save_time > self.auto_save_interval)
                    
                    if should_save:
                        self.save_memory()
                        logger.debug(f"[{time.ctime()}] 为用户 {self.user_id} 自动保存记忆")
                        
                except Exception as e:
                    logger.error(f"自动保存循环异常: {e}")
                    if self._stop_event.wait(timeout=60):
                        break
        except SystemExit:
            logger.info("收到系统退出信号，停止自动保存循环")
        except KeyboardInterrupt:
            logger.info("收到键盘中断，停止自动保存循环")
        finally:
            try:
                current_time = time.time()
                should_final_save = False
                with self.lock:
                    should_final_save = current_time - self.last_save_time > 300
                if should_final_save:
                    logger.info("自动保存循环退出前执行最后一次保存")
                    self.save_memory()
            except Exception as final_save_error:
                logger.error(f"退出前保存失败: {final_save_error}")
            logger.info("自动保存循环已停止")

    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
        return False

    # --- WeightedMemoryManager 特有及重写方法 ---

    def _detect_emotion(self, content: str) -> str:
        """检测消息情感 (委托给 core.emotion)"""
        try:
            from core.emotion import get_emotion_manager
            manager = get_emotion_manager()
            state = manager.detector.detect(content)
            if state and state.primary_emotion:
                return state.primary_emotion.value
        except ImportError:
            pass
            
        # 降级逻辑
        emotions = {
            "happy": ["开心", "高兴", "喜欢", "棒", "不错", "哈哈", "谢谢"],
            "sad": ["难过", "伤心", "讨厌", "糟糕", "烦", "失望", "痛苦"],
            "angry": ["生气", "愤怒", "火大", "滚"],
            "anxious": ["焦虑", "担心", "害怕"]
        }
        
        content_lower = content.lower()
        for emotion, keywords in emotions.items():
            for keyword in keywords:
                if keyword in content_lower:
                    return emotion
        return "neutral"
    
    def add_memory(self, content: str, topics: List[str] = None, emotions: List[str] = None,
                   is_important: bool = False, source: str = "chat") -> str:
        """添加带权重的记忆"""
        with self.lock:
            memory_id = str(uuid.uuid4())
            if topics is None:
                topics = self._detect_topics(content)
            if emotions is None:
                emotions = [self._detect_emotion(content)]
            
            weight = self.weight_calculator.calculate_initial_weight(
                content, is_important, topics, emotions
            )
            
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
                "embedding": None
            }
            
            if VECTOR_SEARCH_ENABLED and content:
                try:
                    embedding = embedding_generator.generate_embedding(content)
                    memory["embedding"] = embedding_generator.embedding_to_base64(embedding)
                except Exception as e:
                    logger.error(f"生成记忆向量嵌入失败: {e}")
            
            self.short_term_memory.append(memory)
            
            if is_important or len(content) > 50:
                self._add_to_long_term_memory(memory)
            
            # 只有重要或权重较高的记忆才加入加权记忆库
            # 避免所有对话都成为加权记忆
            if is_important or weight > 1.2:
                self.weighted_memories[memory_id] = memory
                
                for topic in topics:
                    self.topic_weights[topic] += 0.1
                
                if emotions:
                    for emotion in emotions:
                        self.emotion_memory_map[emotion].append({
                            "memory_id": memory_id,
                            "relevance_score": 0.8
                        })
            
            self._trim_short_term_memory()
            self._trim_long_term_memory()
            self._update_topic_index()
            self.last_modified_time = time.time()
            
            # 立即保存以防止重启丢失
            self.save_memory()
            
            logger.info(f"已添加权重记忆，ID: {memory_id}, 权重: {weight}, 话题: {topics}")
            return memory_id
    
    def get_weighted_memories(self, min_weight: float = None, topics: List[str] = None,
                             limit: int = 10) -> List[Dict[str, Any]]:
        """获取按权重排序的记忆列表"""
        with self.lock:
            memories_snapshot = list(self.weighted_memories.values())
            
        filtered_memories = []
        for memory in memories_snapshot:
            if min_weight is not None and memory.get("weight", 0) < min_weight:
                continue
            if topics:
                if not any(topic in memory.get("topics", []) for topic in topics):
                    continue
            
            updated_memory = memory.copy()
            updated_memory["weight"] = self.weight_calculator.apply_time_decay(
                memory["weight"], memory["timestamp"]
            )
            filtered_memories.append(updated_memory)
        
        filtered_memories.sort(key=lambda x: x.get("weight", 0), reverse=True)
        return filtered_memories[:limit]
            
    def _search_by_keyword(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """关键词搜索辅助方法"""
        results = []
        query_lower = query.lower()
        
        with self.lock:
            memories_snapshot = list(self.weighted_memories.values())
            
        for memory in memories_snapshot:
            if query_lower in memory.get("content", "").lower():
                results.append(memory)
        results.sort(key=lambda x: x.get("weight", 0), reverse=True)
        return results[:limit]

    def search_memories(self, query: str, limit: int = 10, min_similarity: float = 0.3) -> List[Dict[str, Any]]:
        """基于语义向量搜索记忆"""
        if not VECTOR_SEARCH_ENABLED or not query:
            if not VECTOR_SEARCH_ENABLED:
                logger.warning("向量搜索未启用，回退到关键词搜索")
            return self._search_by_keyword(query, limit)
        
        try:
            query_embedding = embedding_generator.generate_embedding(query)
            candidates = []
            
            with self.lock:
                memories_snapshot = list(self.weighted_memories.values())
            
            for memory in memories_snapshot:
                if "embedding" in memory and memory["embedding"]:
                    try:
                        mem_embedding = embedding_generator.base64_to_embedding(memory["embedding"])
                        similarity = embedding_generator.cosine_similarity(query_embedding, mem_embedding)
                        
                        if similarity >= min_similarity:
                            result = memory.copy()
                            result["similarity"] = similarity
                            weight_score = min(result.get("weight", 1.0) / 10.0, 1.0)
                            result["hybrid_score"] = similarity * 0.7 + weight_score * 0.3
                            candidates.append(result)
                    except Exception as e:
                        logger.error(f"处理记忆向量时出错: {e}")
                        continue
            
            if not candidates:
                logger.info(f"向量搜索未找到结果，尝试关键词搜索: {query}")
                return self._search_by_keyword(query, limit)

            candidates.sort(key=lambda x: x.get("hybrid_score", 0), reverse=True)
            return candidates[:limit]
            
        except Exception as e:
            logger.error(f"向量搜索失败: {e}")
            return self._search_by_keyword(query, limit)
    
    def update_memory_weight(self, memory_id: str, weight_delta: float) -> bool:
        """更新记忆权重"""
        with self.lock:
            if memory_id not in self.weighted_memories:
                logger.warning(f"记忆ID不存在: {memory_id}")
                return False
            
            memory = self.weighted_memories[memory_id]
            new_weight = max(0.1, memory["weight"] + weight_delta)
            memory["weight"] = round(new_weight, 2)
            memory["last_access_time"] = time.time()
            self.last_modified_time = time.time()
            logger.info(f"已更新记忆权重，ID: {memory_id}, 新权重: {new_weight}")
            return True
    
    def get_top_topics(self, limit: int = 5) -> List[Tuple[str, float]]:
        """获取权重最高的话题列表"""
        with self.lock:
            for topic in list(self.topic_weights.keys()):
                topic_memories = self.get_weighted_memories(topics=[topic])
                total_weight = sum(m.get("weight", 0) for m in topic_memories)
                self.topic_weights[topic] = round(total_weight, 2)
            
            sorted_topics = sorted(self.topic_weights.items(), 
                                  key=lambda x: x[1], reverse=True)
            return sorted_topics[:limit]
    
    def access_memory(self, memory_id: str, importance: int = 1) -> Optional[Dict[str, Any]]:
        """访问记忆并增加权重"""
        with self.lock:
            if memory_id not in self.weighted_memories:
                logger.warning(f"记忆ID不存在: {memory_id}")
                return None
            
            memory = self.weighted_memories[memory_id]
            memory["weight"] = self.weight_calculator.update_weight_by_access(
                memory["weight"], importance
            )
            memory["last_access_time"] = time.time()
            self.last_modified_time = time.time()
            logger.debug(f"已访问记忆，ID: {memory_id}, 新权重: {memory['weight']}")
            return memory.copy()
    
    def _load_weighted_data(self):
        """加载权重相关数据"""
        try:
            weighted_file = WEIGHTED_MEMORY_DIR / f"{self.user_id}_weighted.json"
            if weighted_file.exists():
                with open(weighted_file, 'r', encoding=DEFAULT_ENCODING) as f:
                    data = json.load(f)
                    
                    if "weighted_memories" in data:
                        self.weighted_memories = {}
                        for memory in data["weighted_memories"]:
                            memory["weight"] = self.weight_calculator.apply_time_decay(
                                memory["weight"], memory["timestamp"]
                            )
                            self.weighted_memories[memory["id"]] = memory
                    
                    if "topic_weights" in data:
                        self.topic_weights = defaultdict(float, data["topic_weights"])
                    
                    if "emotion_memory_map" in data:
                        self.emotion_memory_map = defaultdict(list, data["emotion_memory_map"])
                    
                    logger.info(f"已加载用户 {self.user_id} 的权重数据")
        except Exception as e:
            logger.error(f"加载权重数据时出错: {e}")
    
    def save_memory(self):
        """保存记忆数据（包括权重数据）"""
        # 保存基础数据 (逻辑来自原 EnhancedMemoryManager.save_memory)
        try:
            with self.lock:
                short_copy = list(self.short_term_memory)
                long_copy = list(self.long_term_memory)
                self.last_save_time = time.time()
            
                # IO操作放入锁内以避免竞争条件 (Critical Fix for race condition)
                short_file = str(self.memory_dir / f"{self.user_id}_short.json")
                long_file = str(self.long_term_dir / f"{self.user_id}_long.json")
                self._safe_json_dump(short_copy, short_file)
                self._safe_json_dump(long_copy, long_file)
                
                # 保存权重数据 (也在锁内)
                self._save_weighted_data_locked()
                self.last_save_time = time.time()
                
        except Exception as e:
            logger.error(f"保存记忆失败: {e}")
        
    def _save_weighted_data_locked(self):
        """保存权重相关数据 (假设已持有锁)"""
        try:
            weighted_file = WEIGHTED_MEMORY_DIR / f"{self.user_id}_weighted.json"
            data = {
                "weighted_memories": list(self.weighted_memories.values()),
                "topic_weights": dict(self.topic_weights),
                "emotion_memory_map": dict(self.emotion_memory_map),
                "last_updated": time.time()
            }
        
            temp_file_path = str(weighted_file) + '.tmp'
            with open(temp_file_path, 'w', encoding=DEFAULT_ENCODING) as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            if os.path.exists(weighted_file):
                os.remove(weighted_file)
            os.rename(temp_file_path, weighted_file)
            
            logger.debug(f"已保存用户 {self.user_id} 的权重数据")
        except Exception as e:
            logger.error(f"保存权重数据时出错: {e}")

    def _save_weighted_data(self):
        """保存权重相关数据 (对外接口，获取锁)"""
        with self.lock:
            self._save_weighted_data_locked()
        
    def clear_weighted_memories(self) -> int:
        """清除所有加权记忆"""
        with self.lock:
            count = len(self.weighted_memories)
            self.weighted_memories.clear()
            self.topic_weights.clear()
            self.emotion_memory_map.clear()
            
            # 保存空状态
            try:
                weighted_file = WEIGHTED_MEMORY_DIR / f"{self.user_id}_weighted.json"
                if weighted_file.exists():
                    # 写入空数据
                    data = {
                        "weighted_memories": [],
                        "topic_weights": {},
                        "emotion_memory_map": {}
                    }
                    with open(weighted_file, 'w', encoding=DEFAULT_ENCODING) as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"清除加权记忆文件失败: {e}")
                
            logger.info(f"已清除所有加权记忆，共 {count} 条")
            return count

    def reclassify_all_memories(self):
        """重新分类所有记忆 (包括加权记忆)"""
        if getattr(self, 'skip_auto_reclassify', False):
            logger.debug("跳过自动重分类 (skip_auto_reclassify=True)")
            return

        logger.info("开始重新分类所有记忆...")
        
        # 1. 处理 long_term_memory (逻辑来自原 EnhancedMemoryManager)
        count = 0
        with self.lock:
            for memory in self.long_term_memory:
                content = memory.get("content", "")
                if not content:
                    continue
                new_topics = self._detect_topics(content)
                current_topics = memory.get("topics", [])
                
                if not current_topics or \
                   (len(new_topics) > 0 and "其他" in current_topics) or \
                   (len(new_topics) > len(current_topics)):
                    memory["topics"] = new_topics
                    count += 1
                if "emotion" not in memory:
                    memory["emotion"] = self._detect_emotion(content)
            
            self._update_topic_index()
            
            # 2. 处理 weighted_memories
            for memory_id, memory in self.weighted_memories.items():
                content = memory.get("content", "")
                if not content:
                    continue
                new_topics = self._detect_topics(content)
                current_topics = memory.get("topics", [])
                
                if not current_topics or \
                   (len(new_topics) > 0 and "其他" in current_topics) or \
                   (len(new_topics) > len(current_topics)):
                    memory["topics"] = new_topics
                    count += 1
                if "emotion" not in memory:
                    memory["emotion"] = self._detect_emotion(content)
                    
            # 更新话题权重统计
            self.topic_weights = defaultdict(float)
            for memory in self.weighted_memories.values():
                for topic in memory.get("topics", []):
                    self.topic_weights[topic] += memory.get("weight", 1.0) * 0.1
                    
        if count > 0:
            logger.info(f"记忆重新分类完成，更新了 {count} 条")
            self.save_memory()
        else:
            logger.info("记忆重新分类完成，无需更新")
    
    def search_by_similarity(self, query: str, limit: int = 10, min_similarity: float = 0.5, 
                            min_weight: float = None, source: str = None, topics: List[str] = None) -> List[Dict[str, Any]]:
        """基于向量相似度搜索记忆，结合权重因素"""
        if not VECTOR_SEARCH_ENABLED:
            logger.warning("向量搜索功能未启用")
            return self.get_weighted_memories(min_weight=min_weight, limit=limit, topics=topics)
        
        try:
            query_embedding = embedding_generator.generate_embedding(query)
        except Exception as e:
            logger.error(f"生成查询向量嵌入失败: {e}")
            return []
            
        memories_with_embeddings = []
        embeddings = []
        
        with self.lock:
            memories_snapshot = list(self.weighted_memories.values())
        
        for memory in memories_snapshot:
            if min_weight is not None and memory.get("weight", 0) < min_weight:
                continue
            if source and memory.get("source") != source:
                continue
            if topics:
                memory_topics = memory.get("topics", [])
                if not any(t in memory_topics for t in topics):
                    continue
            
            if "embedding" in memory and memory["embedding"]:
                try:
                    embedding = embedding_generator.base64_to_embedding(memory["embedding"])
                    memories_with_embeddings.append(memory)
                    embeddings.append(embedding)
                except Exception as e:
                    logger.error(f"解码向量嵌入失败: {e}")
        
        results = []
        for i, memory in enumerate(memories_with_embeddings):
            similarity = embedding_generator.cosine_similarity(query_embedding, embeddings[i])
            
            if similarity >= min_similarity:
                current_weight = self.weight_calculator.apply_time_decay(
                    memory["weight"], memory["timestamp"]
                )
                
                normalized_weight = min(current_weight / 20.0, 1.0)
                weighted_score = (normalized_weight * 0.4) + (similarity * 0.6)
                
                result = memory.copy()
                result["similarity_score"] = similarity
                result["current_weight"] = current_weight
                result["weighted_score"] = weighted_score
                
                results.append(result)
        
        results.sort(key=lambda x: x.get("weighted_score", 0), reverse=True)
        return results[:limit]

    async def get_recent_history(self, session_id: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取最近的历史记录 (适配 SessionRouter)
        Args:
            session_id: 会话ID (在当前架构中通常等于 user_id)
            limit: 获取的消息数量限制
        Returns:
            历史消息列表
        """
        with self.lock:
            # 合并短期和长期记忆，确保完整历史
            all_memory = self.short_term_memory + self.long_term_memory
            # 去重 (按ID)
            unique_memory = {m['id']: m for m in all_memory}
            
            # 确保按时间戳排序
            sorted_memory = sorted(unique_memory.values(), key=lambda x: x.get("timestamp", 0))
            
            # 提取需要的字段
            result = []
            for msg in sorted_memory:
                if not msg.get("content"):
                    continue
                    
                result.append({
                    "role": msg.get("role", "assistant"), # 默认为 assistant 如果缺失
                    "content": msg.get("content", ""),
                    "timestamp": msg.get("timestamp", 0),
                    "id": msg.get("id", ""),
                    "is_important": msg.get("is_important", False)
                })
            
            if len(result) > limit:
                return result[-limit:]
            return result

    def get_history(self) -> List[Dict[str, Any]]:
        """获取所有历史记录 (同步版本)"""
        with self.lock:
            return list(self.short_term_memory)
    
    def hybrid_search(self, query: str, limit: int = 10, min_similarity: float = 0.5, 
                     min_weight: float = None, keyword_weight: float = 0.3) -> List[Dict[str, Any]]:
        """混合搜索：结合关键词、向量相似度和权重的搜索方法"""
        keywords = re.findall(r'\b\w+\b', query.lower())
        
        vector_results = self.search_by_similarity(query, limit=limit*2, 
                                                  min_similarity=min_similarity, 
                                                  min_weight=min_weight)
        
        results_with_keyword_scores = []
        for result in vector_results:
            content_lower = result.get("content", "").lower()
            match_count = sum(1 for keyword in keywords if keyword in content_lower)
            keyword_score = min(match_count / len(keywords) if keywords else 0, 1.0)
            
            weighted_score = result.get("weighted_score", 0)
            hybrid_score = (keyword_score * keyword_weight) + (weighted_score * (1 - keyword_weight))
            
            result["keyword_score"] = keyword_score
            result["hybrid_score"] = hybrid_score
            results_with_keyword_scores.append(result)
        
        results_with_keyword_scores.sort(key=lambda x: x.get("hybrid_score", 0), reverse=True)
        return results_with_keyword_scores[:limit]
    
    def generate_missing_embeddings(self) -> int:
        """为所有缺少向量嵌入的记忆生成嵌入"""
        if not VECTOR_SEARCH_ENABLED:
            logger.warning("向量搜索功能未启用，无法生成嵌入")
            return 0
        
        with self.lock:
            count = 0
            for memory_id, memory in self.weighted_memories.items():
                if "embedding" not in memory or not memory["embedding"]:
                    try:
                        content = memory.get("content", "")
                        if content:
                            embedding = embedding_generator.generate_embedding(content)
                            memory["embedding"] = embedding_generator.embedding_to_base64(embedding)
                            count += 1
                    except Exception as e:
                        logger.error(f"为记忆 {memory_id} 生成嵌入失败: {e}")
            
            if count > 0:
                self._save_weighted_data()
                logger.info(f"为用户 {self.user_id} 生成了 {count} 个缺失的向量嵌入")
            
            return count
    
    def update_weight_config(self, new_config: Dict[str, float]):
        """更新权重配置"""
        with self.lock:
            self.weight_calculator.update_config(new_config)
            for memory_id, memory in self.weighted_memories.items():
                base_weight = self.weight_calculator.calculate_initial_weight(
                    memory["content"],
                    memory.get("is_important", False),
                    memory.get("topics", []),
                    memory.get("emotions", [])
                )
                memory["weight"] = self.weight_calculator.apply_time_decay(
                    base_weight, memory["timestamp"]
                )
            self.last_modified_time = time.time()
            logger.info(f"已更新用户 {self.user_id} 的权重配置")

# 单例工厂函数
def get_weighted_memory_manager(user_id: str = "default") -> WeightedMemoryManager:
    """获取或创建用户的权重记忆管理器实例"""
    if not hasattr(get_weighted_memory_manager, '_instances'):
        get_weighted_memory_manager._instances = {}
    
    if user_id not in get_weighted_memory_manager._instances:
        get_weighted_memory_manager._instances[user_id] = WeightedMemoryManager(user_id=user_id)
    
    return get_weighted_memory_manager._instances[user_id]

# 导出便捷函数
def add_weighted_memory(user_id: str, content: str, topics: List[str] = None,
                       emotions: List[str] = None, is_important: bool = False) -> str:
    """便捷函数：添加带权重的记忆"""
    manager = get_weighted_memory_manager(user_id)
    return manager.add_memory(content, topics, emotions, is_important)

def get_weighted_topics(user_id: str, limit: int = 5) -> List[Tuple[str, float]]:
    """便捷函数：获取用户的高权重话题"""
    manager = get_weighted_memory_manager(user_id)
    return manager.get_top_topics(limit)

def update_memory_importance(user_id: str, memory_id: str, weight_delta: float) -> bool:
    """便捷函数：更新记忆权重"""
    manager = get_weighted_memory_manager(user_id)
    return manager.update_memory_weight(memory_id, weight_delta)

def search_memory_by_similarity(user_id: str, query: str, limit: int = 10, 
                               min_similarity: float = 0.5, min_weight: float = None) -> List[Dict[str, Any]]:
    """便捷函数：基于向量相似度搜索记忆"""
    manager = get_weighted_memory_manager(user_id)
    return manager.search_by_similarity(query, limit, min_similarity, min_weight)

def hybrid_search_memory(user_id: str, query: str, limit: int = 10, 
                         min_similarity: float = 0.5, min_weight: float = None, 
                         keyword_weight: float = 0.3) -> List[Dict[str, Any]]:
    """便捷函数：混合搜索记忆（关键词、向量相似度和权重）"""
    manager = get_weighted_memory_manager(user_id)
    return manager.hybrid_search(query, limit, min_similarity, min_weight, keyword_weight)

def generate_embeddings_for_user(user_id: str) -> int:
    """便捷函数：为用户的所有记忆生成向量嵌入"""
    manager = get_weighted_memory_manager(user_id)
    return manager.generate_missing_embeddings()
