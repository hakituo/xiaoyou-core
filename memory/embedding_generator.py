#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
向量嵌入生成模块

负责生成文本的向量嵌入表示，支持语义相似度计算
"""

import logging
import numpy as np
from typing import List, Optional, Union, Tuple
import base64
import time
import threading

# 配置日志
logger = logging.getLogger(__name__)

# 默认模型配置
DEFAULT_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIMENSION = 384  # MiniLM-L12-v2的嵌入维度
MAX_BATCH_SIZE = 32  # 批量处理的最大文本数量

class EmbeddingGenerator:
    """
    向量嵌入生成器，负责文本到向量的转换和相似度计算
    """
    _instance = None
    _lock = threading.RLock()
    
    def __new__(cls):
        """单例模式实现"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(EmbeddingGenerator, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化嵌入生成器"""
        # 使用懒加载模式，避免应用启动时就加载模型
        self._model = None
        self._model_loaded = False
        self._loading_lock = threading.RLock()
        self._model_name = DEFAULT_EMBEDDING_MODEL
    
    def _load_model(self):
        """加载嵌入模型（懒加载）"""
        with self._loading_lock:
            if not self._model_loaded:
                try:
                    logger.info(f"开始加载嵌入模型: {self._model_name}")
                    start_time = time.time()
                    
                    # 尝试导入sentence_transformers
                    try:
                        # 设置环境变量以支持国内下载（如果本地没有模型）
                        import os
                        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
                        # 忽略SSL验证错误（针对某些特定网络环境）
                        import ssl
                        try:
                            _create_unverified_https_context = ssl._create_unverified_context
                        except AttributeError:
                            pass
                        else:
                            ssl._create_default_https_context = _create_unverified_https_context

                        from sentence_transformers import SentenceTransformer
                        
                        # 尝试加载模型
                        # 如果本地没有，SentenceTransformer会尝试下载
                        # 我们使用hf-mirror镜像源来加速下载
                        logger.info("尝试加载 SentenceTransformer 模型...")
                        # 强制使用CPU加载模型，避免占用显存导致LLM OOM
                        self._model = SentenceTransformer(self._model_name, device="cpu")
                        self._use_hash_fallback = False
                        logger.info("成功加载 sentence_transformers 模型 (CPU Mode)")
                        
                    except Exception as e:
                        logger.warning(f"无法加载 sentence_transformers 模型 ({e})，将使用哈希嵌入作为后备")
                        logger.warning("这可能是因为网络连接问题或模型文件缺失。系统将继续运行，但语义搜索能力将受限。")
                        self._use_hash_fallback = True
                    
                    self._model_loaded = True
                    
                    end_time = time.time()
                    logger.info(f"模型加载流程完成，耗时: {end_time - start_time:.2f}秒")
                except Exception as e:
                    logger.error(f"加载嵌入模型流程发生未预期的错误: {e}")
                    logger.warning("启用简单哈希嵌入作为最后防线")
                    self._use_hash_fallback = True
                    self._model_loaded = True
    
    def ensure_model_loaded(self):
        """确保模型已加载"""
        if not self._model_loaded:
            self._load_model()
            
    def _generate_simple_hash_embedding(self, text: str) -> np.ndarray:
        """最后防线：基于哈希的简单嵌入"""
        vector = np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)
        # 简单分词
        import re
        words = re.findall(r'\w+', text.lower())
        if not words:
            return vector
            
        for word in words:
            # 简单的哈希映射
            h = 0
            for c in word:
                h = (31 * h + ord(c)) & 0xFFFFFFFF
            idx = h % EMBEDDING_DIMENSION
            vector[idx] += 1.0
            
        # 归一化
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm
            
        return vector
            
    def generate_embedding(self, text: str) -> np.ndarray:
        """
        生成单个文本的向量嵌入
        
        Args:
            text: 输入文本
            
        Returns:
            文本的向量表示（numpy数组）
        """
        self.ensure_model_loaded()
        
        try:
            # 确保输入是字符串
            if not isinstance(text, str):
                text = str(text)
            
            # 检查是否使用了哈希后备方案
            if hasattr(self, '_use_hash_fallback') and self._use_hash_fallback:
                return self._generate_simple_hash_embedding(text)

            # 正常方案
            if self._model is None:
                # 模型加载失败的情况（不应该发生，因为有hash fallback）
                return self._generate_simple_hash_embedding(text)
                
            # 生成嵌入向量
            embedding = self._model.encode([text], convert_to_numpy=True)[0]
            return embedding
        except Exception as e:
            logger.error(f"生成向量嵌入失败: {e}")
            # 返回哈希嵌入作为最后的手段
            return self._generate_simple_hash_embedding(text)
    
    def generate_embeddings_batch(self, texts: List[str]) -> List[np.ndarray]:
        """
        批量生成文本向量嵌入
        
        Args:
            texts: 文本列表
            
        Returns:
            向量列表，每个向量对应输入文本列表中的一项
        """
        self.ensure_model_loaded()
        
        try:
            # 确保所有输入都是字符串
            texts = [str(text) if not isinstance(text, str) else text for text in texts]
            
            # 分批次处理以避免内存问题
            embeddings = []
            for i in range(0, len(texts), MAX_BATCH_SIZE):
                batch = texts[i:i+MAX_BATCH_SIZE]
                
                # 检查是否使用了后备方案
                if hasattr(self, '_use_fallback') and self._use_fallback:
                    batch_embeddings = [self._generate_embedding_fallback(t) for t in batch]
                elif self._model is not None:
                    batch_embeddings = self._model.encode(batch, convert_to_numpy=True)
                else:
                    batch_embeddings = [np.zeros(EMBEDDING_DIMENSION, dtype=np.float32) for _ in batch]
                    
                embeddings.extend(batch_embeddings)
            
            return embeddings
        except Exception as e:
            logger.error(f"批量生成向量嵌入失败: {e}")
            # 返回零向量列表作为默认值
            return [np.zeros(EMBEDDING_DIMENSION, dtype=np.float32) for _ in texts]
    
    @staticmethod
    def cosine_similarity(embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """
        计算两个向量之间的余弦相似度
        
        Args:
            embedding1: 第一个向量
            embedding2: 第二个向量
            
        Returns:
            余弦相似度值（范围[-1, 1]）
        """
        try:
            # 计算余弦相似度
            dot_product = np.dot(embedding1, embedding2)
            norm1 = np.linalg.norm(embedding1)
            norm2 = np.linalg.norm(embedding2)
            
            # 避免除零错误
            if norm1 == 0 or norm2 == 0:
                return 0.0
            
            return float(dot_product / (norm1 * norm2))
        except Exception as e:
            logger.error(f"计算余弦相似度失败: {e}")
            return 0.0
    
    def find_most_similar(self, query_embedding: np.ndarray, 
                         embeddings: List[np.ndarray], 
                         top_k: int = 5) -> List[Tuple[int, float]]:
        """
        找出与查询向量最相似的向量
        
        Args:
            query_embedding: 查询向量
            embeddings: 候选向量列表
            top_k: 返回前k个最相似的结果
            
        Returns:
            包含(索引, 相似度)元组的列表，按相似度降序排列
        """
        try:
            # 计算与所有向量的相似度
            similarities = []
            for i, embedding in enumerate(embeddings):
                similarity = self.cosine_similarity(query_embedding, embedding)
                similarities.append((i, similarity))
            
            # 按相似度降序排序
            similarities.sort(key=lambda x: x[1], reverse=True)
            
            # 返回前k个结果
            return similarities[:top_k]
        except Exception as e:
            logger.error(f"查找最相似向量失败: {e}")
            return []
    
    @staticmethod
    def embedding_to_base64(embedding: np.ndarray) -> str:
        """
        将向量转换为base64编码的字符串，用于存储
        
        Args:
            embedding: 向量数组
            
        Returns:
            base64编码的字符串
        """
        try:
            # 转换为bytes并编码
            embedding_bytes = embedding.astype(np.float32).tobytes()
            return base64.b64encode(embedding_bytes).decode('utf-8')
        except Exception as e:
            logger.error(f"向量转base64失败: {e}")
            return ""
    
    @staticmethod
    def base64_to_embedding(base64_str: str) -> np.ndarray:
        """
        将base64编码的字符串转换回向量
        
        Args:
            base64_str: base64编码的字符串
            
        Returns:
            向量数组
        """
        try:
            # 解码并转换为numpy数组
            embedding_bytes = base64.b64decode(base64_str)
            embedding = np.frombuffer(embedding_bytes, dtype=np.float32)
            return embedding
        except Exception as e:
            logger.error(f"base64转向量失败: {e}")
            # 返回零向量
            return np.zeros(EMBEDDING_DIMENSION, dtype=np.float32)
    
    def set_model(self, model_name: str):
        """
        设置嵌入模型
        
        Args:
            model_name: 模型名称或路径
        """
        with self._loading_lock:
            self._model_name = model_name
            self._model_loaded = False
            self._model = None
            logger.info(f"嵌入模型已更改为: {model_name}")

# 全局实例
_embedding_generator_instance = None

def get_embedding_generator() -> EmbeddingGenerator:
    """
    获取嵌入生成器的全局实例
    
    Returns:
        EmbeddingGenerator: 嵌入生成器实例
    """
    global _embedding_generator_instance
    if _embedding_generator_instance is None:
        _embedding_generator_instance = EmbeddingGenerator()
    return _embedding_generator_instance

# 创建全局实例供直接使用
embedding_generator = get_embedding_generator()