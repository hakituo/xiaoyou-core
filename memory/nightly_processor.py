#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
夜间自动处理机制

该模块实现每日聊天记录分析功能，在用户睡眠时段自动运行，对当日聊天话题进行频率统计和权重计算，
将高频话题自动增加1个权重单位
"""

import json
import os
import time
import threading
import logging
import schedule
import datetime
from typing import List, Dict, Any, Optional, Union, Tuple, Set
from pathlib import Path
from collections import defaultdict, Counter
import re

# 导入记忆管理器
from .weighted_memory_manager import get_weighted_memory_manager

# 配置日志
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_NIGHTLY_CONFIG = {
    "enabled": True,               # 是否启用夜间处理
    "start_time": "23:00",         # 开始时间
    "end_time": "06:00",           # 结束时间
    "weight_increment": 1.0,       # 高频话题权重增量
    "min_frequency": 3,            # 高频话题最小频率阈值
    "auto_run": True,              # 是否自动运行
    "max_topics_to_update": 10     # 最多更新的话题数量
}

# 分析结果存储目录
ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "history" / "analysis"

# 确保分析目录存在
def _ensure_analysis_dir_exists():
    """确保分析结果目录存在，如果不存在则创建"""
    try:
        if not ANALYSIS_DIR.exists():
            ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
            logger.info(f"创建分析结果目录: {ANALYSIS_DIR}")
    except Exception as e:
        logger.error(f"创建分析结果目录时出错: {e}")

# 初始化分析目录
_ensure_analysis_dir_exists()

class NightlyProcessor:
    """
    夜间自动处理组件，负责在配置的时间窗口内处理聊天记录和调整权重
    """
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化夜间处理器
        
        Args:
            config: 夜间处理配置参数
        """
        self.config = config or DEFAULT_NIGHTLY_CONFIG
        self._stop_event = threading.Event()
        self._scheduler_thread = None
        self._is_running = False
        
        # 初始化调度器
        if self.config["enabled"] and self.config["auto_run"]:
            self._start_scheduler()
    
    def _start_scheduler(self):
        """
        启动定时任务调度器
        """
        # 检查是否已有运行的调度器
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            logger.warning("调度器线程已存在，停止旧线程")
            self._stop_event.set()
            try:
                if hasattr(self._scheduler_thread, '_started') and self._scheduler_thread._started.is_set():
                    self._scheduler_thread.join(timeout=3.0)
            except RuntimeError as e:
                logger.error(f"停止旧调度器线程时出错: {e}")
        
        # 重置停止事件
        self._stop_event.clear()
        
        # 设置定时任务
        schedule.clear()
        
        # 每天在配置的开始时间运行处理任务
        schedule.every().day.at(self.config["start_time"]).do(self.process_all_users)
        
        logger.info(f"已设置夜间处理任务，每天 {self.config['start_time']} 执行")
        
        # 启动调度器线程
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="nightly-scheduler"
        )
        
        try:
            self._scheduler_thread.start()
            self._is_running = True
            logger.info("夜间处理调度器已启动")
        except RuntimeError as e:
            logger.error(f"启动调度器线程失败: {e}")
            self._is_running = False
    
    def _scheduler_loop(self):
        """
        调度器循环，定期检查并运行定时任务
        """
        logger.info("调度器循环已启动")
        
        try:
            while not self._stop_event.is_set():
                try:
                    # 运行所有到期的任务
                    schedule.run_pending()
                    
                    # 短暂休眠，避免CPU占用过高
                    if self._stop_event.wait(timeout=60):
                        break
                        
                except Exception as e:
                    logger.error(f"调度器循环异常: {e}")
                    # 出错后等待一段时间再继续
                    if self._stop_event.wait(timeout=60):
                        break
                        
        except SystemExit:
            logger.info("收到系统退出信号，停止调度器循环")
        except KeyboardInterrupt:
            logger.info("收到键盘中断，停止调度器循环")
        finally:
            self._is_running = False
            logger.info("调度器循环已停止")
    
    def process_all_users(self):
        """
        处理所有用户的聊天记录
        """
        if not self._is_in_time_window():
            logger.info("当前不在配置的时间窗口内，跳过处理")
            return
        
        try:
            # 获取所有用户的记忆管理器实例
            memory_managers = get_weighted_memory_manager._instances
            
            logger.info(f"开始夜间处理，共有 {len(memory_managers)} 个用户需要处理")
            
            # 逐个处理用户
            for user_id, manager in memory_managers.items():
                try:
                    self.process_user_chat_history(user_id, manager)
                except Exception as e:
                    logger.error(f"处理用户 {user_id} 的聊天记录时出错: {e}")
            
            logger.info("夜间处理完成")
            
        except Exception as e:
            logger.error(f"夜间处理过程中发生错误: {e}")
    
    def process_user_chat_history(self, user_id: str, manager = None) -> Dict[str, Any]:
        """
        处理单个用户的聊天记录
        
        Args:
            user_id: 用户ID
            manager: 记忆管理器实例（可选）
            
        Returns:
            Dict: 处理结果统计信息
        """
        logger.info(f"开始处理用户 {user_id} 的聊天记录")
        
        # 获取记忆管理器实例
        if manager is None:
            manager = get_weighted_memory_manager(user_id)
        
        # 获取当日（24小时内）的聊天记录
        today_start = datetime.datetime.now() - datetime.timedelta(days=1)
        today_timestamp = today_start.timestamp()
        
        # 收集当日所有消息
        today_messages = []
        
        # 从短期记忆中收集
        for msg in manager.short_term_memory:
            if msg.get("timestamp", 0) >= today_timestamp:
                today_messages.append(msg)
        
        # 从长期记忆中收集
        for msg in manager.long_term_memory:
            if msg.get("timestamp", 0) >= today_timestamp:
                today_messages.append(msg)
        
        logger.info(f"用户 {user_id} 今日共有 {len(today_messages)} 条消息")
        
        # 分析话题频率
        topic_counter = Counter()
        content_analysis = self._analyze_message_content(today_messages)
        
        # 统计话题频率
        for msg in today_messages:
            topics = msg.get("topics", [])
            topic_counter.update(topics)
        
        # 合并内容分析的话题
        topic_counter.update(content_analysis["detected_topics"])
        
        # 识别高频话题
        high_frequency_topics = []
        min_freq = self.config["min_frequency"]
        
        for topic, frequency in topic_counter.items():
            if frequency >= min_freq:
                high_frequency_topics.append((topic, frequency))
        
        # 按频率排序
        high_frequency_topics.sort(key=lambda x: x[1], reverse=True)
        
        # 限制更新的话题数量
        high_frequency_topics = high_frequency_topics[:self.config["max_topics_to_update"]]
        
        logger.info(f"用户 {user_id} 今日高频话题: {high_frequency_topics}")
        
        # 更新话题权重
        updated_topics = []
        weight_increment = self.config["weight_increment"]
        
        for topic, _ in high_frequency_topics:
            # 查找与该话题相关的记忆并增加权重
            topic_memories = manager.get_weighted_memories(topics=[topic], limit=20)
            
            for memory in topic_memories:
                # 更新记忆权重
                manager.update_memory_weight(memory["id"], weight_increment)
                updated_topics.append({
                    "topic": topic,
                    "memory_id": memory["id"],
                    "new_weight": memory.get("weight", 0) + weight_increment
                })
        
        # 生成分析报告
        analysis_result = {
            "user_id": user_id,
            "processing_time": datetime.datetime.now().isoformat(),
            "total_messages": len(today_messages),
            "high_frequency_topics": high_frequency_topics,
            "updated_topics_count": len(updated_topics),
            "word_frequency": content_analysis["word_frequency"],
            "sentiment_analysis": content_analysis["sentiment_analysis"],
            "most_active_time": content_analysis["most_active_time"]
        }
        
        # 保存分析结果
        self._save_analysis_result(user_id, analysis_result)
        
        logger.info(f"用户 {user_id} 处理完成，更新了 {len(updated_topics)} 个话题相关的记忆权重")
        
        return analysis_result
    
    def _analyze_message_content(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        分析消息内容，提取关键词、检测话题和情绪
        
        Args:
            messages: 消息列表
            
        Returns:
            Dict: 分析结果
        """
        # 简单的主题关键词映射
        topic_keywords = {
            "技术": ["编程", "代码", "软件", "算法", "开发", "项目", "架构", "框架"],
            "生活": ["吃饭", "睡觉", "旅游", "购物", "电影", "音乐", "运动", "健康"],
            "工作": ["会议", "报告", "任务", "截止日期", "同事", "客户", "公司", "老板"],
            "学习": ["考试", "作业", "书籍", "课程", "学校", "成绩", "老师", "学生"],
            "娱乐": ["游戏", "视频", "直播", "社交媒体", "明星", "综艺", "动漫", "小说"],
            "情感": ["开心", "伤心", "生气", "难过", "高兴", "喜欢", "讨厌", "爱"],
            "天气": ["下雨", "晴天", "温度", "气候", "季节", "台风", "雪"],
            "健康": ["身体", "生病", "医院", "医生", "药物", "锻炼", "饮食", "休息"]
        }
        
        # 简单的情绪关键词
        positive_emotions = ["开心", "高兴", "快乐", "喜欢", "兴奋", "满意", "幸福"]
        negative_emotions = ["伤心", "难过", "生气", "讨厌", "失望", "焦虑", "紧张", "害怕"]
        
        # 初始化结果
        word_counter = Counter()
        detected_topics = []
        emotion_scores = {"positive": 0, "negative": 0, "neutral": 0}
        time_counter = defaultdict(int)
        
        # 分析每条消息
        for msg in messages:
            content = msg.get("content", "").lower()
            timestamp = msg.get("timestamp", time.time())
            
            # 分析时间分布
            hour = datetime.datetime.fromtimestamp(timestamp).hour
            time_counter[hour] += 1
            
            # 分词和词频统计（简单实现）
            words = re.findall(r'[\u4e00-\u9fa5]+|[a-zA-Z0-9]+', content)
            word_counter.update([w for w in words if len(w) > 1])  # 过滤单字
            
            # 检测话题
            for topic, keywords in topic_keywords.items():
                for keyword in keywords:
                    if keyword in content:
                        detected_topics.append(topic)
                        break
            
            # 简单情绪分析
            has_emotion = False
            for emotion in positive_emotions:
                if emotion in content:
                    emotion_scores["positive"] += 1
                    has_emotion = True
                    break
            
            if not has_emotion:
                for emotion in negative_emotions:
                    if emotion in content:
                        emotion_scores["negative"] += 1
                        has_emotion = True
                        break
            
            if not has_emotion:
                emotion_scores["neutral"] += 1
        
        # 找出最活跃的时间段
        most_active_time = None
        max_count = 0
        for hour, count in time_counter.items():
            if count > max_count:
                max_count = count
                most_active_time = f"{hour:02d}:00-{hour+1:02d}:00"
        
        return {
            "word_frequency": dict(word_counter.most_common(20)),  # 返回前20个高频词
            "detected_topics": detected_topics,
            "sentiment_analysis": emotion_scores,
            "most_active_time": most_active_time
        }
    
    def _save_analysis_result(self, user_id: str, result: Dict[str, Any]):
        """
        保存分析结果到文件
        
        Args:
            user_id: 用户ID
            result: 分析结果
        """
        try:
            # 生成文件名（按日期）
            today = datetime.datetime.now().strftime("%Y%m%d")
            analysis_file = ANALYSIS_DIR / f"{user_id}_{today}.json"
            
            # 读取现有结果（如果有）
            existing_results = []
            if analysis_file.exists():
                try:
                    with open(analysis_file, 'r', encoding='utf-8') as f:
                        existing_results = json.load(f)
                except Exception as e:
                    logger.warning(f"读取现有分析结果时出错: {e}")
                    existing_results = []
            
            # 添加新结果
            existing_results.append(result)
            
            # 保存结果
            with open(analysis_file, 'w', encoding='utf-8') as f:
                json.dump(existing_results, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"已保存用户 {user_id} 的分析结果到 {analysis_file}")
            
        except Exception as e:
            logger.error(f"保存分析结果时出错: {e}")
    
    def _is_in_time_window(self) -> bool:
        """
        检查当前时间是否在配置的时间窗口内
        
        Returns:
            bool: 是否在时间窗口内
        """
        current_time = datetime.datetime.now().time()
        
        # 解析配置的时间
        start_time = datetime.datetime.strptime(self.config["start_time"], "%H:%M").time()
        end_time = datetime.datetime.strptime(self.config["end_time"], "%H:%M").time()
        
        # 处理跨天的情况
        if start_time <= end_time:
            # 同一天内的时间窗口
            return start_time <= current_time <= end_time
        else:
            # 跨天的时间窗口
            return current_time >= start_time or current_time <= end_time
    
    def update_config(self, new_config: Dict[str, Any]):
        """
        更新配置
        
        Args:
            new_config: 新的配置参数
        """
        # 更新配置
        self.config.update(new_config)
        logger.info(f"夜间处理器配置已更新: {new_config}")
        
        # 如果启用状态或时间发生变化，重启调度器
        if "enabled" in new_config or "auto_run" in new_config or \
           "start_time" in new_config or "end_time" in new_config:
            if self.config["enabled"] and self.config["auto_run"]:
                self._start_scheduler()
            else:
                self.stop()
    
    def run_manually(self, user_id: str = None) -> Optional[Dict[str, Any]]:
        """
        手动触发处理
        
        Args:
            user_id: 可选，指定用户ID，为None时处理所有用户
            
        Returns:
            Dict or None: 处理结果，如果处理所有用户则返回None
        """
        logger.info(f"手动触发夜间处理，用户ID: {user_id}")
        
        if user_id:
            # 处理指定用户
            manager = get_weighted_memory_manager(user_id)
            return self.process_user_chat_history(user_id, manager)
        else:
            # 处理所有用户
            self.process_all_users()
            return None
    
    def stop(self):
        """
        停止夜间处理器
        """
        logger.info("正在停止夜间处理器...")
        
        # 设置停止事件
        self._stop_event.set()
        
        # 等待调度器线程结束
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            try:
                self._scheduler_thread.join(timeout=5.0)
                logger.info("调度器线程已停止")
            except Exception as e:
                logger.error(f"停止调度器线程时出错: {e}")
        
        # 清除定时任务
        schedule.clear()
        
        # 更新状态
        self._is_running = False
        logger.info("夜间处理器已停止")
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取处理器状态
        
        Returns:
            Dict: 状态信息
        """
        return {
            "enabled": self.config["enabled"],
            "running": self._is_running,
            "next_run_time": self._get_next_run_time(),
            "config": self.config.copy()
        }
    
    def _get_next_run_time(self) -> Optional[str]:
        """
        获取下次运行时间
        
        Returns:
            str or None: 下次运行时间，格式为ISO格式
        """
        try:
            # 获取所有任务
            jobs = schedule.get_jobs()
            if jobs:
                # 计算下次运行时间
                job = jobs[0]
                now = datetime.datetime.now()
                next_run = job.next_run
                
                return next_run.isoformat() if next_run else None
        except Exception as e:
            logger.error(f"获取下次运行时间时出错: {e}")
        
        return None

# 创建全局夜间处理器实例
global_nightly_processor = None

def get_nightly_processor() -> NightlyProcessor:
    """
    获取全局夜间处理器实例
    
    Returns:
        NightlyProcessor: 夜间处理器实例
    """
    global global_nightly_processor
    
    if global_nightly_processor is None:
        global_nightly_processor = NightlyProcessor()
    
    return global_nightly_processor

# 便捷函数
def manually_process_user_history(user_id: str) -> Dict[str, Any]:
    """
    便捷函数：手动处理用户历史记录
    """
    processor = get_nightly_processor()
    return processor.run_manually(user_id)

def update_nightly_config(new_config: Dict[str, Any]):
    """
    便捷函数：更新夜间处理配置
    """
    processor = get_nightly_processor()
    processor.update_config(new_config)

def get_nightly_status() -> Dict[str, Any]:
    """
    便捷函数：获取夜间处理器状态
    """
    processor = get_nightly_processor()
    return processor.get_status()