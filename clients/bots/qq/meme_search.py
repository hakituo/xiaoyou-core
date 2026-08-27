"""表情包语义检索模块（运行时）

加载 data/memes/_index/ 下的 numpy 向量索引，提供：
- pick_meme_by_semantic(query) -> Optional[Path]
  根据 LLM 给的自然语言描述，向量检索最匹配的图片，带 LRU 去重。

设计原则：
- 懒加载：首次调用时才加载模型和向量，避免启动开销
- 失败降级：向量缺失或模型加载失败时返回 None，调用方 fallback 到随机
- 不依赖 ChromaDB：纯 numpy 内存检索（457×512 ≈ 1MB）
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from core.utils.logger import get_logger

logger = get_logger("meme_search")

# 索引文件路径
MEMES_ROOT = Path(__file__).resolve().parents[3] / "data" / "memes"
INDEX_DIR = MEMES_ROOT / "_index"
VECTORS_PATH = INDEX_DIR / "vectors.npy"
PATHS_PATH = INDEX_DIR / "paths.json"

# bge-small-zh 模型路径
BGE_MODEL_PATH = Path(__file__).resolve().parents[3] / "models" / "BERT" / "bge-small-zh-v1.5"

# 默认检索参数
DEFAULT_TOP_K = 5
DEFAULT_MIN_SIMILARITY = 0.25

# 单例锁
_lock = threading.RLock()
_loaded = False
_vectors: Optional[np.ndarray] = None  # (N, 512) 已归一化
_paths: list[str] = []  # N 个相对路径
_backend = None  # ("onnx", tokenizer, session) 或 ("st", None, model)


def _load_index() -> bool:
    """加载向量索引和 bge 模型（线程安全，仅加载一次）。"""
    global _loaded, _vectors, _paths, _backend
    with _lock:
        if _loaded:
            return _vectors is not None
        _loaded = True
        if not VECTORS_PATH.is_file() or not PATHS_PATH.is_file():
            logger.warning(
                f"向量索引不存在: {VECTORS_PATH}。请先运行 "
                "python -m scripts.meme.build_meme_descriptions && "
                "python -m scripts.meme.build_meme_vector_index"
            )
            return False
        try:
            _vectors = np.load(VECTORS_PATH).astype(np.float32)
            with open(PATHS_PATH, "r", encoding="utf-8") as f:
                _paths = json.load(f)
            if _vectors.shape[0] != len(_paths):
                logger.error(
                    f"向量数 {_vectors.shape[0]} 与路径数 {len(_paths)} 不一致"
                )
                _vectors = None
                return False
            # 兜底归一化（build 脚本已归一化，这里再保险一次）
            norms = np.linalg.norm(_vectors, axis=1, keepdims=True)
            norms = np.where(norms > 0, norms, 1.0)
            _vectors = _vectors / norms
            logger.info(f"已加载表情包向量索引: {_vectors.shape}")
        except Exception as e:
            logger.error(f"加载向量索引失败: {e}", exc_info=True)
            _vectors = None
            return False
        _backend = _load_bge_backend()
        return _backend[0] is not None


def _load_bge_backend():
    """加载 bge-small-zh 模型（ONNX 优先，sentence-transformers 回退）。"""
    if not BGE_MODEL_PATH.is_dir():
        logger.error(f"bge 模型目录不存在: {BGE_MODEL_PATH}")
        return (None, None, None)
    onnx_path = BGE_MODEL_PATH / "onnx" / "model.onnx"
    if onnx_path.is_file():
        try:
            import onnxruntime as ort
            from transformers import AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained(str(BGE_MODEL_PATH))
            session = ort.InferenceSession(
                str(onnx_path), providers=["CPUExecutionProvider"]
            )
            logger.info("bge 模型已加载 (ONNX)")
            return ("onnx", tokenizer, session)
        except Exception as e:
            logger.warning(f"ONNX 加载失败，尝试 sentence-transformers: {e}")
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(str(BGE_MODEL_PATH), device="cpu")
        logger.info("bge 模型已加载 (sentence-transformers)")
        return ("st", None, model)
    except Exception as e:
        logger.error(f"sentence-transformers 加载失败: {e}")
        return (None, None, None)


def _encode_query(text: str) -> Optional[np.ndarray]:
    """用 bge 模型编码查询文本，返回归一化向量 (512,)。"""
    if not _load_index():
        return None
    mode, tokenizer, model = _backend
    try:
        if mode == "onnx":
            encoded = tokenizer(
                [text], padding=True, truncation=True, max_length=512, return_tensors="np"
            )
            # 与 DataOps bert_runtime_mixin.py 一致：只传 input_ids + attention_mask
            ort_inputs = {
                "input_ids": encoded["input_ids"].astype(np.int64),
                "attention_mask": encoded["attention_mask"].astype(np.int64),
            }
            try:
                outputs = model.run(["last_hidden_state"], ort_inputs)
                vec = np.asarray(outputs[0])[0, 0, :]  # CLS pooling
            except Exception:
                outputs = model.run(["pooler_output"], ort_inputs)
                vec = np.asarray(outputs[0])[0]
        elif mode == "st":
            vec = model.encode([text], convert_to_numpy=True, normalize_embeddings=True)[0]
        else:
            return None
        vec = np.asarray(vec, dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec
    except Exception as e:
        logger.error(f"查询编码失败: {e}", exc_info=True)
        return None


def pick_meme_by_semantic(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    exclude_paths: Optional[set[str]] = None,
) -> Optional[Path]:
    """根据自然语言描述检索最匹配的表情包图片。

    Args:
        query: 自然语言描述，如"刚解决问题后的喜悦"
        top_k: 返回前 K 个候选，从中随机选一张（避免每次都发最相似的那张）
        min_similarity: 最低相似度阈值，低于此值返回 None
        exclude_paths: 排除的路径集合（字符串形式），通常来自 LRU

    Returns:
        匹配的图片 Path，未找到返回 None
    """
    if not query or not query.strip():
        return None
    if not _load_index():
        return None

    query_vec = _encode_query(query)
    if query_vec is None:
        return None

    # 余弦相似度（向量已归一化，直接点积）
    sims = _vectors @ query_vec  # (N,)

    # 排序取 top-K
    top_indices = np.argsort(sims)[::-1][:top_k]

    # 过滤：相似度阈值 + 排除列表
    candidates: list[tuple[float, str]] = []
    for idx in top_indices:
        sim = float(sims[idx])
        if sim < min_similarity:
            continue
        rel = _paths[idx]
        if exclude_paths and rel in exclude_paths:
            continue
        candidates.append((sim, rel))

    if not candidates:
        # 放宽阈值：取 top-1 看看是否达到最低要求
        if len(top_indices) > 0:
            best_idx = top_indices[0]
            best_sim = float(sims[best_idx])
            if best_sim >= min_similarity * 0.7:  # 阈值 70% 兜底
                candidates = [(best_sim, _paths[best_idx])]
        if not candidates:
            logger.debug(f"语义检索无候选 (query={query!r}, max_sim={sims[top_indices[0]]:.3f})")
            return None

    # 从 top-K 候选里随机选一张（带相似度权重，越高越可能被选中）
    import random
    weights = [max(sim, 0.01) for sim, _ in candidates]
    chosen_rel = random.choices(
        [rel for _, rel in candidates], weights=weights, k=1
    )[0]
    chosen_path = MEMES_ROOT / chosen_rel
    if not chosen_path.is_file():
        logger.warning(f"索引指向的图片不存在: {chosen_path}")
        return None
    logger.info(
        f"语义检索匹配: query={query!r} -> {chosen_rel} "
        f"(top {len(candidates)} 候选，最高 sim={candidates[0][0]:.3f})"
    )
    return chosen_path


def get_status() -> dict:
    """返回索引状态（用于诊断/日志）。"""
    return {
        "loaded": _loaded,
        "vectors_shape": list(_vectors.shape) if _vectors is not None else None,
        "paths_count": len(_paths),
        "backend": _backend[0] if _backend else None,
    }


def reset_for_test() -> None:
    """重置单例状态（仅测试用）。"""
    global _loaded, _vectors, _paths, _backend
    with _lock:
        _loaded = False
        _vectors = None
        _paths = []
        _backend = None
