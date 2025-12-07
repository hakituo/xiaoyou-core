#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版对话记忆管理器

功能特点：
1. 长期记忆与短期记忆分离
2. 基于主题聚类的记忆组织
3. 智能重要性评估
4. 个性化回复策略
5. 记忆检索优化
6. 自动学习用户偏好
"""

import json
import os
import time
import threading
import logging
import re
from typing import List, Dict, Any, Optional, Union, Tuple, Set
from datetime import datetime
from pathlib import Path
from collections import defaultdict, deque
import hashlib

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

# 使用配置目录路径
settings = get_settings()
HISTORY_DIR = Path(settings.memory.history_dir)
if not HISTORY_DIR.is_absolute():
    HISTORY_DIR = Path(os.getcwd()) / HISTORY_DIR

LONG_TERM_DIR = HISTORY_DIR / "long_term"

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
    except Exception as e:
        logger.error(f"创建历史记录目录时出错: {e}")

# 初始化历史记录目录
_ensure_history_dir_exists()

class EnhancedMemoryManager:
    """
    增强版记忆管理器，支持长期记忆、短期记忆分离，主题聚类和个性化回复策略
    """
    def __init__(self, user_id: str = "default",
                 max_short_term: int = DEFAULT_MAX_SHORT_TERM,
                 max_long_term: int = DEFAULT_MAX_LONG_TERM,
                 auto_save_interval: int = DEFAULT_AUTO_SAVE_INTERVAL):
        """
        初始化增强版记忆管理器
        
        Args:
            user_id: 用户ID，用于保存/加载记忆
            max_short_term: 短期记忆最大条数
            max_long_term: 长期记忆最大条数
            auto_save_interval: 自动保存间隔（秒）
        """
        # 参数验证
        self.user_id = str(user_id)
        self.max_short_term = max(MAX_LENGTH_MIN, min(max_short_term, MAX_LENGTH_MAX))
        self.max_long_term = max(MAX_LENGTH_MIN, min(max_long_term, MAX_LENGTH_MAX))
        self.auto_save_interval = max(0, int(auto_save_interval))
        
        # 实例属性初始化
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
        
        # 启动自动保存线程
        if self.auto_save_interval > 0:
            self._start_auto_save()
        
        # 加载保存的记忆
        self.load_memory()
        
        # 启动时自动重分类（优化历史数据）
        threading.Thread(target=self.reclassify_all_memories, daemon=True).start()
    
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
        """
        从消息内容中提取关键信息
        
        Args:
            content: 消息内容
            
        Returns:
            List[str]: 关键信息列表
        """
        key_info = []
        
        # 提取可能的关键信息模式
        patterns = [
            # 时间相关
            r'\b(?:\d{4}年\d{1,2}月\d{1,2}日|\d{4}/\d{1,2}/\d{1,2}|\d{1,2}/\d{1,2}/\d{4})\b',
            # 数字和单位
            r'\b\d+(?:\.\d+)?\s*(?:个|件|元|美元|人民币|斤|公斤|米|厘米|升|毫升|小时|分钟|秒)\b',
            # 专有名词（简化版，实际应使用更复杂的NLP方法）
            r'\b[A-Z][a-zA-Z0-9_]{2,}\b',  # 可能的英文专有名词
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content)
            key_info.extend(matches)
        
        return list(set(key_info))[:5]  # 最多返回5个关键信息
    
    def _detect_topics(self, content: str) -> List[str]:
        """
        自动检测消息主题
        
        Args:
            content: 消息内容
            
        Returns:
            List[str]: 检测到的主题列表
        """
        # 简单的主题检测逻辑，实际应用中可使用更复杂的NLP方法
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
        
        # 1. 关键词匹配
        for topic, keywords in topic_keywords.items():
            for keyword in keywords:
                if keyword in content_lower:
                    detected_topics.append(topic)
                    break
        
        # 2. 如果没有检测到主题，且内容较长，尝试归类为"其他"
        if not detected_topics and len(content) > 10:
            detected_topics.append("其他")
            
        return detected_topics

    def _detect_emotion(self, content: str) -> str:
        """
        检测消息情感
        
        Args:
            content: 消息内容
            
        Returns:
            str: 情感标签 (positive, negative, neutral)
        """
        emotions = {
            "positive": ["开心", "高兴", "喜欢", "棒", "不错", "哈哈", "谢谢", "有趣", "期待", "爱你", "舒服", "美", "好听"],
            "negative": ["难过", "伤心", "讨厌", "糟糕", "烦", "失望", "生气", "滚", "垃圾", "痛苦", "累", "困", "不好"],
        }
        
        content_lower = content.lower()
        for emotion, keywords in emotions.items():
            for keyword in keywords:
                if keyword in content_lower:
                    return emotion
        return "neutral"

    def reclassify_all_memories(self):
        """重新分类所有历史记忆"""
        logger.info("开始重新分类所有历史记忆...")
        count = 0
        with self.lock:
            # 重新分类长期记忆
            for memory in self.long_term_memory:
                content = memory.get("content", "")
                if not content:
                    continue
                    
                # 更新主题
                # 总是重新检测，以利用更新后的关键词
                new_topics = self._detect_topics(content)
                current_topics = memory.get("topics", [])
                
                # 如果新检测到的主题比原来的多，或者原来没有主题，或者原来是"其他"但现在检测到了具体主题
                if not current_topics or \
                   (len(new_topics) > 0 and "其他" in current_topics) or \
                   (len(new_topics) > len(current_topics)):
                    memory["topics"] = new_topics
                    count += 1
                
                # 更新情感 (如果不存在)
                if "emotion" not in memory:
                    memory["emotion"] = self._detect_emotion(content)
            
            # 重建主题索引
            self.topics = defaultdict(list)
            for memory in self.long_term_memory:
                for topic in memory.get("topics", []):
                    self.topics[topic].append(memory)
                    
        if count > 0:
            logger.info(f"重新分类完成，更新了 {count} 条记忆的主题")
            self.save_memory()
        else:
            logger.info("重新分类完成，无需更新")

    def _extract_user_preferences(self, content: str):
        """
        从用户消息中提取偏好信息
        
        Args:
            content: 用户消息内容
        """
        # 简单的偏好提取规则
        preference_patterns = {
            "preferred_topics": ["喜欢", "感兴趣", "想了解", "关注"],
            "disliked_topics": ["不喜欢", "讨厌", "反感", "不想"],
            "response_style": ["简洁", "详细", "专业", "口语化", "幽默", "严肃"],
        }
        
        for pref_type, indicators in preference_patterns.items():
            for indicator in indicators:
                if indicator in content:
                    # 更新用户偏好计数
                    if pref_type not in self.user_preferences:
                        self.user_preferences[pref_type] = {}
                    
                    # 提取偏好内容（简化版）
                    parts = content.split(indicator)
                    if len(parts) > 1:
                        preference_content = parts[1].strip().split('。')[0]
                        if preference_content:
                            self.user_preferences[pref_type][preference_content] = \
                                self.user_preferences[pref_type].get(preference_content, 0) + 1
    
    def _add_to_long_term_memory(self, message: Dict[str, Any]):
        """
        将消息添加到长期记忆
        
        Args:
            message: 要添加的消息
        """
        # 确保有主题分类
        if "topics" not in message or not message["topics"]:
            message["topics"] = self._detect_topics(message.get("content", ""))
            
        # 确保有情感分类
        if "emotion" not in message:
            message["emotion"] = self._detect_emotion(message.get("content", ""))

        # 检查是否已存在相同内容的消息（去重）
        content_hash = hashlib.md5(message["content"].encode()).hexdigest()
        message["content_hash"] = content_hash
        
        # 避免重复添加相同内容的消息
        for existing in self.long_term_memory:
            if existing.get("content_hash") == content_hash:
                # 更新现有消息的重要性和主题
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
        """
        修剪短期记忆，保留最重要的内容
        """
        if len(self.short_term_memory) <= self.max_short_term:
            return
        
        # 计算每条消息的重要性分数
        scored_messages = []
        now = time.time()
        
        for msg in self.short_term_memory:
            # 时间衰减因子
            time_age = now - msg["timestamp"]
            recency_factor = 1.0 + min(2.0 * (1.0 - time_age / 3600), 2.0)  # 1小时内的消息权重更高
            
            # 重要性权重
            importance_weight = 3.0 if msg.get("is_important", False) else 1.0
            
            # 角色权重
            role_weight = {
                'system': 3.0,
                'user': 2.0,
                'assistant': 1.0
            }.get(msg.get("role", "assistant"), 1.0)
            
            # 主题权重（有主题的消息更重要）
            topic_weight = 1.0 + min(len(msg.get("topics", [])) * 0.5, 2.0)
            
            # 综合分数
            score = recency_factor * importance_weight * role_weight * topic_weight
            scored_messages.append((msg, score))
        
        # 按分数降序排序
        scored_messages.sort(key=lambda x: x[1], reverse=True)
        
        # 保留前max_short_term个消息
        self.short_term_memory = [msg[0] for msg in scored_messages[:self.max_short_term]]
        
        # 按时间顺序恢复
        self.short_term_memory.sort(key=lambda x: x["timestamp"])
        
        logger.info(f"短期记忆已修剪，当前保留 {len(self.short_term_memory)}/{self.max_short_term} 条消息")
    
    def _trim_long_term_memory(self):
        """
        修剪长期记忆，保留最重要和最近引用的内容
        """
        if len(self.long_term_memory) <= self.max_long_term:
            return
        
        # 计算每条消息的重要性分数
        scored_messages = []
        now = time.time()
        
        for msg in self.long_term_memory:
            # 最近引用时间的权重
            last_ref = msg.get("last_reference_time", msg["timestamp"])
            recency_factor = 1.0 + min(2.0 * (1.0 - (now - last_ref) / (7 * 24 * 3600)), 2.0)  # 7天内引用的权重更高
            
            # 重要性权重
            importance_weight = 3.0 if msg.get("is_important", False) else 1.0
            
            # 主题权重（多主题的消息更重要）
            topic_weight = 1.0 + min(len(msg.get("topics", [])) * 0.5, 2.0)
            
            # 综合分数
            score = recency_factor * importance_weight * topic_weight
            scored_messages.append((msg, score))
        
        # 按分数降序排序
        scored_messages.sort(key=lambda x: x[1], reverse=True)
        
        # 保留前max_long_term个消息
        self.long_term_memory = [msg[0] for msg in scored_messages[:self.max_long_term]]
        
        # 更新主题索引
        self._update_topic_index()
        
        logger.info(f"长期记忆已修剪，当前保留 {len(self.long_term_memory)}/{self.max_long_term} 条消息")
    
    def _update_topic_index(self):
        """更新主题索引"""
        # 重建主题索引
        new_topics = defaultdict(list)
        all_messages = self.short_term_memory + self.long_term_memory
        
        for message in all_messages:
            for topic in message.get("topics", []):
                new_topics[topic].append(message)
        
        self.topics = new_topics
    def _extract_core_fields(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        从消息列表中提取核心字段
        
        Args:
            messages: 原始消息列表
            
        Returns:
            List[Dict]: 只包含核心字段的消息列表
        """
        core_fields = ['role', 'content', 'timestamp']
        result = []
        
        for msg in messages:
            filtered_msg = {k: v for k, v in msg.items() if k in core_fields}
            result.append(filtered_msg)
            
        return result
    def _safe_json_dump(self, data: Any, file_path: str):
        """
        安全地将数据保存为JSON文件，使用原子操作
        
        Args:
            data: 要保存的数据
            file_path: 文件路径
        """
        temp_file_path = file_path + '.tmp'
        
        try:
            # 写入临时文件
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # 原子操作替换文件
            if os.path.exists(file_path):
                os.remove(file_path)
            os.rename(temp_file_path, file_path)
            
        except Exception as e:
            # 清理临时文件
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception:
                    pass
            raise e

    def load_memory(self):
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

    def save_memory(self):
        try:
            # 只在复制数据时持有锁，避免长时间阻塞主线程
            with self.lock:
                short_copy = list(self.short_term_memory)
                long_copy = list(self.long_term_memory)
                self.last_save_time = time.time()
            
            # 耗时的I/O操作在锁外进行
            short_file = str(self.memory_dir / f"{self.user_id}_short.json")
            long_file = str(self.long_term_dir / f"{self.user_id}_long.json")
            self._safe_json_dump(short_copy, short_file)
            self._safe_json_dump(long_copy, long_file)
        except Exception as e:
            logger.error(f"保存记忆失败: {e}")

    def shutdown(self):
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
                    # 等待指定间隔或直到收到停止信号
                    if self._stop_event.wait(timeout=self.auto_save_interval):
                        break
                    
                    # 检查是否需要保存
                    current_time = time.time()
                    
                    with self.lock:
                        should_save = (current_time - self.last_modified_time > 60 and 
                                      current_time - self.last_save_time > self.auto_save_interval)
                    
                    if should_save:
                        self.save_memory()
                        logger.debug(f"[{time.ctime()}] 为用户 {self.user_id} 自动保存记忆")
                        
                except Exception as e:
                    logger.error(f"自动保存循环异常: {e}")
                    # 出错后等待一段时间再继续
                    if self._stop_event.wait(timeout=60):
                        break
                        
        except SystemExit:
            logger.info("收到系统退出信号，停止自动保存循环")
        except KeyboardInterrupt:
            logger.info("收到键盘中断，停止自动保存循环")
        finally:
            # 确保在退出前进行最后一次保存
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
    # 上下文管理器支持
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
        return False  # 不抑制异常

# 单例工厂函数
def get_memory_manager(user_id: str = "default") -> EnhancedMemoryManager:
    """
    获取或创建用户的记忆管理器实例
    
    Args:
        user_id: 用户ID
        
    Returns:
        EnhancedMemoryManager: 记忆管理器实例
    """
    # 使用字典缓存记忆管理器实例
    if not hasattr(get_memory_manager, '_instances'):
        get_memory_manager._instances = {}
    
    if user_id not in get_memory_manager._instances:
        get_memory_manager._instances[user_id] = EnhancedMemoryManager(user_id=user_id)
    
    return get_memory_manager._instances[user_id]

# 清理过期的记忆管理器实例
