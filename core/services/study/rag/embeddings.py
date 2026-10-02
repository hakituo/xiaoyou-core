"""向量后端：本地 bge-small-zh-v1.5（ONNX Runtime）。

**不自己造轮子。** 项目里 `memory.embedding_generator` 已经是这个模型的 ONNX 实现：

    - 权重：models/BERT/bge-small-zh-v1.5（FP32，含 onnx/model.onnx）
    - 池化：CLS（sentence-transformers 管线 Transformer → Pooling → Normalize）
    - 维度：512
    - 预热后约 4.5ms/句；首次会话建立约 50s（一次性，可后台预热）

所以这里只做三件事：
    1. 复用共享生成器算向量，不在 RAG 里再加载一份模型；
    2. 自己保存 chunk_id -> 向量的映射（检索要在内存里比相似度）；
    3. 任何失败都向上抛，由 StudyRetriever 降级为纯词法检索。
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple

import numpy as np

from core.utils.logger import get_logger

logger = get_logger("RagEmbeddings")

#: 长文本截断，避免超长 chunk 拖慢编码（与生成器默认一致）
MAX_CHARS = 2000


class BgeOnnxBackend:
    """基于共享 ONNX 生成器的向量后端。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._vectors: Dict[str, np.ndarray] = {}
        self._generator = None

    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return self._ensure_generator() is not None

    def _ensure_generator(self):
        if self._generator is not None:
            return self._generator
        try:
            # 必须走工厂函数而不是 import 模块级全局：全局是在 import 那一刻
            # 创建的对象，若单例之后被重建（换模型、测试置空 _instance 等），
            # 它会一直指向旧实例，导致 RAG 用不上被预热的那一份。
            # ChatAgent 预热的也是 get_embedding_generator()，两边必须同源。
            from memory.embedding_generator import get_embedding_generator

            self._generator = get_embedding_generator()
            return self._generator
        except Exception as e:  # noqa: BLE001
            logger.warning("共享 embedding 生成器不可用，向量检索关闭: %s", e)
            return None

    def encode(self, texts: List[str]) -> Optional[np.ndarray]:
        """返回 (n, dim) 的 L2 归一化向量矩阵；失败返回 None。"""
        generator = self._ensure_generator()
        if generator is None or not texts:
            return None
        try:
            vectors = generator.generate_embeddings_batch([t[:MAX_CHARS] for t in texts])
            matrix = np.asarray([np.asarray(v, dtype=np.float32).ravel() for v in vectors])
        except Exception as e:  # noqa: BLE001
            logger.warning("embedding 生成失败: %s", e)
            return None
        if matrix.ndim != 2 or matrix.size == 0:
            return None
        # L2 归一化，之后点积即余弦相似度
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms

    # ------------------------------------------------------------------
    def add(self, chunk_id: str, text: str) -> None:
        matrix = self.encode([text])
        if matrix is None:
            raise RuntimeError("embedding 生成失败，交由上层降级")
        with self._lock:
            self._vectors[chunk_id] = matrix[0]

    def remove(self, chunk_id: str) -> None:
        with self._lock:
            self._vectors.pop(chunk_id, None)

    def clear(self) -> None:
        with self._lock:
            self._vectors.clear()

    def search(self, query: str, top_k: int = 20) -> List[Tuple[str, float]]:
        with self._lock:
            if not self._vectors:
                return []
            ids = list(self._vectors.keys())
            matrix = np.vstack([self._vectors[i] for i in ids])

        query_vec = self.encode([query])
        if query_vec is None:
            return []
        scores = matrix @ query_vec[0]
        order = np.argsort(-scores)[:top_k]
        return [(ids[i], float(scores[i])) for i in order if float(scores[i]) > 0]

    def reindex(self, items: Dict[str, str]) -> int:
        """批量重建向量（索引加载后、或模型从不可用恢复时用）。"""
        if not items:
            return 0
        keys = list(items.keys())
        matrix = self.encode([items[k] for k in keys])
        if matrix is None:
            return 0
        with self._lock:
            for key, vector in zip(keys, matrix):
                self._vectors[key] = vector
        return len(keys)

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"vectors": len(self._vectors)}
