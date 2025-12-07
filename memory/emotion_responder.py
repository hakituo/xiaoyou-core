#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
情绪感知与响应模块

该模块实现情绪识别功能，能够检测用户的情绪状态，特别是识别伤心、低落等负面情绪，
并基于高权重记忆内容生成个性化安慰话术，同时建立情绪-记忆关联机制。
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
DEFAULT_EMOTION_CONFIG = {
    "detection_threshold": 0.6,
    "negative_emotion_priority": True,
    "comfort_memory_weight_min": 1.5,
    "max_comfort_memories": 5,
    "emotion_memory_association": True,
    "association_threshold": 0.7,
    "emotion_history_window": 24,
    "comfort_response_variation": 0.8,
    "auto_adjust_threshold": False,
    "sentiment_analysis_method": "keyword"
}

# 情绪关键词字典
EMOTION_KEYWORDS = {
    "伤心": [
        "难过", "伤心", "悲伤", "沮丧", "失落", "伤心欲绝", "心如刀割", "哭", "哭泣", 
        "流泪", "难过", "难受", "心碎", "悲痛", "哀伤", "痛苦", "委屈", "郁闷", "沮丧",
        "不开心", "心情不好", "情绪低落", "心灰意冷", "心如死灰", "想哭", "流泪", "难过"
    ],
    "生气": [
        "生气", "愤怒", "恼火", "气愤", "火冒三丈", "气死我了", "烦", "烦躁", "厌烦", 
        "讨厌", "痛恨", "厌恶", "不满", "不爽", "气死", "气死了", "发怒", "暴跳如雷",
        "生气了", "很生气", "太气人了", "气死我", "烦透了", "烦躁不安"
    ],
    "焦虑": [
        "焦虑", "紧张", "担心", "担忧", "害怕", "恐惧", "惶恐", "不安", "忐忑", 
        "心慌", "心虚", "心悸", "害怕", "恐惧", "胆战心惊", "惴惴不安", "如坐针毡",
        "七上八下", "坐立不安", "提心吊胆"
    ],
    "快乐": [
        "开心", "快乐", "高兴", "愉快", "兴奋", "喜悦", "欢乐", "幸福", "甜蜜", 
        "愉快", "满足", "兴奋", "兴高采烈", "眉开眼笑", "心花怒放", "喜出望外",
        "开心极了", "很高兴", "太开心了", "快乐", "欢乐"
    ],
    "疲惫": [
        "累", "疲惫", "疲劳", "困倦", "乏力", "精疲力尽", "筋疲力尽", "疲惫不堪", 
        "很累", "累死了", "太困了", "没精神", "没力气", "想睡觉", "困了", "疲倦"
    ],
    "中性": []  # 默认类别
}

# 情绪类别权重（负面情绪优先级更高）
EMOTION_PRIORITY = {
    "伤心": 1.0,
    "焦虑": 0.9,
    "生气": 0.8,
    "疲惫": 0.7,
    "快乐": 0.6,
    "中性": 0.1
}

# 情绪安慰模板
EMOTION_COMFORT_TEMPLATES = {
    "伤心": [
        "我知道你现在感觉很难过，但是记住，我会一直在这里陪伴你。",
        "我很抱歉看到你不开心，愿意和我分享一下发生了什么吗？",
        "每个人都有难过的时候，这很正常。重要的是我们如何面对它。",
        "我记得你之前也遇到过类似的情况，当时你处理得很好。",
        "深呼吸，一切都会过去的。你比自己想象的要坚强。",
        "难过的时候，我会一直在这里倾听。",
        "有时候，允许自己悲伤也是一种治愈的方式。",
        "我相信明天会更好，你也会感觉好一些的。",
        "你不是一个人在战斗，我会一直在你身边。",
        "让我们一起想办法，看看如何让你感觉好一些。"
    ],
    "焦虑": [
        "我能感受到你的焦虑，我们可以一起慢慢理清思路。",
        "深呼吸，慢慢来，我们可以一步一步地解决问题。",
        "焦虑的时候，试着专注于当下的每一个呼吸。",
        "记住，很多事情并不像我们想象的那么糟糕。",
        "我们可以把问题拆分成小部分，逐一解决。",
        "你已经做了很多，不要对自己要求太高。",
        "放轻松，我会和你一起面对这一切。",
        "有时候，暂时放下问题，给自己一些休息的时间也是好的。",
        "记住你之前成功克服的挑战，这次也一样可以。",
        "深呼吸几次，让我们一起平静下来。"
    ],
    "生气": [
        "我理解你的愤怒，有时候生气是很正常的情绪。",
        "生气没关系，但不要让它伤害到你自己。",
        "深呼吸，让我们一起想办法解决问题，而不是沉浸在愤怒中。",
        "把你的感受说出来，或许会感觉好一些。",
        "我知道这件事让你很生气，但请记住，生气解决不了问题。",
        "我们可以一起找到解决问题的方法，而不是停留在愤怒中。",
        "有时候，暂时离开让你生气的环境，会帮助你冷静下来。",
        "我在这里倾听，你可以把你的感受都告诉我。",
        "生气是一种能量，我们可以把它转化为解决问题的动力。",
        "我理解你的感受，让我们一起想办法改善这种情况。"
    ],
    "疲惫": [
        "你看起来很累，或许应该给自己一些休息的时间。",
        "休息不是浪费时间，而是为了更好地前行。",
        "你的努力我都看在眼里，记得照顾好自己。",
        "有时候，停下来喘口气，反而能让你更有力量继续前进。",
        "我知道你一直在努力，现在是时候好好照顾自己了。",
        "疲惫是身体在提醒你需要休息，不要忽视它。",
        "给自己一些放松的时间，你值得拥有。",
        "休息好了，明天又是新的开始。",
        "你的健康比任何事情都重要，记得休息。",
        "让我们一起想想，如何让你的生活更轻松一些。"
    ],
    "快乐": [
        "看到你这么开心，我也感到很高兴！",
        "快乐是会传染的，你的笑容真的很有感染力。",
        "希望这种快乐能一直伴随着你！",
        "能和我分享一下是什么让你这么开心吗？",
        "你开心的样子真好看，继续保持！",
        "快乐是生活中最好的礼物，恭喜你找到了它。",
        "看到你这么开心，这一天都变得美好了。",
        "你的快乐让我也感到很幸福！",
        "希望这样的美好时刻能一直延续下去。",
        "能分享你的快乐，是我的荣幸。"
    ]
}

# 情绪-记忆关联存储目录
EMOTION_ASSOCIATION_DIR = Path(__file__).resolve().parents[2] / "data" / "emotion_associations"

# 确保关联存储目录存在
def _ensure_association_dir_exists():
    """确保情绪关联存储目录存在，如果不存在则创建"""
    try:
        if not EMOTION_ASSOCIATION_DIR.exists():
            EMOTION_ASSOCIATION_DIR.mkdir(parents=True, exist_ok=True)
            logger.info(f"创建情绪关联存储目录: {EMOTION_ASSOCIATION_DIR}")
    except Exception as e:
        logger.error(f"创建情绪关联存储目录时出错: {e}")

# 初始化目录
_ensure_association_dir_exists()

class EmotionResponder:
    """
    情绪感知与响应组件，负责识别用户情绪并生成相应的回复
    """
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化情绪响应器
        
        Args:
            config: 情绪响应配置参数
        """
        self.config = config or DEFAULT_EMOTION_CONFIG
        self._emotion_history = defaultdict(list)  # 用户情绪历史
        self._emotion_memory_associations = defaultdict(dict)  # 情绪-记忆关联
    
    def detect_emotion(self, text: str) -> Dict[str, Any]:
        """
        检测文本中的情绪
        
        Args:
            text: 用户输入的文本
            
        Returns:
            Dict: 情绪检测结果，包含情绪类型、置信度和关键词
        """
        method = str(self.config.get("sentiment_analysis_method") or "keyword").strip()
        if method == "llm":
            try:
                return self._detect_emotion_llm(text)
            except Exception as e:
                logger.warning(f"LLM情绪检测失败: {e}")
                fallback = self._detect_emotion_simple_ml(text)
                return fallback
        if method == "simple_ml":
            return self._detect_emotion_simple_ml(text)
        return self._detect_emotion_keyword(text)
    
    def _detect_emotion_keyword(self, text: str) -> Dict[str, Any]:
        """
        使用关键词匹配检测情绪
        
        Args:
            text: 用户输入的文本
            
        Returns:
            Dict: 情绪检测结果
        """
        text_lower = text.lower()
        emotion_scores = defaultdict(float)
        detected_keywords = defaultdict(list)
        
        # 统计每个情绪类别的关键词匹配
        for emotion, keywords in EMOTION_KEYWORDS.items():
            if emotion == "中性":
                continue
                
            for keyword in keywords:
                if keyword in text_lower:
                    # 基于关键词出现次数计算分数
                    count = text_lower.count(keyword)
                    emotion_scores[emotion] += count * EMOTION_PRIORITY[emotion]
                    detected_keywords[emotion].extend([keyword] * count)
        
        # 如果没有检测到情绪，默认为中性
        if not emotion_scores:
            return {
                "emotion": "中性",
                "confidence": 1.0,
                "keywords": [],
                "timestamp": time.time()
            }
        
        # 找出最主要的情绪
        max_emotion = max(emotion_scores.keys(), key=lambda e: emotion_scores[e])
        max_score = emotion_scores[max_emotion]
        
        # 归一化置信度
        total_score = sum(emotion_scores.values())
        confidence = max_score / total_score if total_score > 0 else 0.0
        
        # 检查是否超过阈值
        if confidence < self.config["detection_threshold"]:
            return {
                "emotion": "中性",
                "confidence": 1.0 - confidence,
                "keywords": [],
                "timestamp": time.time()
            }
        
        return {
            "emotion": max_emotion,
            "confidence": confidence,
            "keywords": list(set(detected_keywords[max_emotion])),  # 去重
            "timestamp": time.time()
        }
    
    def _detect_emotion_simple_ml(self, text: str) -> Dict[str, Any]:
        """
        使用简单的机器学习方法（基于关键词频率和位置权重）检测情绪
        
        Args:
            text: 用户输入的文本
            
        Returns:
            Dict: 情绪检测结果
        """
        text_lower = text.lower()
        emotion_scores = defaultdict(float)
        detected_keywords = defaultdict(list)
        
        # 分词
        words = re.findall(r'[\u4e00-\u9fa5]+|[a-zA-Z0-9]+', text_lower)
        
        # 对每个词计算位置权重（前面的词权重更高）
        total_words = len(words)
        for i, word in enumerate(words):
            # 位置权重（0-1），前面的词权重更高
            position_weight = 1.0 - (i / max(total_words, 1))
            
            # 检查该词是否属于某个情绪关键词
            for emotion, keywords in EMOTION_KEYWORDS.items():
                if emotion == "中性":
                    continue
                    
                for keyword in keywords:
                    if keyword == word:
                        # 综合考虑关键词权重、位置权重和情绪优先级
                        score = EMOTION_PRIORITY[emotion] * position_weight
                        emotion_scores[emotion] += score
                        detected_keywords[emotion].append(keyword)
        
        # 如果没有检测到情绪，默认为中性
        if not emotion_scores:
            return {
                "emotion": "中性",
                "confidence": 1.0,
                "keywords": [],
                "timestamp": time.time()
            }
        
        # 找出最主要的情绪
        max_emotion = max(emotion_scores.keys(), key=lambda e: emotion_scores[e])
        max_score = emotion_scores[max_emotion]
        
        # 归一化置信度
        total_score = sum(emotion_scores.values())
        confidence = max_score / total_score if total_score > 0 else 0.0
        
        # 检查是否超过阈值
        if confidence < self.config["detection_threshold"]:
            return {
                "emotion": "中性",
                "confidence": 1.0 - confidence,
                "keywords": [],
                "timestamp": time.time()
            }
        
        return {
            "emotion": max_emotion,
            "confidence": confidence,
            "keywords": list(set(detected_keywords[max_emotion])),  # 去重
            "timestamp": time.time()
        }

    def _detect_emotion_llm(self, text: str) -> Dict[str, Any]:
        prompt = (
            "请根据以下文本判断情绪，仅在这些标签中选择一个：快乐、生气、焦虑、伤心、疲惫、中性。"
            "只返回JSON，如{\"emotion\":\"快乐\",\"confidence\":0.85}。文本：" + (text or "")
        )
        response_text = ""
        try:
            from core.model_adapter import ModelAdapter
            adapter = ModelAdapter()
            result = adapter.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=64
            )
            if isinstance(result, dict):
                if result.get("status") == "success":
                    response_text = str(result.get("response") or "")
                else:
                    response_text = str(result)
            else:
                response_text = str(result)
        except Exception as e:
            logger.warning(f"LLM接口调用失败: {e}")
            return self._detect_emotion_simple_ml(text)
        emotion_labels = ["快乐", "生气", "焦虑", "伤心", "疲惫", "中性"]
        emotion = "中性"
        confidence = 1.0
        try:
            data = json.loads(response_text)
            e = str(data.get("emotion") or data.get("label") or "").strip()
            c = data.get("confidence")
            if e in emotion_labels:
                emotion = e
            else:
                for lbl in emotion_labels:
                    if lbl in e:
                        emotion = lbl
                        break
            if isinstance(c, (int, float)):
                v = float(c)
                if 0.0 <= v <= 1.0:
                    confidence = v
        except Exception:
            for lbl in emotion_labels:
                if lbl in response_text:
                    emotion = lbl
                    break
            import re
            m = re.search(r"([01](?:\.\d+)?)", response_text)
            if m:
                try:
                    v = float(m.group(1))
                    if 0.0 <= v <= 1.0:
                        confidence = v
                except Exception:
                    pass
        if emotion == "中性" and self.config.get("negative_emotion_priority", True):
            fallback = self._detect_emotion_simple_ml(text)
            if fallback.get("emotion") != "中性":
                return fallback
            kw_fb = self._detect_emotion_keyword(text)
            if kw_fb.get("emotion") != "中性":
                return kw_fb
        if confidence < float(self.config.get("detection_threshold") or 0.6):
            return {
                "emotion": "中性",
                "confidence": 1.0 - confidence,
                "keywords": [],
                "timestamp": time.time()
            }
        logger.info(f"情绪检测(LLM): emotion={emotion}, confidence={confidence}")
        return {
            "emotion": emotion,
            "confidence": confidence,
            "keywords": [],
            "timestamp": time.time()
        }
    
    def generate_response(self, user_id: str, emotion: str, confidence: float, context: Optional[str] = None) -> Dict[str, Any]:
        """
        基于检测到的情绪生成响应
        
        Args:
            user_id: 用户ID
            emotion: 检测到的情绪
            confidence: 情绪置信度
            context: 上下文文本
            
        Returns:
            Dict: 响应内容，包含回复文本和相关信息
        """
        logger.info(f"为用户 {user_id} 生成情绪响应，情绪: {emotion}, 置信度: {confidence}")
        
        # 记录情绪历史
        self._record_emotion_history(user_id, emotion, confidence)
        
        # 根据情绪类型生成响应
        if emotion == "中性":
            # 中性情绪返回常规响应
            return self._generate_neutral_response(user_id, context)
        
        # 对于非中性情绪，生成相应的响应
        if emotion in EMOTION_COMFORT_TEMPLATES:
            # 获取高权重记忆用于个性化回复
            relevant_memories = self._get_relevant_memories_for_emotion(user_id, emotion)
            
            # 生成个性化响应
            response = self._generate_personalized_response(emotion, relevant_memories, context)
            
            # 更新情绪-记忆关联
            if self.config["emotion_memory_association"]:
                for memory in relevant_memories:
                    self._associate_memory_with_emotion(user_id, memory, emotion)
            
            return response
        
        # 默认响应
        return {
            "response_text": "我注意到你现在可能有一些情绪，愿意和我分享吗？",
            "emotion": emotion,
            "confidence": confidence,
            "timestamp": time.time()
        }
    
    def _get_relevant_memories_for_emotion(self, user_id: str, emotion: str) -> List[Dict[str, Any]]:
        """
        获取与特定情绪相关的高权重记忆
        
        Args:
            user_id: 用户ID
            emotion: 情绪类型
            
        Returns:
            List[Dict]: 相关记忆列表
        """
        # 获取记忆管理器实例
        manager = get_weighted_memory_manager(user_id)
        
        # 获取情绪相关的关键词
        emotion_keywords = EMOTION_KEYWORDS.get(emotion, [])
        
        # 获取高权重记忆
        memories = manager.get_weighted_memories(
            min_weight=self.config["comfort_memory_weight_min"],
            limit=50
        )
        
        # 过滤出与情绪相关的记忆
        relevant_memories = []
        
        # 首先尝试获取之前与该情绪关联过的记忆
        if self.config["emotion_memory_association"] and user_id in self._emotion_memory_associations:
            emotion_associations = self._emotion_memory_associations[user_id]
            for memory_id, assoc_emotions in emotion_associations.items():
                if emotion in assoc_emotions:
                    # 查找对应的记忆
                    for mem in memories:
                        if mem.get("id") == memory_id:
                            relevant_memories.append(mem)
                            break
        
        # 如果相关记忆不足，尝试基于关键词查找
        if len(relevant_memories) < self.config["max_comfort_memories"]:
            # 查找包含情绪关键词或正面关键词的记忆
            positive_keywords = ["开心", "成功", "克服", "解决", "好", "喜欢", "爱", "支持"]
            
            for mem in memories:
                if len(relevant_memories) >= self.config["max_comfort_memories"]:
                    break
                    
                # 检查是否已在相关记忆中
                if any(m.get("id") == mem.get("id") for m in relevant_memories):
                    continue
                    
                content = mem.get("content", "").lower()
                
                # 如果记忆包含正面关键词，则认为相关
                if any(keyword in content for keyword in positive_keywords):
                    relevant_memories.append(mem)
        
        # 按权重排序并返回
        relevant_memories.sort(key=lambda x: x.get("weight", 0), reverse=True)
        
        return relevant_memories[:self.config["max_comfort_memories"]]
    
    def _generate_personalized_response(self, emotion: str, memories: List[Dict[str, Any]], context: Optional[str] = None) -> Dict[str, Any]:
        """
        生成个性化情绪响应
        
        Args:
            emotion: 情绪类型
            memories: 相关记忆列表
            context: 上下文文本
            
        Returns:
            Dict: 响应内容
        """
        # 获取适合该情绪的模板
        templates = EMOTION_COMFORT_TEMPLATES.get(emotion, EMOTION_COMFORT_TEMPLATES["伤心"])
        
        # 选择一个基础模板
        base_response = random.choice(templates)
        
        # 如果有相关记忆，个性化响应
        personalized_parts = []
        
        if memories:
            # 从记忆中提取相关信息
            memory_content = []
            for mem in memories[:2]:  # 使用前2个最相关的记忆
                content = mem.get("content", "")
                
                # 提取关键短语（简单实现）
                if len(content) > 20:
                    # 查找包含关键词的短语
                    keywords = ["记得", "之前", "那次", "当", "时候", "成功", "解决", "帮助"]
                    
                    for keyword in keywords:
                        if keyword in content:
                            # 提取包含关键词的短句
                            sentences = re.split(r'[。！？\.!?]', content)
                            for sentence in sentences:
                                if keyword in sentence and len(sentence) > 5:
                                    memory_content.append(sentence[:30] + "...")  # 限制长度
                                    break
                        if memory_content:
                            break
            
            # 生成个性化部分
            if memory_content:
                # 根据情绪类型选择合适的连接词
                connectors = {
                    "伤心": ["就像你之前提到的", "我记得你曾经分享过", "还记得那次"],
                    "焦虑": ["我记得你之前成功处理过类似情况", "就像那次你", "还记得你如何解决了"],
                    "生气": ["我理解你的感受，就像上次", "还记得当你遇到", "我知道你一直"],
                    "疲惫": ["我记得你之前也有过忙碌的时候", "就像那次你完成了", "还记得你是如何平衡"],
                    "快乐": ["就像你上次分享的", "我记得你提到过", "还记得当你"],
                }
                
                connector = random.choice(connectors.get(emotion, connectors["伤心"]))
                personalized_parts.append(f"{connector} {memory_content[0]}")
        
        # 组合响应
        final_response = base_response
        
        if personalized_parts:
            # 根据随机性决定是否添加个性化部分
            if random.random() < self.config["comfort_response_variation"]:
                final_response = " " + final_response
                if random.random() < 0.5:
                    final_response = personalized_parts[0] + final_response
                else:
                    final_response = final_response + " " + personalized_parts[0]
        
        return {
            "response_text": final_response,
            "emotion": emotion,
            "memory_count": len(memories),
            "personalized": len(personalized_parts) > 0,
            "timestamp": time.time()
        }
    
    def _generate_neutral_response(self, user_id: str, context: Optional[str] = None) -> Dict[str, Any]:
        """
        生成中性情绪的响应
        
        Args:
            user_id: 用户ID
            context: 上下文文本
            
        Returns:
            Dict: 响应内容
        """
        neutral_responses = [
            "我在听，你继续说。",
            "能详细说说吗？",
            "很有趣，能告诉我更多吗？",
            "我理解，你有什么想法？",
            "这很有意思，继续。",
            "我在认真听，你接着说。",
            "嗯，然后呢？",
            "你是怎么看的？",
            "这确实值得思考。",
            "我很感兴趣，能多分享一些吗？"
        ]
        
        return {
            "response_text": random.choice(neutral_responses),
            "emotion": "中性",
            "timestamp": time.time()
        }
    
    def _record_emotion_history(self, user_id: str, emotion: str, confidence: float):
        """
        记录用户的情绪历史
        
        Args:
            user_id: 用户ID
            emotion: 情绪类型
            confidence: 置信度
        """
        now = time.time()
        
        # 添加到历史记录
        self._emotion_history[user_id].append({
            "emotion": emotion,
            "confidence": confidence,
            "timestamp": now
        })
        
        # 清理过期历史
        window_seconds = self.config["emotion_history_window"] * 3600
        self._emotion_history[user_id] = [
            e for e in self._emotion_history[user_id] 
            if now - e["timestamp"] <= window_seconds
        ]
        
        # 限制历史记录数量
        if len(self._emotion_history[user_id]) > 100:  # 最多保留100条记录
            self._emotion_history[user_id] = self._emotion_history[user_id][-100:]
    
    def _associate_memory_with_emotion(self, user_id: str, memory: Dict[str, Any], emotion: str):
        """
        将记忆与情绪建立关联
        
        Args:
            user_id: 用户ID
            memory: 记忆对象
            emotion: 情绪类型
        """
        memory_id = memory.get("id")
        if not memory_id:
            return
        
        # 初始化用户的情绪-记忆关联
        if user_id not in self._emotion_memory_associations:
            self._emotion_memory_associations[user_id] = {}
        
        # 初始化记忆的情绪关联
        if memory_id not in self._emotion_memory_associations[user_id]:
            self._emotion_memory_associations[user_id][memory_id] = {}
        
        # 更新情绪关联强度
        current_strength = self._emotion_memory_associations[user_id][memory_id].get(emotion, 0.0)
        
        # 根据记忆权重和情绪置信度计算新的强度
        memory_weight = memory.get("weight", 1.0)
        new_strength = min(current_strength + (memory_weight * 0.1), 1.0)  # 上限为1.0
        
        self._emotion_memory_associations[user_id][memory_id][emotion] = new_strength
        
        # 定期保存关联数据
        if random.random() < 0.1:  # 10%的概率保存
            self._save_emotion_memory_associations(user_id)
    
    def _save_emotion_memory_associations(self, user_id: str):
        """
        保存情绪-记忆关联数据
        
        Args:
            user_id: 用户ID
        """
        try:
            file_path = EMOTION_ASSOCIATION_DIR / f"{user_id}_emotions.json"
            
            # 保存关联数据
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self._emotion_memory_associations[user_id], f, ensure_ascii=False, indent=2)
            
            logger.debug(f"已保存用户 {user_id} 的情绪-记忆关联数据到 {file_path}")
            
        except Exception as e:
            logger.error(f"保存情绪-记忆关联数据时出错: {e}")
    
    def _load_emotion_memory_associations(self, user_id: str):
        """
        加载情绪-记忆关联数据
        
        Args:
            user_id: 用户ID
        """
        try:
            file_path = EMOTION_ASSOCIATION_DIR / f"{user_id}_emotions.json"
            
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    associations = json.load(f)
                    self._emotion_memory_associations[user_id] = associations
                
                logger.debug(f"已加载用户 {user_id} 的情绪-记忆关联数据")
                
        except Exception as e:
            logger.error(f"加载情绪-记忆关联数据时出错: {e}")
    
    def get_emotion_summary(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户的情绪统计摘要
        
        Args:
            user_id: 用户ID
            
        Returns:
            Dict: 情绪统计摘要
        """
        # 获取用户的情绪历史
        emotions = self._emotion_history.get(user_id, [])
        
        # 如果没有历史记录，尝试加载保存的数据
        if not emotions:
            self._load_emotion_memory_associations(user_id)
        
        # 统计各情绪出现次数
        emotion_counter = Counter()
        emotion_confidences = defaultdict(list)
        
        for e in emotions:
            emotion_counter[e["emotion"]] += 1
            emotion_confidences[e["emotion"]].append(e["confidence"])
        
        # 计算平均置信度
        avg_confidences = {}
        for emotion, confidences in emotion_confidences.items():
            avg_confidences[emotion] = sum(confidences) / len(confidences)
        
        # 获取最常见的情绪
        dominant_emotion = None
        dominant_count = 0
        
        for emotion, count in emotion_counter.items():
            if emotion != "中性" and count > dominant_count:
                dominant_count = count
                dominant_emotion = emotion
        
        # 获取最近的情绪
        recent_emotions = sorted(emotions, key=lambda x: x["timestamp"], reverse=True)[:5]
        
        return {
            "user_id": user_id,
            "total_emotion_records": len(emotions),
            "emotion_distribution": dict(emotion_counter),
            "average_confidences": avg_confidences,
            "dominant_emotion": dominant_emotion,
            "recent_emotions": recent_emotions,
            "association_count": len(self._emotion_memory_associations.get(user_id, {})),
            "timestamp": time.time()
        }
    
    def update_config(self, new_config: Dict[str, Any]):
        """
        更新配置
        
        Args:
            new_config: 新的配置参数
        """
        self.config.update(new_config)
        logger.info(f"情绪响应器配置已更新: {new_config}")
    
    def process_message(self, user_id: str, message: str) -> Dict[str, Any]:
        """
        处理用户消息，识别情绪并生成响应
        
        Args:
            user_id: 用户ID
            message: 用户消息文本
            
        Returns:
            Dict: 处理结果，包含情绪识别结果和响应
        """
        # 检测情绪
        emotion_result = self.detect_emotion(message)
        emotion = emotion_result["emotion"]
        confidence = emotion_result["confidence"]
        
        logger.info(f"处理用户 {user_id} 的消息，检测到情绪: {emotion}, 置信度: {confidence}")
        
        # 生成响应
        response = self.generate_response(user_id, emotion, confidence, message)
        
        # 合并结果
        return {
            "emotion_detection": emotion_result,
            "response": response,
            "user_id": user_id,
            "timestamp": time.time()
        }

# 创建全局情绪响应器实例
global_emotion_responder = None

def get_emotion_responder() -> EmotionResponder:
    """
    获取全局情绪响应器实例
    
    Returns:
        EmotionResponder: 情绪响应器实例
    """
    global global_emotion_responder
    
    if global_emotion_responder is None:
        global_emotion_responder = EmotionResponder()
    
    return global_emotion_responder

# 便捷函数
def detect_user_emotion(text: str) -> Dict[str, Any]:
    """
    便捷函数：检测文本中的情绪
    """
    responder = get_emotion_responder()
    return responder.detect_emotion(text)

def respond_to_emotion(user_id: str, emotion: str, confidence: float, context: Optional[str] = None) -> Dict[str, Any]:
    """
    便捷函数：根据情绪生成响应
    """
    responder = get_emotion_responder()
    return responder.generate_response(user_id, emotion, confidence, context)

def process_user_message(user_id: str, message: str) -> Dict[str, Any]:
    """
    便捷函数：处理用户消息，识别情绪并生成响应
    """
    responder = get_emotion_responder()
    return responder.process_message(user_id, message)

def get_user_emotion_summary(user_id: str) -> Dict[str, Any]:
    """
    便捷函数：获取用户的情绪统计摘要
    """
    responder = get_emotion_responder()
    return responder.get_emotion_summary(user_id)
